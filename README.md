# KDE AI Assistant

A Plasma 6 panel applet and small per-user daemon for a fast desktop AI
sidebar. No response backend is currently configured; the project remains a
scaffold for a future local or hosted assistant.

## What It Provides

- Plasma panel icon with idle/thinking/offline status.
- Popup sidebar for general assistant chat.
- Context actions for clipboard text and active-window metadata.
- Explicit screenshot capture through Spectacle.
- Button to open the full assistant web UI.
- Per-user daemon with loopback HTTP API and transient runtime state.

## Current State

The response path is intentionally disabled. The daemon still contains the
desktop-context, screenshot, and optional full-web-UI plumbing, but chat
requests return an unavailable response until a new backend is selected.

- KWin DBus for active-window metadata.
- Klipper DBus for clipboard text.
- Spectacle for user-requested screenshots.

Useful environment overrides:

- `KDE_AI_ASSISTANT_DAEMON_HOST`
- `KDE_AI_ASSISTANT_DAEMON_PORT`
- `KDE_AI_ASSISTANT_DAEMON_URL`
- `KDE_AI_ASSISTANT_FULL_UI_URL`
- `KDE_AI_ASSISTANT_ROOT_BROKER`
- `KDE_AI_ASSISTANT_ADMIN_GROUP`

## Install

From this repo:

```bash
scripts/install.sh
```

The installer copies:

- `src/kde_ai_assistant_daemon.py` to `~/.local/bin/kde-ai-assistant-daemon`
- `src/kde_ai_assistant_client.py` to `~/.local/bin/kde-ai-assistant`
- `systemd/user/kde-ai-assistant-daemon.service` to
  `~/.config/systemd/user/kde-ai-assistant-daemon.service`
- the Plasma applet package to the user's Plasma package store with
  `kpackagetool6`

Then add the widget to a Plasma panel, or test it with:

```bash
plasmawindowed io.github.dragonswithin.kdeaiassistant
```

## Checks

```bash
python3 -m py_compile src/kde_ai_assistant_daemon.py src/kde_ai_assistant_client.py
bash -n scripts/install.sh
systemctl --user status kde-ai-assistant-daemon.service
kde-ai-assistant status --pretty
kde-ai-assistant context --kind window --pretty
```

## Notes

This is a desktop-session assistant. Core model services should be managed by
their own durable services; the KDE daemon exists only to bridge a logged-in KDE
session to those backends.
