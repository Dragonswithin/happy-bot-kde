"""Shell tools: run a command as the user, or open it in a terminal window.

``run_command`` is what makes "control anything" true: whatever has no
dedicated tool can still be done with a command. Each call is classified by
``shell_risk.classify_command`` before it runs, so a command that deletes or
makes an OS-level change waits for the user's approval and everything else
runs at once.

The command runs under ``bash -c`` in its own process group, with no terminal
and no standard input, in the user's home directory unless
``working_directory`` is given. Its output (stdout and stderr together) is
read as it arrives: the latest line is reported as progress every second so
the popup shows that the command is alive, and the turn's cancel event (the
Stop button) kills the whole process group at once. A timeout does the same.
When output is long, the beginning and the end are kept. A non-zero exit
status is reported in the result rather than raised, because the output is
usually what the model needs to recover.

A command that would ask for a password (``shell_risk.needs_password``:
sudo, package installs through yay or pacman, ...) is refused before it
runs, because there is no terminal for the user to type into; the model is
told to use ``run_in_terminal`` instead.

``run_in_terminal`` opens the user's terminal (KDE's ``TerminalApplication``
setting, else Konsole) running the command, and waits until it finishes:
installs, builds, and anything that asks for a password or wants the user to
watch. Inside the terminal the command runs under ``script``, which keeps a
real terminal (so password prompts work) while recording what is shown to a
log in the runtime directory; when it ends, its exit status is written to a
status file and the window stays open until the user presses a key. Meanwhile
the tool reports "Waiting for you in the terminal window" and the latest
output line as progress. It returns the exit status and the last lines of
output. Closing the window early is reported as such. Stop (the turn's
cancel event) stops waiting but leaves the terminal and its command running,
because killing an install half-way can leave the system in a broken state.
Waiting ends after ``TERMINAL_WAIT_SECONDS`` at most.

Because tools run one at a time, nothing else can run (or kill the install)
while the user is busy in the terminal.
"""

from __future__ import annotations

import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import threading
import time
from typing import Any

from ..desktop_context import run_command as run_program
from ..runtime_paths import ensure_runtime_root
from ..shell_risk import classify_command, needs_password
from .registry import RISK_CHANGE, Tool, ToolFailure, cancel_requested, object_schema, report_progress

DEFAULT_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 1800
OUTPUT_HEAD_CHARS = 2500
OUTPUT_TAIL_CHARS = 4500
POLL_SECONDS = 0.2
TERMINAL_FALLBACKS = ("konsole", "kgx", "gnome-terminal", "xterm")
TERMINAL_WAIT_SECONDS = 4 * 3600
TERMINAL_RESULT_CHARS = 4000
# Terminal windows still open when the tool returned (they wait for a key
# press, or were left running on Stop). Kept referenced so they are not
# reported as leaked child processes; they belong to the user.
_left_running: list[subprocess.Popen] = []
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\r")


def _working_directory(arguments: dict[str, Any]) -> str:
    value = arguments.get("working_directory")
    directory = os.path.abspath(os.path.expanduser(value)) if isinstance(value, str) and value.strip() else os.path.expanduser("~")
    return directory


def _command(arguments: dict[str, Any]) -> str:
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ToolFailure("'command' is required")
    return command


def classify(arguments: dict[str, Any]) -> tuple[str, str]:
    return classify_command(_command(arguments), _working_directory(arguments))


def precheck(arguments: dict[str, Any]) -> None:
    reason = needs_password(_command(arguments))
    if reason:
        raise ToolFailure(
            f"Not run: {reason}, and this command has no terminal to type it into. "
            "Use run_in_terminal so the user can watch it and enter their password.")


