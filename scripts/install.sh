#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
BIN_DIR="${HOME}/.local/bin"
SERVICE_SRC="${REPO_ROOT}/systemd/user/kde-ai-assistant-daemon.service"
SERVICE_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
SERVICE_DST="${SERVICE_DIR}/kde-ai-assistant-daemon.service"
PLASMOID_ID="io.github.dragonswithin.kdeaiassistant"
PLASMOID_DIR="${REPO_ROOT}/plasmoid/${PLASMOID_ID}"

usage() {
  printf 'Usage: %s [--dry-run] [--no-start]\n' "$0"
}

dry_run=0
start_service=1
for arg in "$@"; do
  case "$arg" in
    --dry-run)
      dry_run=1
      ;;
    --no-start)
      start_service=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$command_name" >&2
    exit 1
  fi
}

require_command systemctl
require_command kpackagetool6

if (( dry_run )); then
  printf 'Would install %s -> %s\n' "${REPO_ROOT}/src/kde_ai_assistant_daemon.py" "${BIN_DIR}/kde-ai-assistant-daemon"
  printf 'Would install %s -> %s\n' "${REPO_ROOT}/src/kde_ai_assistant_client.py" "${BIN_DIR}/kde-ai-assistant"
  printf 'Would install %s -> %s\n' "$SERVICE_SRC" "$SERVICE_DST"
  if (( start_service )); then
    printf 'Would enable/start user service: kde-ai-assistant-daemon.service\n'
  else
    printf 'Would reload user systemd without starting the daemon\n'
  fi
  printf 'Would install or upgrade Plasma applet from %s\n' "$PLASMOID_DIR"
  exit 0
fi

install -d -m 0755 "$BIN_DIR" "$SERVICE_DIR"
install -m 0755 "${REPO_ROOT}/src/kde_ai_assistant_daemon.py" "${BIN_DIR}/kde-ai-assistant-daemon"
install -m 0755 "${REPO_ROOT}/src/kde_ai_assistant_client.py" "${BIN_DIR}/kde-ai-assistant"
install -m 0644 "$SERVICE_SRC" "$SERVICE_DST"

systemctl --user daemon-reload
if (( start_service )); then
  systemctl --user enable --now kde-ai-assistant-daemon.service
fi

if kpackagetool6 --type Plasma/Applet --show "$PLASMOID_ID" >/dev/null 2>&1; then
  kpackagetool6 --type Plasma/Applet --upgrade "$PLASMOID_DIR"
else
  kpackagetool6 --type Plasma/Applet --install "$PLASMOID_DIR"
fi

printf 'KDE AI Assistant installed.\n'
printf 'Daemon: systemctl --user status kde-ai-assistant-daemon.service\n'
printf 'CLI: kde-ai-assistant status --pretty\n'
printf 'Widget test: plasmawindowed %s\n' "$PLASMOID_ID"
