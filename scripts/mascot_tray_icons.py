#!/usr/bin/env python3
"""Install the named tray poses from the same SVG layers the floating mascot uses."""
from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from happy_bot.ui_settings import MASCOT_ICON, ROBOT_STYLES, robot_theme_icon  # noqa: E402

IMAGES = REPO / "plasmoid" / MASCOT_ICON / "contents/images"
LAYERS = {
    "busy": ("busy",),
    "memory": ("memory",),
    "nudge": ("nudge",),
    "hot": ("hot-face", "sweat"),
    "download": ("download",),
    "upload": ("upload",),
    "transfer": ("transfer",),
    "recording": ("recording",),
}


def icons() -> Iterator[tuple[str, Path, tuple[str, ...]]]:
    """Named icons owned by this generator. Pip's base icon belongs to the application."""
    yield f"{MASCOT_ICON}-microphone-active", IMAGES / "microphone-active.svg", ()
    for style in ROBOT_STYLES:
        prefix = robot_theme_icon(style)
        if style == "pip":
            base = IMAGES / "happy-bot.svg"
        else:
            base = IMAGES / "robots" / f"{style}.svg"
            yield prefix, base, ()
        for pose, layers in LAYERS.items():
            yield f"{prefix}-{pose}", base, layers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    if not args.remove:
        args.directory.mkdir(parents=True, exist_ok=True)
    for name, base, layers in icons():
        target = args.directory / f"{name}.svg"
        if args.remove:
            target.unlink(missing_ok=True)
            continue
        if not layers:
            shutil.copyfile(base, target)
            continue
        icon = ET.parse(base)
        for layer in layers:
            icon.getroot().extend(ET.parse(IMAGES / "reactions" / f"{layer}.svg").getroot())
        icon.write(target, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
