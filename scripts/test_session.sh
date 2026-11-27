#!/usr/bin/env bash
# Run a headless desktop test with its own session bus and service sockets.
set -eu
test_runtime=$(mktemp -d)
cleanup() {
    # Activated services can briefly outlive dbus-run-session while the
    # documents portal releases its FUSE mount.
    for _ in {1..50}; do
        mountpoint -q "$test_runtime/doc" || break
        sleep 0.1
    done
    rm -rf --one-file-system -- "$test_runtime"
}
trap cleanup EXIT
# dbus-daemon and the services it activates must inherit the private runtime
# directory too. Changing it only in the test command is too late.
env -u AT_SPI_BUS_ADDRESS -u DISPLAY -u WAYLAND_DISPLAY \
    XDG_RUNTIME_DIR="$test_runtime" dbus-run-session -- "$@"
