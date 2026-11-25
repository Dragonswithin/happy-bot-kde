"""Finds model services already running on this computer, for setup.

A user with a local model should not have to know its port. ``discover_local``
lists the TCP ports that something on this machine is listening on, asks each
one over loopback whether it is an OpenAI-compatible model service (``GET
/v1/models``), and returns those that answer like one with the models they
offer.

Scope and manners: only this machine is probed, only ports above 1023, only
with one short ``GET`` each, and only when the user asks (setup or the
settings page), never in the background. Listening ports are read from
``/proc/net/tcp`` and ``/proc/net/tcp6``; a service bound to all interfaces
is reachable on loopback and is included. Probes run in parallel with a short
timeout, so a full scan takes about a second.

A service's model list can be a catalogue of everything it could serve
rather than what it is serving. Services that also answer the widely copied
``GET /api/ps`` ("running models") are asked for it, and each model is then
marked ``loaded`` true or false with the loaded ones first; ``loaded_known``
says whether the service told us. Setup shows loaded models by default.

Whether a model can look at pictures (``sees_pictures``) is asked of a service on this computer
when a model is added or checked: services that call themselves OpenAI-compatible report it in
different places, so the answers below are tried in turn, each one short ``GET`` or ``POST``:
the model list's ``architecture.input_modalities`` holding "image" or its ``models`` entries'
``capabilities`` holding "multimodal" or "vision" (llama.cpp), then ``POST <root>/api/show``'s
``capabilities`` holding "vision" (Ollama and services that copy its API, such as FastFlowLM).
The answer is True, False when a service described the model without pictures, or None when no
service said.

Nothing here assumes a vendor or a well-known port.
"""

from __future__ import annotations

import http.client
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .providers.base import ProviderError
from .providers.openai_compatible import list_models

PROBE_TIMEOUT_SECONDS = 1.2
MAX_PORTS = 200
_LISTEN_STATE = "0A"
_LOCAL_V4 = ("0100007F", "00000000")           # 127.0.0.1, 0.0.0.0 in /proc byte order
_LOCAL_V6_SUFFIXES = ("00000000000000000000000001000000", "00000000000000000000000000000000",
                      "0000000000000000FFFF00000100007F")


def listening_ports(proc_root: Path = Path("/proc/net")) -> list[int]:
    """Ports above 1023 with a listener reachable on loopback, ascending."""
    ports: set[int] = set()
    for name in ("tcp", "tcp6"):
        try:
            lines = (proc_root / name).read_text(encoding="ascii", errors="replace").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 4 or fields[3] != _LISTEN_STATE:
                continue
            address, _, port_hex = fields[1].rpartition(":")
            if name == "tcp" and address not in _LOCAL_V4:
                continue
            if name == "tcp6" and address not in _LOCAL_V6_SUFFIXES:
                continue
            try:
                port = int(port_hex, 16)
            except ValueError:
                continue
            if port > 1023:
                ports.add(port)
    return sorted(ports)[:MAX_PORTS]


def loaded_model_names(root_url: str) -> set[str] | None:
    """Names a service reports as running via ``GET <root>/api/ps``, or None if it has no such endpoint."""
    try:
        with urlopen(f"{root_url}/api/ps", timeout=PROBE_TIMEOUT_SECONDS) as response:
            document = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as error:
        error.close()
        return None
    except (URLError, TimeoutError, OSError, ValueError, http.client.HTTPException):
        return None
    entries = document.get("models") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        return None
    names = set()
    for entry in entries:
        if isinstance(entry, dict):
            names.update(str(entry[key]) for key in ("name", "model") if entry.get(key))
    return names


def _probe(port: int) -> dict[str, Any] | None:
    root_url = f"http://127.0.0.1:{port}"
    base_url = f"{root_url}/v1"
    try:
        models = list_models(base_url, timeout=PROBE_TIMEOUT_SECONDS)
    except ProviderError:
        return None
    if not models:
        return None
    loaded = loaded_model_names(root_url) if len(models) > 1 else None
    for model in models:
        model["loaded"] = loaded is None or model["id"] in loaded
    models.sort(key=lambda model: not model["loaded"])
    return {"base_url": base_url, "port": port, "models": models, "loaded_known": loaded is not None}


def discover_local(skip_ports: tuple[int, ...] = (), ports: list[int] | None = None) -> list[dict[str, Any]]:
    """Local model services: ``[{"base_url", "port", "loaded_known", "models": [{"id", "context_window", "loaded"}]}]``."""
    candidates = [port for port in (ports if ports is not None else listening_ports()) if port not in skip_ports]
    if not candidates:
        return []
    with ThreadPoolExecutor(max_workers=24) as pool:
        return [found for found in pool.map(_probe, candidates) if found]


_PICTURE_CAPABILITIES = ("multimodal", "vision")


def _fetch_json(url: str, body: dict[str, Any] | None = None) -> Any:
    """One short request to a local service; None when it does not answer with JSON."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(url, data=data, method="POST" if data else "GET",
                      headers={"Content-Type": "application/json"} if data else {})
    try:
        with urlopen(request, timeout=PROBE_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as error:
        error.close()
        return None
    except (URLError, TimeoutError, OSError, ValueError, http.client.HTTPException):
        return None


def sees_pictures(base_url: str, model_id: str) -> bool | None:
    """Whether the service at ``base_url`` says ``model_id`` accepts images (see the module docstring)."""
    root = base_url.rstrip("/")
    said = False
    listing = _fetch_json(f"{root}/models")
    if isinstance(listing, dict):
        for entry in listing.get("data") or []:
            if isinstance(entry, dict) and entry.get("id") == model_id and isinstance(entry.get("architecture"), dict):
                said = True
                if "image" in (entry["architecture"].get("input_modalities") or []):
                    return True
        for entry in listing.get("models") or []:
            if isinstance(entry, dict) and model_id in (entry.get("name"), entry.get("model")) \
                    and isinstance(entry.get("capabilities"), list):
                said = True
                if any(item in _PICTURE_CAPABILITIES for item in entry["capabilities"]):
                    return True
    service_root = root[:-3] if root.endswith("/v1") else root
    shown = _fetch_json(f"{service_root}/api/show", {"model": model_id})
    if isinstance(shown, dict) and isinstance(shown.get("capabilities"), list):
        said = True
        if "vision" in shown["capabilities"]:
            return True
    return False if said else None
