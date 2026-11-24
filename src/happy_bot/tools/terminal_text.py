"""Turns raw terminal output into the text the model reads.

The shell tools in ``tools/shell.py`` capture what a command printed: through
a pipe for ``run_command``, and through ``script``'s log of a real terminal
for ``run_in_terminal``. A real terminal log is written for a screen, not for
a reader: progress bars redraw one line hundreds of times with carriage
returns, and colour codes and other control sequences are mixed in. Some of
those sequences carry private details (systemd's OSC 3008 session markers
name the host, machine id and boot id) that must not be passed to a model,
which may be a hosted service.

``clean`` keeps what the screen finally showed: escape sequences are removed,
and on each line only the text after the last carriage return is kept, as a
terminal would display it. ``keep_head_and_tail`` shortens long output to its
beginning and end, because the start (what the command was going to do, such
as a package list) and the end (how it finished) are what matter. Both are
pure functions with no state.
"""

from __future__ import annotations

import re

# OSC sequences end with BEL or with ST (ESC \); CSI sequences end with a
# final byte in @-~; the remaining two-byte escapes select character sets
# and keypad modes.
_ESCAPES = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b\[[0-9;?<=>]*[ -/]*[@-~]"
    r"|\x1b[()][0-9A-Za-z]"
    r"|\x1b[=>78DEHMc]"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(text: str) -> str:
    """The text as a terminal would finally show it, without control sequences."""
    text = _ESCAPES.sub("", text)
    lines = []
    for line in text.split("\n"):
        segments = [segment for segment in line.split("\r") if segment.strip()]
        lines.append(_CONTROL.sub("", segments[-1]).rstrip() if segments else "")
    return "\n".join(lines)


def keep_head_and_tail(text: str, head: int, tail: int) -> str:
    """``text`` if it fits in ``head + tail`` characters, else its start and end with a note of the cut."""
    if len(text) <= head + tail:
        return text
    cut = len(text) - head - tail
    return f"{text[:head]}\n[... {cut} characters cut ...]\n{text[-tail:]}"
