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
  type, with no model call; Enter opens the top hit.
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
  only. No model. Results are selectable with the keyboard.
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
   Existing MCP servers already do this on KDE (`computer-use-linux`,
   `kwin-mcp`). Evaluate bundling one behind the MCP client before writing
   this tier; a bundled server must install with the app, not separately.
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
- API keys: KWallet through the Secret Service when available, else a `0600`
  file under `~/.config/kde-ai-assistant`. Never in Plasma applet config, never
  returned by an endpoint, never logged.
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
    providers/          base contract, openai_compatible
    tools/              registry, one module per domain (windows, files, ...)
    mcp_client.py       stdio MCP sessions, child-process supervision
    instant_search.py   no-model query path to the file_search tool
    permissions.py      risk classes, policy, pending approvals
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
configured; killing the index server shows a recoverable error.

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

**Phase 5: GUI control.** Tier 3, built in or through a bundled MCP server.
*Exit:* "click Save in the focused dialog" and typing into a focused field
work in a Qt and a GTK app on a text-only local model.

**Phase 6: One-go install and setup.** First-run setup, settings page,
single install and uninstall commands, error messages with fixes. Test on a
fresh user account with no prior configuration.
*Exit:* on a fresh account, one install command plus first-run setup reaches
a passing acceptance run with no file edited by hand. **This completes the
first usable release: Phases 0 to 6.**

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
- Existing projects were surveyed on 2026-11-22 (PlasmaLLM, KDE Assistant,
  kde-ai, computer-use-linux, kwin-mcp). None is this product; the last two
  are candidates to bundle for tier 3.
