# Happy Bot

A search bar for the KDE Plasma 6 panel: type anything and the computer does
it. It finds files through your existing local index, answers from the web
through your configured search tool, and acts on the system through tools,
using any model you configure, local or hosted with an API key. The goal,
architecture and phase order are in `docs/ROADMAP.md`.

## What Works Today

- The assistant's icon in the Plasma panel, which opens one popup where you
  type (Meta+Space or a click). Or, under **Show in panel: Search bar**, a
  text field in the panel itself with results in a popup above it; while
  you type there, Plasma outlines the panel in its focus colour. Vertical
  panels always show the icon.
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
  file) or makes an OS-level change, installing software included, pauses
  and shows an approval card.
- Long steps show that they are alive: a spinner, how long they have run,
  and the latest line of output. Stop ends a running command at once, and a
  desktop notification says when a request that took over a minute (your
  choice, under Behaviour) is done.
- Installs, builds and anything that needs your password open in a terminal
  window, where you watch the progress and type the password yourself; the
  assistant never handles it. It waits for that window's command to finish
  (the box says it is waiting for you), then reports how it went.
- When installing, it follows your instructions on the Behaviour settings
  page; the suggested ones say to use official, pre-built packages before
  building from source, to ask before any third-party source, and never to
  stop a program it started for you. It checks afterwards that the app shows
  in the launcher, refreshing the launcher (and, if needed, restarting the
  panel right after the request) when it does not.
  Everything else runs at once. The Behaviour settings page (or
  `happy-bot policy changes` / `policy everything`) makes it ask more
  often.
- Conversations are kept: reopening the box returns to the current one, and
  a sidebar lists earlier ones to reopen and continue. They are saved,
  readable only by you, in `~/.local/share/happy-bot/conversations`
  and deleted 30 days after their last use (changed on the History & Folders
  settings page; 0 saves nothing). They can contain whatever the assistant
  read for you.
- Every action that changed something is recorded in
  `$XDG_RUNTIME_DIR/happy-bot/actions.jsonl` until you log out.

- It can operate other applications: read a window's buttons, menus and
  fields through the accessibility interface, press them, fill in text, and
  send keys. The first time it sends keys, Plasma asks you to allow input
  control. Applications that expose no accessibility information cannot be
  operated this way.

## Settings

Right-click the assistant's icon and choose Configure. Every setting has a
control there; no file needs editing.

On the **Search Bar** page, check **Use robot mascot** and click **Apply**
to show the robot on the panel and beside Happy Bot’s replies. Uncheck it
to return to the wand.

- **AI Model:** which model answers; find one running on this computer or
  add a hosted one; its address, model id, API key, extra request headers,
  context window and whether it can see images; a live test.
- **Search & Tools:** press **Set up** next to Files or Web and choose
  **Use this** on the recommended choice; Happy Bot adds it and tries a
  search before keeping it. Choices come from what the computer already has
  (KDE's file search, tools set up for other AI programs, a SearXNG you
  run) and a few checked web searches (DuckDuckGo needs no key; Brave and
  Tavily need a free key). **By hand…** picks the server, tool, which
  argument gets the text and how many results yourself; connected tool servers, each with an on/off switch, a
  "look-up only" mark, its start command, environment values such as API
  keys, and which of its tools the assistant may use; a scan for servers
  set up for other AI programs; connecting one by hand.
- **Behaviour:** when to ask for approval; **Allow…** next to *Typing into
  other apps*, which asks Plasma's permission once; which kinds of action the
  assistant may take at all (windows, applications, other apps' buttons
  and typing, system settings, files, commands); your own standing
  instructions; steps per request, how long commands may run, when to
  notify; which terminal installs open in.
- **History & Folders:** how long conversations are kept, deleting them
  all, and where Desktop, Documents, Downloads, Pictures, Music and Videos
  are.
- **Search Bar:** live results while typing (on or off, after how many
  characters, after what pause, how many), the popup's size, and the
  address of the background service for unusual setups.
- **Keyboard Shortcuts:** the shortcut that opens the assistant.

API keys and other secrets typed there are stored in the daemon's settings
file (mode 0600) and never shown again.

## More Things It Does

Besides the bar and the settings above:

- **Quick results while typing**, with no AI model: a calculator, unit
  conversions (with `qalc`), dates ("3 weeks from friday"), world clocks
  ("time in Tokyo"), open windows, applications, System Settings pages and
  earlier conversations. Optional prefixes: `/` files only, `=` answers only,
  `?` ask the web, `>` run a command. Up and Down recall earlier requests,
  Tab completes, and file results have a right-click menu and can be dragged.
- **KRunner** (Alt+Space) shows the same results and an "Ask the assistant"
  entry whose answer arrives as a notification.
- **Undo**: "undo that" reverses the last change (file moves, new or
  replaced files, the trash, volume, brightness, themes, window places and
  more); "what did you do today?" is answered from the action log; after
  every answer the popup lists anything that was not done.
- **Reminders, routines and notes**: "remind me at 4…", saved routines that
  run by name, on a schedule, when a folder changes or when a drive is
  plugged in, quick notes and a to-do list in Markdown files. Conversations
  can be pinned in the sidebar to keep them.
- **Desktop and devices**: media and sound devices, the phone through KDE
  Connect, Bluetooth, brightness, night light, Do Not Disturb, power
  profiles, themes, keyboard layouts, key repeat, mice and touchpads,
  printers, VPNs, removable drives, the weather,
  default applications and autostart, virtual desktops, activities and
  saved window layouts.
- **Files and documents**: archives, conversions, picture edits, PDF pages,
  duplicates, the trash, comparing files, reading text in pictures (OCR),
  recent files, bookmarks and reading web pages.
