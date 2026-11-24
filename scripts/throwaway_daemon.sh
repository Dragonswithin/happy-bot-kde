#!/usr/bin/env bash
# A second, disposable Happy Bot daemon for trying setup and requests without
# touching the user's real settings, history or daemon.
#
# It runs this checkout's code (src/) on its own loopback port with its own
# config, data and runtime folders under $XDG_RUNTIME_DIR/happy-bot-throwaway,
# so it starts with empty settings (or a settings file you give it) and
# everything it saves disappears with "stop" or a logout. Tool servers and
# model services it is pointed at are the real ones on this computer.
#
#   scripts/throwaway_daemon.sh start [--port N] [--config FILE]
#       start it (default port 19555); FILE, if given, is copied in as its
#       config.json, so a test can begin with models or roles already set
#   eval "$(scripts/throwaway_daemon.sh env)"
#       point this shell's CLI at it: PYTHONPATH=src python3 -m happy_bot.cli ...
#       (or the daemon's HTTP API through happy_bot.cli.request_json)
#   scripts/throwaway_daemon.sh status    is it running, and where
#   scripts/throwaway_daemon.sh stop      stop it and delete its folder
#
# Routine timers it creates are written into its own folder, which systemd
# never reads, so they never run. Its log is daemon.log in its folder.
# Settings that change real state outside Happy Bot (for example switching
# KDE's file index on from "Set up") still act on the real desktop.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${XDG_RUNTIME_DIR:?XDG_RUNTIME_DIR is not set}/happy-bot-throwaway"
PID_FILE="${BASE}/daemon.pid"
PORT_FILE="${BASE}/port"

env_lines() {
  local port
  port="$(cat "$PORT_FILE" 2>/dev/null || echo 19555)"
  printf 'export XDG_CONFIG_HOME=%q XDG_DATA_HOME=%q XDG_RUNTIME_DIR=%q\n' \
    "${BASE}/config" "${BASE}/data" "${BASE}/run"
  printf 'export HAPPY_BOT_DAEMON_URL=%q PYTHONPATH=%q\n' "http://127.0.0.1:${port}" "${REPO_ROOT}/src"
}

running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

start() {
  local port=19555 config=""
  while (( $# )); do
    case "$1" in
      --port) port="$2"; shift 2 ;;
      --config) config="$2"; shift 2 ;;
      *) printf 'throwaway_daemon: unknown option %s\n' "$1" >&2; exit 2 ;;
    esac
  done
  if running; then
    printf 'already running on port %s\n' "$(cat "$PORT_FILE")"
    return
  fi
  install -d -m 0700 "$BASE" "${BASE}/config/happy-bot" "${BASE}/data" "${BASE}/run"
  if [[ -n "$config" ]]; then
    install -m 0600 "$config" "${BASE}/config/happy-bot/config.json"
  fi
  printf '%s\n' "$port" > "$PORT_FILE"
  (
    eval "$(env_lines)"
    setsid python3 -m happy_bot.daemon_http --foreground --port "$port" > "${BASE}/daemon.log" 2>&1 &
    printf '%s\n' "$!" > "$PID_FILE"
  )
  for _ in $(seq 40); do
    if curl -s -o /dev/null "http://127.0.0.1:${port}/health"; then
      printf 'running on port %s; settings in %s\n' "$port" "${BASE}/config/happy-bot"
      return
    fi
    sleep 0.25
  done
  printf 'throwaway_daemon: it did not start; see %s\n' "${BASE}/daemon.log" >&2
  exit 1
}

stop() {
  if running; then
    kill "$(cat "$PID_FILE")"
  fi
  # Only ever this script's own folder.
  [[ "$BASE" == */happy-bot-throwaway ]] && rm -rf -- "$BASE"
  printf 'stopped\n'
}

case "${1:-}" in
  start) shift; start "$@" ;;
  env) env_lines ;;
  status) if running; then printf 'running on port %s (pid %s)\n' "$(cat "$PORT_FILE")" "$(cat "$PID_FILE")"; else printf 'not running\n'; fi ;;
  stop) stop ;;
  *) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