def _kill(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_command(arguments: dict[str, Any]) -> str:
    command = _command(arguments)
    directory = _working_directory(arguments)
    if not os.path.isdir(directory):
        raise ToolFailure(f"the working directory {directory} does not exist")
    timeout = arguments.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ToolFailure("'timeout_seconds' must be a number")
    timeout = max(1, min(MAX_TIMEOUT_SECONDS, int(timeout)))
    try:
        process = subprocess.Popen(
            ["bash", "-c", command], cwd=directory, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True, text=True, errors="replace", bufsize=1)
    except OSError as error:
        raise ToolFailure(f"could not start the command: {error}") from error

    chunks: list[str] = []
    latest = [""]

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            chunks.append(line)
            if line.strip():
                latest[0] = line.strip()

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    started = time.monotonic()
    stopped = ""
    while process.poll() is None:
        if cancel_requested():
            stopped = "stopped by the user"
            _kill(process)
            break
        if time.monotonic() - started > timeout:
            stopped = f"timed out after {timeout} s and was stopped"
            _kill(process)
            break
        elapsed = int(time.monotonic() - started)
        report_progress(latest[0] or f"running for {elapsed} s, no output yet")
        time.sleep(POLL_SECONDS)
    process.wait()
    reader.join(timeout=2)
    if process.stdout is not None:
        process.stdout.close()
    output = "".join(chunks)
    if len(output) > OUTPUT_HEAD_CHARS + OUTPUT_TAIL_CHARS:
        cut = len(output) - OUTPUT_HEAD_CHARS - OUTPUT_TAIL_CHARS
        output = f"{output[:OUTPUT_HEAD_CHARS]}\n[... {cut} characters cut ...]\n{output[-OUTPUT_TAIL_CHARS:]}"
    status = stopped or f"exit status {process.returncode}"
    return f"[{status}]\n{output.rstrip() or '(no output)'}"


def terminal_program() -> str:
    """The user's terminal: KDE's TerminalApplication setting if it exists, else the first installed fallback."""
    configured = run_program(["kreadconfig6", "--file", "kdeglobals", "--group", "General",
                              "--key", "TerminalApplication"], timeout=3)["stdout"].strip()
    for candidate in ([shlex.split(configured)[0]] if configured else []) + list(TERMINAL_FALLBACKS):
        found = shutil.which(candidate)
        if found:
            return found
    raise ToolFailure("no terminal program is installed")


def terminal_command(terminal: str, command: str, directory: str, log: str = "", status: str = "") -> list[str]:
    """Argument list that opens ``terminal`` running ``command`` and keeps the window open afterwards.

    With ``log`` and ``status`` the command runs under ``script`` (a real
    terminal, recorded to ``log``) and its exit status is written to ``status``.
    """
    if log and status:
        run = (f"script --quiet --flush --return --log-out {shlex.quote(log)} "
               f"--command {shlex.quote(command)}; status=$?; echo $status > {shlex.quote(status)}")
    else:
        run = f"{command}\nstatus=$?"
    script = (
        f"cd {shlex.quote(directory)} || exit 1; {run}\n"
        "echo; echo \"Finished with exit status $status.\"; "
        "read -r -n 1 -s -p 'Press any key to close this window.'; exit $status"
    )
    name = os.path.basename(terminal)
    if name == "konsole":
        return [terminal, "--separate", "-e", "bash", "-c", script]
    if name in ("gnome-terminal", "kgx"):
        return [terminal, "--", "bash", "-c", script]
    return [terminal, "-e", "bash", "-c", script]


def _read_log(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return ""
    return _ANSI.sub("", text)


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("Script ")]
    return lines[-1] if lines else ""


def run_in_terminal(arguments: dict[str, Any]) -> str:
    command = _command(arguments)
    directory = _working_directory(arguments)
    if not os.path.isdir(directory):
        raise ToolFailure(f"the working directory {directory} does not exist")
    token = secrets.token_hex(6)
    work = ensure_runtime_root()
    log, status_file = str(work / f"terminal-{token}.log"), str(work / f"terminal-{token}.status")
    try:
        window = subprocess.Popen(terminal_command(terminal_program(), command, directory, log, status_file),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  start_new_session=True)
    except OSError as error:
        raise ToolFailure(f"could not open a terminal: {error}") from error
    started = time.monotonic()
    outcome = ""
    try:
        while True:
            if os.path.exists(status_file):
                time.sleep(0.2)  # let the status line be written completely
                try:
                    with open(status_file, encoding="utf-8") as handle:
                        code = handle.read().strip()
                except OSError:
                    code = "?"
                outcome = f"finished with exit status {code}"
                break
            if window.poll() is not None:
                outcome = "the terminal window was closed before the command finished"
                break
            if cancel_requested():
                outcome = "stopped waiting at the user's request; the terminal and its command are still running"
                break
            if time.monotonic() - started > TERMINAL_WAIT_SECONDS:
                outcome = "stopped waiting after the time limit; the terminal is still open"
                break
            last = _last_line(_read_log(log))
            report_progress("Waiting for you in the terminal window" + (f" · {last}" if last else ""))
            time.sleep(POLL_SECONDS * 2)
        output = _read_log(log).strip()
        # Finished windows stay open until the user presses a key; reap the
        # ones already closed and keep the rest referenced.
        _left_running[:] = [item for item in _left_running if item.poll() is None]
        if window.poll() is None:
            _left_running.append(window)
    finally:
        for path in (log, status_file):
            try:
                os.unlink(path)
            except OSError:
                pass
    if len(output) > TERMINAL_RESULT_CHARS:
        output = "[... earlier output cut ...]\n" + output[-TERMINAL_RESULT_CHARS:]
    return f"[{outcome}]\n{output or '(no output recorded)'}"


def shell_tools() -> list[Tool]:
    command = {"type": "string"}
    directory = {"type": "string", "description": "Default: the home folder"}
    return [
        Tool(
            "run_command",
            "Run a shell command (bash) as the user and return its output. Use for anything no other tool covers. "
            "Not interactive: no password prompts, no editors. For installs, builds and anything needing a password, "
            "use run_in_terminal.",
            object_schema({
                "command": command,
                "working_directory": directory,
                "timeout_seconds": {"type": "integer", "description": f"Default {DEFAULT_TIMEOUT_SECONDS}, max {MAX_TIMEOUT_SECONDS}"},
            }, ["command"]),
            RISK_CHANGE, run_command, classify=classify, precheck=precheck,
            summarize=lambda arguments: f"Run: {str(arguments.get('command', ''))[:300]}",
        ),
        Tool(
            "run_in_terminal",
            "Open a terminal window running a command, for the user to watch and interact with: installing software "
            "(yay, pacman, flatpak), builds, long downloads, anything that asks for a password. Waits until the "
            "command finishes and returns its exit status and last output; do not check on it or stop it meanwhile.",
            object_schema({"command": command, "working_directory": directory}, ["command"]),
            RISK_CHANGE, run_in_terminal, classify=classify,
            summarize=lambda arguments: f"Open a terminal running: {str(arguments.get('command', ''))[:300]}",
        ),
    ]
