"""A compatibility check of one configured AI: does Happy Bot talk to it correctly?

Model services that call themselves OpenAI-compatible differ in the details Happy Bot depends on,
and a difference shows up only when that feature is used: Gemini, for one, sends parallel tool
calls without the ``index`` OpenAI's own stream has, which once glued calls together. ``run`` sends
the model a few small requests through the same provider code a conversation uses
(``providers.create_provider``), each exercising one feature, and reports per check:

- ``answers``: a plain streamed answer (and whether the service reports token use, which spending
  limits need for an online AI).
- ``tool_call``: one tool call with nested arguments that arrive as one valid JSON object.
- ``parallel_calls``: two tool calls in one reply, each whole and separate. A model that calls them
  one at a time is fine (``warn``); merged or broken calls are a ``fail``.
- ``tool_result``: the model's own tool call and its result sent back, as the agent loop does
  (with the call's ``echo``, such as Gemini's thought signatures or a Responses API replay), and an
  answer that uses the result.
- ``handover``: a conversation whose earlier tool call came from another AI (no echo), as when a
  request is handed down the model order; the service must accept it.
- ``picture`` (only for a model marked ``vision``): a small generated picture of one colour, which
  the model must name (``Message.images``).

Each result is ``{"check", "status", "detail"}`` with status ``pass``, ``warn`` (works, with a
limitation worth knowing), ``fail`` (a request failed or Happy Bot misread the reply), or ``skip``.
Nothing on the computer is touched: the tools are made up and never run. Each request blocks until
the model answers (a local model may take a while); the whole check is a handful of small requests,
so for an online AI it costs a fraction of a cent. ``POST /models/check`` and ``happy-bot model
check`` run it; adding a model keeps the quicker single-request ``model_setup.check_model``.
"""

from __future__ import annotations

import struct
import tempfile
import threading
import zlib
from pathlib import Path
from typing import Any

from .conversation import Message, TextDelta, ToolCall, ToolCallReady, ToolSpec, TurnEnd
from .providers import ProviderError, create_provider
from .redaction import is_local_address

WEATHER = ToolSpec("get_weather", "The weather in a city.", {
    "type": "object",
    "properties": {"city": {"type": "string"},
                   "units": {"type": "object", "properties": {"system": {"type": "string", "enum": ["metric", "imperial"]}}}},
    "required": ["city"]})
CLOCK = ToolSpec("get_time", "The current time in a time zone.", {
    "type": "object", "properties": {"zone": {"type": "string"}}, "required": ["zone"]})
SYSTEM = Message("system", "You are being tested by the program you work in. Follow the request exactly. "
                           "The tools are test tools; call them when asked.")
WEATHER_RESULT = "Paris: 17 degrees Celsius, light rain, report number 4242."


class _Reply:
    """One streamed reply: its text, tool calls, echo and token counts."""

    def __init__(self, provider: Any, messages: list[Message], tools: list[ToolSpec]) -> None:
        self.text, self.calls, self.echo, self.input_tokens = "", [], "", 0
        for event in provider.stream(messages, tools, threading.Event()):
            if isinstance(event, TextDelta):
                self.text += event.text
            elif isinstance(event, ToolCallReady):
                self.calls.append(event.call)
            elif isinstance(event, TurnEnd):
                self.echo, self.input_tokens = event.echo, event.input_tokens

    def as_message(self) -> Message:
        """The reply as the agent loop stores it, so it can be sent back."""
        return Message("assistant", self.text, tuple(self.calls), echo=self.echo)


def _result(check: str, status: str, detail: str) -> dict[str, str]:
    return {"check": check, "status": status, "detail": detail}


def _broken(calls: list[ToolCall]) -> list[str]:
    return [f"{call.name or '(no name)'}: {call.arguments_error}" for call in calls if call.arguments_error]


