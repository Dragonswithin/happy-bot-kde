# Happy Bot: Product Goal And Roadmap

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
| Local GPU model | loopback llama.cpp service, OpenAI-compatible, **tool calls supported**, parallel tool calls, 131072 ctx, **text only (no vision)**, one slot |
| Local NPU model | loopback FastFlowLM service, OpenAI-compatible; tool-call support unverified |
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
- One config file under `~/.config/happy-bot`, edited only through the
  settings dialog or CLI. Every value in it, and every option the applet has,
  has a control in the settings dialog: the user never edits a file.
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
  `$XDG_RUNTIME_DIR/happy-bot`. Other local users can reach loopback.
- Keep the bind loopback-only.
- API keys and other secrets (tool-server environment values, model request
  headers) live in the one settings file, `0600`, under
  `~/.config/happy-bot`. They are never in Plasma applet config, never
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
src/happy_bot/
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
    search_choices.py   what can do file or web search here, for "Set up"
    search_setup.py     uses one choice: adds it, assigns the job, tests it
    file_index_server.py  built-in MCP server over KDE's index or plocate
    instant_search.py   no-model query path to the file_search tool
    desktop_actions.py  actions on the desktop, starting with opening things
    settings.py         config file, secret lookup
    desktop_context.py  existing KWin / Klipper / Spectacle capture
