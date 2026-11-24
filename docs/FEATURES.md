# Happy Bot: Feature Backlog

This is the full list of what the assistant should eventually do to be useful,
grouped by area. It is a backlog, not a plan: `docs/ROADMAP.md` stays the
authority for the product goal, architecture, risk policy and phase order, and
an item here is built only after it is placed in a phase there. Everything
below must still fit the roadmap's four properties: one bar, any AI, the
user's existing tools through MCP, and one app.

Status marks:

- **✓** built and passed a phase exit check, or already covered by what was.
- **●** built on 2026-11-23 with automated tests ("checked live" where it
  was also tried on the maintainer's desktop); not yet checked by a person.
- **◐** built in part, or built but not verified; the note says what is missing.
- **⏸** deferred; the note says why (usually an outside dependency, or a
  decision that is the maintainer's).
- Unmarked: not started.

The roadmap's "Built 2026-11-23" findings list where each new feature lives.

## Priority After The First Release

Chosen by the maintainer on 2026-11-23, in this order, to follow the Phase 6 exit check:

1. **Undo and trust** (§17): undo the last change, a readable activity
   history, and checking the model's claims against the action log.
2. **Media and phone** (§10, §11): MPRIS playback control and KDE Connect.
3. **Reminders and routines** (§10, §12): timers, reminders, scheduled
   requests and named routines as user systemd timers.
4. **Bar quick results** (§1): apps, settings pages, windows, calculator and
   conversions while typing, with no model call.

## Image And Voice Input (Requested 2026-11-23, Deferred by the maintainer)

The maintainer asked for both, to be planned now and built later (⏸ below: "don't do
that now, just add it to the features/roadmap"). Neither configured
model takes images or audio today: the local GPU service runs
Qwen3.6-35B-A3B without a vision projector (llama.cpp reports vision and
audio off), and the hosted model is marked as not seeing images. Until then,
text in pictures is read with OCR (``text_from_image``), which works with
text-only models and stays as an option afterwards.

- ⏸ Choose and set up a local model that takes images, and one for speech to
  text, on the GPU (llama.cpp) or NPU (FastFlowLM) service, so both can be
  tested locally. This changes the development machine's model services and needs the maintainer's
  go-ahead on which model; candidates seen in the NPU catalogue include
  ``qwen3vl-it:4b``, ``qwen2.5vl-it:3b``, ``minicpm-v-4.7-moe:35b-a3b`` and
  the Gemma 4 models.
- ⏸ Image input: send screenshots and pictures to models marked "can see
  images", as image parts of the request; a "look at the screen" tool for
  them; OCR stays for text-only models.
- ⏸ Voice input: push-to-talk in the popup (microphone button and shortcut),
  recorded with PipeWire and sent to a speech-to-text endpoint the user
  chooses in settings; the text fills the bar or is sent at once.
- ⏸ Voice output: optional spoken answers through a text-to-speech endpoint
  the user chooses.

## 1. The Bar

- ✓ Meta+Space popup, live file hits while typing, Enter sends to the
  assistant.
- ✓ A choice of panel form: the icon with the popup (default), or a search
  bar typed into in the panel itself (the `inputInPanel` setting), which
  accepts Plasma's blue panel focus indicator while it has focus.
- ✓ Streamed answers, tool activity lines, approval cards, Stop.
- ✓ Saved conversations sidebar with `history_days` expiry.
- ● Instant results that are not files: apps, System Settings pages, open
  windows, recent conversations and calculator results, all with no model.
  (quick results; also in KRunner)
- ● Inline calculator, unit, currency, time-zone and date arithmetic ("3 weeks
  from friday") with no model. (currency is not done: qalc's rates need a
  network fetch)
- ● Optional prefix shortcuts for power users (`?` web, `/` files, `>` shell,
  `=` calc); never required, so the bar still has no modes.
- ● Up arrow recalls earlier requests; Tab completes app and file names. (Tab
  completes the top result's name)
- ● Action chips on results: Open, Open with, Show in folder, Copy path, Send
  to chat. (right-click menu: Open, Show in folder, Copy path, Ask about this;
  no Open with)
- ● Drag a result out to another app; drop files onto the bar to ask about
  them. (not tried by a person)
- ✓ Follow-ups in the same thread ("now do the same for Pictures").
- ● Pin a conversation; search across saved conversations. (pinned ones are
  listed first and never expire; earlier conversations also appear in quick
  results by title)
- ● Continue a conversation from the CLI and back. (happy-bot history,
  ask --conversation)
- ● A notification when a long task finishes (done for long requests);
  clicking it reopens the thread. (its Open button opens the popup through the
  applet's shortcut action, which the maintainer saw open the popup; the button itself
  not yet clicked)
- ● A global "ask about selection" shortcut: highlighted text in any app
  becomes the request's context. (Explain selected text, answered as a
  notification; KDE registers it at the next login, not yet verified)
- ● A global "ask about this window" shortcut. (same entry; keys are assigned
  in System Settings)
- ● Compact answer cards for common results: weather, definition, conversion,
  a file list with thumbnails. (quick results show computed answers and
  conversions as cards in the bar; in answers, the weather tool's result is
  a weather card and lists of files open with a click, pictures showing
  their thumbnail; definitions have no tool of their own, so they stay text)
- ● Markdown, code blocks with Copy, and tables in answers. (each code block
  has its own Copy button and its language; checked rendered offscreen, not
  yet seen by a person in the popup)
- ● A KRunner plugin so the same assistant answers from KRunner. (checked live
  over DBus)
- ⏸ Push-to-talk voice input through a speech-to-text endpoint the user
  configures, and optional spoken replies. (see Image And Voice Input)

## 2. Finding Things

- ✓ File search through the user's index (lexical while typing, hybrid when
  the model asks).
- ✓ Open a result with its default app.
- ⏸ Meaning-based matching in the instant path when the index can answer fast
  enough. (the user's index answers lexically while typing; the hybrid search
  stays a model tool)
- ● Filters typed in plain words: "pdfs from last month", "images over 5 MB",
  "edited today". (find_files by size, age and type)
- ● Find apps, settings pages, open windows, browser tabs and bookmarks.
  (apps, settings pages, windows, bookmarks; browser tabs need a browser
  extension)
- ✓ Find by content inside documents, email and chats, through MCP or the
  index. (through the user's index)
- ● "Where did I save…" from recently used files (KActivities or
  `recently-used.xbel`). (recently-used.xbel)
- ● Find duplicate, large and old files.
- ● Search inside archives.
- ● Find text in images through the index's OCR. (text_from_image (tesseract))
- ● Show where a file came from (download URL in extended attributes) when
  recorded.

## 3. Answers And Knowledge

- ✓ Web answers with links through the configured search tool.
- ● Fetch and read a web page or PDF by URL, then summarise or answer from it.
  (public addresses only, checked live)
- ✓ Offline reference through MCP (for example ZIM archives) when there is no
  network or for privacy. (any MCP server the user connects)
- ● Weather and sunrise/sunset for a configured location. (Open-Meteo, no key;
  off with local only)
- ✓ Definitions, translation, spelling, synonyms. (the model, with web search
  when needed)
- ● Explain an error message pasted into the bar or found in the journal.
  (read_journal)
- ✓ Cite sources for every claim taken from the web. (required by the system
  prompt)
- ● A "local only" switch: answer without anything leaving the machine.

## 4. Windows And Workspace

- ✓ List, focus, move, resize, tile and close windows.
- ● Saved layouts ("coding layout": editor left, terminal right, browser on
  the second monitor).
- ● Virtual desktops: create, name, switch, move a window to one.
- ● Activities: switch, and create one from a description.
- ● Minimise all, show desktop, keep above, fullscreen.
- ● "Close everything except Firefox", with unsaved work protected.
- ⏸ Restore yesterday's window session. (Plasma's own session restore does
  this; saved layouts cover the rest)
- ● Find a window by its content ("the window with the invoice"). (titles,
  then what each window shows through its accessibility tree)
- ✓ Arrange windows across several monitors. (arrange_window takes a screen)

## 5. System Settings And Hardware

- ✓ Volume, dark mode and colour schemes, reading KDE settings, display list,
  Wi-Fi list, system information.
- ◐ Wi-Fi connect and display switching (built and tested; not verified on
  real hardware).
- ● Brightness, night light, power profile, sleep, lock, log out; reboot and
  shut down ask first. (lock, sleep, log out, reboot and shut down were
  already built)
- ● Bluetooth: pair, connect and disconnect devices by name.
- ● Audio: choose output and input devices, per-app volume, microphone mute.
- ● Do Not Disturb with an end time ("quiet until 3pm").
- ● Wallpaper, accent colour, fonts, cursor and icon theme. (fonts are
  deferred)
- ● Keyboard layout, input methods, key repeat, touchpad settings. (layouts,
  key repeat, mouse and touchpad speed, natural scrolling, tap to click)
- ● Printers: list, set default, show the queue, cancel a job.
- ● VPN connect and disconnect through NetworkManager.
- ● Battery health and charge limit on laptops. (health and charge; a charge
  limit is deferred, it needs root)
- ● Default applications ("make Firefox my default browser").
- ● Autostart applications: list, add, remove.
- ● Mount, unmount and eject removable drives; "is my backup drive plugged
  in?" (drives the system mounted are refused)
- ● Describe the hardware: GPU, memory, disks, temperatures. (temperatures
  added)

## 6. Files And Documents

- ✓ Read, write, move and trash files; make folders; disk usage; bulk rename
  with preview.
- ● Copy, compress and extract.
- ● Convert formats with tools already installed (`ffmpeg`, ImageMagick,
  LibreOffice). (ffmpeg and ImageMagick; LibreOffice is not installed here)
- ● Resize, rotate or strip metadata from images in bulk.
- ● Merge, split and extract PDF pages; fill PDF forms. (filling PDF forms is
  deferred)
- ✓ Summarise or answer from a document, spreadsheet or folder of notes.
  (read_text_file, text_from_image, read_web_page)
- ✓ Tidy Downloads into folders by type or date, with a preview. (the model
  plans moves with move_path; each move can be undone)
- ● Find and remove duplicates (removal is `danger`).
- ● Change permissions and ownership of the user's own files. (ownership
  changes need root and are not offered)
- ◐ Share a file: to the phone through KDE Connect, as an email attachment, or
  as a link through a configured tool. (to the phone; email attachments need a
  mail tool server)
- ● Restore from Trash.
- ● Compare two files or folders.

## 7. Driving Other Applications

- ✓ Accessibility tree snapshot, press controls, set and read text, type and
  press keys, in Qt and GTK apps.
- ✓ Launch apps, verify an install shows in the launcher, refresh the menu
  cache.
- ⏸ Pointer input and screenshot-and-click for models with vision. (see Image
  And Voice Input)
- ● KDE apps through their DBus interfaces: Dolphin tabs, Kate at a line,
  Okular at a page, Konsole tab with a command. (Kate at a line, Okular at a
  page, folders in Dolphin, a terminal in a folder)
- ⏸ Browser control: open and list tabs, read the current page, through an
  extension or MCP. (needs a browser extension or an MCP server)
- ◐ Fill a web or desktop form from saved personal details, with a preview.
  (ui_set_text with details the user asked the assistant to remember)
- ⏸ Record a GUI task and replay it as a macro through the accessibility tree.
  (needs a recorder for accessibility events)
- ✓ Say plainly in the UI when an app publishes no accessibility tree.
  (ui_snapshot reports it)

## 8. Software Management

- ◐ Install apps from official sources first, ask before third-party ones,
  verify in the launcher (built; a real install is not verified).
- ● System update with reboot detection. (check_updates lists what is
  waiting from the distribution, the AUR and Flatpak, warns when the kernel
  is among them, and gives the one command run_in_terminal uses; after it,
  the shell tool reports a pending restart. Checked on the maintainer's
  computer with nothing waiting; a real update has not been run through it)
- ● One search across repositories, AUR and Flatpak, with the official source
  marked. (checked live)
- ✓ Clean uninstall including leftovers (`danger`). (through run_in_terminal,
  approved as danger)
- ● "What changed in my last update?" from the package log.
- ⏸ Package rollback through the broker. (no external broker exists yet)
- ● View and edit Flatpak permissions.
- ✓ Explain and fix a broken package or dependency conflict. (read_journal,
  recent_updates and the terminal)
- ● Firmware updates through `fwupd`.

## 9. Clipboard, Text And Screen

- ✓ Read the clipboard, summarise it, write the result back.
- ● Search clipboard history (Klipper).
- ● Transform selected or clipboard text: translate, fix grammar, shorten,
  change tone, reformat JSON or CSV, make a table. (selected_text and the
  model)
- ● Screenshot a region and ask about it (vision model or OCR). (OCR; vision
  models later)
- ● OCR a screen region to the clipboard.
- ● Start and stop screen recording (Spectacle). (Spectacle's recorder; the
  user stops it)
- ● Extract text from an image file.
- ● Colour picker.

## 10. Personal Information And Communication

- ⏸ Calendar: today's agenda and new events ("lunch with Sam Thursday at
  noon") through Akonadi, CalDAV or MCP. (through a calendar tool server the
  user connects; no built-in)
