"""Adding an AI model with one press and placing it in the user's order of models to ask.

The AI Model page's choices all end here (``POST /models/use``): a model service found on this
computer, an online service picked from ``model_presets`` with the user's API key, or an address
typed by hand. ``use`` then:

1. builds the model entry: the preset's address (or the given one), the model id, the key, the
   context window the service reports for that model (``list_models``), else the preset's or the
   settings default, whether it can look at pictures when a service on this computer says so
   (``model_discovery.sees_pictures``; otherwise the earlier setting stays), and a suggested
   model's published prices, for the spending cap;
2. names it after the preset or the model id, reusing the name of an identical entry;
3. places it in ``model_order`` by its ``job``: ``main`` first (it answers), ``backup`` right after
   the first (it answers when the first does not), ``none`` at the end (an existing model keeps
   its place);
4. saves through ``AssistantServer.replace_settings`` and runs the full compatibility check
   (``model_check.run``: answering, one and two tool calls, its tool results, continuing another
   AI's chat, pictures). A model that does not answer is removed again and the previous settings
   put back; one with a problem or a limitation is kept, and the message says what it is
   (``model_check.summary``), so a service Happy Bot misreads is noticed when it is added.

``check_model``, one small request asking for a tool call, is what ``POST /models/test`` runs.
Both block until the model has answered; a hosted model is asked only when the user pressed a
button.
"""

from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING, Any

from . import model_check, model_discovery, model_presets
from . import settings as settings_store
from .conversation import Message, TextDelta, ToolCallReady, ToolSpec
from .providers import ProviderError, create_provider
from .providers.openai_compatible import list_models
from .redaction import is_local_address

if TYPE_CHECKING:
    from .daemon_http import AssistantServer

JOBS = ("main", "backup", "none")
_PROBE_TOOL = ToolSpec("confirm_ready", "Call this to confirm you can use tools.",
                       {"type": "object", "properties": {}, "required": []})


class ModelChoiceError(ValueError):
    """The model cannot be added as given; the message is shown to the user."""


def check_model(model: dict[str, Any]) -> dict[str, Any]:
    """``{"answers": True, "tools": bool, "reply"}``; raises ``ProviderError`` when the model does not answer."""
    messages = [
        Message("system", "You are being tested. Call the confirm_ready tool. Do not reply with text."),
        Message("user", "Call confirm_ready now."),
    ]
    called, text = False, ""
    for event in create_provider(model).stream(messages, [_PROBE_TOOL], threading.Event()):
        if isinstance(event, ToolCallReady) and event.call.name == "confirm_ready":
            called = True
        elif isinstance(event, TextDelta):
            text += event.text
    return {"answers": True, "tools": called, "reply": text[:200]}


def _entry(body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    preset = model_presets.find(str(body.get("preset") or ""))
    base_url = (preset["base_url"] if preset else str(body.get("base_url") or "")).strip().rstrip("/")
    model_id = str(body.get("model") or "").strip()
    api_key = str(body.get("api_key") or "").strip()
    if not base_url.startswith(("http://", "https://")):
        raise ModelChoiceError("The address must start with http:// or https://")
    if not model_id:
        raise ModelChoiceError("Choose a model first.")
    if preset and not api_key:
        raise ModelChoiceError(f"Paste your {preset['title']} API key first.")
    window = 0
    try:
        window = next((item["context_window"] for item in list_models(base_url, api_key)
                       if item["id"] == model_id), 0)
    except ProviderError:
        pass  # some services do not list models; the preset's or the default window is used
    entry = {"provider": (preset or {}).get("provider", "openai_compatible"), "base_url": base_url, "model": model_id, "api_key": api_key,
             "context_window": window or (preset or {}).get("context_window") or settings_store.DEFAULT_CONTEXT_WINDOW}
    if is_local_address(base_url) and model_discovery.sees_pictures(base_url, model_id):
        entry["vision"] = True
    if preset:
        prices = model_presets.suggested(preset["id"], model_id)
        entry.update({key: prices[key] for key in ("input_price", "output_price") if key in prices})
    # "claude-opus-5-5", not "claude-claude-opus-5-5": the service's name only when the id lacks it.
    base = f"{preset['id']}-{model_id}" if preset and not model_id.lower().startswith(preset["id"]) else model_id
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", base).strip("-")[:56] or "model", entry


def _name_for(wanted: str, entry: dict[str, Any], models: dict[str, Any]) -> str:
    for name, existing in models.items():
        if existing["base_url"].rstrip("/") == entry["base_url"] and existing["model"] == entry["model"]:
            return name
    name, number = wanted, 2
    while name in models:
        name, number = f"{wanted}-{number}", number + 1
    return name


def use(server: "AssistantServer", body: dict[str, Any]) -> dict[str, Any]:
    job = str(body.get("job") or "main")
    if job not in JOBS:
        return {"ok": False, "error": f"unknown job '{job}'"}
    try:
        wanted, entry = _entry(body)
    except ModelChoiceError as error:
        return {"ok": False, "error": str(error)}
    previous = server.settings
    name = _name_for(wanted, entry, previous["models"])
    kept = previous["models"].get(name, {})
    if not entry["api_key"] and kept.get("api_key"):
        entry["api_key"] = kept["api_key"]  # re-adding a stored model without retyping its key
    if not entry["context_window"] and kept.get("context_window"):
        entry["context_window"] = kept["context_window"]
    order = [other for other in previous.get("model_order", []) if other != name]
    if job == "main":
        order.insert(0, name)
    elif job == "backup":
        order.insert(min(1, len(order)), name)
    elif name in previous.get("model_order", []):
        order = list(previous["model_order"])
    else:
        order.append(name)
    updated = {**previous, "models": {**previous["models"], name: {**kept, **entry}},
               "model_order": order, "active_model": order[0]}
    try:
        stored = server.replace_settings(updated)
    except settings_store.SettingsError as error:
        return {"ok": False, "error": str(error)}
    results = model_check.run(stored["models"][name])
    answered = next((item for item in results if item["check"] == "answers"), None)
    if answered is None or answered["status"] == "fail":
        server.replace_settings(previous)
        reason = answered["detail"] if answered else "no answer"
        return {"ok": False, "error": f"It did not answer, so it was not added: {reason}"}
    passed, message = model_check.summary(name, results)
    tools = any(item["check"] == "tool_call" and item["status"] == "pass" for item in results)
    return {"ok": True, "name": name, "tools": tools, "passed": passed, "results": results, "message": message}
