"""Document and file-collection tools: archives, conversions, images, PDFs, duplicates, the trash.

All of them leave their inputs untouched and write new files next to them
(or where the user says), never replacing an existing file, so every
change is ``change`` and its outputs are recorded in ``undo_journal`` as
``file_created`` (undo moves them to the trash). The tools that only read
are ``read``. Paths under system locations are refused for output.

Programs: archives use the standard library (``shutil`` and ``zipfile``/
``tarfile``; extraction rejects members that would land outside the target
folder); media conversion uses ``ffmpeg`` for sound and video and ImageMagick
(``magick``) for pictures; PDFs use poppler's ``pdfunite`` and
``pdfseparate``; text in pictures uses ``tesseract``; the trash uses ``gio
trash``. A missing program is reported by name.

``find_duplicates`` and ``find_files`` walk at most ``MAX_WALK`` files so a
request over a huge folder stays bounded; they say when they stopped early.
"""

from __future__ import annotations

import difflib
import filecmp
import hashlib
import os
import shutil
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from .. import undo_journal
from ..shell_risk import SYSTEM_PATHS
from .power import run_checked
from .registry import RISK_CHANGE, RISK_DANGER, RISK_READ, Tool, ToolFailure, object_schema

MAX_WALK = 200_000
MAX_LISTED = 50
AUDIO_VIDEO = {"mp3", "flac", "ogg", "opus", "wav", "m4a", "aac", "mp4", "mkv", "webm", "mov", "avi", "gif"}
IMAGES = {"png", "jpg", "jpeg", "webp", "avif", "tiff", "bmp", "heic", "pdf", "ico"}


def _path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ToolFailure(f"'{name}' is required and must be a path")
    return Path(os.path.abspath(os.path.expanduser(value.strip())))


def _existing(value: Any, name: str) -> Path:
    path = _path(value, name)
    if not path.exists():
        raise ToolFailure(f"{path} does not exist")
    return path


def _new_output(path: Path) -> Path:
    text = str(path)
    if any(text == root or text.startswith(root + "/") for root in SYSTEM_PATHS):
        raise ToolFailure(f"{path} is a system location")
    if path.exists():
        raise ToolFailure(f"{path} already exists; choose another name (nothing is replaced)")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _created(path: Path, what: str) -> str:
    undo_journal.record("file_created", f"Created {path}", {"path": str(path)})
    return f"{what} {path}."


def create_archive(arguments: dict[str, Any]) -> str:
    sources = [_existing(item, "paths") for item in arguments.get("paths") or []]
    if not sources:
        raise ToolFailure("'paths' must list at least one file or folder")
    target = _new_output(_path(arguments.get("archive"), "archive"))
    name = target.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for source in sources:
                for path in [source, *sorted(source.rglob("*"))] if source.is_dir() else [source]:
                    archive.write(path, path.relative_to(source.parent))
    elif name.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.zst", ".tar")):
        mode = "w:gz" if name.endswith(("gz", "tgz")) else "w:xz" if name.endswith("xz") else \
            "w:zst" if name.endswith("zst") else "w"
        with tarfile.open(target, mode) as archive:
            for source in sources:
                archive.add(source, source.name)
    else:
        raise ToolFailure("the archive name must end in .zip, .tar.gz, .tgz, .tar.xz, .tar.zst or .tar")
    return _created(target, f"Packed {len(sources)} item(s) into")


def extract_archive(arguments: dict[str, Any]) -> str:
    archive = _existing(arguments.get("archive"), "archive")
    destination = _path(arguments.get("destination") or str(archive.parent / archive.name.split(".")[0]), "destination")
    destination = _new_output(destination)
    destination.mkdir()
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as opened:
                for member in opened.namelist():
                    if not (destination / member).resolve().is_relative_to(destination.resolve()):
                        raise ToolFailure(f"the archive contains an unsafe path ({member}); not extracted")
                opened.extractall(destination)
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive) as opened:
                opened.extractall(destination, filter="data")
        else:
            raise ToolFailure(f"{archive} is not a zip or tar archive")
    except (tarfile.TarError, zipfile.BadZipFile, OSError) as error:
        shutil.rmtree(destination, ignore_errors=True)
        raise ToolFailure(f"could not extract {archive}: {error}") from error
    except ToolFailure:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return _created(destination, f"Extracted {archive.name} into")


