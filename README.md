# KDE AI Assistant

A search bar for the KDE Plasma 6 panel: type anything and the computer does
it. It finds files through your existing local index, answers from the web
through your configured search tool, and acts on the system through tools,
using any model you configure, local or hosted with an API key. The goal,
architecture and phase order are in `docs/ROADMAP.md`.

## What Works Today

- A text field in the Plasma panel with one results popup. A vertical panel,
  or the widget's "Button" setting, shows an icon and puts the field inside
  the popup instead.
- Live file search while typing, through a search tool you already have,
  with no AI model involved. Down and Enter, or a click, opens a result.
- Tool servers (MCP, stdio) are started and supervised by the daemon. Ones
  you already configured for other AI programs can be imported.
- Desktop context capture: active window (KWin), clipboard (Klipper),
  explicit screenshots (Spectacle).

- Requests typed into the bar are carried out or answered by the AI model
  you configure, streamed into the popup with a line for each step.
- The assistant can read and act: arrange, focus and close windows, start
  applications, open files and links, change volume, media playback, Wi-Fi,
  Bluetooth, displays, colour scheme and KDE settings, set the clipboard,
  create, move and copy files, and run shell commands.
- Anything that deletes (including moving to the trash and replacing a
  file) or makes an OS-level change pauses and shows an approval card.
  Everything else runs at once. `kde-ai-assistant policy changes` or
  `policy everything` makes it ask more often.
- Every action that changed something is recorded in
  `$XDG_RUNTIME_DIR/kde-ai-assistant/actions.jsonl` until you log out.

It cannot yet click or type inside other applications; that is the next
phase in `docs/ROADMAP.md`.

## Setting Up A Model

Any service with an OpenAI-compatible chat API works, local or hosted:

```bash
kde-ai-assistant model probe http://127.0.0.1:8080          # what does it offer?
kde-ai-assistant model add NAME --url URL [--model ID]       # local, no key
kde-ai-assistant model add NAME --url URL --model ID --key-stdin   # paste the key, Enter
kde-ai-assistant model test                                  # answers? can call tools?
kde-ai-assistant model use NAME
kde-ai-assistant ask "what is on my clipboard?"
```

`--header NAME=VALUE` adds a request header for services that need one.
`kde-ai-assistant folders` shows where the assistant thinks Desktop,
Documents and Downloads are (it follows the system's settings), and
`kde-ai-assistant folders Documents /some/path` overrides one. With
a hosted model, whatever the tools read (clipboard, file contents) is sent to
that service.

## Setting Up Search

```bash
kde-ai-assistant tools discover          # servers found in other programs' settings
kde-ai-assistant tools import NAME       # add one (--read-only if it changes nothing)
kde-ai-assistant tools list              # its tools, and suggested roles
kde-ai-assistant role set file_search SERVER TOOL
kde-ai-assistant role set web_search SERVER TOOL
kde-ai-assistant search some words
```

Settings are stored in `~/.config/kde-ai-assistant/config.json` (mode 0600).
The schema is documented at the top of `src/kde_ai_assistant/settings.py`.
Change them through the commands above rather than by editing the file; the
daemon validates and applies changes immediately.

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
python3 -m py_compile src/kde_ai_assistant/*/*.py
bash -n scripts/install.sh
systemd-analyze --user verify systemd/user/kde-ai-assistant-daemon.service
systemctl --user status kde-ai-assistant-daemon.service
kde-ai-assistant status --pretty
kde-ai-assistant context --kind window --pretty
```

## Requirements

Plasma 6 on Wayland, Python 3.11 or newer, and PyGObject (`python-gobject`
or `python3-gi`), which the window tools use to talk to KWin. Everything else
is the Python standard library.

## Notes

This is a desktop-session assistant: the daemon runs as a systemd user unit
tied to the Plasma session and stops when you log out. Model services and
tool servers that should outlive the session are managed by their own owners;
the daemon only connects to them.
