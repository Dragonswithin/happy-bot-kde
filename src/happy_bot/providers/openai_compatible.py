"""Provider for any endpoint that speaks the OpenAI chat-completions format.

This one adapter covers local servers (llama.cpp, Ollama, LM Studio, vLLM and
similar) and hosted services and gateways that expose the same API. It is
configured only by ``base_url`` (the API root that has ``/chat/completions``
and ``/models`` beneath it, typically ending in ``/v1``), a model id, an
optional API key sent as a bearer token, and optional extra request headers
for services that need them. No vendor is assumed.

Requests are streamed. The reply arrives as server-sent events; text deltas
are yielded as they come, hidden reasoning is reported as ``ThinkingDelta``,
and tool calls, which arrive as fragments of a JSON string spread over many
events and keyed by ``index``, are reassembled and yielded complete once the
stream ends. Arguments that are not a JSON object are passed on with
``arguments_error`` set so the agent loop can tell the model, instead of
failing the turn.

``stream_options.include_usage`` is requested for token counts; a server that
rejects the option with HTTP 400 is retried once without it. Only ``model``,
``messages``, ``tools``, ``stream`` and that option are sent: several services
refuse requests that set sampling options such as ``temperature``.

Some services refuse a follow-up request unless the assistant's earlier
message comes back exactly: its ``reasoning_content`` (DeepSeek, Kimi) or each
tool call's ``extra_content`` (Gemini's thought signatures). Those are kept as
``echo`` on the message and the call, tagged with this ``base_url``, and sent
back only to the same address, so a conversation that moves to another model
never carries one service's fields to another.

Blocking: ``stream`` blocks on network reads, up to ``timeout`` seconds
between chunks. It checks ``cancel`` after every received line and closes the
connection when cancelled or when the generator is closed. Uses only
``urllib``.
"""

from __future__ import annotations

import http.client
import json
import threading
from typing import Any, Iterator, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..conversation import (
    Message,
    ProviderEvent,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolCallReady,
    ToolSpec,
    TurnEnd,
)
from .base import ProviderError

DEFAULT_TIMEOUT_SECONDS = 300.0
PROBE_TIMEOUT_SECONDS = 6.0
CONTEXT_WINDOW_KEYS = ("context_window", "context_length", "n_ctx", "max_context_length", "max_input_tokens")


def _headers(api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream, application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers.update(extra or {})
    return headers


def _explain_http_error(error: HTTPError, base_url: str) -> str:
    detail = ""
    try:
        body = json.loads(error.read().decode("utf-8", errors="replace"))
        inner = body.get("error") if isinstance(body, dict) else None
        detail = str(inner.get("message") if isinstance(inner, dict) else inner or "")
    except (ValueError, OSError):
        pass
    if error.code in (401, 403):
        reason = "The model service rejected the API key"
    elif error.code == 404:
        reason = f"The model or address was not found at {base_url}"
    elif error.code == 429:
        reason = "The model service is rate limiting or out of quota"
    else:
        reason = f"The model service returned HTTP {error.code}"
    return f"{reason}: {detail[:300]}" if detail else f"{reason}."


def _echo_for(echo: str, base_url: str) -> dict[str, Any]:
    """The fields to send back, when ``echo`` was written by this same service; else nothing."""
    try:
        data = json.loads(echo) if echo else {}
    except ValueError:
        return {}
    if not isinstance(data, dict) or data.get("for") != base_url or not isinstance(data.get("fields"), dict):
        return {}
    return data["fields"]


def _make_echo(fields: dict[str, Any], base_url: str) -> str:
    return json.dumps({"for": base_url, "fields": fields}, ensure_ascii=False) if fields else ""


def _message_to_wire(message: Message, base_url: str = "") -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.text}
    wire: dict[str, Any] = {"role": message.role, "content": message.text}
    if message.tool_calls:
        wire["content"] = message.text or None
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
                **_echo_for(call.echo, base_url),
            }
            for call in message.tool_calls
        ]
    if message.role == "assistant":
        wire.update(_echo_for(message.echo, base_url))
    return wire


def _finish_tool_call(index: int, parts: dict[str, Any], base_url: str = "") -> ToolCall:
    raw = "".join(parts["arguments"]).strip()
    call_id = parts["id"] or f"call_{index}"
    echo = _make_echo(parts.get("extra") or {}, base_url)
    if not raw:
        return ToolCall(call_id, parts["name"], {}, echo=echo)
    try:
        arguments = json.loads(raw)
    except ValueError as exc:
        return ToolCall(call_id, parts["name"], {}, f"arguments were not valid JSON ({exc})", echo)
    if not isinstance(arguments, dict):
        return ToolCall(call_id, parts["name"], {}, "arguments must be a JSON object", echo)
    return ToolCall(call_id, parts["name"], arguments, echo=echo)