def list_archive(arguments: dict[str, Any]) -> str:
    archive = _existing(arguments.get("archive"), "archive")
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as opened:
            names = opened.namelist()
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as opened:
            names = opened.getnames()
    else:
        raise ToolFailure(f"{archive} is not a zip or tar archive")
    wanted = str(arguments.get("contains") or "").lower()
    names = [name for name in names if wanted in name.lower()]
    shown = "\n".join(names[:MAX_LISTED * 4])
    return f"{len(names)} entries{' matching ' + repr(wanted) if wanted else ''}:\n{shown}"


def convert_file(arguments: dict[str, Any]) -> str:
    source = _existing(arguments.get("path"), "path")
    to = str(arguments.get("to") or "").lower().lstrip(".")
    if to not in AUDIO_VIDEO | IMAGES:
        raise ToolFailure(f"'to' must be one of {', '.join(sorted(AUDIO_VIDEO | IMAGES))}")
    target = _new_output(_path(arguments.get("output") or str(source.with_suffix("." + to)), "output"))
    if to in IMAGES and source.suffix.lower().lstrip(".") not in AUDIO_VIDEO - {"gif"}:
        run_checked(["magick", str(source), str(target)], timeout=300)
    else:
        run_checked(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(source), str(target)],
                    timeout=1800)
    return _created(target, f"Converted {source.name} to")


def edit_images(arguments: dict[str, Any]) -> str:
    sources = [_existing(item, "paths") for item in arguments.get("paths") or []]
    if not sources:
        raise ToolFailure("'paths' must list at least one picture")
    operations: list[str] = []
    resize = arguments.get("resize")
    if resize is not None:
        if not isinstance(resize, str) or not resize.replace("%", "").replace("x", "").isdigit():
            raise ToolFailure("'resize' must look like 50% or 1920x or 800x600")
        operations += ["-resize", resize]
    rotate = arguments.get("rotate")
    if rotate is not None:
        if rotate not in (90, 180, 270, -90):
            raise ToolFailure("'rotate' must be 90, 180 or 270")
        operations += ["-rotate", str(rotate)]
    if arguments.get("strip_metadata"):
        operations.append("-strip")
    if not operations:
        raise ToolFailure("give at least one of resize, rotate, strip_metadata")
    made = []
    for source in sources:
        target = _new_output(source.with_name(f"{source.stem}-edited{source.suffix}"))
        run_checked(["magick", str(source), *operations, str(target)], timeout=120)
        undo_journal.record("file_created", f"Created {target}", {"path": str(target)})
        made.append(str(target))
    return "Edited copies (the originals are untouched):\n" + "\n".join(made)


def _page_spec(text: str) -> list[int]:
    pages: list[int] = []
    for part in str(text).replace(" ", "").split(","):
        first, _, last = part.partition("-")
        if not first.isdigit() or (last and not last.isdigit()):
            raise ToolFailure("'pages' must look like 1-3,5")
        pages += list(range(int(first), int(last or first) + 1))
    return pages


