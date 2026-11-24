"""Provider for OpenAI's Responses API (``POST {base_url}/responses``), which OpenAI's newer models need for tools.

OpenAI's newest GPT models refuse function tools on ``/chat/completions`` ("use /v1/responses"), so
the OpenAI preset (``model_presets``) uses this provider kind, ``openai_responses``. It has the same
interface as ``openai_compatible`` and reuses its request headers, error wording, tool-call assembly
and echo tagging; only the wire format differs:

- Request: ``model``, ``input`` (the conversation as items), ``tools`` (flat ``{"type": "function",
  "name", "description", "parameters", "strict": false}``: non-strict, because the assistant's tool
  schemas have optional fields), ``stream``, and ``store: false`` so OpenAI keeps no copy; the whole
  history is sent each time. Leading system messages become ``instructions``.
- History: user and system messages are ``{"role", "content"}`` items; a tool result is a
  ``function_call_output`` item. An assistant message from this same address is replayed from its
  ``echo``: every output item of that response, unchanged and in order (reasoning items with their
  ``encrypted_content``, messages, function calls), because OpenAI requires reasoning items to come
  back with the tool results that follow them. An assistant message without that echo (written by
  another model) is sent as plain text plus ``function_call`` items.
- Stream: server-sent events with a ``type``. ``response.output_text.delta`` is text;
  reasoning events are reported as ``ThinkingDelta``; ``response.output_item.added`` starts a
  function call and ``response.function_call_arguments.delta`` grows its arguments;
  ``response.output_item.done`` completes an item and keeps it for the echo;
  ``response.completed`` (or ``.incomplete``) gives usage and the full output; ``error`` and
  ``response.failed`` raise ``ProviderError``.

Blocking and cancellation are as in ``openai_compatible``: reads block up to ``timeout`` between
chunks, ``cancel`` is checked after every line, and the connection is closed on the way out.
"""

from __future__ import annotations

import http.client
import json
import threading
from typing import Any, Iterator, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..conversation import Message, ProviderEvent, TextDelta, ThinkingDelta, ToolCallReady, ToolSpec, TurnEnd
from .base import ProviderError
from .openai_compatible import DEFAULT_TIMEOUT_SECONDS, _echo_for, _explain_http_error, _finish_tool_call, _headers, _make_echo


def _input_items(messages: Sequence[Message], base_url: str) -> tuple[str, list[dict[str, Any]]]:
    """``(instructions, input items)`` for ``messages``."""
    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system" and not items:
            instructions.append(message.text)
        elif message.role in ("system", "user"):
            items.append({"role": message.role, "content": message.text})
        elif message.role == "tool":
            items.append({"type": "function_call_output", "call_id": message.tool_call_id, "output": message.text})
        elif message.role == "assistant":
            replay = _echo_for(message.echo, base_url).get("output")
            if isinstance(replay, list) and replay:
                items.extend(replay)
                continue
            if message.text:
                items.append({"role": "assistant", "content": message.text})
            for call in message.tool_calls:
                items.append({"type": "function_call", "call_id": call.id, "name": call.name,
                              "arguments": json.dumps(call.arguments, ensure_ascii=False)})
    return "\n\n".join(text for text in instructions if text), items


class OpenAIResponsesProvider:
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
        request = Request(f"{self.base_url}/responses", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                          headers=_headers(self.api_key, self.headers), method="POST")
        try:
            return urlopen(request, timeout=self.timeout)
        except HTTPError as error:
            with error:
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
        instructions, items = _input_items(messages, self.base_url)
        body: dict[str, Any] = {"model": self.model, "input": items, "stream": True, "store": False}
        if instructions:
            body["instructions"] = instructions
        if tools:
            body["tools"] = [{"type": "function", "name": tool.name, "description": tool.description,
                              "parameters": tool.parameters, "strict": False} for tool in tools]
        response = self._open(body)
        calls: dict[int, dict[str, Any]] = {}
        by_item: dict[str, int] = {}
        done_items: dict[int, dict[str, Any]] = {}
        final_output: list[dict[str, Any]] | None = None
        usage: dict[str, Any] = {}
        stop_reason = ""
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
                kind = str(event.get("type") or "")
                index = int(event.get("output_index") or 0)
                if kind == "response.output_text.delta":
                    yield TextDelta(str(event.get("delta") or ""))
                elif "reasoning" in kind and kind.endswith(".delta"):
                    yield ThinkingDelta()
                elif kind == "response.output_item.added":
                    item = event.get("item") or {}
                    if item.get("type") == "function_call":
                        calls[index] = {"id": item.get("call_id") or "", "name": item.get("name") or "",
                                        "arguments": [str(item.get("arguments") or "")]}
                        by_item[str(item.get("id") or "")] = index
                    elif item.get("type") == "reasoning":
                        yield ThinkingDelta()
                elif kind == "response.function_call_arguments.delta":
                    slot = calls.get(by_item.get(str(event.get("item_id") or ""), index))
                    if slot is not None:
                        slot["arguments"].append(str(event.get("delta") or ""))
                elif kind == "response.output_item.done":
                    item = event.get("item") or {}
                    done_items[index] = item
                    if item.get("type") == "function_call" and index in calls:
                        calls[index]["arguments"] = [str(item.get("arguments") or "")]
                        calls[index]["id"] = item.get("call_id") or calls[index]["id"]
                elif kind in ("response.completed", "response.incomplete"):
                    result = event.get("response") or {}
                    usage = result.get("usage") or {}
                    if isinstance(result.get("output"), list):
                        final_output = result["output"]
                    stop_reason = "stop" if kind == "response.completed" else str(
                        (result.get("incomplete_details") or {}).get("reason") or "incomplete")
                elif kind in ("error", "response.failed"):
                    failure = (event.get("response") or {}).get("error") or event.get("error") or event
                    message = failure.get("message") if isinstance(failure, dict) else failure
                    raise ProviderError(f"The model service reported an error: {str(message)[:300]}")
        except (TimeoutError, OSError, http.client.HTTPException) as error:
            raise ProviderError(f"The connection to the model was lost: {error}") from error
        finally:
            response.close()
        if stop_reason != "cancelled":
            for index in sorted(calls):
                if calls[index]["name"]:
                    yield ToolCallReady(_finish_tool_call(index, calls[index]))
        output = final_output if final_output is not None else [done_items[index] for index in sorted(done_items)]
        yield TurnEnd(
            stop_reason=stop_reason,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            echo=_make_echo({"output": output} if output else {}, self.base_url),
        )
