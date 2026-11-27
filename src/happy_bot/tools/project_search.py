"""Find literal text in a selected project and expose matches as clickable lines."""

import json
from pathlib import Path
import shutil
import subprocess
import threading

from .registry import RISK_READ, Tool, ToolFailure, object_schema


def search(arguments):
    root = Path(str(arguments.get("folder", ""))).expanduser()
    needle = arguments.get("text")
    if not root.is_absolute() or not root.is_dir() or not isinstance(needle, str) or not needle.strip():
        raise ToolFailure("Choose a project folder and enter the text to find.")
    binary = shutil.which("rg")
    if not binary:
        raise ToolFailure("Install ripgrep to search inside a project.")
    args = [binary, "--no-config", "--json", "--fixed-strings", "--smart-case", "--max-filesize", "2M", "--", needle, "."]
    matches = []
    with subprocess.Popen(args, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        timer = threading.Timer(10, proc.kill)
        timer.start()
        try:
            for raw in proc.stdout:
                event = json.loads(raw)
                if event["type"] != "match":
                    continue
                data = event["data"]
                name = data["path"].get("text")
                if name:
                    matches.append({"path": str(root / name), "line": data["line_number"],
                                    "text": data["lines"].get("text", "").strip()[:160]})
                if len(matches) == 15:
                    break
            if len(matches) < 15 and proc.wait() not in (0, 1):
                raise ToolFailure("Project search did not finish. Try a smaller folder.")
        finally:
            timer.cancel()
            if proc.poll() is None:
                proc.kill()
    # Stay inside the registry's text limit so the structured result can be replayed.
    while matches:
        value = json.dumps(matches, ensure_ascii=False)
        if len(value) <= 7800:
            return value
        matches.pop()
    return "[]"


def card(result):
    try:
        matches = json.loads(result)
    except ValueError:
        return None
    return {"kind": "project_matches", "matches": matches} if isinstance(matches, list) and matches else None


def open_line(path, line):
    if not isinstance(path, str) or not Path(path).is_absolute() or not Path(path).is_file():
        raise ValueError("The matched file is no longer available.")
    if type(line) is not int or line < 1:
        raise ValueError("Choose a valid line.")
    editor = shutil.which("kate") or shutil.which("kwrite")
    if not editor:
        raise ValueError("Install Kate or KWrite to open a match at its line.")
    subprocess.Popen([editor, "--line", str(line), "--", path], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def project_tool():
    return Tool("search_project", "Find literal text or code inside the user's chosen project directory. Returns filenames, "
                "line numbers and excerpts. Ask for the folder if it is unclear.",
                object_schema({"folder": {"type": "string"}, "text": {"type": "string"}}, ["folder", "text"]),
                RISK_READ, search, card=card, summarize=lambda args: f"Search inside {args.get('folder', 'the project')}")
