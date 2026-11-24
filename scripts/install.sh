#!/usr/bin/env bash
# Installs, upgrades or removes KDE AI Assistant for the current user. No root needed.
#
# Install (default) puts things here:
#   src/kde_ai_assistant/            -> ~/.local/lib/kde-ai-assistant/kde_ai_assistant/
#   launchers/*                      -> ~/.local/bin/
#   systemd/user/*.service           -> ~/.config/systemd/user/
#   plasmoid/<id>/                   -> the user's Plasma applet store (kpackagetool6)
#   krunner/kde-ai-assistant.desktop -> ~/.local/share/krunner/dbusplugins/ (KRunner plugin)
#   desktop/kde-ai-assistant-shortcuts.desktop -> ~/.local/share/applications/, linked from
#                                      ~/.local/share/kglobalaccel/ (global shortcuts)
# and, the first time, adds the search bar to the panel that holds the
# application launcher, so nothing is left to do by hand. Setup then continues
# in the bar itself: press Enter in it, or right-click it and choose Configure.
#
# The package directory is replaced wholesale so files removed from the
# source do not linger. The daemon is restarted, not just started, so an
# upgrade never keeps serving old code. A running plasmashell keeps the
# applet QML it already loaded; the script says so when it upgrades one.
#
# PyGObject is needed for the window and application-control tools; its
# absence is reported, not fatal.
#
# Options:
#   --dry-run     print the plan and change nothing
#   --no-start    install without enabling or restarting the daemon
#   --no-panel    do not add the search bar to a panel
#   --uninstall   remove everything this script installed, the bar from every
#                 panel, and the reminder and routine timers the assistant
#                 created; your settings in ~/.config/kde-ai-assistant stay
#   --purge       with --uninstall: remove the settings too
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
BIN_DIR="${HOME}/.local/bin"
LIB_DIR="${HOME}/.local/lib/kde-ai-assistant"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/kde-ai-assistant"
PACKAGE_SRC="${REPO_ROOT}/src/kde_ai_assistant"
SERVICE_NAME="kde-ai-assistant-daemon.service"
SERVICE_SRC="${REPO_ROOT}/systemd/user/${SERVICE_NAME}"
SERVICE_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
PLASMOID_ID="io.github.dragonswithin.kdeaiassistant"
PLASMOID_DIR="${REPO_ROOT}/plasmoid/${PLASMOID_ID}"
LAUNCHERS=(kde-ai-assistant-daemon kde-ai-assistant)
KRUNNER_SRC="${REPO_ROOT}/krunner/kde-ai-assistant.desktop"
KRUNNER_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/krunner/dbusplugins"
SHORTCUTS_SRC="${REPO_ROOT}/desktop/kde-ai-assistant-shortcuts.desktop"
APPLICATIONS_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/applications"
KGLOBALACCEL_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/kglobalaccel"

usage() {
  printf 'Usage: %s [--dry-run] [--no-start] [--no-panel]\n       %s --uninstall [--purge] [--dry-run]\n' "$0" "$0"
}

dry_run=0
start_service=1
add_to_panel=1
uninstall=0
purge=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    --no-start) start_service=0 ;;
    --no-panel) add_to_panel=0 ;;
    --uninstall) uninstall=1 ;;
    --purge) purge=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
if (( purge && ! uninstall )); then
  usage >&2
  exit 2
fi

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

# Runs a Plasma desktop script and prints its output; fails quietly when no
# Plasma shell is running (for example over SSH).
plasma_script() {
  command -v qdbus6 >/dev/null 2>&1 || return 1
  qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "$1" 2>/dev/null
}

applet_installed() {
  kpackagetool6 --type Plasma/Applet --show "$PLASMOID_ID" >/dev/null 2>&1
}

remove_from_panels() {
  plasma_script "
    var removed = 0;
    panels().forEach(function (panel) {
      panel.widgets().forEach(function (widget) {
        if (widget.type === '${PLASMOID_ID}') { widget.remove(); removed += 1; }
      });
    });
    print(removed);" || true
}

# Adds the bar to the panel that holds the application launcher (else the
# first panel) unless a panel already has it. Prints added, present or none.
add_bar_to_panel() {
  plasma_script "
    var launchers = ['org.kde.plasma.kickoff', 'org.kde.plasma.kicker', 'org.kde.plasma.kickerdash'];
    var all = panels();
    var present = false, target = null;
    all.forEach(function (panel) {
      panel.widgets().forEach(function (widget) {
        if (widget.type === '${PLASMOID_ID}') { present = true; }
        if (target === null && launchers.indexOf(widget.type) >= 0) { target = panel; }
      });
    });
    if (present) { print('present'); }
    else if (all.length === 0) { print('none'); }
    else { (target || all[0]).addWidget('${PLASMOID_ID}'); print('added'); }" || true
}

require_command kpackagetool6
require_command systemctl

