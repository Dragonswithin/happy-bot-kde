#!/usr/bin/env python3
"""Record what real AI services stream back, for the replay tests (tests/test_recorded_replies.py).

Services that call themselves OpenAI-compatible differ in how they stream (Gemini sends tool calls
without an ``index``, for one), and a difference shows up only against the real service. This
script sends a few fixed, synthetic requests to configured models through Happy Bot's own provider
code (``happy_bot.providers``) and saves the raw bytes each service sent back under
``tests/fixtures/model_replies/<label>/``: one ``<case>.sse`` per request and a ``cases.json``
manifest with the provider kind, the model id, when it was recorded and what a correct reading of
each reply is. The replay test then feeds those bytes to the providers with no network, so a code
change that misreads one service fails the test suite.

Cases (``model_check``'s requests): ``text`` (a one-word answer), ``one_call`` (get_weather for
Paris), ``two_calls`` (get_weather and get_time in one reply) and ``after_result`` (the model's own
call and its result sent back; the answer must use the result).

Usage (reads the daemon's settings file; needs no running daemon):

    scripts/record_model_replies.py LABEL=MODEL [LABEL=MODEL ...]            # plan only
    scripts/record_model_replies.py --record gemini=gemini-4-hydrogen ...    # send and save

MODEL is a name from the AI Model page. Without ``--record`` nothing is sent. With it, each model
gets four small requests (for an online one, a fraction of a cent). A recording is refused, and
nothing for that label is written, when a reply contains the model's API key, the user's name, home
folder or host name, or when the current code cannot read it (then the code needs fixing first).
Recordings hold only the synthetic requests' replies; no conversation or file of the user is sent.
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import io
import json
import os
import platform
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from happy_bot import model_check, settings as settings_store  # noqa: E402
from happy_bot.conversation import Message  # noqa: E402
from happy_bot.providers import create_provider, openai_compatible, openai_responses  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "model_replies"
TOOLS = [model_check.WEATHER, model_check.CLOCK]
ASK_ONE = [model_check.SYSTEM, Message("user", "Call get_weather for the city Paris with units system metric. Do not answer yet.")]
ASK_TWO = [model_check.SYSTEM, Message("user", "In this one reply, call get_weather for Paris AND get_time for the zone "
                                               "Asia/Tokyo: both calls at once. Do not answer yet.")]
ASK_TEXT = [model_check.SYSTEM, Message("user", "Reply with the single word: ready")]


class Recorder:
    """Replaces the providers' ``urlopen`` so each reply's raw bytes are kept as they arrive."""

    def __init__(self) -> None:
        self.bodies: list[bytes] = []
        self.real = openai_compatible.urlopen

    def __call__(self, request, timeout=None):
        with self.real(request, timeout=timeout) as response:
            body = response.read()
        self.bodies.append(body)
        return io.BytesIO(body)


def _stream(provider, messages, tools):
    return model_check._Reply(provider, messages, tools)


def record(label: str, name: str, model: dict) -> dict:
    """The four cases for one model: ``{case: (bytes, expectation)}``; raises ValueError when unusable."""
    recorder = Recorder()
    openai_compatible.urlopen = openai_responses.urlopen = recorder
    try:
        provider = create_provider(model)
        cases = {}
        reply = _stream(provider, ASK_TEXT, [])
        cases["text"] = (recorder.bodies[-1], {"text_contains": "ready"})
        one = _stream(provider, ASK_ONE, TOOLS)
        cases["one_call"] = (recorder.bodies[-1], {"calls": [[call.name, call.arguments] for call in one.calls]})
        two = _stream(provider, ASK_TWO, TOOLS)
        cases["two_calls"] = (recorder.bodies[-1], {"calls": [[call.name, call.arguments] for call in two.calls]})
        for kind, parsed in (("one_call", one), ("two_calls", two)):
            broken = [call.arguments_error for call in parsed.calls if call.arguments_error]
            if broken or not parsed.calls:
                raise ValueError(f"{label}: {kind} could not be read with the current code ({broken or 'no calls'})")
        own = one.as_message()
        back = [Message("tool", model_check.WEATHER_RESULT, tool_call_id=call.id) for call in own.tool_calls]
        _stream(provider, [*ASK_ONE, own, *back, Message("user", "Now tell me the temperature and the report number.")], TOOLS)
        cases["after_result"] = (recorder.bodies[-1], {"text_contains": "4242"})
        if not reply.text.strip():
            raise ValueError(f"{label}: the text reply was empty")
        return cases
    finally:
        openai_compatible.urlopen = openai_responses.urlopen = recorder.real


def private_words(model: dict) -> list[str]:
    words = [getpass.getuser(), str(Path.home()), platform.node()]
    if model.get("api_key"):
        words.append(str(model["api_key"]))
    words += [str(value) for value in (model.get("headers") or {}).values()]
    return [word for word in words if len(word) >= 3]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pairs", nargs="+", metavar="LABEL=MODEL")
    parser.add_argument("--record", action="store_true", help="Send the requests and save the replies.")
    args = parser.parse_args()
    settings = settings_store.load_settings()
    plan = []
    for pair in args.pairs:
        label, _, name = pair.partition("=")
        if not label or not name or name not in settings.get("models", {}):
            parser.error(f"{pair}: give LABEL=MODEL with a model from the AI Model page")
        plan.append((label, name, settings["models"][name]))
    for label, name, model in plan:
        print(f"{label}: {name} ({model['provider']}, {model['model']}) -> {FIXTURES / label}, 4 requests")
    if not args.record:
        print("Nothing sent. Add --record to send the requests and save the replies.")
        return 0
    failed = False
    for label, name, model in plan:
        try:
            cases = record(label, name, model)
        except Exception as error:  # report every model, then fail
            print(f"{label}: not saved: {error}", file=sys.stderr)
            failed = True
            continue
        # Whole words only: a user named "ken" must not match "prompt_tokens".
        leaked = [word for word in private_words(model) for body, _ in cases.values()
                  if re.search(rb"(?<![A-Za-z0-9_])" + re.escape(word.encode()) + rb"(?![A-Za-z0-9_])", body)]
        if leaked:
            print(f"{label}: not saved: a reply contains private text", file=sys.stderr)
            failed = True
            continue
        folder = FIXTURES / label
        folder.mkdir(parents=True, exist_ok=True)
        for case, (body, _) in cases.items():
            (folder / f"{case}.sse").write_bytes(body)
        manifest = {"provider": model["provider"], "model": model["model"],
                    "recorded": datetime.date.today().isoformat(),
                    "cases": {case: expectation for case, (_, expectation) in cases.items()}}
        (folder / "cases.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{label}: saved {len(cases)} replies")
    return 1 if failed else 0


if __name__ == "__main__":
    os.umask(0o022)
    sys.exit(main())
