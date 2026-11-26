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
Output is cleaned and, when long, shortened to its beginning and end by
``tools/terminal_text.py``. A command that did not finish with exit status 0
(including a timeout or Stop) is reported as a failed step, with the same
text, status and output, so the model can still recover from it; the agent
loop relies on that to tell a completed step from one worth retrying.

A command that would ask for a password (``shell_risk.needs_password``:
sudo, package installs through yay or pacman, ...) is refused before it
runs, because there is no terminal for the user to type into; the model is
told to use ``run_in_terminal`` instead.

Both tools are built by ``shell_tools`` with two of the user's settings
(``agent`` in ``settings.py``): ``run_command``'s default time limit when the
model names none, and the terminal ``run_in_terminal`` opens. The terminal is
one of ``SUPPORTED_TERMINALS``, whose command lines ``terminal_command`` knows,
installed natively or as a Flatpak (``FLATPAK_TERMINALS``: Kwi and Konsole, whose
Flatpaks run commands on the host); when none is chosen it is KDE's default
terminal (``TerminalService`` or ``TerminalApplication`` in kdeglobals) if that
is a supported one, else the first supported terminal installed.

``run_in_terminal`` opens that terminal running the command, and waits until it finishes:
installs, builds, and anything that asks for a password or wants the user to
watch. Inside the terminal the command runs under ``script``, which keeps a
real terminal (so password prompts work) while recording what is shown to a
log in the runtime directory. ``script`` starts the command with ``$SHELL``,
the user's login shell (fish, zsh, ...), so it is given bash instead: the
command is bash, as for ``run_command`` and as ``shell_risk`` reads it; when it ends, its exit status is written to a
status file and the window stays open until the user presses a key. Meanwhile
the tool reports "Waiting for you in the terminal window" and the latest
output line as progress. It returns the exit status and the start and end
of the output, and says when a reboot is now needed (``pending_reboot``: the
running kernel's modules were removed by an update, or the distribution's
``/run/reboot-required`` flag is set), so the model cannot miss it. Anything
but exit status 0 is a failed step. Closing the window early is reported as
such. Stop (the turn's cancel event) stops waiting but leaves the terminal
and its command running, because killing an install half-way can leave the
system in a broken state.
Waiting ends after ``TERMINAL_WAIT_SECONDS`` at most.

Because tools run one at a time, nothing else can run (or kill the install)
while the user is busy in the terminal.
"""

from __future__ import annotations

import os
import secrets
import shlex
from pathlib import Path
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
from .terminal_text import clean, keep_head_and_tail

DEFAULT_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 1800
OUTPUT_HEAD_CHARS = 2500
OUTPUT_TAIL_CHARS = 4500
POLL_SECONDS = 0.2
# Terminals whose way of running a command is known (see terminal_command), in
# the order tried when the user chose none and KDE's own choice is not usable.
SUPPORTED_TERMINALS = ("konsole", "kwi", "kitty", "alacritty", "foot", "wezterm", "kgx", "gnome-terminal", "xterm")
# Terminals also found as Flatpaks: Flatpak exports a launcher named after the app id (on PATH in a
# Plasma session, else in these folders), and the command still runs on the host (checked for Kwi).
FLATPAK_TERMINALS = {"kwi": "org.kde.kwi", "konsole": "org.kde.konsole"}
FLATPAK_EXPORTS = (Path.home() / ".local/share/flatpak/exports/bin", Path("/var/lib/flatpak/exports/bin"))
TERMINAL_WAIT_SECONDS = 4 * 3600
TERMINAL_HEAD_CHARS = 1500
TERMINAL_TAIL_CHARS = 3500
REBOOT_REQUIRED_FLAG = "/run/reboot-required"
KERNEL_MODULES = Path("/usr/lib/modules")
CONTAINER_MARKERS = ("/.dockerenv", "/run/.containerenv", "/run/systemd/container", "/run/host/container-manager")
# Terminal windows still open when the tool returned (they wait for a key
# press, or were left running on Stop). Kept referenced so they are not
# reported as leaked child processes; they belong to the user.
_left_running: list[subprocess.Popen] = []


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


def run_command(arguments: dict[str, Any], default_timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    command = _command(arguments)
    directory = _working_directory(arguments)
    if not os.path.isdir(directory):
        raise ToolFailure(f"the working directory {directory} does not exist")
    timeout = arguments.get("timeout_seconds", default_timeout)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ToolFailure("'timeout_seconds' must be a number")
    timeout = max(1, min(MAX_TIMEOUT_SECONDS, int(timeout)))
    try:
        process = subprocess.Popen(
            ["bash", "-c", command], cwd=directory, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as error:
        raise ToolFailure(f"could not start the command: {error}") from error

    chunks: list[str] = []
    latest = [""]

    def read_output() -> None:
        # Read bytes: text mode would turn a progress bar's carriage returns
        # into newlines before clean() could collapse the redraws.
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace")
            chunks.append(line)
            shown = clean(line).strip()
            if shown:
                latest[0] = shown

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
    output = keep_head_and_tail(clean("".join(chunks)).strip(), OUTPUT_HEAD_CHARS, OUTPUT_TAIL_CHARS)
    status = stopped or f"exit status {process.returncode}"
    result = f"[{status}]\n{output or '(no output)'}"
    if stopped or process.returncode != 0:
        raise ToolFailure(result)
    return result


def find_terminal(name: str) -> str | None:
    """Path of a supported terminal: its program on ``PATH``, else its Flatpak launcher, else None."""
    found = shutil.which(name)
    app = FLATPAK_TERMINALS.get(name)
    if found or not app:
        return found
    exported = shutil.which(app) or next((str(folder / app) for folder in FLATPAK_EXPORTS
                                          if (folder / app).is_file()), None)
    return exported


def terminal_name(path: str) -> str:
    """The supported name for a terminal's path ("/…/exports/bin/org.kde.kwi" is "kwi")."""
    base = os.path.basename(path)
    return next((name for name, app in FLATPAK_TERMINALS.items() if app == base), base)


def installed_terminals() -> list[str]:
    """The supported terminals installed (natively or as Flatpaks), for the settings page to offer."""
    return [name for name in SUPPORTED_TERMINALS if find_terminal(name)]


def _kde_terminal() -> str:
    """KDE's default terminal (System Settings, Default Applications) as a supported name, or "".

    ``TerminalService`` names its launcher ("org.kde.kwi.desktop"); ``TerminalApplication`` its
    command, which for a Flatpak is "flatpak run … org.kde.kwi".
    """
    for key in ("TerminalService", "TerminalApplication"):
        configured = run_program(["kreadconfig6", "--file", "kdeglobals", "--group", "General",
                                  "--key", key], timeout=3)["stdout"].strip()
        try:
            words = shlex.split(configured)
        except ValueError:
            continue
        if not words:
            continue
        if os.path.basename(words[0]) == "flatpak":
            words = [word for word in words if word in FLATPAK_TERMINALS.values()] or words
        name = terminal_name(words[0].removesuffix(".desktop"))
        if name in SUPPORTED_TERMINALS:
            return name
    return ""


def terminal_program(preferred: str = "") -> str:
    """Path of the terminal to open: ``preferred`` (the user's setting) if given, else automatic.

    Automatic is KDE's default terminal when it is a supported one (``_kde_terminal``), else the
    first supported one installed; Flatpak installs count (``find_terminal``).
    """
    if preferred:
        found = find_terminal(preferred)
        if not found:
            raise ToolFailure(f"the terminal chosen in the assistant's settings ({preferred}) is not installed; "
                              "tell the user to choose another under Behaviour in the assistant's settings")
        return found
    kde_choice = _kde_terminal()
    for candidate in ([kde_choice] if kde_choice else []) + list(SUPPORTED_TERMINALS):
        found = find_terminal(candidate)
        if found:
            return found
    raise ToolFailure("no supported terminal program is installed")


def terminal_command(terminal: str, command: str, directory: str, log: str = "", status: str = "") -> list[str]:
    """Argument list that opens ``terminal`` running ``command`` and keeps the window open afterwards.

    With ``log`` and ``status`` the command runs under ``script`` (a real
    terminal, recorded to ``log``) and its exit status is written to ``status``.
    ``SHELL="$BASH"`` (the full path of the bash running the window's script)
    makes ``script`` run the command under bash, not the user's login shell.
    """
    if log and status:
        run = (f"SHELL=\"$BASH\" script --quiet --flush --return --log-out {shlex.quote(log)} "
               f"--command {shlex.quote(command)}; status=$?; echo $status > {shlex.quote(status)}")
    else:
        run = f"{command}\nstatus=$?"
    script = (
        f"cd {shlex.quote(directory)} || exit 1; {run}\n"
        "echo; echo \"Finished with exit status $status.\"; "
        "read -r -n 1 -s -p 'Press any key to close this window.'; exit $status"
    )
    name = terminal_name(terminal)
    if name == "konsole":
        return [terminal, "--separate", "-e", "bash", "-c", script]
    if name == "kwi":  # kwi [options] -e program [arguments]
        return [terminal, "-e", "bash", "-c", script]
    if name in ("gnome-terminal", "kgx"):
        return [terminal, "--", "bash", "-c", script]
    if name in ("kitty", "foot"):
        return [terminal, "bash", "-c", script]
    if name == "wezterm":
        return [terminal, "start", "--", "bash", "-c", script]
    return [terminal, "-e", "bash", "-c", script]


def _read_log(path: str) -> str:
    """The terminal log as cleaned text, without ``script``'s own start and end lines."""
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as handle:  # keep \r: clean() needs it
            text = handle.read()
    except OSError:
        return ""
    return "\n".join(line for line in clean(text).split("\n")
                     if not line.startswith(("Script started on ", "Script done on ")))


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def pending_reboot() -> str:
    """Why a reboot is needed now, or "" when nothing says so."""
    if os.path.exists(REBOOT_REQUIRED_FLAG):
        return "the system reports that a reboot is required"
    release = os.uname().release
    if (KERNEL_MODULES / release).is_dir():
        return ""
    # Containers share the host's kernel. An empty modules directory is also
    # common on minimal systems; look for evidence of a replacement kernel.
    if os.getenv("container") or any(os.path.exists(marker) for marker in CONTAINER_MARKERS):
        return ""
    if any(entry.is_file() for entry in KERNEL_MODULES.glob("*/modules.dep")):
        return f"the running kernel ({release}) was replaced by an update"
    return ""


def run_in_terminal(arguments: dict[str, Any], terminal: str = "") -> str:
    command = _command(arguments)
    directory = _working_directory(arguments)
    if not os.path.isdir(directory):
        raise ToolFailure(f"the working directory {directory} does not exist")
    token = secrets.token_hex(6)
    work = ensure_runtime_root()
    log, status_file = str(work / f"terminal-{token}.log"), str(work / f"terminal-{token}.status")
    try:
        window = subprocess.Popen(terminal_command(terminal_program(terminal), command, directory, log, status_file),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  start_new_session=True)
    except OSError as error:
        raise ToolFailure(f"could not open a terminal: {error}") from error
    started = time.monotonic()
    outcome = ""
    succeeded = False
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
                succeeded = code == "0"
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
    result = f"[{outcome}]\n{keep_head_and_tail(output, TERMINAL_HEAD_CHARS, TERMINAL_TAIL_CHARS) or '(no output recorded)'}"
    reboot = pending_reboot()
    if reboot:
        result += f"\n[A reboot is needed: {reboot}. Tell the user.]"
    if not succeeded:
        raise ToolFailure(result)
    return result


def shell_tools(default_timeout: int = DEFAULT_TIMEOUT_SECONDS, terminal: str = "") -> list[Tool]:
    """The two shell tools, using the user's default time limit and terminal (see module docstring)."""
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
                "timeout_seconds": {"type": "integer", "description": f"Default {default_timeout}, max {MAX_TIMEOUT_SECONDS}"},
            }, ["command"]),
            RISK_CHANGE, lambda arguments: run_command(arguments, default_timeout), classify=classify, precheck=precheck,
            summarize=lambda arguments: f"Run: {str(arguments.get('command', ''))[:300]}",
        ),
        Tool(
            "run_in_terminal",
            "Open a terminal window running a command, for the user to watch and interact with: installing software "
            "(yay, pacman, flatpak), builds, long downloads, anything that asks for a password. Waits until the "
            "command finishes and returns its exit status and last output; do not check on it or stop it meanwhile.",
            object_schema({"command": command, "working_directory": directory}, ["command"]),
            RISK_CHANGE, lambda arguments: run_in_terminal(arguments, terminal), classify=classify,
            summarize=lambda arguments: f"Open a terminal running: {str(arguments.get('command', ''))[:300]}",
        ),
    ]
