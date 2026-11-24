"""Memory tools: the assistant remembers or forgets a fact about the user when asked.

What the assistant knows about the user lives in one visible place: their
instructions on the settings page (``agent.instructions``). ``remember``
appends a line there ("My notes are in ~/Documents/Notes", "I live in
Vancouver"), and ``forget`` removes the lines that mention some words, so
every remembered fact can be read and edited by the user on the Behaviour
page, and nothing is kept anywhere hidden. New facts take effect from the
next new conversation, like any instruction.

The tools change settings through the daemon (``read_settings`` /
``update_settings``, as the routine tools do); the settings' length limit
(``settings.MAX_INSTRUCTIONS_CHARS``) applies. ``remember`` is ``change``;
``forget`` is ``danger`` because it deletes something the user told it.
"""

from __future__ import annotations

from typing import Any, Callable

from .registry import RISK_CHANGE, RISK_DANGER, RISK_READ, Tool, ToolFailure, object_schema


def memory_tools(read_settings: Callable[[], dict[str, Any]], update_settings) -> list[Tool]:
    from ..settings import SettingsError

    def instructions() -> str:
        return (read_settings().get("agent") or {}).get("instructions", "")

    def save(text: str) -> None:
        def mutate(settings: dict[str, Any]) -> None:
            settings.setdefault("agent", {})["instructions"] = text

        try:
            update_settings(mutate)
        except SettingsError as error:
            raise ToolFailure(f"{error}. Ask the user to shorten their instructions on the Behaviour page.") from error

    def remember(arguments: dict[str, Any]) -> str:
        fact = " ".join(str(arguments.get("fact") or "").split())
        if not fact:
            raise ToolFailure("'fact' is required")
        current = instructions()
        if fact.lower() in current.lower():
            return "That is already remembered."
        save((current.rstrip() + "\n" if current.strip() else "") + f"- {fact}")
        return f"Remembered: {fact}. It is listed in the assistant's settings under Behaviour, Your instructions."

    def forget(arguments: dict[str, Any]) -> str:
        words = str(arguments.get("about") or "").strip().lower()
        if len(words) < 3:
            raise ToolFailure("'about' must be at least a few letters of what to forget")
        lines = instructions().splitlines()
        kept = [line for line in lines if words not in line.lower()]
        if len(kept) == len(lines):
            return f"Nothing remembered mentions '{words}'."
        save("\n".join(kept).strip())
        return f"Forgot {len(lines) - len(kept)} line(s) mentioning '{words}'."

    def recall(arguments: dict[str, Any]) -> str:
        return instructions() or "Nothing is remembered about the user yet."

    return [
        Tool("remember", "Remember a fact or preference about the user for future conversations, when they ask "
             "you to (\"remember that my notes are in ~/Notes\").", object_schema({"fact": {"type": "string"}}, ["fact"]),
             RISK_CHANGE, remember, summarize=lambda a: f"Remember: {str(a.get('fact', ''))[:120]}"),
        Tool("forget", "Forget remembered facts that mention some words, when the user asks.",
             object_schema({"about": {"type": "string"}}, ["about"]), RISK_DANGER, forget,
             classify=lambda a: (RISK_DANGER, "deletes something you asked it to remember"),
             summarize=lambda a: f"Forget what mentions '{a.get('about', '?')}'"),
        Tool("recall", "Everything the user has asked the assistant to remember (their standing instructions).",
             object_schema(), RISK_READ, recall, summarize=lambda a: "Check what is remembered"),
    ]
