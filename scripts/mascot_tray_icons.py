#!/usr/bin/env python3
"""Install the named tray poses from the same SVG layers the floating mascot uses."""
from __future__ import annotations

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

APP_ID = "io.github.dragonswithin.happybot"
IMAGES = Path(__file__).resolve().parents[1] / "plasmoid" / APP_ID / "contents/images"
LAYERS = {
    "busy": ("busy",),
    "memory": ("memory",),
    "hot": ("hot-face", "sweat"),
    "download": ("download",),
    "upload": ("upload",),
    "transfer": ("transfer",),
    "recording": ("recording",),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    for pose, layers in LAYERS.items():
        target = args.directory / f"{APP_ID}-{pose}.svg"
        if args.remove:
            target.unlink(missing_ok=True)
            continue
        args.directory.mkdir(parents=True, exist_ok=True)
        icon = ET.parse(IMAGES / "happy-bot.svg")
        for layer in layers:
            icon.getroot().extend(ET.parse(IMAGES / "reactions" / f"{layer}.svg").getroot())
        icon.write(target, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