def pdf_pages(arguments: dict[str, Any]) -> str:
    action = arguments.get("action")
    output = _new_output(_path(arguments.get("output"), "output"))
    if action == "merge":
        sources = [_existing(item, "paths") for item in arguments.get("paths") or []]
        if len(sources) < 2:
            raise ToolFailure("'paths' must list at least two PDFs to merge")
        run_checked(["pdfunite", *map(str, sources), str(output)], timeout=300)
        return _created(output, f"Merged {len(sources)} PDFs into")
    if action == "extract":
        source = _existing(arguments.get("path"), "path")
        pages = _page_spec(arguments.get("pages") or "")
        with tempfile.TemporaryDirectory() as tmp:
            parts = []
            for page in pages:
                part = Path(tmp) / f"{page:05d}.pdf"
                run_checked(["pdfseparate", "-f", str(page), "-l", str(page), str(source), str(part)], timeout=120)
                parts.append(str(part))
            if len(parts) == 1:
                shutil.copyfile(parts[0], output)
            else:
                run_checked(["pdfunite", *parts, str(output)], timeout=300)
        return _created(output, f"Saved pages {arguments.get('pages')} of {source.name} as")
    raise ToolFailure("'action' must be merge or extract")


def _walk(folder: Path):
    count = 0
    for root, directories, files in os.walk(folder):
        directories[:] = [name for name in directories if not name.startswith(".")]
        for name in files:
            count += 1
            if count > MAX_WALK:
                return
            yield Path(root) / name


def find_duplicates(arguments: dict[str, Any]) -> str:
    folder = _existing(arguments.get("folder"), "folder")
    by_size: dict[int, list[Path]] = {}
    walked = 0
    for path in _walk(folder):
        walked += 1
        try:
            if path.is_file() and not path.is_symlink() and path.stat().st_size > 0:
                by_size.setdefault(path.stat().st_size, []).append(path)
        except OSError:
            continue
    groups: dict[str, list[Path]] = {}
    for paths in (group for group in by_size.values() if len(group) > 1):
        for path in paths:
            digest = hashlib.sha256()
            try:
                with open(path, "rb") as handle:
                    for block in iter(lambda: handle.read(1 << 20), b""):
                        digest.update(block)
            except OSError:
                continue
            groups.setdefault(digest.hexdigest(), []).append(path)
    duplicates = sorted((group for group in groups.values() if len(group) > 1),
                        key=lambda group: -group[0].stat().st_size * len(group))
    if not duplicates:
        return f"No duplicate files in {folder} ({walked} files checked)."
    lines = [f"{len(duplicates)} sets of identical files (largest waste first; keep one of each):"]
    for group in duplicates[:MAX_LISTED]:
        lines.append(f"- {group[0].stat().st_size // 1024} KB each: " + " | ".join(map(str, group)))
    if walked >= MAX_WALK:
        lines.append(f"[stopped after {MAX_WALK} files]")
    return "\n".join(lines)


def find_files(arguments: dict[str, Any]) -> str:
    folder = _existing(arguments.get("folder"), "folder")
    minimum = float(arguments.get("min_size_mb") or 0) * 1024 * 1024
    older = arguments.get("older_than_days")
    newer = arguments.get("newer_than_days")
    extensions = {item.lower().lstrip(".") for item in arguments.get("extensions") or []}
    now = time.time()
    found = []
    for path in _walk(folder):
        try:
            info = path.stat()
        except OSError:
            continue
        age_days = (now - info.st_mtime) / 86400
        if info.st_size < minimum or (older and age_days < older) or (newer and age_days > newer):
            continue
        if extensions and path.suffix.lower().lstrip(".") not in extensions:
            continue
        found.append((info.st_size, info.st_mtime, path))
    found.sort(key=lambda item: -item[0] if minimum else -item[1])
    lines = [f"{size / 1048576:.1f} MB  {time.strftime('%Y-%m-%d', time.localtime(mtime))}  {path}"
             for size, mtime, path in found[:MAX_LISTED]]
    return (f"{len(found)} files match" + (f"; the first {MAX_LISTED}:" if len(found) > MAX_LISTED else ":")
            + "\n" + "\n".join(lines)) if found else "No files match."


def _trash_items() -> list[tuple[str, str]]:
    items = []
    for line in run_checked(["gio", "trash", "--list"]).splitlines():
        uri, _, original = line.partition("\t")
        if uri:
            items.append((uri, original))
    return items


