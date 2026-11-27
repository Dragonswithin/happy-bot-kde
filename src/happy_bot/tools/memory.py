"""Chat tools for the same remembered facts shown in Behaviour settings."""

from __future__ import annotations

from typing import Any, Callable

from .. import remembered_facts
from .registry import RISK_DANGER, RISK_READ, Tool, ToolFailure, object_schema


def memory_tools(read_settings: Callable[[], dict[str, Any]], update_settings) -> list[Tool]:
    def remember(arguments: dict[str, Any]) -> str:
        try:
            fact = remembered_facts.normalize(arguments.get("fact"))
            added = False

            def mutate(settings):
                nonlocal added
                facts = settings["agent"]["remembered_facts"]
                if any(item.casefold() == fact.casefold() for item in facts):
                    return
                facts.append(fact)
                added = True

            update_settings(mutate)
        except (ValueError, OSError) as error:
            raise ToolFailure(str(error)) from error
        return "Saved in Behaviour → Remembered facts." if added else "That is already remembered."

    def forget(arguments: dict[str, Any]) -> str:
        words = str(arguments.get("about") or "").strip().casefold()
        if len(words) < 3:
            raise ToolFailure("Enter at least three characters from a remembered fact.")
        removed = 0

        def mutate(settings):
            nonlocal removed
            facts = settings["agent"]["remembered_facts"]
            kept = [item for item in facts if words not in item.casefold()]
            removed = len(facts) - len(kept)
            settings["agent"]["remembered_facts"] = kept

        try:
            update_settings(mutate)
        except (ValueError, OSError) as error:
            raise ToolFailure(str(error)) from error
        return f"Forgot {removed} fact(s)." if removed else "No remembered facts matched."

    def recall(arguments: dict[str, Any]) -> str:
        facts = read_settings()["agent"]["remembered_facts"]
        return "\n".join(f"- {fact}" for fact in facts) or "Nothing is remembered about the user yet."

    return [
        Tool("remember", "Save a fact for future requests only when the user explicitly asks to remember it.",
             object_schema({"fact": {"type": "string"}}, ["fact"]), RISK_DANGER, remember,
             classify=lambda a: (RISK_DANGER, "stores a personal fact for future requests"),
             summarize=lambda a: f"Remember: {str(a.get('fact', ''))[:120]}", private=True),
        Tool("forget", "Delete saved facts matching the phrase when the user explicitly asks to forget them.",
             object_schema({"about": {"type": "string"}}, ["about"]), RISK_DANGER, forget,
             classify=lambda a: (RISK_DANGER, "deletes matching remembered facts"),
             summarize=lambda a: f"Forget what mentions '{a.get('about', '?')}'", private=True),
        Tool("recall", "Read the saved facts the user asked Happy Bot to remember.",
             object_schema(), RISK_READ, recall, summarize=lambda a: "Check what is remembered", private=True),
    ]