- ● Reminders and timers ("remind me at 4 to call the vet") as notifications
  that survive a restart. (a real reminder fired on time)
- ⏸ Contacts lookup. (through a tool server)
- ⏸ Email: read, summarise and draft replies through MCP or the mail client;
  sending asks first. (through a tool server)
- ● KDE Connect: ring the phone, send it a file or text, read its
  notifications and battery level. (listing checked live; ringing not tried;
  SMS always asks first)
- ● Quick notes appended to a notes file or app.
- ● A to-do list with due dates.

## 11. Media

- ● Play, pause, skip and "what's playing" through MPRIS. (now_playing, seek;
  checked live)
- ● Play something by name from a local library or a media server through MCP.
  (from the Music folder)
- ● Build a playlist from a description.
- ⏸ Cast to a TV or speaker when a tool exists for it. (needs a casting tool
  server)
- ● Download audio or video from a URL when the user has a tool for it. (with
  the user's yt-dlp, into Downloads)
- ● Scheduled requests ("every weekday at 8, summarise my calendar and the
  weather") as user systemd timers.
- ● Triggers: a file appears, a device connects, the battery is low, a network
  joins, a time arrives. (a schedule, a watched folder, a drive plugged in, joining
  a network, the battery dropping below a level; network and battery are checked
  every two minutes and fire once when they become true)
- ● Named routines ("start work" opens apps, applies a layout, sets Do Not
  Disturb). (a folder-watching routine ran end to end)
- ● Save a successful multi-step request as a routine.
- ● List, pause and delete routines from the bar.
- ● A dry run for every routine.

## 13. Power Users And Developers

- ✓ Run commands, run in a visible terminal and wait, classify shell risk.
- ✓ Explain a command before running it, or explain one that already ran. (the
  approval card and the model)
- ● Read and explain the journal ("why did the network drop at 2pm?").
- ● Manage systemd user units; system units through the broker. (system units
  need the broker)
- ● Git status, recent commits and "what did I change today" in a named
  repository.
- ● Open a project in the editor at a file and line.
- ● Container status and logs.
- ✓ Run a read-only command over SSH on a saved host. (run_command)
- ● What is using CPU, memory or GPU, and stop a process (asks first).
  (stopping asks first)
- ● Network diagnostics: ping, DNS, port check, speed test. (no speed test:
  nothing to measure against without a chosen server)

## 14. Memory And Personalisation

- ✓ Standard folders from XDG user-dirs, with overrides.
- ✓ Standing preferences in the system prompt (install sources, never kill a
  started program unless asked). (since 2026-11-23 in the editable
  instructions)
- ● User-editable facts (home city, preferred apps, units, address). (remember
  and recall into the instructions)
- ● Learned aliases ("my notes" is `~/Documents/Notes`), visible and editable.
  (the same remembered lines)
- ⏸ Per-app hints learned from successful GUI tasks.
- ● Forget a fact or a conversation on request.
- ● Export and import all personal data. (without secrets)

## 15. Models And Providers

- ✓ OpenAI-compatible provider with tools and streaming, loopback discovery,
  extra headers, models added by id when a service cannot list them.
- ⏸ Native providers where the compatible route loses features (Anthropic,
  Gemini), written from current vendor documentation. (the OpenAI-compatible
  route works for the hosted model in use)
- ● A model per task: a fast one for small actions, a strong one for long
  tasks, a vision one for screenshots. (a quick model starts every request
  and hands the same conversation to the chosen model after four steps or
  on failure; a request can still name its model. A vision model waits for
  image input, which is deferred)
- ● Fallback when a model is unreachable, offered rather than silent when it
  would send data off the machine. (only a local fallback is used
  automatically)
- ● Token and cost display for hosted models, and a monthly spend cap.
- ● Context management: summarise long threads, trim large tool results.
  (dropped turns are replaced by a short digest; large tool results are cut)
- ● Show which model answered each message.

## 16. Tools And Extensibility

- ✓ Stdio MCP client, import from other agents' configs, roles, read-only
  marking per server.
- ● One-press setup of file search and web search: choices found on this
  computer (other AI programs' tools that pass a test search, KDE's file
  index, the file-name database) and checked web-search suggestions, the
  best one marked, each tested before it is kept. (search_setup.py; the
  KDE-index switch-on and the page driven by hand are not yet verified)
- ● HTTP and SSE MCP transports. (streamable HTTP, both reply forms)
- ⏸ An in-app list of suggested MCP servers by need (calendar, email, browser,
  media) that the user approves. (needs a list checked against current
  sources)
- ● Per-tool enable and disable, and per-server risk overrides. (built-in
  groups and each server's tools)
- ● Tool usage statistics: which tools the model uses and which fail.
  (tool_usage totals the action log)
- ● Offer the assistant's desktop tools as an MCP server to other agents,
  under the same approval rules. (happy-bot mcp-serve)
- ● Small Python tools dropped into a folder as plugins.

## 17. Safety, Trust And Privacy

- ✓ Token auth, Origin/Host checks, `0600` secrets file, per-call `danger`
  gate, action log, stricter policy levels.
- ● Undo for the last change where possible: move back, restore from trash,
  previous volume or window layout. (checked live)
- ● An optional plan preview before a multi-step request starts.
- ● "What did you do today?" as a readable history from the action log.
  (checked live)
- ✓ A plain warning in settings that read results leave the machine with a
  hosted model (planned in Phase 6).
- ● Redact secrets found in tool results before they reach a hosted model.
- ⏸ Privileged actions through the external broker with exact-command
  approval. (no broker exists yet)
- ● Check the model's claims against the action log, so "I opened the
  terminal" after a declined approval is caught. (the popup lists what was not
  done after every answer)

## 18. Reliability And Diagnostics

- ✓ MCP servers restart on demand; errors name the fix; long steps report
  progress.
- ● A self-check in the CLI and settings: model reachable, tools running,
  portal consent kept, applet version matches the daemon. (checked live)
- ✓ Restart the daemon after an upgrade and prompt to reload the applet. (the
  installer restarts it and says to reload the panel)
- ● An evaluation run of the acceptance scenarios against a chosen model, with
  timings and pass/fail. (8 of 8 passed live on the local GPU model)
- ● Tell the user when a single-slot model is busy with another client. (a
  notice when every slot of a local service is busy)

## 19. Install, Setup And Reach

- ◐ One-command install and uninstall, first-run setup (the fresh-account
  exit check is open).
- ◐ An AUR package, then the KDE Store, then Flatpak if it proves workable.
  (an Arch PKGBUILD builds from the checkout; publishing to the AUR, the KDE
  Store or Flatpak is deferred)
- ● Move settings between machines through an export file.
- ◐ Translations through i18n catalogues. (Messages.sh extracts the 291 applet
  strings for translators; no translations exist yet)
- ◐ Accessibility of the assistant's own UI: screen-reader labels, high
  contrast, full keyboard use. (every icon button has a text label for screen
  readers; a full review is deferred)
- ✓ Layouts for vertical panels and touch. (the bar is an icon with a popup)
- ⏸ On several monitors, open the popup on the screen that has the cursor.
  (Plasma places the popup by its panel)
