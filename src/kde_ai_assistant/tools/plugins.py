"""User plugins: small Python files that add tools, loaded from the plugins folder when the user allows it.

With ``agent.load_plugins`` switched on (settings page, Behaviour; off by
default), every ``*.py`` file in ``$XDG_CONFIG_HOME/kde-ai-assistant/plugins``
is loaded for each request and its ``tools()`` function is called. It must
return a list of ``tools.registry.Tool``; each tool's ``risk`` (``read``,
``change`` or ``danger``) and optional ``classify`` are trusted as written,
because the user wrote or installed the file themselves. A minimal plugin::

    from kde_ai_assistant.tools.registry import RISK_READ, Tool, object_schema

    def tools():
        return [Tool("say_hello", "Greets someone.", object_schema({"name": {"type": "string"}}, ["name"]),
                     RISK_READ, lambda arguments: f"Hello, {arguments['name']}!")]

A plugin that fails to load or returns something else is skipped and named
in the request's warnings; it never stops the assistant. Plugin tools come
after the built-in ones, and a name already taken is skipped. Only files
owned by the user and not writable by others are loaded, since loading runs
their code inside the daemon.
"""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

from .registry import RISK_CHANGE, RISK_DANGER, RISK_READ, Tool


def plugin_dir() -> Path:
    from ..settings import config_dir

    return config_dir() / "plugins"


def load_plugins(folder: Path | None = None) -> tuple[list[Tool], list[str]]:
    """``(tools, warnings)`` from every plugin file in ``folder`` (default ``plugin_dir()``)."""
    folder = folder or plugin_dir()
    tools: list[Tool] = []
    warnings: list[str] = []
    for path in sorted(folder.glob("*.py")) if folder.is_dir() else []:
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            warnings.append(f"plugin {path.name} was not loaded: others can change it (fix with chmod go-w)")
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"kde_ai_assistant_plugin_{path.stem}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            offered = module.tools()
        except Exception as error:  # noqa: BLE001 - a broken plugin must not stop the assistant
            warnings.append(f"plugin {path.name} failed to load: {type(error).__name__}: {error}")
            continue
        if not isinstance(offered, list) or not all(isinstance(tool, Tool) for tool in offered):
            warnings.append(f"plugin {path.name}: tools() must return a list of Tool")
            continue
        for tool in offered:
            if tool.risk not in (RISK_READ, RISK_CHANGE, RISK_DANGER):
                warnings.append(f"plugin {path.name}: tool {tool.name} has an unknown risk {tool.risk!r}")
                continue
            tools.append(Tool(**{**tool.__dict__, "source": f"plugin:{path.stem}"}))
    return tools, warnings