class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.headers = dict(headers or {})

    def _open(self, body: dict[str, Any]) -> Any:
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=_headers(self.api_key, self.headers),
            method="POST",
        )
        try:
            return urlopen(request, timeout=self.timeout)
        except HTTPError as error:
            with error:
                if error.code == 400 and "stream_options" in body:
                    body = {key: value for key, value in body.items() if key != "stream_options"}
                    return self._open(body)
                raise ProviderError(_explain_http_error(error, self.base_url)) from error
        except (URLError, TimeoutError, OSError, http.client.HTTPException) as error:
            reason = getattr(error, "reason", error)
            raise ProviderError(f"Could not reach the model at {self.base_url}: {reason}") from error

    def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        cancel: threading.Event,
    ) -> Iterator[ProviderEvent]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_to_wire(message, self.base_url) for message in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = [
                {"type": "function", "function": {
                    "name": tool.name, "description": tool.description, "parameters": tool.parameters}}
                for tool in tools
            ]
        response = self._open(body)
        pending: dict[int, dict[str, Any]] = {}
        reasoning: list[str] = []
        stop_reason = ""
        usage: dict[str, Any] = {}
        try:
            for raw in response:
                if cancel.is_set():
                    stop_reason = "cancelled"
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("error"):
                    error = event["error"]
                    detail = error.get("message") if isinstance(error, dict) else error
                    raise ProviderError(f"The model service reported an error: {str(detail)[:300]}")
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("reasoning_content") or delta.get("reasoning"):
                        if delta.get("reasoning_content"):
                            reasoning.append(str(delta["reasoning_content"]))
                        yield ThinkingDelta()
                    if delta.get("content"):
                        yield TextDelta(str(delta["content"]))
                    for fragment in delta.get("tool_calls") or []:
                        slot = pending.setdefault(
                            int(fragment.get("index", 0)), {"id": "", "name": "", "arguments": [], "extra": {}})
                        if isinstance(fragment.get("extra_content"), dict):
                            slot["extra"]["extra_content"] = fragment["extra_content"]
                        function = fragment.get("function") or {}
                        slot["id"] = fragment.get("id") or slot["id"]
                        slot["name"] = function.get("name") or slot["name"]
                        if function.get("arguments"):
                            slot["arguments"].append(str(function["arguments"]))
                    if choice.get("finish_reason"):
                        stop_reason = str(choice["finish_reason"])
        except (TimeoutError, OSError, http.client.HTTPException) as error:
            raise ProviderError(f"The connection to the model was lost: {error}") from error
        finally:
            response.close()
        if stop_reason != "cancelled":
            for index in sorted(pending):
                if pending[index]["name"]:
                    yield ToolCallReady(_finish_tool_call(index, pending[index], self.base_url))
        yield TurnEnd(
            stop_reason=stop_reason,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            echo=_make_echo({"reasoning_content": "".join(reasoning)} if reasoning else {}, self.base_url),
        )


def list_models(
    base_url: str,
    api_key: str = "",
    timeout: float = PROBE_TIMEOUT_SECONDS,
    headers: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return ``[{"id", "context_window"}]`` from ``GET <base_url>/models``.

    ``context_window`` is 0 when the service does not report one. Raises
    ``ProviderError`` if the address does not answer like a models endpoint.
    """
    root = base_url.rstrip("/")
    request = Request(f"{root}/models", headers=_headers(api_key, headers), method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            document = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as error:
        with error:
            raise ProviderError(_explain_http_error(error, root)) from error
    except (URLError, TimeoutError, OSError, ValueError, http.client.HTTPException) as error:
        # HTTPException covers a port that answers with something other than HTTP.
        reason = getattr(error, "reason", error)
        raise ProviderError(f"Could not reach a model service at {root}: {reason}") from error
    entries = document.get("data") if isinstance(document, dict) else document
    if not isinstance(entries, list):
        raise ProviderError(f"{root} did not answer like a model service")
    models = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        window = 0
        for source in (entry, entry.get("meta") if isinstance(entry.get("meta"), dict) else {}):
            for key in CONTEXT_WINDOW_KEYS:
                if isinstance(source.get(key), int) and source[key] > 0:
                    window = window or source[key]
        models.append({"id": str(entry["id"]), "context_window": window})
    return models
