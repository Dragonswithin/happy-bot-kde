"""Validation and edits for the local remembered-facts list."""

from __future__ import annotations

MAX_FACT_LENGTH = 500
MAX_FACTS = 100
TOOL_NAMES = frozenset({"remember", "recall", "forget"})


def normalize(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Enter a remembered fact as text.")
    fact = " ".join(value.split())
    if not fact or len(fact) > MAX_FACT_LENGTH:
        raise ValueError(f"A remembered fact needs 1–{MAX_FACT_LENGTH} characters.")
    return fact


PROMPTS = {
    "name": "Preferred name: {}",
    "language": "Preferred language: {}",
    "units": "Preferred measurement units: {}",
}


def record(text: object, local_only: object = True, prompt: object = "") -> dict:
    if not isinstance(local_only, bool):
        raise ValueError("Choose whether the fact is local only.")
    if not isinstance(prompt, str) or (prompt and prompt not in PROMPTS):
        raise ValueError("Unknown remembered fact prompt.")
    return {"text": normalize(text), "local_only": local_only, "prompt": prompt}


def display(fact: dict) -> str:
    return PROMPTS.get(fact["prompt"], "{}").format(fact["text"])


def validate(values: object) -> list[dict]:
    if not isinstance(values, list) or len(values) > MAX_FACTS:
        raise ValueError(f"Remembered facts must be a list of at most {MAX_FACTS} entries.")
    facts = [record(value.get("text"), value.get("local_only", True), value.get("prompt", ""))
             if isinstance(value, dict) else record(value) for value in values]
    if len({display(value).casefold() for value in facts}) != len(facts):
        raise ValueError("That fact is already remembered.")
    prompts = [fact["prompt"] for fact in facts if fact["prompt"]]
    if len(set(prompts)) != len(prompts):
        raise ValueError("This prompt already has a saved answer.")
    return facts


def split_legacy(instructions: str, suggested: str) -> tuple[str, list[dict]]:
    """Recognize the old append format only after the exact suggested instructions."""
    if not instructions.startswith(suggested + "\n"):
        return instructions, []
    tail = instructions[len(suggested):].splitlines()
    if any(line.strip() and not line.startswith("- ") for line in tail):
        return instructions, []
    try:
        return suggested, validate([line[2:] for line in tail if line.startswith("- ")])
    except ValueError:
        return instructions, []


def move_instruction(agent: dict, line: str) -> None:
    """Move a line selected by the user from a custom legacy instruction block."""
    lines = agent["instructions"].splitlines()
    if not isinstance(line, str) or not line.startswith("- ") or lines.count(line) != 1:
        raise ValueError("That instruction changed. Reload and select it again.")
    agent["remembered_facts"] = validate([*agent["remembered_facts"], normalize(line[2:])])
    lines.remove(line)
    agent["instructions"] = "\n".join(lines)
