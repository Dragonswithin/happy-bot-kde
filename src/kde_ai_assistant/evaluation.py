"""``kde-ai-assistant eval``: a quick, safe check of how well a model drives the assistant.

Each scenario is an everyday request with the tools a good answer must use
(any one of ``expect_tools``) and, optionally, text the answer must contain.
Scenarios are sent as dry runs (``"dry_run": true``: only look-up tools are
offered, nothing on the computer changes) in fresh conversations, to the
active model or the one named with ``--model``. The result per scenario is
pass or fail, the tools the model used and the seconds it took, so models
can be compared on this machine with the user's own setup.

``run(stream, model)`` takes a function that sends one request and yields
the daemon's events (the CLI passes one built on ``/ask``), which keeps
this module free of HTTP and easy to test.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class Scenario:
    request: str
    expect_tools: tuple[str, ...]
    answer_pattern: str = ""


SCENARIOS = (
    Scenario("What time is it?", ("current_time",), r"\d"),
    Scenario("What is on my clipboard?", ("clipboard_text", "clipboard_history")),
    Scenario("Which window am I working in?", ("active_window", "list_windows")),
    Scenario("How full is my main disk?", ("disk_usage", "list_drives", "run_command", "system_info")),
    Scenario("Which files did I use most recently?", ("recent_files",)),
    Scenario("Is anything playing music right now?", ("now_playing",)),
    Scenario("Find documents about the roadmap on my computer.", ("__file_search__", "find_files", "list_directory")),
    Scenario("What did you change on my computer today?", ("recent_activity",)),
)

Stream = Callable[[str, str], Iterable[dict[str, Any]]]


def run(stream: Stream, model: str = "", file_search_tool: str = "") -> list[dict[str, Any]]:
    """Run every scenario; each result is ``{request, passed, tools, seconds, problem}``."""
    results = []
    for scenario in SCENARIOS:
        expected = {file_search_tool if name == "__file_search__" else name for name in scenario.expect_tools} - {""}
        started = time.monotonic()
        tools: list[str] = []
        answer: list[str] = []
        problem = ""
        for event in stream(scenario.request, model):
            if event.get("type") == "tool_call":
                tools.append(event.get("name", ""))
            elif event.get("type") == "text_delta":
                answer.append(event.get("text", ""))
            elif event.get("type") == "error":
                problem = event.get("message", "error")
        text = "".join(answer)
        if not problem and not expected.intersection(tools):
            problem = f"did not use {' or '.join(sorted(expected))}"
        if not problem and scenario.answer_pattern and not re.search(scenario.answer_pattern, text):
            problem = "the answer did not contain what was expected"
        if not problem and not text.strip():
            problem = "no answer"
        results.append({"request": scenario.request, "passed": not problem, "tools": tools,
                        "seconds": round(time.monotonic() - started, 1), "problem": problem})
    return results
