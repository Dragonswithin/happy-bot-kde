# KDE AI Assistant

A search bar for the KDE Plasma 6 panel: type anything and the computer does
it. It finds files through your existing local index, answers from the web
through your configured search tool, and acts on the system through tools,
using any model you configure, local or hosted with an API key. The goal,
architecture and phase order are in `docs/ROADMAP.md`.

Today the repo is only the scaffold for that: a panel applet and a per-user
daemon with desktop-context capture. No model provider, agent loop or action
tools exist yet.

## What It Provides

- A text field in the Plasma panel with one results popup under it. A
  vertical panel, or the applet's `inputInPopup` setting, shows an icon and
  puts the field inside the popup instead.
- Context actions for clipboard text and active-window metadata.
- Explicit screenshot capture through Spectacle.
- Per-user daemon with loopback HTTP API and transient runtime state.

## Current State

No model is connected yet: requests typed into the bar reach the daemon and
return an unavailable response. The daemon provides desktop context only.

- KWin DBus for active-window metadata.
- Klipper DBus for clipboard text.
- Spectacle for user-requested screenshots.

Useful environment overrides:

- `KDE_AI_ASSISTANT_DAEMON_HOST`
- `KDE_AI_ASSISTANT_DAEMON_PORT`
- `KDE_AI_ASSISTANT_DAEMON_URL`
- `KDE_AI_ASSISTANT_ROOT_BROKER`
- `KDE_AI_ASSISTANT_ADMIN_GROUP`

## Install

From this repo:

```bash
scripts/install.sh
```

The installer copies:

- `src/kde_ai_assistant/` to `~/.local/lib/kde-ai-assistant/kde_ai_assistant/`
- `launchers/kde-ai-assistant-daemon` and `launchers/kde-ai-assistant` to
  `~/.local/bin/`
- `systemd/user/kde-ai-assistant-daemon.service` to
  `~/.config/systemd/user/kde-ai-assistant-daemon.service`
- the Plasma applet package to the user's Plasma package store with
  `kpackagetool6`

It then enables and restarts the daemon. Running it again upgrades in place.

Add the "AI Assistant" widget to a Plasma panel, next to the application
launcher. Right-click it and choose Configure to switch between a search bar
and a button, set the bar width and the results size, and (on the Keyboard
Shortcuts page) set a shortcut that focuses it. After an upgrade, log out and
in, or restart plasmashell, so the panel loads the new widget code.

To test the widget in a window instead:

```bash
plasmawindowed io.github.dragonswithin.kdeaiassistant
```

Widget load errors are not printed to the terminal; read them with
`journalctl --user -e | grep -E 'plasmashell|plasmawindowed'`.

## Access Control

The daemon listens on loopback only and can act for the user, so every
request must carry the bearer token it writes at each start to
`$XDG_RUNTIME_DIR/kde-ai-assistant/token` (mode 0600). Requests with an
`Origin` header (any browser page) or a foreign `Host` header are refused.
The CLI and the widget read the token themselves.

## Checks

```bash
python3 -m unittest discover -s tests
python3 -m py_compile src/kde_ai_assistant/*.py
bash -n scripts/install.sh
systemd-analyze --user verify systemd/user/kde-ai-assistant-daemon.service
systemctl --user status kde-ai-assistant-daemon.service
kde-ai-assistant status --pretty
kde-ai-assistant context --kind window --pretty
```

## Notes

This is a desktop-session assistant. Core model services should be managed by
their own durable services; the KDE daemon exists only to bridge a logged-in KDE
session to those backends.
