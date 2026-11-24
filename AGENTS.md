# Happy Bot Project Instructions

- Product goal: a search bar on the Plasma panel beside the launcher where
  the user types anything and the computer does it: find files through the
  user's existing index, answer from the web through their configured search
  tool, or act on the system through tools, using any model the user
  configures. It is one app with one install and setup, not a chat sidebar
  and not a set of services the user wires together. `docs/ROADMAP.md` is the
  authoritative goal, architecture and phase order; read it before planning
  or coding.
- No model, vendor or endpoint is assumed in code. Local services are offered
  as suggestions; the user chooses.
- This repo is a standalone KDE Plasma assistant surface, not a machine-setup
  repo for any one computer.
- Keep the UI/backend bridge reusable. New code should avoid hard-coded
  backend paths when a user-configurable path or environment variable is
  reasonable.
- Prefer user-local install paths for the desktop assistant:
  `~/.local/bin`, `~/.config/systemd/user`, and KDE's per-user Plasma applet
  package store.
- The daemon is intentionally a logged-in desktop-session service. Do not make
  it a durable boot-level service unless the feature being added is no longer
  desktop-interactive.
- Do not store screenshots, logs, transcripts, or command output in the repo.
  Runtime state belongs under `$XDG_RUNTIME_DIR/happy-bot`. The one
  exception, chosen by the maintainer, is the user's conversation history: saved 0600
  under `$XDG_DATA_HOME/happy-bot/conversations` and deleted after
  `history_days` (default 30) without use.
- Keep root/system actions behind an explicit external broker. This project can
  report broker availability, but it should not grow an unbounded root helper.
- Before closeout, run focused checks: Python syntax, shell syntax, service
  unit sanity where possible, and Plasma package install/windowed smoke when a
  KDE session is available.
