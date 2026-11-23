# KDE AI Assistant: Product Goal And Roadmap

This document is the authoritative statement of what this project is for and
the order in which it gets built. It replaces any earlier "chat sidebar with a
pluggable backend" plan. Read it before proposing or starting work.

## Product Goal

A search bar on the Plasma panel, next to the application launcher. The user
types anything and the computer does it or answers it.

Four properties define the product. All are required:

1. **One bar, any request.** The same field finds a file, answers a question
   from the web, changes a setting, arranges windows, or drives another
   application. The user never picks a mode.
2. **Any AI.** The model is a user choice, local or hosted with an API key,
   never a project assumption.
3. **Uses what the user already has.** File and document search goes through
   the user's existing local search/RAG index. Web answers go through the
   web-search tool the user already configured. These arrive as tools the
   assistant connects to (MCP servers), not as code copied into this repo.
4. **One app.** One install command, one first-run setup, one settings page,
   one thing to uninstall. The daemon, tool servers and model connection are
   internal details the user never has to start, wire or debug separately.

A build that only chats, or that works only after hand-editing several
services' configuration, is not "usable" for this project.

### Acceptance Scenarios

"Usable" means these work typed into the panel bar, on a local model and on a
hosted one, on a machine set up only through the installer and first-run
setup:

- "tax return 2025 pdf" shows matching files from the user's index as they
  type, with no model call; Down then Enter (or a click) opens one. Plain
  Enter always sends the text to the assistant, so the same key never means
  two things.
- "Find the notes where I wrote about the fence quote." (index search through
  the model, results are openable)
- "What happened in the news today about X?" (configured web-search tool,
  answer with links)