tests/
```

`scripts/install.sh` currently copies two single files; it must install the
package (for example under `~/.local/lib/happy-bot`) with thin
launchers in `~/.local/bin`.

## Phases

Each phase ends with something demonstrable. Do not start a phase before the
previous exit check passes.

**Phase 0: Baseline and bar spike.** Run the installer, confirm the daemon,
CLI context commands and `plasmawindowed` applet work as they are. Remove the
dead `ai.example.com` default and the `/open-full-ui` path (daemon, CLI
and applet). Spike a text field as the applet's panel form: typing, focus by
shortcut, popup under the bar.
*Exit:* `happy-bot status` and `context` succeed; a text field in the
real panel accepts typing and opens a popup, or the fallback is chosen and
recorded here.

**Phase 1: Secure daemon and package split.** Token auth, Origin/Host checks,
no CORS wildcard, package layout, installer update, unit tests for auth.
Split only what exists today (`daemon_http.py`, `desktop_context.py`); do not
create empty placeholder modules for later phases. The applet needs a way to
obtain the token: QML `XMLHttpRequest` refuses local files unless
`QML_XHR_ALLOW_FILE_READ` is set, so settle the mechanism with a short spike
first (candidate: the `org.kde.plasma.plasma5support` executable data source
running a `happy-bot token` subcommand).
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

**Phase 7: Effortless setup, then the half-done backlog** (placed by the
maintainer on 2026-11-23, in this order).

1. Setup an 8-year-old can do: one press sets up file search and web
   search, picking from what the computer already has and verified
   suggestions; one press asks Plasma's permission for typing into other
   apps; every self-check fix names the button that fixes it.
2. Answer cards and Markdown (§1): richer cards in answers (weather,
   definition, conversion, file lists) and a Copy button per code block.
3. A model per task (§15): a fast model for small actions and a strong one
   for long tasks, chosen automatically.
4. Install and update polish (§8): official sources first with a real
   install verified, and system update with reboot detection.
5. Packaging, translations and accessibility (§19): publish the AUR
   package, ship translation catalogues, and review the UI for screen
   readers, contrast and keyboard use.

*Exit:* on a fresh account with only a model chosen, an 8-year-old's path
works: Set up next to Files, Set up next to Web, Allow typing, each one press
with no typing except an API key the user chooses to use; then each later
item passes its own check recorded under Phase 7 findings.

**Phase 8: Search speed-ups** (placed by the maintainer on 2026-11-25, from
the ideas chosen that day in `docs/FEATURES.md`). The panel bar finds,
launches and now does, still with no AI: recent items as chips on the empty
bar, instant commands, emoji and special characters, and actions on an
application or file result.
*Exit:* in the real panel, a person sees the empty bar's chips and opens
one from the keyboard, runs "volume 30" and "timer 10m" with Enter, copies
a character found with "emoji heart", and uses an application's Start at
login and a file's Send to phone from their right-click menus.
Status: built, exit check not yet passed (see Phase 8 findings).

**Phase 9: Fix selected text** (placed by the maintainer on 2026-11-25,
next on the list chosen that day). Select text in any application, press
the "Fix selected text" shortcut, choose Fix grammar, Shorter, Translate or
Explain (or type an instruction), and Replace puts the result in place of
the selection.
*Exit:* in a real application (a text editor and a browser field), a person
fixes, shortens and translates a selection and replaces it from Happy Bot,
the application's Undo brings the old text back, and the clipboard holds
what it held before.
Status: built, exit check not yet passed (see Phase 9 findings).

**Later.** Native providers, broker-backed privileged actions, packaging
(AUR, KDE Store), non-stdio MCP transports. The full feature backlog, and the
priority order the maintainer chose for after the first release, is in
`docs/FEATURES.md`; an item there is planned only once it is placed in a
phase here. Image and voice input, first deferred on 2026-11-23, were built
on 2026-11-25 once the maintainer gave the GPU service a vision projector
and the NPU service Whisper (see the findings below and the backlog's "Image
And Voice Input"); spoken answers are still to come.

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
  (Later inverted: the icon became the default and the field the
  `inputInPanel` option; see "After Phase 6" below.)
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
- Both servers were set up through `happy-bot tools import` and
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
  the action log recorded it. `happy-bot policy changes` prevents
  this class of surprise at the price of more prompts.

**After Phase 6: look and behaviour changes (2026-11-23, from the maintainer's use).**

- The panel shows only the assistant's icon; typing happens in a popup
  above it (Meta+Space or a click). Typing inside the panel made Plasma draw
  its own blue panel focus indicator, which a widget cannot switch off.
  The maintainer then asked for the panel search bar back as an option, the
  indicator accepted by whoever picks it: "Show in panel: Search bar" (the
  applet's `inputInPanel` and `barWidth` settings) restores the Phase 0
  field (`PanelBar.qml`), and the popup then only shows results, as a
  tooltip-type window that never takes focus. The icon stays the default
  and vertical panels always use it. It loads without QML errors in
  `plasmawindowed`; not yet tried by a person in a real panel. At the
  maintainer's request the logo at the bar's left end is a button of its
  own: a click opens the popup on the current conversation and the saved
  ones with nothing typed, and a second click closes it.
- File matches and the conversation take turns in the popup instead of
  sharing it; saved conversations are listed in a sidebar and kept for
  `history_days` (default 30) in `$XDG_DATA_HOME/happy-bot`.
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
- The maintainer's standing preference, then in the system prompt (since 2026-11-23 in
  his editable instructions): install from a pre-built package
  (repositories, `-bin`, Flatpak) before building from source, and never
  kill a program started for him unless asked.
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

**Settings dialog covers everything (2026-11-23, the maintainer: "the end user should
not need to configure anything in a file").**

- The dialog has five pages: AI Model, Search & Tools, Behaviour, History &
  Folders, and Search Bar (plus Plasma's Keyboard Shortcuts). Before this,
  model headers, context window and vision, tool-server environment values,
  commands, on/off and allowed tools, hand-picked role tools, connecting a
  server by hand, `history_days` and three of the six folders could be set
  only through the CLI or the file.
- New daemon settings, section `agent`: the user's own instructions (added
  to the system prompt), steps per request, the command time limit, the
  finish-notification delay, the terminal, and built-in action groups the
  user switches off. A switched-off group is left out of the tool list
  altogether, and the model is told so, rather than relying on it to obey.
- New applet settings: live results on or off, minimum characters, pause
  and result count.
- Left as environment variables, because no user needs them: the daemon's
  host and port, the CLI's daemon address, and the root broker path and
  group (the broker is only reported, not used, until broker-backed actions
  are built).
- The maintainer's standing preferences (official and pre-built install sources first,
  ask before third-party sources, never stop a program started for him) were
  hard-coded in the system prompt, so the new Instructions field showed
  nothing. They moved into `agent.instructions`: new users start from a
  distribution-neutral suggested text (`settings.SUGGESTED_INSTRUCTIONS`,
  "Restore suggested" on the page), and the maintainer's own Arch wording (pacman, then
  the AUR through yay preferring `-bin`, then the project's Flatpak remote)
  was written to his settings. The system prompt keeps only what the tools
  need to work (run installs in the terminal, verify an install).
- Verified: unit and endpoint tests; `qmllint`; every page loaded with
  `qml6` offscreen; every editor's save path exercised against a fake
  settings store. Not verified by a person in the real dialog.

**Backlog built (2026-11-23, the maintainer: "add and test all the pending features").**

The maintainer's four priorities came first, then the rest of `docs/FEATURES.md`, whose
status marks say what is built (●), partial (◐) and deferred (⏸, with the
reason). Where things live:

- Undo and trust: `undo_journal.py` and `tools/undo.py` (undo_change,
  recent_activity, tool_usage); the per-turn `actions` and `usage` on the
  `done` event (`agent_loop.py`), shown as "Not done: …" and model/token
  lines in the popup; `redaction.py` for hosted models; `agent.confirm_plans`.
- Media and phone: `session_dbus.py`, `tools/media.py` (MPRIS, sound
  devices, per-app volume, microphone, music by name, playlists),
  `tools/phone.py` (KDE Connect; SMS is `danger`, see below).
- Reminders and routines: `user_timers.py`, `tools/reminders.py`,
  `routines.py` (setting, prompt lines, unit sync), `tools/routine_tools.py`,
  the Routines & Reminders settings page, `ask --dry-run --notify`.
- Bar: `quick_answers.py`, `quick_results.py` (`/quick`), prefixes and
  recall (`barInput.js`), right-click file actions, drag and drop,
  `krunner_bridge.py` with `krunner/happy-bot.desktop`, and the
  global-shortcut entry `desktop/happy-bot-shortcuts.desktop`.
- More tools: `power.py`, `appearance.py`, `devices.py`, `defaults.py`,
  `documents.py`, `screen.py`, `workspace.py`, `software.py`,
  `developer.py`, `finding.py`, `notes.py`, `memory.py`, `plugins.py`.
- Platform: `mcp_http.py` (HTTP tool servers), `mcp_serve.py` (lend the
  built-in tools to other AI programs), `self_check.py` (`doctor`, "Check
  everything"), `personal_data.py` (`export`/`import`), `spend.py` (prices,
  monthly cap), local fallback model, `evaluation.py` (`eval`),
  `packaging/arch/PKGBUILD`, `plasmoid/…/Messages.sh`.

Checked live on the maintainer's desktop: quick results and KRunner matches over DBus;
a reminder that fired on time; a folder-watching routine that ran the local
model and notified; create-then-undo through the local model; `doctor` all
healthy; `eval` 8 of 8 on the local GPU model; media, phone, devices,
appearance, power, software and finding read tools; the package build. Not
checked by a person: every new settings control and popup change in the real
panel, ringing the phone, sending SMS, Bluetooth pairing, the global
shortcuts (KDE registers the entry at the next login), drag and drop.

Findings:

- A safety rule had to be added after a live check went wrong: a large
  data disk on the test machine is USB-attached and mounted under `/srv`, so it looked
  "removable", and checking the drive tool started a real unmount (it timed
  out at the password prompt; nothing was unmounted). Drives mounted outside
  the desktop's media folders are now refused, and mutating tools are no
  longer tried live against real devices.
- The test suite wrote into the maintainer's real undo journal and spending record,
  because tools record under `$XDG_RUNTIME_DIR` and `$XDG_DATA_HOME`.
  `tests/isolation.py` now gives every test process private folders; the
  stray entries were removed.
- Sending a text message (`send_sms`) and deleting saved routines, layouts or
  remembered facts are classed `danger`. SMS goes beyond the maintainer's two-part
  definition: a message to another person cannot be taken back.
- A second round built weather (`tools/weather.py`, Open-Meteo), mice,
  touchpads and key repeat (`appearance.py`), pinned conversations, routines
  that run when a drive is plugged in (a service the drive's device unit
  wants), finding a window by what it shows (`workspace.py`), opening
  folders and terminals (`apps.py`), a digest of turns dropped from long
  conversations (`conversation.trim_history`), media downloads with the
  user's yt-dlp, and an Open button on the "finished" notification. A
  third round added routines that run on joining a network or when the
  battery runs low (`routine_conditions.py`, checked every two minutes by a
  timer, firing once when the condition becomes true).
  `desktop_actions.open_assistant_popup` opens the popup by invoking the
  applet's "activate widget" shortcut action through KGlobalAccel; the maintainer saw
  the popup open when it was tried. The maintainer also confirmed the popup's settings
  gear works.
- Neither configured model takes images or audio; OCR (`text_from_image`) is
  the image route for now. Image and voice input, and a local model to test
  them, are deferred by the maintainer to a later phase.

**Phase 7 (started 2026-11-23).**

- One-press search setup: "Set up" next to Files and Web lists choices best
  first (`search_choices.py`) and "Use this" adds the tool, gives it the job
  and runs a test search, undoing everything if the test fails
  (`search_setup.py`). Choices: servers already set up for other AI
  programs that pass a test search; KDE's file index and the plocate
  database through `happy-bot file-index-serve` (`file_index_server.py`);
  for the web, a SearXNG found on this computer, DuckDuckGo (no key), Brave
  and Tavily (keys). The suggested packages were checked on npm and PyPI and
  started once to read their tool names; their versions are pinned.
- Findings from trying it against a throwaway daemon with empty settings:
  the wording guess offered an offline-encyclopedia server (openzim) for
  file search because its description mentions documents, so a found server
  must now return at least one path that exists on this computer. A port
  that speaks SSH broke the SearXNG probe until HTTP protocol errors were
  caught. plocate's database does not cover `/home` on this machine (a
  separate btrfs subvolume), so the file-names choice is offered only when
  the database reaches the user's home.
- Verified on that daemon: DuckDuckGo and the maintainer's own file index
  were set up with one press each and the bar's file search returned real
  files; a missing API key was refused before anything changed; a wrong
  SearXNG address failed its test and left the previous web search in
  place; KDE's file index was set up through the installed command. Not
  verified: switching KDE's file index on from the button (it was left off
  on the maintainer's account), and the settings page driven by a person.
- Typing permission: the Behaviour page shows whether typing into other
  apps is allowed and an "Allow…" button that shows Plasma's question now
  (`POST /typing/allow`). Not yet pressed by a person. Triggered once from
  the daemon on the maintainer's account: Plasma's portal received the
  request and nobody answered within the two minutes, so it stays unset.
- Answer cards: answers are drawn by `AnswerBody.qml`, which splits the
  Markdown (`answerParts.js`, tested in Node by `tests/test_answer_parts.py`)
  into text, code blocks (each with its language and its own Copy button)
  and lists of two or more file paths (rows with the file type's icon or a
  picture's thumbnail, opened with a click). A tool can now attach a card to
  a successful result (`Tool.card`, sent as `card` on `tool_result`); the
  weather tool reads its own text back into one, drawn by `WeatherCard.qml`
  under the step. Both were rendered offscreen with the KDE theme and
  looked right; neither has been seen in the real popup yet.
- A model per task, as the maintainer chose ("start quick, hand over"):
  with `agent.quick_model` set, every request starts on that model with at
  most `QUICK_MODEL_STEPS` (4) model requests. If it fails at any point or
  uses them all, the chosen model continues the same history (which holds
  the quick model's steps and results) after a notice, and the final `done`
  reports both models' actions. The quick model is skipped when it would
  break "local only" or the spending cap. Verified against a throwaway
  daemon: an unreachable quick model handed a request to the local GPU
  model, which answered, and the notice was recorded. Not verified: a real
  quick model running out of steps (covered by a scripted test).
- Updates: `check_updates` (read) reports what is waiting from the
  distribution (`checkupdates`), the AUR (`yay -Qua`) and Flatpak, warns
  when the kernel is among them, names any source it could not check
  instead of calling it up to date, and gives the single update command for
  `run_in_terminal`, after which the shell tool's existing restart check
  applies. On the maintainer's computer it reported nothing waiting, which
  matched the three commands run by hand. Installing an app from official
  sources was then verified with a real install the maintainer asked for:
  "install the KDE colour chooser" searched every source, ran
  `sudo pacman -S` in a terminal after approval, waited for the
  maintainer's password and confirmed the launcher entry; pacman's log and
  the desktop file agree. A real system update has not been run yet
  (nothing was waiting).
- Translations: `scripts/translations.sh` makes the template from every
  `i18n`/`i18np` call (all 329 distinct source strings checked present),
  merges `po/<lang>.po` files and compiles them into a staged copy of the
  applet; the installer and the Arch package install that copy, so compiled
  files never enter the checkout. A throwaway German file went through the
  real installer into the installed applet and was removed again. No
  translation exists; which languages to offer is the maintainer's call.
- Accessibility: result rows, saved conversations and the "Ask the
  assistant" row now have screen-reader names, and the Menu key or
  Shift+F10 opens the selected match's actions (before, only a right-click
  did). Not yet tried with Orca.
- Publishing the AUR package and the KDE Store entry is a public action on
  the maintainer's accounts and waits for him.
- AI Model page, after the maintainer found it confusing (2026-11-24): it now
  asks two questions, "Ask first" (`active_model`) and "If it fails, ask"
  (`agent.fallback_model`, local models only), and adds an AI three ways:
  found on this computer (each with "Ask first" or "Use if it fails"),
  "Online service…" (`model_presets.py`: twelve services, each with its key
  page, directions and suggested models, checked against the services' own
  documentation) or "By hand…". Every addition goes through
  `POST /models/use` (`model_setup.py`), which tests the model and removes
  it again if it does not answer. Checking the services showed that
  DeepSeek, Kimi and Gemini refuse a follow-up request unless the
  assistant's reasoning or tool-call signatures come back unchanged; the
  provider now keeps them as `echo` and sends them back only to the same
  address. Claude keys not scoped to a workspace need an extra header, so
  the Claude directions say to pick a workspace. Verified on a throwaway
  daemon: the NPU model set to answer first and the GPU model as backup
  (both answered and used tools), a refused OpenRouter key left nothing
  behind, and a missing key was asked for. The maintainer's own settings
  were set the same way (NPU first, GPU if it fails, no quicker model).
  Not verified: any online service with a real key.
- Still too confusing for the maintainer, so the page became one ordered
  list (`model_order`) with each AI's settings under it. The order replaces
  the main, backup and quicker-model settings: requests go down the list,
  a model that fails hands the request to the next, and one marked
  `hand_over_long` passes long requests on. Spending limits are per model
  (`monthly_cap`); a model over its limit is skipped. The maintainer
  allowed online models anywhere in the order (2026-11-24): the user places
  them, and the page marks them online; "local only" still skips them.
  Settings from before are converted on load (quick model first with
  `hand_over_long`, then the active one, then the fallback; the old total
  cap becomes each priced model's limit); the maintainer's converted to
  NPU first, GPU second. Verified on a throwaway daemon: with an
  unreachable model first and the GPU model second, the GPU model answered
  after a notice.
- Per-chat AI picker, at the maintainer's request: `ModelPicker.qml` sits
  beside the popup's field (in the header when the panel bar is used) and
  appears only with two or more AIs. "Automatic" follows `model_order`;
  picking one sends `model` with each request of the chat, the daemon keeps
  it on the conversation (`Conversation.model`) and returns it with the
  chat, and `/health` lists the AIs (name, online) for the picker. Plasma's
  own combo box made binding loops on its implicit size in the popup, which
  resizes to its content, so the picker uses the standard one at a fixed
  width. Loads without errors in `plasmawindowed`; not yet used by a person.
- OpenAI's newest models refused tools on `/chat/completions` when the
  maintainer added one ("Function tools with reasoning_effort are not
  supported for gpt-6-luna in /v1/chat/completions"). A second provider
  kind, `openai_responses` (`providers/openai_responses.py`), speaks OpenAI's
  Responses API from its documentation: flat tool definitions, the history
  as input items, `store: false`, and each response's output items
  (reasoning with its `encrypted_content`, messages, function calls) replayed
  unchanged through `echo`, which OpenAI requires with the tool results that
  follow. The OpenAI preset uses it; everything else stays on chat
  completions. Tested against recorded-style events; not yet with a real key.
- Floating button and hotkey, at the maintainer's request:
  `FloatingButton.qml` is a LayerShellQt surface on the top layer (above
  windows, below full screen, never focused), so the application in use
  stays active. Its position is the layer-shell margins from the screen's
  top left, saved as `floatingX`/`floatingY`; a test showed margins set
  after the window appears take effect only with a new frame, so each move
  redraws, and that QML must assign them as a plain `{left, top, ...}`
  object (`Qt.rect` gives wrong values). The hotkey is the widget's global
  shortcut, now also on the Search Bar page. Both call
  `openForApplication`: `GET /context/app` names the window in use (the
  topmost ordinary window, so the popup itself is never it; the name comes
  from its desktop entry), the popup shows "Helping with: …", and each
  request carries it as `about_window`, which `ask_stream` turns into a
  note at the start of the model's copy only. Seen working: the button
  appearing in place from the widget (checked by its colour in a
  screenshot). Not yet tried by a person: clicking, dragging, the hotkey.
- The maintainer found the button only handed over to the panel bar, which
  users may not show. The floating window now opens into Happy Bot itself:
  it grows from the button toward the middle of the screen and holds the
  same `ResultsView.qml` as the popup (field on the side nearest the
  button, then matches or the conversation), takes the keyboard only while
  open (layer-shell "on demand") and closes on a click elsewhere, Escape or
  its close button. While it is open it is main.qml's `surface` for the
  keyboard handlers. With the button on, the hotkey opens it too. A test
  copy started open showed the field and AI picker in place.
- The floating button's right-click first opened the widget's own menu,
  whose "Remove from panel" removes the whole widget, floating button
  included; the maintainer's widget was removed that way (2026-11-23,
  23:41) and was put back with its search bar, mascot and floating button
  switched on. The floating button now has its own menu (settings, new
  conversation, hide the floating button) without that entry.
- The maintainer then asked for Happy Bot to be an app of its own that also
  has a Plasma widget, so it is in the application list and works floating
  or from the panel. `happy-bot-app` runs the widget in Plasma's
  `plasmawindowed --statusnotifier`, which gives it the "application" form
  factor; there it hides plasmawindowed's window and is only the floating
  Happy Bot (the panel widget no longer has a floating button, so there is
  never a second one). The menu entry `io.github.dragonswithin.happybot.desktop`
  runs the launcher; a second launch reaches the running app through the
  daemon (`happy-bot app show` → `POST /app/show`, which the app waits for
  on `GET /app/wait`), because its tray entry is not registered while its
  window is hidden. Starting it now or at login is on the Search Bar page
  (`POST /app`, `app_control.py`). KWin counts the floating window as an
  ordinary window, so the "window in use" lookup skips Happy Bot's and
  Plasma's own. Verified: the app starts with its window hidden and the
  button in place; "show" opened it (720×324, focused) and a second one
  closed it; the window in use stayed Konsole while it was open; an
  install restarts a running app on the new version.
- Settings belong to the app (the maintainer, 2026-11-24): the panel
  widget's own settings are only what concerns it (icon or search bar, the
  bar's width, the daemon's address). Happy Bot's look and feel moved from
  each copy's Plasma settings into the daemon's `ui` settings
  (`ui_settings.py`, `POST /ui`, read with `/health`), so the panel widget
  and the app match, including the mascot. The dialog's page list depends
  on the copy (`config.qml`): the app shows Appearance and the five daemon
  pages, the panel only Panel. The dialog opens on the first page even when
  it is hidden, so that page is one entry that is Appearance or Panel. In
  the panel, "Configure Happy Bot…" opens the app's settings, starting the
  app if needed (`POST /app/show` with "settings"; the wait's answer
  carries the action and its age so a just-started app still acts on it).
  Each copy handed over its old values once ("imported"): the maintainer's
  robot mascot came from the panel and the floating position from the app.
  The hotkey stays the app copy's own desktop shortcut. Verified: both
  copies show the robot; each settings dialog showed the right pages.
  A change made in one copy reaches the other within the 12-second status
  check.
- The maintainer found two X buttons when opening the floating Happy Bot:
  the "Helping with" line's (which only stopped sharing the application)
  and, only once something showed below the field, the header's. Clicking
  the first did not close Happy Bot. The application awareness is now
  invisible, as the maintainer asked: no "Helping with" line, and the note
  to the model is worded as background that it ignores when the user asks
  about something else. The floating Happy Bot always shows its header
  (`ResultsView.alwaysShowHeader`), so its one close button is always there.
- Asked to put the wallpaper back to a slideshow of a folder, the model
  (Qwen 3.6 on the NPU) found no tool for it: set_wallpaper took one
  picture only. It wrote invented keys into kdeglobals, quit plasmashell
  and started it again from a shell command, so the new shell lived inside
  Happy Bot's own service, and twice said it was done without checking; the
  wallpaper never changed. set_wallpaper now takes a folder for a slideshow
  (through Plasma's desktop scripting, at once, no restart) and reads the
  result back before reporting it; quitting, killing or hand-starting the
  desktop shell or KWin is now `danger`, its reason naming
  `systemctl --user restart plasma-plasmashell.service`; and the
  instructions say a change is done only once seen to take.
- The maintainer found file results popping up over a reply typed into an
  open conversation, and over "Search the web". Typing no longer searches
  at all (the `instant_*` settings are retired and dropped from stored
  settings); only "Find a file" on the welcome screen opens a file finder
  (`AssistantSession.findingFiles`) with matches as the user types; a click
  (or Down and Enter) opens one, Enter alone asks the assistant to find it. The labelled
  "Close chat" button replaces the bare "+" that already went back to the
  welcome screen, and "Desktop help" names the application in use ("Help
  with Kate", from `/context/app`, now with the icon from its desktop
  entry), so the application awareness is visible where it is offered.
- The maintainer could not find how to get the panel search bar back: it
  was behind a second right-click entry, "Panel widget settings…", beside
  "Configure Happy Bot…", and the Appearance and Panel pages each had an
  "Advanced" daemon address that said not to use it. Happy Bot now has one
  settings dialog: the app's Appearance page sets the panel widget's icon
  or search bar and the bar's width through the Plasma shell
  (`panel_widget.py`, `/panel`), the second menu entry is gone, the
  widget's own Plasma page only points to the app's settings, and the
  address has no field (it stays a hand-edited setting).
- Asked what the context-aware help really did: it only told the model the
  application's name and window title. The maintainer chose a privacy
  setting (`agent.app_context`: off, AIs on this computer only, any AI;
  default local) and richer context: version info with every request from
  an application, and for a chat started with "Help with …" the selection,
  the window's controls and its open file (`app_snapshot.py`). The note and
  private tool results (`Tool.private`: ui_snapshot, ui_get_text,
  selected_text) are kept apart in the history (`Message.context`,
  `Message.private`) and each model's copy is built by
  `app_context.for_model`, which also closes a gap found on the way: tool
  results read by a local model reached a later online one unredacted.
  Konsole publishes no accessibility interface, so its controls cannot be
  read; Dolphin's could (101 controls, a note of about 5,000 characters).
  Screenshots for picture-capable models wait on image support in the
  providers: the `vision` model setting is stored but nothing sends images.
- Screenshots followed: both providers send pictures (`Message.images`,
  `providers.base.image_data_url`), and the maintainer marked the online
  AIs as seeing pictures. The capture first ran when Happy Bot opened; the
  maintainer refused that ("users would get very upset if it took pictures
  at launch"), so it happens only after "Help with …" is clicked
  (`POST /context/screenshot`): KWin makes the application active, Spectacle
  captures that window once KWin reports it active, and the popup or
  floating view stays open (`holdOpen`) and takes focus back. The panel
  widget also noted no application ("Desktop help" always); it now notes
  the topmost window as the floating button does.
- The maintainer asked Gemini for help with Konsole and saw several failed
  tool calls ("arguments were not valid JSON ... Extra data"). Captured
  live: Gemini's OpenAI-compatible stream sends each tool call whole, with
  its own `id` and no `index`; the provider filed every fragment without an
  index under 0, gluing parallel calls into one (`{}{"query":...}`) and
  losing the rest. `openai_compatible._tool_call_slot` keeps calls apart by
  id when there is no index (and when an index is reused with a new id);
  checked against Gemini afterwards: two calls, both valid.
- So that other services' differences are caught before users meet them,
  `model_check.py` checks each configured AI through the real provider
  code: a streamed answer, one tool call with nested arguments, two calls
  at once, its own tool call and result sent back (echo), a conversation
  another AI started (hand-over), and a picture for `vision` models
  (`POST /models/check`, `happy-bot model check [NAME|--all]`, the AI Model
  page's Test). With the provider fix reverted it fails Gemini's parallel
  calls; with it, all five configured AIs (NPU, GPU, Claude, Gemini, GPT)
  passed every check on 2026-11-24, the online three naming the test
  picture's colour.
- Two follow-ups the maintainer chose: adding an AI now runs the full
  check (`model_setup.use`; one that does not answer is not kept, a problem
  is named in the message), and the test suite replays real services'
  recorded replies (`tests/test_recorded_replies.py`, recorded by
  `scripts/record_model_replies.py` for FastFlowLM, llama.cpp, Anthropic,
  Gemini and OpenAI's Responses API on 2026-11-24). Recordings are synthetic
  requests' replies only, scanned for keys and personal details before they
  are saved; the maintainer chose to keep them in the repository, an
  exception to "no command output in the repo". With the Gemini fix
  reverted, the replay fails on Gemini's parallel calls.

**From the maintainer's use (2026-11-25).**

- Search, after three rounds of the maintainer's use: the panel's search
  bar is a launcher-style search. As the user types, applications, settings
  pages, answers, saved chats and files show right above the bar
  (`PanelResults.qml`, a Plasma dialog that never takes the keyboard, so
  typing stays in the bar), under headings with applications first
  (`Look.groupHits`); Enter opens the top one, waiting for results if typed
  before them, and the AI is asked only from the "Ask Happy Bot about …"
  row. Typing "minecraft" had given an AI conversation instead of the
  installed Prism Launcher. The popup and the floating Happy Bot are the
  assistant again (typing there is a request); "Find a file" searches the
  same way as the bar. Open windows were dropped from results as odd. The
  bar clears after a result is opened, a request asked, or a click away.
- Browser bookmarks and recently visited websites can join those results,
  each switched on under Appearance → Search (`browsers.py`: Firefox and
  Chromium families, native and Flatpak, from private copies of their
  databases, kept in memory and never sent anywhere).
- Software: the search marks what is already installed (the model had
  offered to install Prism Launcher, which was installed), and with Shelly
  present the model installs through `shelly install` in a terminal, which
  `shell_risk` treats like `pacman -S`.
- Pictures: whether a model on this computer takes images is asked of its
  service when it is added (`model_discovery.sees_pictures`: llama.cpp's
  model list, or an Ollama-style `/api/show`); the GPU model passed the full
  check, naming the test picture. The NPU model also reports vision, but its
  runbook keeps picture work on the GPU, so it is left unmarked.
- Voice (`voice.py`): a microphone in the bar, the popup and the floating
  Happy Bot, and a "Talk to Happy Bot" shortcut. PipeWire records until a
  pause; only audio with speech is sent (Whisper "hears" "you" in silence),
  loudness-normalized 16 kHz mono with the language set, as the
  maintainer's Whisper needs; the text goes to the AI at once. The
  maintainer's first try with a weak microphone worked but missed words;
  judging that waits for a better microphone.
- Answer buttons (`tools/choices.py`): the AI can ask one short question
  with answer buttons or offer next steps to click; the turn ends there
  (`Tool.ends_turn`). Offered only to Happy Bot's own window. Live on the GPU
  model, "minecraft" offered "Open Prism Launcher" and two installs; a plain
  question got none. Thinking was left as it is: the GPU model's template
  only switches it on or off.
- The mascot gets live readings once a second (`system_sensors.py`: the CPU
  sensor with its own limit, PSI memory stalls, the default route's byte
  counters, reset on interface change, counter reset and resume). Checked
  live: a real download raised the download pose, a microphone capture
  during it took over, and the download pose came back after it.
- Fixes from use: the Behaviour page's two sets of choices acted as one
  (radio buttons sharing a parent; now `ButtonGroup`s); long instructions
  drew over the buttons (a fixed-height `ScrollView`); scrolling a settings
  page over a number box changed it (the popup width went from 30 to 22;
  number boxes now ignore the wheel); the floating view showed only its
  field when opening downward (anchors switched at run time; now placed by
  `y`); the finished-request notification can be switched off and shows the
  mascot when that is chosen.

**Phase 8 (built 2026-11-25).**

- Instant commands (`quick_commands.py`) are recognised from a fixed set of
  phrasings and come first in the results ("Do it now"); the result carries
  only the typed words, which the daemon parses again before running the
  built-in tool, so a request can do no more than typing. Words that are
  commands only when read loosely ("play", "sleep") are left out because
  Enter runs them at once. Checked live: "volume N" at the current volume
  ran `set_volume` for real and wrote the action log. A command that ran
  shows its title in Plasma's on-screen display (`org.kde.osdService`);
  one that fails opens the popup with the error.
- Characters (`characters.py`): emoji come from Plasma's own emoji picker
  dictionaries (`/usr/share/plasma/emoji/<language>.dict`, plasma-desktop),
  which turned out to be Qt's `qCompress` of a little-endian `QDataStream`;
  all 3,943 English entries parse exactly. Symbols come from Python's
  Unicode names over the blocks people type symbols from. Whole-word
  matches rank above prefixes ("pi character" gives π, not "pick"), and
  "right" counts as whole in "rightwards".
- Recent items (`usage_history.py`, `quick_results.recent`) read KDE's
  activity manager database read-only, the record the launcher's own
  Recent lists use. On the maintainer's account it holds applications, files,
  System Settings pages and, from Chromium, web pages; web pages are shown
  only with recent websites switched on. Files under `/tmp`, `/run` and the
  runtime folder are skipped, as is Happy Bot's own launcher. The chips are
  the same hits as rows (`RecentChips.qml`), so Down/Up and Enter work on
  them; nothing starts selected, so Enter on the empty bar still opens the
  popup, and Up from the field still recalls earlier requests.
- Application actions (`app_actions.py`): the package is found from the
  launcher file (Flatpak export folder, else `pacman -Qqo`, AUR when
  foreign). Update and Uninstall open a terminal with the user's package
  manager (Shelly's `update`/`remove` when installed), where the user
  confirms; without Shelly a distribution package's Update is the whole
  `sudo pacman -Syu`, because Arch does not support updating one package
  alone. Start at login writes the autostart entry, or `Hidden=true` over a
  system one. Each is written to the action log.
- After using it, the maintainer asked for the same chips in the popup's
  "Find a file", then for "Search the web" to work like it: a web finder
  (`AssistantSession.finder` "web") shows recent websites as chips, then
  matching bookmarks and visited websites and, after a 600 ms pause and
  from three characters, pages from the user's web search tool
  (`GET /search/web`, `instant_search.search_web`, under "On the web" with
  address and snippet); Enter opens one, the Ask row asks the AI to search.
  The maintainer's SearXNG answers in "Title:/Description:/URL:" blocks,
  which gave bare addresses until `extract_hits` learned to read such
  `Key: value` records; checked live, 0.7 to 1.5 s per search.
- Rendered offscreen with the KDE theme (rows with glyphs, chips with a
  selection) and checked against a throwaway daemon (commands, characters,
  application info, refusals). Not yet seen in the real panel: installing
  the widget replaces the running one, which waits for the maintainer.

**Phase 9 (built 2026-11-25).**

- The shortcut (`desktop/happy-bot-shortcuts.desktop`, "Fix selected text",
  `happy-bot app fix`) reaches the app as a "fix" show request; the daemon
  notes the selection and its window at that moment (`selection_fix`),
  before the app opens, and the app shows them in `SelectionFixCard.qml`.
  Checked live: a primary selection set by hand was noted with its window,
  and a Kwi window was recognised as a terminal, where Replace is refused.
- The rewrite (`text_rewrite.py`) asks the first AI in the user's order
  that the `app_context` privacy setting lets see text from applications,
  once, without tools. On the maintainer's GPU model it took 15 s, nearly
  all hidden thinking; asking a local service to skip thinking
  (`chat_template_kwargs`, `create_provider(no_thinking=True)`, retried
  without on HTTP 400) made it 0.3 to 0.5 s with the same results.
  Conversations still think.
- Prompt findings, from live tries: under the rewriting instructions
  Explain rewrote the text, so it has its own; asked to say when a text was
  already in the user's language, the model called Spanish English, so
  Translate now names the language on its first line and the code compares
  it (English text, German, Spanish and two-line French all came out
  right). A typed instruction ("translate into French") is used as is.
- Replace pastes rather than types (`selection_fix.replace`): the clipboard
  is kept, the result put on it, the window brought forward, Ctrl+V pressed
  through the typing portal, and the old clipboard put back a second
  later. Happy Bot closes first so the application takes the paste. Not
  yet tried in a real application.

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
  Amended by the maintainer on 2026-11-23: setup also offers the indexes the
  computer already keeps (KDE's file index, the plocate file-name database)
  through a small built-in MCP server, `happy-bot file-index-serve`, so file
  search works on a fresh account. It reads those indexes; it builds none.
- Setup must be easy enough for an 8-year-old (the maintainer, 2026-11-23):
  one obvious button per job, plain words, the recommended choice marked,
  and a test that proves it works before anything is kept.
- It must install and configure in one go and behave as one app.
- The local file index used in development was changed for this project (the maintainer, 2026-11-22: "the point of
  the index was to support this project"). It now embeds local document
  chunks in the background and offers `machine_context_hybrid_search`. The
  as-you-type role stays on the lexical `machine_context_search`; the hybrid
  tool takes seconds and is for the model to call.
- Existing projects were surveyed on 2026-11-22 (PlasmaLLM, KDE Assistant,
  kde-ai, computer-use-linux, kwin-mcp). None is this product.
- The panel's search bar is where things are found and launched; the popup
  and the floating Happy Bot are the assistant (the maintainer, 2026-11-25:
  "the panel search box should act as a file/application search first and
  only engage the AI if the user clicks to start it").
- Browser history and bookmarks appear in search only when the user
  switches each on, and are read on this computer only (2026-11-25).
- What is said into the microphone goes to the AI at once, without a
  review step (the maintainer's choice, 2026-11-25).
- Choosing an instant command or an application's menu action in the bar
  is the user's consent to that one action, so the approval policy's
  `change` prompts do not apply to it; a command the tool classes as
  `danger` is refused there. Uninstalling, a deletion, runs only in a
  terminal where the package manager asks the user to confirm (made while
  building Phase 8 and kept by the maintainer, 2026-11-25).
