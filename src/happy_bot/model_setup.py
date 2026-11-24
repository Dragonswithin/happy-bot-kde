"""Adding an AI model with one press and giving it a job: answer first, or answer when that one fails.

The AI Model page's choices all end here (``POST /models/use``): a model service found on this
computer, an online service picked from ``model_presets`` with the user's API key, or an address
typed by hand. ``use`` then:

1. builds the model entry: the preset's address (or the given one), the model id, the key, the
   context window the service reports for that model (``list_models``), else the preset's or the
   settings default, and a suggested model's published prices, for the spending cap;
2. names it after the preset or the model id, reusing the name of an identical entry;
3. gives it its ``job``: ``main`` (``active_model``: it answers first), ``backup``
   (``agent.fallback_model``: it answers when the main one does not; only a model on this
   computer, so nothing is sent online without the user choosing that model as main) or ``none``;
4. saves through ``AssistantServer.replace_settings`` and checks the model (``check_model``): it
   must answer, and is asked to call a tool. A model that does not answer is removed again and the
   previous settings put back; one that answers without using the tool is kept, with a warning
   that it cannot search or act.

``check_model`` is also what ``POST /models/test`` runs. It sends one small request to the model
and blocks until it finishes; a hosted model is asked only when the user pressed a button.
"""

from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING, Any

from . import model_presets
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
    entry = {"provider": "openai_compatible", "base_url": base_url, "model": model_id, "api_key": api_key,
             "context_window": window or (preset or {}).get("context_window") or settings_store.DEFAULT_CONTEXT_WINDOW}
    if preset:
        prices = model_presets.suggested(preset["id"], model_id)
        entry.update({key: prices[key] for key in ("input_price", "output_price") if key in prices})
    base = f"{preset['id']}-{model_id}" if preset else model_id
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
    if job == "backup" and not is_local_address(entry["base_url"]):
        return {"ok": False, "error": "Only a model on this computer can be the backup, so nothing is sent online "
                                      "unless you make an online model the main one."}
    previous = server.settings
    name = _name_for(wanted, entry, previous["models"])
    kept = previous["models"].get(name, {})
    if not entry["api_key"] and kept.get("api_key"):
        entry["api_key"] = kept["api_key"]  # re-adding a stored model without retyping its key
    updated = {**previous, "models": {**previous["models"], name: {**kept, **entry}},
               "agent": dict(previous.get("agent") or settings_store.default_agent())}
    if job == "main":
        updated["active_model"] = name
        if updated["agent"].get("fallback_model") == name:
            updated["agent"]["fallback_model"] = ""
    elif job == "backup":
        updated["agent"]["fallback_model"] = name
    try:
        stored = server.replace_settings(updated)
        result = check_model(stored["models"][name])
    except settings_store.SettingsError as error:
        return {"ok": False, "error": str(error)}
    except ProviderError as error:
        server.replace_settings(previous)
        return {"ok": False, "error": f"It did not answer, so it was not added: {error}"}
    message = (f"{name} answers and can use tools. It is ready." if result["tools"] else
               f"{name} answers but did not use a tool, so Happy Bot cannot search or act with it.")
    return {"ok": True, "name": name, "tools": result["tools"], "message": message}