if (( uninstall )); then
  if (( dry_run )); then
    printf 'Would stop and disable %s and remove its unit file\n' "$SERVICE_NAME"
    printf 'Would remove the reminder and routine timers the assistant created, and the KRunner plugin\n'
    printf 'Would remove the search bar from every panel and uninstall the applet\n'
    printf 'Would remove %s and the launchers in %s\n' "$LIB_DIR" "$BIN_DIR"
    if (( purge )); then printf 'Would remove settings in %s\n' "$CONFIG_DIR"; else printf 'Would keep settings in %s\n' "$CONFIG_DIR"; fi
    exit 0
  fi
  systemctl --user disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
  rm -f -- "${SERVICE_DIR}/${SERVICE_NAME}"
  # Reminder and routine units carry this marker (src/kde_ai_assistant/user_timers.py);
  # nothing else in the directory is touched.
  for unit in "${SERVICE_DIR}"/kde-ai-assistant-reminder-* "${SERVICE_DIR}"/kde-ai-assistant-routine-*; do
    [[ -f "$unit" ]] && grep -q '^X-KdeAiAssistant=yes' "$unit" || continue
    case "$unit" in *.timer|*.path) systemctl --user disable --now "$(basename -- "$unit")" >/dev/null 2>&1 || true ;; esac
    rm -f -- "$unit"
  done
  rm -f -- "${KRUNNER_DIR}/kde-ai-assistant.desktop" "${KGLOBALACCEL_DIR}/kde-ai-assistant-shortcuts.desktop" \
    "${APPLICATIONS_DIR}/kde-ai-assistant-shortcuts.desktop"
  systemctl --user daemon-reload || true
  remove_from_panels >/dev/null
  if applet_installed; then
    kpackagetool6 --type Plasma/Applet --remove "$PLASMOID_ID" >/dev/null 2>&1 || true
  fi
  for launcher in "${LAUNCHERS[@]}"; do
    rm -f -- "${BIN_DIR}/${launcher}"
  done
  rm -rf -- "$LIB_DIR"
  if (( purge )); then
    rm -rf -- "$CONFIG_DIR"
    printf 'KDE AI Assistant removed, including its settings.\n'
  else
    printf 'KDE AI Assistant removed. Your settings remain in %s (use --purge to remove them too).\n' "$CONFIG_DIR"
  fi
  exit 0
fi

require_command python3

if ! python3 -c 'import gi; gi.require_version("Gio", "2.0")' >/dev/null 2>&1; then
  printf 'Note: PyGObject is not installed (package python-gobject or python3-gi).\n' >&2
  printf '      Window and application-control tools will be unavailable until it is; everything else works.\n' >&2
fi

had_applet=0
if applet_installed; then
  had_applet=1
fi

if (( dry_run )); then
  printf 'Would replace %s with %s\n' "${LIB_DIR}/kde_ai_assistant" "$PACKAGE_SRC"
  for launcher in "${LAUNCHERS[@]}"; do
    printf 'Would install %s -> %s\n' "${REPO_ROOT}/launchers/${launcher}" "${BIN_DIR}/${launcher}"
  done
  printf 'Would install %s -> %s\n' "$SERVICE_SRC" "${SERVICE_DIR}/${SERVICE_NAME}"
  printf 'Would install %s -> %s\n' "$KRUNNER_SRC" "${KRUNNER_DIR}/kde-ai-assistant.desktop"
  printf 'Would install %s -> %s (and link it for global shortcuts)\n' "$SHORTCUTS_SRC" "${APPLICATIONS_DIR}/kde-ai-assistant-shortcuts.desktop"
  if (( start_service )); then
    printf 'Would enable and restart user service: %s\n' "$SERVICE_NAME"
  else
    printf 'Would reload user systemd without starting the daemon\n'
  fi
  printf 'Would install or upgrade Plasma applet from %s\n' "$PLASMOID_DIR"
  if (( add_to_panel && ! had_applet )); then
    printf 'Would add the search bar to the panel that holds the application launcher\n'
  fi
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
install -D -m 0644 "$KRUNNER_SRC" "${KRUNNER_DIR}/kde-ai-assistant.desktop"
install -D -m 0644 "$SHORTCUTS_SRC" "${APPLICATIONS_DIR}/kde-ai-assistant-shortcuts.desktop"
install -d -m 0755 "$KGLOBALACCEL_DIR"
ln -sf -- "${APPLICATIONS_DIR}/kde-ai-assistant-shortcuts.desktop" "${KGLOBALACCEL_DIR}/kde-ai-assistant-shortcuts.desktop"

systemctl --user daemon-reload
if (( start_service )); then
  systemctl --user enable "$SERVICE_NAME" >/dev/null
  systemctl --user restart "$SERVICE_NAME"
fi

if (( had_applet )); then
  kpackagetool6 --type Plasma/Applet --upgrade "$PLASMOID_DIR" >/dev/null
  printf 'Search bar upgraded. Log out and in (or restart plasmashell) to load the new version.\n'
else
  kpackagetool6 --type Plasma/Applet --install "$PLASMOID_DIR" >/dev/null
  placed=""
  if (( add_to_panel )); then
    placed="$(add_bar_to_panel | tr -d '[:space:]')"
  fi
  case "$placed" in
    added) printf 'The search bar is now in your panel. Press Enter in it to set up a model.\n' ;;
    present) printf 'The search bar is already in a panel.\n' ;;
    *) printf 'Add the "AI Assistant" widget to your panel next to the application launcher.\n' ;;
  esac
fi

case ":${PATH}:" in
  *":${BIN_DIR}:"*) ;;
  *) printf 'Note: %s is not on your PATH; the kde-ai-assistant command is there.\n' "$BIN_DIR" ;;
esac

printf 'KDE AI Assistant installed.\n'
