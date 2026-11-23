"""The shell tool: run any command as the user.

``run_command`` is what makes "control anything" true: whatever has no
dedicated tool can still be done with a command. Each call is classified by
``shell_risk.classify_command`` before it runs, so a command that deletes or
makes an OS-level change waits for the user's approval and everything else
runs at once.

The command runs under ``bash -c`` in its own process group, with no terminal
and no standard input, in the user's home directory unless
``working_directory`` is given. Output (stdout and stderr together) is
captured; when it is long the beginning and the end are kept. On timeout the
whole process group is killed. A non-zero exit status is reported in the
result rather than raised, because the output is usually what the model needs
to recover.

Interactive programs and commands that need a password cannot be used; they
get end-of-file on input.
"""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Any

from ..shell_risk import classify_command
from .registry import RISK_CHANGE, Tool, ToolFailure, object_schema

DEFAULT_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 600
OUTPUT_HEAD_CHARS = 2500
OUTPUT_TAIL_CHARS = 4500


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
            stderr=subprocess.STDOUT, start_new_session=True, text=True, errors="replace")
    except OSError as error:
        raise ToolFailure(f"could not start the command: {error}") from error
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        output, _ = process.communicate()
    output = output or ""
    if len(output) > OUTPUT_HEAD_CHARS + OUTPUT_TAIL_CHARS:
        cut = len(output) - OUTPUT_HEAD_CHARS - OUTPUT_TAIL_CHARS
        output = f"{output[:OUTPUT_HEAD_CHARS]}\n[... {cut} characters cut ...]\n{output[-OUTPUT_TAIL_CHARS:]}"
    status = f"timed out after {timeout} s and was stopped" if timed_out else f"exit status {process.returncode}"
    return f"[{status}]\n{output.rstrip() or '(no output)'}"


def shell_tools() -> list[Tool]:
    return [Tool(
        "run_command",
        "Run a shell command (bash) as the user and return its output. Use for anything no other tool covers. "
        "Not interactive: no password prompts, no editors.",
        object_schema({
            "command": {"type": "string"},
            "working_directory": {"type": "string", "description": "Default: the home folder"},
            "timeout_seconds": {"type": "integer", "description": f"Default {DEFAULT_TIMEOUT_SECONDS}, max {MAX_TIMEOUT_SECONDS}"},
        }, ["command"]),
        RISK_CHANGE, run_command, classify=classify,
        summarize=lambda arguments: f"Run: {str(arguments.get('command', ''))[:300]}",
    )]
