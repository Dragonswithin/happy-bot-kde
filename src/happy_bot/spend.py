"""Token use and money spent on hosted models, per calendar month, with an optional cap.

A model entry may carry prices (``input_price`` and ``output_price``, in the
user's currency per million tokens, settings.py; both default to 0 = free,
as for a local model). After every request ``record`` adds the tokens the
service reported (``TurnEnd`` in ``conversation.py``) and their cost to the
ledger, ``$XDG_DATA_HOME/happy-bot/spend.json`` (0600), kept as one
entry per month and model so it survives restarts but stays small.

``agent.monthly_spend_cap`` (0 = no cap) stops new requests to priced models
once the month's total reaches it (``over_cap``); local and unpriced models
are never stopped. ``month_summary`` is what the CLI and the popup show.

The ledger is written under ``_lock``; a damaged file is started afresh.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .runtime_paths import APP_DIR_NAME, write_private_file

_lock = threading.Lock()


def ledger_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME / "spend.json"


def _month() -> str:
    return time.strftime("%Y-%m")


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def cost(model: dict[str, Any], input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * float(model.get("input_price", 0)) + output_tokens * float(model.get("output_price", 0))) / 1e6


def record(name: str, model: dict[str, Any], input_tokens: int, output_tokens: int, path: Path | None = None) -> float:
    """Add one request's tokens and cost; returns the cost."""
    target = path or ledger_path()
    spent = cost(model, input_tokens, output_tokens)
    with _lock:
        data = _load(target)
        entry = data.setdefault(_month(), {}).setdefault(name, {"input_tokens": 0, "output_tokens": 0, "cost": 0.0})
        entry["input_tokens"] += input_tokens
        entry["output_tokens"] += output_tokens
        entry["cost"] = round(entry["cost"] + spent, 6)
        months = sorted(data)[-24:]
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_private_file(target, json.dumps({month: data[month] for month in months}, indent=1))
    return spent


def month_total(path: Path | None = None) -> float:
    with _lock:
        return round(sum(entry.get("cost", 0) for entry in _load(path or ledger_path()).get(_month(), {}).values()), 6)


def over_cap(model: dict[str, Any], cap: float, path: Path | None = None) -> bool:
    """Whether a request to ``model`` must be refused because this month's spending reached ``cap``."""
    priced = float(model.get("input_price", 0)) > 0 or float(model.get("output_price", 0)) > 0
    return bool(cap) and priced and month_total(path) >= cap


def month_summary(path: Path | None = None) -> dict[str, Any]:
    with _lock:
        models = _load(path or ledger_path()).get(_month(), {})
    return {"month": _month(), "models": models, "total_cost": round(sum(item.get("cost", 0) for item in models.values()), 4)}
