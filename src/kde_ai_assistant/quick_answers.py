"""Answers the search bar computes itself while the user types: no model, no network.

``answer(text)`` returns at most one answer for the typed text, or None:

- arithmetic (``2+2*3``, ``sqrt(2)*10``, ``2^10``), evaluated with a small
  safe evaluator over Python's ``ast`` (numbers, operators, parentheses and
  a fixed set of functions and constants; nothing else is executed);
- percentages (``15% of 80``, ``80 + 15%``);
- unit conversions (``5 km to miles``, ``100 F in C``), through the user's
  ``qalc`` (libqalculate) when it is installed; only text shaped like
  ``<number> <unit> to|in <unit>`` is sent to it, because qalc reads almost
  any words as units;
- dates (``3 weeks from friday``, ``10 days ago``, ``days until 2026-12-25``);
- clock time elsewhere (``time in Tokyo``), from the system's time zone
  database (``zoneinfo``).

An answer is ``{"title", "subtitle", "value"}``: ``title`` is shown,
``value`` is what Enter copies. Everything runs in well under a second; the
qalc call has a two-second limit.
"""

from __future__ import annotations

import ast
import datetime
import math
import operator
import re
import shutil
import subprocess
import zoneinfo
from typing import Any

_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
           ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "log": math.log10,
              "ln": math.log, "abs": abs, "round": round, "exp": math.exp, "floor": math.floor, "ceil": math.ceil}
_CONSTANTS = {"pi": math.pi, "e": math.e}
_MATHLIKE = re.compile(r"^[\d\s.+\-*/%^()a-z,]+$")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_SPAN = {"day": 1, "days": 1, "week": 7, "weeks": 7}


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("exponent too large")
        return _BINARY[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS
            and len(node.args) == 1 and not node.keywords):
        return _FUNCTIONS[node.func.id](_evaluate(node.args[0]))
    raise ValueError("not arithmetic")


def _format(number: float) -> str:
    if isinstance(number, float) and number.is_integer() and abs(number) < 1e15:
        number = int(number)
    if isinstance(number, int):
        return f"{number:,}".replace(",", " ") if abs(number) >= 10000 else str(number)
    return f"{number:.10g}"


def calculate(text: str) -> str | None:
    """The result of plain arithmetic, or None if the text is not arithmetic."""
    expression = text.strip().lower().replace("^", "**").replace("×", "*").replace("÷", "/").rstrip("=").strip()
    if not expression or not _MATHLIKE.match(expression) or not re.search(r"\d", expression):
        return None
    if not re.search(r"[+\-*/%(]", expression):  # a bare number is not a question
        return None
    try:
        value = _evaluate(ast.parse(expression, mode="eval"))
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError):
        return None
    return _format(value)


def percentage(text: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"\s*([\d.]+)\s*%\s*of\s*([\d.]+)\s*", text.lower())
    if match:
        value = float(match.group(1)) / 100 * float(match.group(2))
        return _format(value), f"{match.group(1)}% of {match.group(2)}"
    match = re.fullmatch(r"\s*([\d.]+)\s*([+-])\s*([\d.]+)\s*%\s*", text.lower())
    if match:
        base, change = float(match.group(1)), float(match.group(3)) / 100
        value = base * (1 + change if match.group(2) == "+" else 1 - change)
        return _format(value), f"{match.group(1)} {match.group(2)} {match.group(3)}%"
    return None


_CONVERSION = re.compile(r"\s*(-?[\d.,]+)\s*([a-zA-Z°µ/²³ ]{1,30}?)\s+(?:to|in|as)\s+([a-zA-Z°µ/²³ ]{1,30}?)\s*")
# Bare temperature letters mean degrees here; to qalc "F" and "C" are farad and coulomb.
_TEMPERATURES = {"f": "°F", "fahrenheit": "°F", "c": "°C", "celsius": "°C", "k": "K", "kelvin": "K"}


