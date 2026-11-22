#!/usr/bin/env bash
# Installs or upgrades KDE AI Assistant for the current user. No root needed.
#
# What it puts where:
#   src/kde_ai_assistant/            -> ~/.local/lib/kde-ai-assistant/kde_ai_assistant/
#   launchers/*                      -> ~/.local/bin/
#   systemd/user/*.service           -> ~/.config/systemd/user/
#   plasmoid/<id>/                   -> the user's Plasma applet store (kpackagetool6)
#
# The package directory is replaced wholesale so files removed from the
# source do not linger. The daemon is restarted, not just started, so an
# upgrade never keeps serving old code. A running plasmashell keeps the
# applet QML it already loaded; the script says so when it upgrades one.
#
# Options: --dry-run prints the plan and changes nothing; --no-start installs
# without enabling or restarting the daemon.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
BIN_DIR="${HOME}/.local/bin"
LIB_DIR="${HOME}/.local/lib/kde-ai-assistant"
PACKAGE_SRC="${REPO_ROOT}/src/kde_ai_assistant"
SERVICE_NAME="kde-ai-assistant-daemon.service"
SERVICE_SRC="${REPO_ROOT}/systemd/user/${SERVICE_NAME}"
SERVICE_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
PLASMOID_ID="io.github.dragonswithin.kdeaiassistant"
PLASMOID_DIR="${REPO_ROOT}/plasmoid/${PLASMOID_ID}"
LAUNCHERS=(kde-ai-assistant-daemon kde-ai-assistant)

usage() {
  printf 'Usage: %s [--dry-run] [--no-start]\n' "$0"
}

dry_run=0
start_service=1
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    --no-start) start_service=0 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

require_command python3
require_command systemctl
require_command kpackagetool6

applet_installed=0
if kpackagetool6 --type Plasma/Applet --show "$PLASMOID_ID" >/dev/null 2>&1; then
  applet_installed=1
fi

if (( dry_run )); then
  printf 'Would replace %s with %s\n' "${LIB_DIR}/kde_ai_assistant" "$PACKAGE_SRC"
  for launcher in "${LAUNCHERS[@]}"; do
    printf 'Would install %s -> %s\n' "${REPO_ROOT}/launchers/${launcher}" "${BIN_DIR}/${launcher}"
  done
  printf 'Would install %s -> %s\n' "$SERVICE_SRC" "${SERVICE_DIR}/${SERVICE_NAME}"
  if (( start_service )); then
    printf 'Would enable and restart user service: %s\n' "$SERVICE_NAME"
  else
    printf 'Would reload user systemd without starting the daemon\n'
  fi
  printf 'Would install or upgrade Plasma applet from %s\n' "$PLASMOID_DIR"
  exit 0
fi

install -d -m 0755 "$BIN_DIR" "$SERVICE_DIR" "$LIB_DIR"
rm -rf -- "${LIB_DIR}/kde_ai_assistant"
install -d -m 0755 "${LIB_DIR}/kde_ai_assistant"
(cd "$PACKAGE_SRC" && find . -name '*.py' -print0) | while IFS= read -r -d '' file; do
  install -D -m 0644 "${PACKAGE_SRC}/${file}" "${LIB_DIR}/kde_ai_assistant/${file}"
done
for launcher in "${LAUNCHERS[@]}"; do
  install -m 0755 "${REPO_ROOT}/launchers/${launcher}" "${BIN_DIR}/${launcher}"
done
install -m 0644 "$SERVICE_SRC" "${SERVICE_DIR}/${SERVICE_NAME}"

systemctl --user daemon-reload
if (( start_service )); then
  systemctl --user enable "$SERVICE_NAME" >/dev/null
  systemctl --user restart "$SERVICE_NAME"
fi

if (( applet_installed )); then
  kpackagetool6 --type Plasma/Applet --upgrade "$PLASMOID_DIR" >/dev/null
  printf 'Panel widget upgraded. Log out and in (or restart plasmashell) to load the new version.\n'
else
  kpackagetool6 --type Plasma/Applet --install "$PLASMOID_DIR" >/dev/null
  printf 'Add the "AI Assistant" widget to your panel next to the application launcher.\n'
fi

printf 'KDE AI Assistant installed.\n'
printf 'Check: kde-ai-assistant status --pretty\n'