- **For power users**: the system log, user services, processes, Git,
  containers, network checks, software search across every source and the
  update history.

Commands:

```bash
happy-bot doctor                     # check everything, with fixes
happy-bot eval [--model NAME]        # try a model on everyday requests (changes nothing)
happy-bot ask --dry-run "…"          # say what it would do, change nothing
happy-bot history [ID]               # earlier conversations
happy-bot export FILE / import FILE  # move settings (without secrets) and conversations
happy-bot mcp-serve                  # let another AI program use the tools (enable in settings)
```

Global shortcuts for "Explain selected text" and "Ask about this window" are
under System Settings > Shortcuts > Happy Bot Shortcuts (no keys are set
by default). An Arch package recipe is in `packaging/arch/`.

## Setting Up From The Command Line

The main settings can also be scripted. For a model, any
service with an OpenAI-compatible chat API works, local or hosted:

```bash
happy-bot model probe http://127.0.0.1:8080          # what does it offer?
happy-bot model add NAME --url URL [--model ID]       # local, no key
happy-bot model add NAME --url URL --model ID --key-stdin   # paste the key, Enter
happy-bot model test                                  # answers? can call tools?
happy-bot model use NAME
happy-bot ask "what is on my clipboard?"
```

`--header NAME=VALUE` adds a request header for services that need one.
`happy-bot folders` shows where the assistant thinks Desktop,
Documents and Downloads are (it follows the system's settings), and
`happy-bot folders Documents /some/path` overrides one. With
a hosted model, whatever the tools read (clipboard, file contents) is sent to
that service.

For search and tools:

```bash
happy-bot tools discover          # servers found in other programs' settings
happy-bot tools import NAME       # add one (--read-only if it changes nothing)
happy-bot tools list              # its tools, and suggested roles
happy-bot role set file_search SERVER TOOL
happy-bot role set web_search SERVER TOOL
happy-bot search some words
```

Settings are stored in `~/.config/happy-bot/config.json` (mode 0600).
The schema is documented at the top of `src/happy_bot/settings.py`.
Change them through the settings dialog or the commands above rather than by
editing the file; the daemon validates and applies changes immediately.

Useful environment overrides:

- `HAPPY_BOT_DAEMON_HOST`
- `HAPPY_BOT_DAEMON_PORT`
- `HAPPY_BOT_DAEMON_URL`
- `HAPPY_BOT_ROOT_BROKER`
- `HAPPY_BOT_ADMIN_GROUP`

## Install

From a checkout of this repository, as your normal user:

```bash
scripts/install.sh
```

That installs the daemon and command-line client, starts the daemon as a
systemd user service tied to your Plasma session, installs the panel widget
and, the first time, adds the search bar to the panel that holds your
application launcher. Then press Enter in the empty bar (or right-click it
and choose Configure Happy Bot) to set it up:

1. **AI model.** "Find models on this computer" lists model services that
   are running locally; or add a hosted service by address, model id and API
   key. Each model is tested when you add it.
2. **Search and tools.** "Look for tools I already have" finds tool servers
   you set up for other AI programs and offers to use them for file search
   and web search.
3. **Approvals and folders.** Sensible defaults; change them if you want.

Nothing needs to be edited by hand. Running the installer again upgrades in
place; after an upgrade, log out and in (or restart plasmashell) so the panel
loads the new widget code.

What goes where:

- `src/happy_bot/` to `~/.local/lib/happy-bot/happy_bot/`
- `launchers/happy-bot-daemon` and `launchers/happy-bot` to
  `~/.local/bin/`
- `systemd/user/happy-bot-daemon.service` to
  `~/.config/systemd/user/`
- the Plasma widget to your Plasma package store (`kpackagetool6`)
- your settings, created on first use, in `~/.config/happy-bot/`

To remove it:

```bash
scripts/install.sh --uninstall           # keeps your settings
scripts/install.sh --uninstall --purge   # removes them too
```

The widget's Appearance settings switch between a search bar and a button
and set the bar width and the results size; its Keyboard Shortcuts page sets
a shortcut that focuses the bar.

To test the widget in a window instead of a panel:

```bash
plasmawindowed io.github.dragonswithin.happybot
```

Widget load errors are not printed to the terminal; read them with
`journalctl --user -e | grep -E 'plasmashell|plasmawindowed'`, or set
`QT_FORCE_STDERR_LOGGING=1`.

## Access Control

The daemon listens on loopback only and can act for the user, so every
request must carry the bearer token it writes at each start to
`$XDG_RUNTIME_DIR/happy-bot/token` (mode 0600). Requests with an
`Origin` header (any browser page) or a foreign `Host` header are refused.
The CLI and the widget read the token themselves.

## Checks

```bash
python3 -m unittest discover -s tests
python3 -m py_compile src/happy_bot/*.py
python3 -m py_compile src/happy_bot/*/*.py
bash -n scripts/install.sh
QT_FORCE_STDERR_LOGGING=1 /usr/lib/qt6/bin/qmllint -I /usr/lib/qt6/qml plasmoid/*/contents/ui/*.qml
systemd-analyze --user verify systemd/user/happy-bot-daemon.service
systemctl --user status happy-bot-daemon.service
happy-bot status --pretty
happy-bot context --kind window --pretty
```

## Requirements

Plasma 6 on Wayland, Python 3.11 or newer, and PyGObject (`python-gobject`
or `python3-gi`) with `at-spi2-core`, which the window and application
control tools use to talk to KWin, the accessibility bus and the desktop
portal. Everything else is the Python standard library.

## Notes

This is a desktop-session assistant: the daemon runs as a systemd user unit
tied to the Plasma session and stops when you log out. Model services and
tool servers that should outlive the session are managed by their own owners;
the daemon only connects to them.