def _qalc(expression: str) -> str | None:
    qalc = shutil.which("qalc")
    if not qalc:
        return None
    try:
        completed = subprocess.run([qalc, "-t", expression], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    result = completed.stdout.strip()
    return result if completed.returncode == 0 and result and "\n" not in result else None


def convert(text: str) -> str | None:
    """A unit conversion through qalc, for text shaped like '<number> <unit> to <unit>'.

    The answer is given in the target unit alone ("3.106855961 miles"), not
    qalc's mixed form ("3 mi + 188 yd + ..."): non-temperature conversions are
    asked as a ratio of the amount to one target unit.
    """
    match = _CONVERSION.fullmatch(text)
    if not match:
        return None
    amount, source, target = match.group(1).replace(",", ""), match.group(2).strip(), match.group(3).strip()
    source = _TEMPERATURES.get(source.lower(), source)
    target = _TEMPERATURES.get(target.lower(), target)
    if "°" in source or "°" in target or target == "K":
        return _qalc(f"{amount} {source} to {target}")
    ratio = _qalc(f"({amount} {source})/(1 {target})")
    if ratio is None or not re.fullmatch(r"-?[\d.]+(E-?\d+)?", ratio.replace("−", "-")):
        return None  # not two compatible units
    return f"{ratio} {target}"


def _weekday_after(today: datetime.date, name: str) -> datetime.date:
    offset = (_WEEKDAYS.index(name) - today.weekday()) % 7 or 7
    return today + datetime.timedelta(days=offset)


def date_answer(text: str, today: datetime.date | None = None) -> tuple[str, str] | None:
    today = today or datetime.date.today()
    lowered = " ".join(text.lower().split())
    match = re.fullmatch(r"(\d+) (days?|weeks?) (from|after) (today|tomorrow|now|" + "|".join(_WEEKDAYS) + ")", lowered)
    if match:
        start = {"today": today, "now": today, "tomorrow": today + datetime.timedelta(days=1)}.get(
            match.group(4)) or _weekday_after(today, match.group(4))
        result = start + datetime.timedelta(days=int(match.group(1)) * _SPAN[match.group(2)])
        return result.strftime("%A %d %B %Y"), lowered
    match = re.fullmatch(r"(\d+) (days?|weeks?) ago", lowered)
    if match:
        result = today - datetime.timedelta(days=int(match.group(1)) * _SPAN[match.group(2)])
        return result.strftime("%A %d %B %Y"), lowered
    match = re.fullmatch(r"days (until|till|to) (\d{4}-\d{2}-\d{2})", lowered)
    if match:
        try:
            target = datetime.date.fromisoformat(match.group(2))
        except ValueError:
            return None
        return f"{(target - today).days} days", f"until {target:%A %d %B %Y}"
    return None


def world_time(text: str, now: datetime.datetime | None = None) -> tuple[str, str] | None:
    match = re.fullmatch(r"(?:time|clock) in ([a-z _'-]{2,40})", " ".join(text.lower().split()))
    if not match:
        return None
    place = match.group(1).strip().replace(" ", "_")
    zones = [zone for zone in zoneinfo.available_timezones() if zone.lower().split("/")[-1] == place]
    if not zones:
        return None
    zone = sorted(zones)[0]
    moment = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(zoneinfo.ZoneInfo(zone))
    return moment.strftime("%H:%M, %A"), zone.replace("_", " ")


def answer(text: str) -> dict[str, Any] | None:
    """One computed answer for the typed text, or None."""
    for compute in (percentage, date_answer, world_time):
        found = compute(text)
        if found:
            return {"title": found[0], "subtitle": found[1], "value": found[0]}
    result = calculate(text)
    if result is not None:
        return {"title": f"= {result}", "subtitle": text.strip(), "value": result}
    converted = convert(text)
    if converted is not None:
        return {"title": converted, "subtitle": text.strip(), "value": converted}
    return None