def list_trash(arguments: dict[str, Any]) -> str:
    items = _trash_items()
    wanted = str(arguments.get("contains") or "").lower()
    shown = [original for _, original in items if wanted in original.lower()]
    if shown:
        return "\n".join(shown[:MAX_LISTED * 2])
    return f"Nothing in the trash matches '{wanted}'." if wanted else "The trash is empty."


def restore_from_trash(arguments: dict[str, Any]) -> str:
    original = str(_path(arguments.get("original_path"), "original_path"))
    matches = [uri for uri, path in _trash_items() if path == original]
    if not matches:
        raise ToolFailure(f"{original} is not in the trash. Use list_trash to see what is.")
    if os.path.lexists(original):
        raise ToolFailure(f"something is already at {original}; it was not restored")
    run_checked(["gio", "trash", "--restore", matches[-1]])
    return f"Restored {original}."


def compare(arguments: dict[str, Any]) -> str:
    first, second = _existing(arguments.get("first"), "first"), _existing(arguments.get("second"), "second")
    if first.is_dir() and second.is_dir():
        report = filecmp.dircmp(first, second)
        return (f"Only in {first}: {', '.join(report.left_only) or 'nothing'}\n"
                f"Only in {second}: {', '.join(report.right_only) or 'nothing'}\n"
                f"Different: {', '.join(report.diff_files) or 'nothing'}\n"
                f"Identical: {len(report.same_files)} files (top level only)")
    if first.is_dir() or second.is_dir():
        raise ToolFailure("compare two files or two folders")
    if filecmp.cmp(first, second, shallow=False):
        return "The files are identical."
    try:
        lines = difflib.unified_diff(first.read_text().splitlines(), second.read_text().splitlines(),
                                     str(first), str(second), lineterm="", n=1)
        return "\n".join(list(lines)[:400])
    except UnicodeDecodeError:
        return f"The files differ (they are not text; sizes {first.stat().st_size} and {second.stat().st_size} bytes)."


def text_from_image(arguments: dict[str, Any]) -> str:
    source = _existing(arguments.get("path"), "path")
    language = str(arguments.get("language") or "eng")
    if not language.replace("+", "").isalpha():
        raise ToolFailure("'language' must be a tesseract language code such as eng or deu")
    text = run_checked(["tesseract", str(source), "-", "-l", language], timeout=120)
    return text or "No text was found in the picture."


def classify_permissions(arguments: dict[str, Any]) -> tuple[str, str]:
    path = str(_path(arguments.get("path"), "path"))
    if any(path == root or path.startswith(root + "/") for root in SYSTEM_PATHS):
        return RISK_DANGER, f"{path} is a system location"
    return RISK_CHANGE, ""


def set_permissions(arguments: dict[str, Any]) -> str:
    path = _existing(arguments.get("path"), "path")
    mode = str(arguments.get("mode") or "")
    named = {"private": "600", "shared": "644", "executable": "755", "read-only": "444"}
    mode = named.get(mode, mode)
    if not (len(mode) == 3 and all(character in "01234567" for character in mode)):
        raise ToolFailure("'mode' must be private, shared, executable, read-only or an octal mode like 640")
    if path.stat().st_uid != os.getuid():
        raise ToolFailure(f"{path} belongs to another user; its permissions are not changed here")
    previous = oct(path.stat().st_mode & 0o777)[2:]
    path.chmod(int(mode, 8))
    return f"{path} permissions changed from {previous} to {mode}."