- "Put Firefox on the left half and Konsole on the right."
- "Turn the volume down to 30% and enable dark mode."
- "What is using all my disk space in Downloads?" (reads, then answers)
- "Connect to the Wi-Fi network named X." / "Switch to the external monitor only."
- "Rename the screenshots on my desktop by date." (previews, asks, then does it)
- "Summarise what is on my clipboard and put the summary back on it."
- "Click Save in this dialog." / "Type my address into the focused field."
  (driving another application's UI is part of the first usable release)

## What The Earlier Plan Got Wrong

- **Scope.** It planned provider adapters, SSE streaming and a settings dialog,
  and nothing that acts on the system. No agent loop, no tools, no approval.
- **Qt facts.** This machine runs Plasma 6.8.3 on **Qt 6.12.0**, and
  `qt6-websockets` **is installed** (`/usr/lib/qt6/qml/QtWebSockets`). The
  "Qt 5.15, no QtWebSockets" finding came from the wrong `qmake`.
- **QML networking.** `QNetworkAccessManager` is a C++ class and is not
  available in QML. QML has `XMLHttpRequest` and, here, `QtWebSockets`.
- **Dependencies.** `aiohttp` and `httpx` are not installed and are not
  needed for streaming: stdlib `http.server` can stream a response and
  `urllib` can read a streamed one, so the daemon stays on the stdlib server.
  The maintainer has allowed dependencies that are genuinely needed; name each one and
  the reason before adding it.
- **"OpenAI-compatible covers Anthropic etc."** It does not cover every
  provider natively. One adapter is the right start, not the whole answer.
- **Secrets.** API keys must not live in a world-readable settings file or be
  returned by `GET /settings`.

## Verified Environment (2026-11-22)

| Fact | Value |
|---|---|
| Plasma / Qt | 6.8.3 / 6.12.0, Wayland session |
| Python | 3.14; `requests`, `dbus`, `gi`, `pydantic` present; no `aiohttp`/`httpx` |
| Local GPU model | `127.0.0.1:52626`, OpenAI-compatible, **tool calls supported**, parallel tool calls, 131072 ctx, **text only (no vision)**, one slot |
| Local NPU model | `127.0.0.1:52625`, OpenAI-compatible; tool-call support unverified |
| KWin DBus | `queryWindowInfo`, `getWindowInfo`, `/Scripting` `loadScript`, `ScreenShot2` |
| Portals | `RemoteDesktop`, `ScreenCast`, `Screenshot`, `GlobalShortcuts`, `Clipboard` |
| Accessibility | `org.a11y.Bus` present, `at-spi2-core` and `libei` installed |
| Input injectors | `ydotool`, `kdotool`, `wtype`, `xdotool` all absent |
| CLI control tools | `qdbus6`, `busctl`, `wpctl`, `pactl`, `nmcli`, `bluetoothctl`, `kscreen-doctor`, `kwriteconfig6`, `kioclient`, `kstart`, `notify-send`, `wl-copy`, `wl-paste`, `spectacle`, `pkexec` |
| Installed state | Nothing installed: no service unit, no applet package |

Consequences: the local models cannot see screenshots, so control must work
through **structured** interfaces (DBus, KWin scripting, CLI tools,
accessibility tree) first. Screenshot-and-click is an optional later tier for
models that have vision. The GPU model has one slot, so requests queue behind
any other client using it.

## Architecture

```
Panel bar applet (inline text field + results popup) / CLI
        |  loopback HTTP, authenticated, event stream
        v
Daemon (per-user, desktop session; the only long-running process)
  instant search path ──> index tool, no model
  agent loop ── provider layer ──> any model endpoint
      |
  permission gate ── approval request ──> user
      |
  tool registry ──> built-in desktop tools
                └─> MCP client ──> user's index, web search, other servers
```

### Panel Bar

The applet's panel form is a text field, not an icon: it sits in the panel
beside the launcher, takes a global shortcut to focus, and opens a results
popup under itself. One popup shows everything: instant file hits, the
streamed answer, tool activity, approval cards, and openable results (files,
links, apps). A conversation continues in the same popup until dismissed.

Two paths share the bar so it feels fast with a slow local model:

- **Instant path (while typing):** debounced query to the search-index tool
  only. No model. Results are selectable with the keyboard. The popup opens
  for this only once there are hits to show; clicking or focusing the empty
  bar never opens anything.
- **Agent path (Enter):** the full request goes to the agent loop, which may
  call the same index tool, web search, or any action tool.

Keyboard focus for a text field embedded in a Plasma panel is a known sharp
edge on Wayland. Prove it in Phase 0 before building on it; the fallback is a
panel button plus shortcut that opens a focused popup with the field inside.

### One App

- The daemon starts and supervises the MCP servers it uses as child
  processes. The user never runs them.
- One config file under `~/.config/kde-ai-assistant`, edited only through the
  settings page or CLI.
- **First-run setup** in the applet, each step skippable and re-runnable:
  pick a model (loopback endpoints are probed and offered; or paste a URL and
  key), pick the file-search tool and the web-search tool (MCP servers found
  in the user's existing agent configs are offered for import), run a live
  test of each, done.
- One installer command installs everything, enables the service, and adds
  nothing the user must finish by hand. One uninstall command reverses it.
- Errors name the fix in the popup ("web search tool is not responding:
  Retry / Open settings"), never a service name or log path.

### Agent Loop

One turn: send conversation + tool schemas to the model; if it returns tool
calls, pass each through the permission gate, run the allowed ones, append the
results, and call the model again; stop on a plain text answer, a step limit,
or user cancel. The loop is provider-neutral and tool-neutral.

### Provider Layer

A provider turns the neutral conversation (messages, tool schemas, tool
results) into one vendor's wire format and back, streaming text deltas and
tool calls.

- First: one **OpenAI-compatible chat-completions provider with tool
  calling**. It covers both local services, Ollama, LM Studio, OpenRouter,
  OpenAI and most hosted gateways through base URL + optional key + model.
- Later: native providers where the compatible route loses features (for
  example Anthropic, Gemini). Check the vendor's current API documentation
  when writing each one; do not write wire formats from memory.
- A model entry may carry extra request headers, and a model can be added
  when the service cannot list its models as long as the model id is given.
  Both were needed for the first hosted service tried.
- Each configured model carries capability flags: `tools`, `vision`,
  `context_window`. A model without `tools` is rejected for agent use with a
  clear message rather than silently degrading to chat.
- Ship no vendor defaults in code. Offer discovered loopback endpoints as
  suggestions in settings; the user picks.

### Tools

Each tool is a name, a JSON schema, a risk class, and a handler that returns a
compact text result. Two sources feed one registry:

- **Built-in tools** for the desktop itself, in the tiers below.
- **MCP tools** from servers the user connects (stdio first). File/RAG search
  and web search come this way. Two roles are assigned in settings,
  `file_search` and `web_search`, so the instant path and the system prompt
  know which tools to prefer; every other MCP tool is simply available to the
  model. MCP tools carry no trustworthy risk class, so the user marks each
  server read-only or not at import, and non-read-only servers follow the
  `danger` rules. Nothing about a specific index or search engine is
  hard-coded.

Built-in tiers:

1. **Observe** (read-only): active window, window list, clipboard, running
   apps, system info, read file, list directory, read a KDE setting.
2. **Act, structured:** launch app / open file or URL, window move, resize,
   tile, focus, close (KWin scripting), set clipboard, notification, volume
   and media, network, bluetooth, displays, KDE settings, generic session
   DBus call, write/move/trash files, run shell command.
3. **Act, GUI:** read an application's accessibility tree and invoke its
   actions (AT-SPI); synthetic keyboard and pointer input through the
   `RemoteDesktop` portal; screenshot + coordinates only for vision models.
   Built natively: `gi.repository.Atspi` for the tree and actions, and the
   `RemoteDesktop` portal for keyboard input (see Phase 5 findings for why
   not KWin's EIS connection). Accessibility is switched on for the session
   when this tier is first used. There is no pointer input: controls are
   pressed through their accessibility actions, which needs no coordinates.
4. **Privileged:** root actions only through the external broker named in
   `AGENTS.md`. No root helper in this repo.

Tier 2's shell and DBus tools are what make "control anything" true on day
one; the specific tools exist so smaller local models succeed without
composing commands.

### Permission Gate

Every tool call is classified before it runs:

- `read`: no state change.
- `change`: everything else that is not `danger`. This includes shell
  commands, DBus calls, synthetic input, creating, writing and moving files,
  settings, windows, network and devices.
- `danger` (the maintainer's definition, keep it this narrow):
  - **Deletion:** removing or trashing files or directories, overwriting an
    existing file with different content, dropping or wiping data, removing
    packages.
  - **OS-level changes that could crash the system or stop it booting:**
    bootloader, kernel, initramfs, partitions and filesystems, `/boot`,
    `/etc/fstab`, system units and drivers, system package changes, raw
    device writes, anything run as root.

Default policy: `read` and `change` run without asking and are shown in the
transcript as they happen. `danger` asks first: the applet shows exactly what
will run and the user allows once or denies; it is never offered "allow for
session". A denial is returned to the model as the tool result. The gate
lives in the daemon, never in the UI, so the CLI and applet share it.

Classification is by the **effect of the specific call**, not by which tool
it is. Dedicated tools declare their class. Free-form tools are inspected per
call: a shell command or DBus call is `danger` only when it matches the
definition above (for example `rm`, `shred`, `dd`, `mkfs`, `truncate`,
redirection onto an existing file, `sudo`/`pkexec`, package removal, writes
under `/boot` or `/etc`). Shell inspection is best-effort pattern matching
and can miss an obfuscated command; keep the pattern list in one tested
module so it can be tightened. The policy is user-configurable to stricter
levels (ask for changes, ask for everything).

### Daemon API And Security

The daemon will execute actions, so the current open surface must close
**before** the first tool lands:

- Remove `Access-Control-Allow-Origin: *`. Reject any request carrying an
  `Origin` header and any `Host` that is not the loopback address and port.
- Require a per-session bearer token stored `0600` under
  `$XDG_RUNTIME_DIR/kde-ai-assistant`. Other local users can reach loopback.
- Keep the bind loopback-only.
- API keys and other secrets (tool-server environment values, model request
  headers) live in the one settings file, `0600`, under
  `~/.config/kde-ai-assistant`. They are never in Plasma applet config, never
  returned by an endpoint (clients see `null` and send `null` back to keep
  the stored value), and never logged. KWallet was the original first choice
  and was dropped: a wallet may be locked or absent when the daemon starts,
  it would add a second place settings live, and a fresh account has none.
- Read tools run without asking, and what they return goes to the model. With
  a hosted model that means clipboard text and file contents leave the
  computer. The settings page must say so plainly for any model whose address
  is not loopback (Phase 6).
- An audit trail of executed tool calls stays in the runtime directory
  (transient), per `AGENTS.md`.

Event stream for one turn: `text_delta`, `tool_call`, `approval_required`,
`tool_result`, `done`, `error`. Approvals and cancel are separate requests.
Use SSE over the existing stdlib server; in QML read it incrementally with
`XMLHttpRequest` (`readyState === LOADING`), with `QtWebSockets` as the
fallback if a short spike shows partial `responseText` is unreliable.

### Source Layout

The daemon is 399 lines and about to grow several owners. Split by
responsibility, each file under about 500 lines with a real header:

```
src/kde_ai_assistant/
    daemon_http.py      request routing, auth, event stream
    agent_loop.py       turn execution, step limit, cancel
    conversation.py     neutral message / tool-call types
    ask_stream.py       one streamed turn for POST /ask
    conversations.py    in-memory conversation histories
    kwin_bridge.py      runs snippets inside KWin, returns their result
    accessibility.py    reads and operates other apps' interfaces (AT-SPI)
    input_portal.py     keyboard input through the RemoteDesktop portal
    glib_loop.py        the one GLib main loop the DBus features share
    permissions.py      approval policy, the gate, pending approvals, action log
    shell_risk.py       decides whether a shell command is a danger action
    model_discovery.py  finds model services running on this computer
    providers/          base contract, openai_compatible
    tools/              registry, catalog, observe, windows, gui, apps,
                        system, files, shell, mcp_bridge
    daemon_routes.py    what each endpoint does
    mcp_client.py       stdio MCP sessions, child-process supervision
    mcp_discovery.py    finds tool servers in other programs' configs
    tool_roles.py       file_search / web_search role mapping and proposals
    instant_search.py   no-model query path to the file_search tool
    desktop_actions.py  actions on the desktop, starting with opening things
    settings.py         config file, secret lookup
    desktop_context.py  existing KWin / Klipper / Spectacle capture
tests/
```

`scripts/install.sh` currently copies two single files; it must install the
package (for example under `~/.local/lib/kde-ai-assistant`) with thin
launchers in `~/.local/bin`.

## Phases

Each phase ends with something demonstrable. Do not start a phase before the
previous exit check passes.

**Phase 0: Baseline and bar spike.** Run the installer, confirm the daemon,
CLI context commands and `plasmawindowed` applet work as they are. Remove the
dead `ai.example.com` default and the `/open-full-ui` path (daemon, CLI
and applet). Spike a text field as the applet's panel form: typing, focus by
shortcut, popup under the bar.
*Exit:* `kde-ai-assistant status` and `context` succeed; a text field in the
real panel accepts typing and opens a popup, or the fallback is chosen and
recorded here.

**Phase 1: Secure daemon and package split.** Token auth, Origin/Host checks,
no CORS wildcard, package layout, installer update, unit tests for auth.
Split only what exists today (`daemon_http.py`, `desktop_context.py`); do not
create empty placeholder modules for later phases. The applet needs a way to
obtain the token: QML `XMLHttpRequest` refuses local files unless
`QML_XHR_ALLOW_FILE_READ` is set, so settle the mechanism with a short spike
first (candidate: the `org.kde.plasma.plasma5support` executable data source
running a `kde-ai-assistant token` subcommand).
*Exit:* an unauthenticated or browser-origin request is refused; the applet
still reaches `/health` with the token; tests pass.

**Phase 2: MCP client and instant search.** Stdio MCP client with supervised
child processes, settings for servers and the `file_search` / `web_search`
roles, instant path, bar shows live file hits and opens them.
*Exit:* typing in the bar lists files from the user's index with no model
configured; killing the index server does not break search (it is restarted
on the next query, and a server that cannot start is reported with its error).

**Phase 3: Provider and agent loop.** OpenAI-compatible provider with
streaming and tool calls, secret storage, agent loop, tier 1 tools plus MCP
tools, streamed answer in the popup. Test the loop against a fake provider.
Run the throwaway GUI-control spike now (one Qt and one GTK app's AT-SPI
tree; one key through a `RemoteDesktop` portal session; a trial of the
candidate MCP servers), because GUI control is on the release path and the
local models cannot fall back to screenshots.
*Exit:* the three search/news acceptance scenarios pass on the local GPU
model and on one hosted model; spike findings are recorded here.

**Phase 4: Permission gate and structured actions.** Risk classes, approval
cards in the popup and CLI, tier 2 tools.
*Exit:* the window, volume, disk, Wi-Fi/monitor, rename and clipboard
scenarios pass from the bar.

**Phase 5: GUI control.** Tier 3, built natively.
*Exit:* pressing Save in a dialog and entering text in a field work in a Qt
and a GTK app on a text-only local model.

**Phase 6: One-go install and setup.** First-run setup, settings page
(models, keys, tool servers and roles, approval policy, folders),
single install and uninstall commands, error messages with fixes. Test on a
fresh user account with no prior configuration.
*Exit:* on a fresh account, one install command plus first-run setup reaches
a passing acceptance run with no file edited by hand. **This completes the
first usable release: Phases 0 to 6.** Status: open, see Phase 6 findings.

**Later.** Native providers, broker-backed privileged actions, packaging
(AUR, KDE Store), non-stdio MCP transports.

## Phase Findings

**Phase 0 (passed 2026-11-22).**

- An inline text field works in a horizontal Plasma 6.8 panel on Wayland.
  The maintainer confirmed at the desktop: one click focuses it, typing lands in it, and
  Enter opens the results popup above the bar. The fallback was not needed
  as the default.
- The mechanism: the applet sets `Plasmoid.status` to
  `AcceptingInputStatus` before forcing focus into the field, and clears it
  when the field loses focus. The results popup is a `PlasmaCore.Dialog` of
  type `Tooltip` with `Qt.WindowDoesNotAcceptFocus`, so the field keeps
  focus while the popup is open and its buttons still take clicks.
- The fallback exists anyway as the applet's `inputInPopup` setting and is
  what vertical panels use: icon in the panel, focused popup with the field
  inside. It loads without errors but has not been exercised by a person.
- Not yet verified by a person: focusing the bar with the applet's
  activation shortcut. Check it in Phase 6.
- QML load errors do not reach the terminal. Read them from
  `journalctl --user` for `plasmawindowed` or `plasmashell`.
- `PlasmaExtras.Popup` and `Plasmoid.containmentModes` do not exist; the
  first Phase 0 attempt used them and the applet never loaded.
- `scripts/install.sh` does not restart a daemon that is already running, so
  an upgrade keeps serving old code. Fix in Phase 1.

**Phase 1 (passed 2026-11-22).**

- Exit check, run against the installed daemon: no token returns 401; a
  valid token with an `Origin` header returns 403; a valid token returns
  200; the applet in the real panel reaches `/health` and recovers by
  itself within one poll after the daemon restarts with a new token.
- The applet reads the token by running `cat` through the
  `org.kde.plasma.plasma5support` "executable" data source. It works.
- `QtCore.StandardPaths.writableLocation()` returns a `file://` URL in QML,
  not a path. Strip the scheme before using it in a command.
- A running plasmashell keeps the applet QML it loaded. After an upgrade the
  panel needs `systemctl --user restart plasma-plasmashell.service` or a new
  login; `plasmawindowed` always loads the installed version.
- Do not set a panel's `AppletOrder` through plasmashell scripting. It left
  the widget outside the layout, drawn over other widgets. Add the widget
  with `addWidget` and let the user place it.
- The maintainer's panel requirements, now implemented as applet settings: the bar
  width and results size are configurable; the panel can show a button
  instead of the bar; clicking or focusing the bar never opens the popup.

**Phase 2 (passed 2026-11-22).**

- Exit check: with no model configured, the maintainer typed in the panel bar, saw
  matching files from his index, and opened one with Down and Enter. From
  the CLI the same search takes about 0.3 s. Killing the index server
  process was followed by a successful search: the daemon restarted it. The
  failure paths (crash during a call, a server that cannot start, a tool
  that reports an error) are covered by tests and return `tool_failed`.
  The roadmap's exit wording was changed to match: silent recovery is
  better than showing an error for a server that restarts fine.
- The MCP client is standard library only: newline-delimited JSON-RPC over
  the child's pipes. It works unchanged against both of the maintainer's servers.
- Both servers were set up through `kde-ai-assistant tools import` and
  `role set`, with no file edited by hand. Role proposals picked the right
  tool on each (`machine_context_search`, `web_search`).
- The maintainer's index is lexical for whole-machine search (full text over paths,
  extracted text, OCR, media tags). Its semantic ranking is only available
  per repository through `project_context_pack`, which needs a repository
  root and so cannot back the search bar. The agent can call it in Phase 3.
  Instant results therefore match words, not meaning.
- A search tool's first call after the daemon starts is slower because the
  server is started on demand.
- The maintainer chose live results while typing (two or more characters, 200 ms
  pause). Clicking or focusing the empty bar still opens nothing.
- Search tools return different shapes, so hits are extracted tolerantly
  (structured content, JSON text, then paths and links in plain text). Only
  objects with a location under a common key count, which keeps a tool's
  bookkeeping paths (index database, scan roots) out of the results.

**Phase 3 (passed 2026-11-22).**

- Exit check, run from the CLI on both models with the real index and web
  search tools:

  | Scenario | Local GPU model | Hosted model |
  |---|---|---|
  | Focused window and clipboard | passed, 6.6 s | passed, 2.7 s |
  | Find the roadmap document | passed, 5.8 s | passed, 2.3 s |
  | Today's news with links | passed, 19 s | passed, 5.2 s |

  The maintainer confirmed in the panel that answers stream in, tool lines appear, and
  the popup closes on Esc, the close button and any click outside.
- The hosted model was Anthropic's OpenAI-compatible endpoint. Its chat
  endpoint works with the plain bearer key, streaming and tools. Its model
  list does not (it needs a vendor header), which is why adding a model no
  longer depends on listing.
- QML `XMLHttpRequest` does deliver a streamed response incrementally at
  `readyState` LOADING (19 partial updates in a 1.3 s reply). No WebSocket
  is needed.
- `org.kde.KWin.queryWindowInfo`, which the original scaffold used for the
  active window, is an interactive click-to-pick call and hangs. Window state
  now comes from `kwin_bridge`, which loads a one-off KWin script that calls
  back over DBus. First call about 80 ms, then a few ms.
- New dependency: **PyGObject** (`gi`), for `Gio` DBus in `kwin_bridge`. It
  is the only way found to receive a result from a KWin script without
  owning a helper binary. It is imported lazily; without it the window tools
  report why and everything else works. Phase 5 needs it too (AT-SPI).
- The local model emits hidden reasoning before every answer and needs room
  for it, so requests set no output-token cap.
- Only `read` tools are offered to the model until the permission gate
  exists. Tools of a server the user did not mark read-only are withheld,
  except the ones assigned to a role.
- GUI-control spike (throwaway, nothing kept):
  - Setting `org.a11y.Status.IsEnabled` to true on the session bus made
    already-running Qt apps (Konsole, KWrite, plasmashell) and Firefox expose
    their accessibility trees at once, with `Press`/`click` actions on menus
    and buttons, readable through `gi.repository.Atspi` in about 10 ms per
    app. Before that, only helper processes were visible. GTK apps were not
    tested because none with a window was running. The flag was restored.
  - `org.kde.KWin.EIS.RemoteDesktop.connectToEIS` returned an input
    connection to an ordinary session process with no consent dialog, and
    `libei` is installed. Synthetic keyboard and pointer input can therefore
    be done natively; no key was actually sent.
  - The candidate MCP servers were not installed. With both native paths
    proven, bundling a third-party server would add a Rust or `uv` runtime to
    a project that must install in one go. Phase 5 builds tier 3 natively.

**Phase 4 (passed 2026-11-22).**

- Exit check on the local model, from the CLI with throwaway windows and
  files: two windows tiled left and right (16 s); volume set to 30% and dark
  mode recognised as already on (6 s); largest items in Downloads (8 s);
  three files renamed by modification date (21 s); clipboard summarised and
  written back (7 s); "external monitor only" correctly reported one
  display; a deletion request paused for approval, was declined, the file
  stayed, and the action log recorded it. The maintainer confirmed from the bar that
  the approval card's Allow moves the file to the trash and that a window
  request runs without asking.
- Not verified for real: connecting to Wi-Fi (this machine is wired and its
  Wi-Fi radio is off) and switching between two displays (one is connected).
  Both tools exist and their argument handling is tested.
- Risk is decided per call, not per tool. `run_command` uses `shell_risk`;
  file tools are `danger` only when a call passes `overwrite: true` onto an
  existing file, targets a system path, or trashes something. Making
  overwrite an explicit argument keeps the classifier and the handler in
  agreement: the handler never replaces anything the call did not ask to.
- An approval is only requested for a call that can succeed. The first
  panel test asked the maintainer to approve trashing a path that did not exist (the
  model guessed the folder), which looked like Allow doing nothing. Tools now
  have a `precheck` that runs before the gate.
- The model is told where the user's standard folders are. They follow the
  system's XDG user-dirs (what KDE's Locations page sets) and can be
  overridden with the assistant's `folders` setting; the maintainer asked for both.
- KWin applies window geometry after a script returns, so window tools
  report the geometry they requested rather than reading it back.
- Models pass window ids without their braces; ids match either way.
- The CLI declines approvals when it has no terminal, so a script cannot
  approve a dangerous action.
- The maintainer removed the Clipboard and Window quick buttons from the popup.
- There are about 45 built-in tools. The local model handles the full list;
  first-token latency was not measurably worse than with ten.

**Phase 5 (passed 2026-11-22).**

- Exit check on the text-only local model:
  - Qt: in a throwaway KWrite window the model pressed New File, entered
    text, opened Save As, filled in the path in the Save dialog and pressed
    Save. The file existed with the right content (68 s, 12 tool calls).
  - GTK: it entered text in a `zenity` (GTK 4) dialog and pressed OK; the
    dialog returned exactly that text (7.5 s).
  - The maintainer confirmed from the bar that "type hello into this window" typed into
    the editor he had been using.
- Keyboard input uses the `RemoteDesktop` portal's `NotifyKeyboardKeysym`,
  not KWin's EIS connection. The portal takes key symbols over DBus, so it
  needs no `libei` binding and no keyboard-layout mapping, and it asks the
  user once. The maintainer saw and approved the desktop's consent dialog; the restore
  token is saved so it should not reappear. Whether it stays silent after a
  new login has not been checked.
- Pressing a control that opens a modal dialog makes the AT-SPI call time
  out, because the application does not reply until the dialog closes. That
  is reported as "sent; the application is busy" rather than as a failure.
- Window titles change while an application is used ("Welcome", "Untitled",
  "Save File"), so addressing windows by title failed mid-task. GUI tools
  now return the stable window id and `ui_press` reports windows of the
  application that opened, closed or were retitled. Dialogs count as
  windows for this.
- "This window" from the bar is the topmost ordinary window, because while
  the user types the active window is the panel.
- A turn may now make 40 model requests (was 12); a multi-step GUI task
  needs a snapshot, an action and a check per step.
- Unnamed fields take their name from the label that points at them
  (`LABELLED_BY`) or their description.
- GUI risk is best-effort and says so: a press is `danger` when the
  control's label is destructive; Enter and typed commands in a terminal are
  checked like shell commands.
- Not built: pointer input and screenshot-and-click for vision models. No
  acceptance scenario needs them and neither local model has vision.
- Applications that publish no accessibility tree cannot be operated; the
  tool says so.

**Phase 6 (built 2026-11-22; exit check NOT yet passed).**

- The exit check needs a fresh user account with someone logged into Plasma
  as it. The maintainer chose not to do that now, so it is open and the first release
  is not done. Nothing below substitutes for it.
- What was verified instead, on the maintainer's account:
  - Empty configuration: a second daemon started with an empty config and
    runtime directory reported nothing set up. Using only the calls the
    settings page makes (`/models/discover`, `/settings`, `/models/test`,
    `/tools/scan`, `/tools/import`) it reached a working setup with no file
    edited by hand: local model found and tested, file search and web search
    adopted from the scan.
  - From that setup, on the local model and on the hosted model: instant
    search, focused window and clipboard, finding a document, renaming files
    by date, tiling two windows, disk usage, a deletion that waited for
    approval and was declined, and filling in and confirming a GTK dialog.
    All passed. News was run on both models in Phase 3.
  - The maintainer confirmed the bar's right-click menu opens the settings dialog and
    the Assistant page shows the model, search tools, approvals and folders.
- Installer, checked 2026-11-23 against an empty throwaway home directory
  with `systemctl` and `qdbus6` replaced by recorders (so the real session
  was not touched): a first install placed the package, launchers and unit,
  enabled and restarted the daemon, asked Plasma to add the bar once, and
  warned that `~/.local/bin` was not on `PATH`; the installed command ran
  from that home without the checkout. A second run upgraded in place and
  did not add the bar again. `--uninstall` disabled the daemon, removed the
  bar from panels and every installed file, and kept the settings;
  `--purge` removed those too and left the home empty.
- Not verified by anyone: the installer on a real account that has never
  had the assistant (that the bar actually lands in the panel and the daemon
  starts at login), the portal consent staying granted after a new login,
  the applet's activation shortcut, connecting to Wi-Fi, switching between
  two displays, and the whole settings page flow driven by hand from a blank
  state.
- The `qmllint` on this machine's `PATH` is the Qt 5 one. It cannot parse
  these files, and Qt tools log to the journal unless
  `QT_FORCE_STDERR_LOGGING=1` is set, so earlier "lint passed" results for
  the applet meant nothing. Use `/usr/lib/qt6/bin/qmllint`. It found an id
  shadowing a property and a role named `state` clashing with `Item.state`.
- The settings pages can be loaded outside Plasma to catch load errors:
  `QT_FORCE_STDERR_LOGGING=1 QT_QPA_PLATFORM=offscreen qml6 ConfigSetup.qml`.
  `i18n` and `Plasmoid` are undefined there, which is expected noise.
- A text field in a panel takes right-clicks for itself, so Plasma's widget
  menu never appeared. The applet has its own right-click menu.
- A model service's `/v1/models` can be a catalogue: the NPU service lists
  50 models and has one loaded. Discovery asks the Ollama-style `/api/ps`
  where it exists and shows loaded models first, the rest on request.
- Probing every local listening port hits non-HTTP services (an SSH port
  answered with its banner). Probes treat any protocol error as "not a
  model service", and a failing endpoint now returns a JSON error instead of
  dropping the connection.
- A cost of the chosen approval policy, seen once: asked only to find a
  document, the local model created an empty folder first (`make_directory`
  is a change, so it ran unprompted) and then said so. Nothing was lost, and
  the action log recorded it. `kde-ai-assistant policy changes` prevents
  this class of surprise at the price of more prompts.

**After Phase 6: look and behaviour changes (2026-11-23, from the maintainer's use).**

- The panel shows only the assistant's icon; typing happens in a popup
  above it (Meta+Space or a click). Typing inside the panel made Plasma draw
  its own blue panel focus indicator, which a widget cannot switch off.
- File matches and the conversation take turns in the popup instead of
  sharing it; saved conversations are listed in a sidebar and kept for
  `history_days` (default 30) in `$XDG_DATA_HOME/kde-ai-assistant`.
- The popup sizes to its content from exact column heights. Sizing it from a
  ListView's estimated `contentHeight` made the window resize itself in a
  loop (it "jumped up and down").
- The maintainer asked it to install Ladybird and could not tell whether anything was
  happening. It was building from the AUR with a 10-minute limit and a final
  `sudo` step it could not answer, and it retried after being stopped.
  Now: running steps report progress every second, Stop kills the command,
  long requests end with a notification, commands that need a password are
  refused in the background and go to `run_in_terminal` instead, and
  installing system software is classed as `danger` (it was only removals).
- A second Ladybird attempt went wrong differently: `run_in_terminal`
  returned as soon as the window opened, so the model polled `ps` (18 times
  in 70 s), judged installs waiting for the maintainer's password "stuck", and killed
  them twice. `run_in_terminal` now waits for the command (run under
  `script` so prompts still work, with a status file for the exit code),
  reports "Waiting for you in the terminal window" as progress, and returns
  the exit status and output. Stop leaves the terminal running. The maintainer kept the
  approval rule as is: with tools running one at a time, nothing can kill
  the install while it runs.
- The maintainer's standing preference, now in the system prompt: install from a
  pre-built package (repositories, `-bin`, Flatpak) before building from
  source, and never kill a program started for him unless asked.
- A third attempt installed Ladybird, but from an unofficial nightly
  (github.com/harilvfs) via `curl … | bash`, which ran without approval and
  used sudo to add `/etc/ssl/ladybird-ca-bundle.crt`. Official options
  existed: AUR `ladybird-bin` (it searched with `pacman -Ss`, which cannot
  see the AUR) and the project's Flatpak (it asked Flathub instead of the
  `ladybird` remote). Now a downloaded script run in one step is `danger`
  and the approval names its source, and the model must use official
  sources in order and ask before any third-party build. The maintainer had the
  nightly removed.
- The fourth attempt installed the official Flatpak correctly but it did not
  show in the launcher: the Plasma shell had been started without the
  Flatpak folders in `XDG_DATA_DIRS`. The maintainer's point: the assistant must finish
  installs itself. New tools `verify_app_install` (is the entry in a folder
  the running shell searches, and in the menu cache built for that list?)
  and `refresh_app_menu` (rebuild the cache; if the shell lacks the folder,
  update the session environment and restart the shell just after the
  request, since restarting mid-request would end it). The model may report
  an install as done only after verification.
- "Update my system" ran `pacman -Syu` and `yay -Su` twice: after the
  first pass the local model started the task again, then wrongly said no
  reboot was needed after a kernel upgrade. The terminal log had been read
  in Python text mode, which turns progress-bar carriage returns into
  newlines, so the model got 4000 characters of progress-bar redraws with
  the package list cut off (and systemd's OSC 3008 markers carrying the
  host and machine id). Now `tools/terminal_text.py` collapses redraws and
  strips escape sequences, results keep their start and end, a non-zero
  exit is a failed step, a terminal result says when a reboot is needed,
  and an approval-needing step that already succeeded in the same request
  is not run again.
- Verified with a real Konsole (a harmless command; nothing installed).
  Not verified: a real install, and whether the local model describes a
  declined action accurately (in one test it claimed to have opened the
  terminal after the user declined).

## Decisions

- Approval is required only for `danger`: deletion, or OS-level changes that
  could crash the system or stop it booting. Everything else runs unprompted.
- GUI control (Phase 5) is required for the first usable release.
- Both local services are offered as suggested models; neither is a default
  baked into code.
- The surface is a search bar in the panel beside the launcher, not a chat
  sidebar.
- File search and web search use the user's existing index and search tools
  through MCP; this project does not build its own index or search engine.
- It must install and configure in one go and behave as one app.
- LocalContext was changed for this project (the maintainer, 2026-11-22: "the point of
  the index was to support this project"). It now embeds local document
  chunks in the background and offers `machine_context_hybrid_search`. The
  as-you-type role stays on the lexical `machine_context_search`; the hybrid
  tool takes seconds and is for the model to call.
- Existing projects were surveyed on 2026-11-22 (PlasmaLLM, KDE Assistant,
  kde-ai, computer-use-linux, kwin-mcp). None is this product.