def _png(rgb: tuple[int, int, int], size: int = 32) -> bytes:
    """A plain PNG of one colour, built without an image library."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def run(model: dict[str, Any]) -> list[dict[str, str]]:
    """Run every check on one model entry (see the module docstring)."""
    try:
        provider = create_provider(model)
    except ProviderError as error:
        return [_result("answers", "fail", str(error))]
    results = []

    try:
        reply = _Reply(provider, [SYSTEM, Message("user", "Reply with the single word: ready")], [])
    except ProviderError as error:
        return [_result("answers", "fail", str(error))]
    if not reply.text.strip():
        results.append(_result("answers", "fail", "the reply had no text"))
    elif reply.input_tokens == 0 and not is_local_address(str(model.get("base_url") or "")):
        results.append(_result("answers", "warn", "answers, but reports no token use, so its spending cannot be counted"))
    else:
        results.append(_result("answers", "pass", f"answered: {reply.text.strip()[:60]}"))

    asked = [SYSTEM, Message("user", "Call get_weather for the city Paris with units system metric. Do not answer yet.")]
    single: _Reply | None = None
    try:
        single = _Reply(provider, asked, [WEATHER, CLOCK])
        weather = [call for call in single.calls if call.name == "get_weather"]
        if _broken(single.calls):
            results.append(_result("tool_call", "fail", "Happy Bot could not read the call: " + "; ".join(_broken(single.calls))))
        elif not weather:
            results.append(_result("tool_call", "warn", "it answered without calling the tool, so it cannot search or act"))
        elif "paris" not in str(weather[0].arguments.get("city", "")).lower():
            results.append(_result("tool_call", "warn", f"called the tool with unexpected arguments: {weather[0].arguments}"))
        else:
            results.append(_result("tool_call", "pass", f"get_weather {weather[0].arguments}"))
    except ProviderError as error:
        results.append(_result("tool_call", "fail", str(error)))

    try:
        both = _Reply(provider, [SYSTEM, Message(
            "user", "In this one reply, call get_weather for Paris AND get_time for the zone Asia/Tokyo: both calls "
                    "at once. Do not answer yet.")], [WEATHER, CLOCK])
        names = sorted(call.name for call in both.calls)
        if _broken(both.calls):
            results.append(_result("parallel_calls", "fail", "calls arrived broken: " + "; ".join(_broken(both.calls))))
        elif names == ["get_time", "get_weather"]:
            results.append(_result("parallel_calls", "pass", "two separate, valid calls"))
        elif len(both.calls) == 1:
            results.append(_result("parallel_calls", "warn", "calls one tool at a time (slower, but works)"))
        else:
            results.append(_result("parallel_calls", "warn", f"made these calls: {names or 'none'}"))
    except ProviderError as error:
        results.append(_result("parallel_calls", "fail", str(error)))

    weather_calls = [call for call in (single.calls if single else []) if call.name == "get_weather" and not call.arguments_error]
    if not weather_calls or single is None:
        results.append(_result("tool_result", "skip", "needs a working tool call first"))
    else:
        own = single.as_message()
        back = [Message("tool", WEATHER_RESULT if call is weather_calls[0] else "Not needed.", tool_call_id=call.id)
                for call in own.tool_calls]
        try:
            answer = _Reply(provider, [*asked, own, *back, Message("user", "Now tell me the temperature and the report number.")],
                            [WEATHER, CLOCK])
            if "4242" in answer.text or "17" in answer.text:
                results.append(_result("tool_result", "pass", "used the tool's result"))
            else:
                results.append(_result("tool_result", "warn", f"answered without the result: {answer.text.strip()[:80] or '(no text)'}"))
        except ProviderError as error:
            results.append(_result("tool_result", "fail", f"sending its own tool call back failed: {error}"))

    foreign = ToolCall("call_from_another_ai", "get_weather", {"city": "Paris"})
    try:
        handed = _Reply(provider, [SYSTEM, Message("user", "What is the weather in Paris?"),
                                   Message("assistant", "", (foreign,)),
                                   Message("tool", WEATHER_RESULT, tool_call_id=foreign.id),
                                   Message("user", "Continue: tell me the report number.")], [WEATHER, CLOCK])
        results.append(_result("handover", "pass" if "4242" in handed.text else "warn",
                               "continues another AI's conversation" if "4242" in handed.text
                               else f"accepted it, but answered: {handed.text.strip()[:80] or '(no text)'}"))
    except ProviderError as error:
        results.append(_result("handover", "fail", f"refuses a conversation another AI started: {error}"))

    if not model.get("vision"):
        results.append(_result("picture", "skip", "not marked as seeing pictures"))
    else:
        with tempfile.TemporaryDirectory() as folder:
            picture = Path(folder, "red.png")
            picture.write_bytes(_png((220, 20, 20)))
            try:
                seen = _Reply(provider, [SYSTEM, Message("user", "What colour is this picture? Answer with one word.",
                                                         images=(str(picture),))], [])
                results.append(_result("picture", "pass" if "red" in seen.text.lower() else "warn",
                                       f"said: {seen.text.strip()[:40] or '(no text)'}"))
            except ProviderError as error:
                results.append(_result("picture", "fail", f"refused the picture: {error}"))
    return results