def document_tools() -> list[Tool]:
    path = {"type": "string"}
    paths = {"type": "array", "items": {"type": "string"}}
    return [
        Tool("create_archive", "Pack files and folders into a new .zip or .tar.gz archive.",
             object_schema({"paths": paths, "archive": path}, ["paths", "archive"]), RISK_CHANGE, create_archive,
             summarize=lambda a: f"Create the archive {a.get('archive', '?')}"),
        Tool("extract_archive", "Unpack a zip or tar archive into a new folder (default: beside it, named after it).",
             object_schema({"archive": path, "destination": path}, ["archive"]), RISK_CHANGE, extract_archive,
             summarize=lambda a: f"Extract {a.get('archive', '?')}"),
        Tool("list_archive", "List what is inside a zip or tar archive, optionally only names containing some text.",
             object_schema({"archive": path, "contains": {"type": "string"}}, ["archive"]), RISK_READ, list_archive,
             summarize=lambda a: f"Look inside {a.get('archive', '?')}"),
        Tool("convert_file", "Convert a picture, song or video to another format, as a new file.",
             object_schema({"path": path, "to": {"type": "string", "description": "png, jpg, webp, pdf, mp3, flac, "
                            "ogg, wav, mp4, mkv, webm, gif, ..."}, "output": path}, ["path", "to"]),
             RISK_CHANGE, convert_file, summarize=lambda a: f"Convert {a.get('path', '?')} to {a.get('to', '?')}"),
        Tool("edit_images", "Resize, rotate or remove the hidden metadata (location, camera) of pictures, saving "
             "edited copies.", object_schema({"paths": paths, "resize": {"type": "string", "description": "50% or "
                                               "1920x or 800x600"}, "rotate": {"type": "integer"},
                                              "strip_metadata": {"type": "boolean"}}, ["paths"]),
             RISK_CHANGE, edit_images, summarize=lambda a: f"Edit {len(a.get('paths') or [])} picture(s)"),
        Tool("pdf_pages", "Merge PDFs into one, or save some pages of a PDF as a new PDF.",
             object_schema({"action": {"type": "string", "enum": ["merge", "extract"]}, "paths": paths, "path": path,
                            "pages": {"type": "string", "description": "e.g. 1-3,5"}, "output": path},
                           ["action", "output"]), RISK_CHANGE, pdf_pages,
             summarize=lambda a: f"PDF {a.get('action', '?')} into {a.get('output', '?')}"),
        Tool("find_duplicates", "Find files with identical contents in a folder (and its subfolders).",
             object_schema({"folder": path}, ["folder"]), RISK_READ, find_duplicates,
             summarize=lambda a: f"Look for duplicates in {a.get('folder', '?')}"),
        Tool("find_files", "Find files in a folder by size, age and type: large files, old files, recent files.",
             object_schema({"folder": path, "min_size_mb": {"type": "number"}, "older_than_days": {"type": "number"},
                            "newer_than_days": {"type": "number"}, "extensions": paths}, ["folder"]),
             RISK_READ, find_files, summarize=lambda a: f"Look through {a.get('folder', '?')}"),
        Tool("list_trash", "What is in the trash, with where each item came from.",
             object_schema({"contains": {"type": "string"}}), RISK_READ, list_trash,
             summarize=lambda a: "Look in the trash"),
        Tool("restore_from_trash", "Put a trashed item back where it came from.",
             object_schema({"original_path": path}, ["original_path"]), RISK_CHANGE, restore_from_trash,
             summarize=lambda a: f"Restore {a.get('original_path', '?')} from the trash"),
        Tool("compare", "Compare two files (show the differences) or two folders (what is only in one, what differs).",
             object_schema({"first": path, "second": path}, ["first", "second"]), RISK_READ, compare,
             summarize=lambda a: "Compare files"),
        Tool("text_from_image", "Read the text in a picture or screenshot (OCR).",
             object_schema({"path": path, "language": {"type": "string", "description": "eng (default), deu, ..."}},
                           ["path"]), RISK_READ, text_from_image, summarize=lambda a: f"Read the text in {a.get('path', '?')}"),
        Tool("set_permissions", "Change who may read, change or run one of the user's files.",
             object_schema({"path": path, "mode": {"type": "string", "description": "private, shared, executable, "
                            "read-only, or octal like 640"}}, ["path", "mode"]), RISK_CHANGE, set_permissions,
             classify=classify_permissions, summarize=lambda a: f"Make {a.get('path', '?')} {a.get('mode', '?')}"),
    ]
