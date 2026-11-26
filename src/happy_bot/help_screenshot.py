"""Local edits and text recognition for the image displayed in a Help draft."""

from __future__ import annotations

import math
import os
import re
import uuid
from pathlib import Path

from .tools.documents import text_from_image


def read_text(path: Path) -> str:
    text = text_from_image({"path": str(path)})
    if text == "No text was found in the picture.":
        return ""
    # OCR often includes the window menus. Prefer a paragraph that names a problem,
    # while keeping other languages and messages without a familiar keyword usable.
    paragraphs = re.split(r"\n\s*\n", text.strip())
    for index, paragraph in enumerate(paragraphs):
        if re.search(r"\b(error|failed|cannot|denied|exception|unable)\b", paragraph, re.IGNORECASE):
            return "\n\n".join(paragraphs[index:index + 2])[:4000]
    return text[:4000]


def edit(path: Path, action: str, coordinates: list) -> Path:
    """Map coordinates in the displayed image (0..1) to its original pixels."""
    from PIL import Image, ImageDraw

    count = {"point": 2, "crop": 4}.get(action)
    if not count or not isinstance(coordinates, list) or len(coordinates) != count or not all(
        type(n) in (int, float) and 0 <= n <= 1 for n in coordinates
    ):
        raise ValueError("Select a point or area inside the screenshot.")
    with Image.open(path) as source:
        width, height = source.size
        x, y = coordinates[:2]
        if action == "crop":
            right, bottom = coordinates[2:]
            if right <= x or bottom <= y:
                raise ValueError("Drag across the area you want to keep.")
            result = source.crop((math.floor(x * width), math.floor(y * height),
                                  math.ceil(right * width), math.ceil(bottom * height)))
        else:
            result = source.convert("RGB")
            cx, cy = round(x * (width - 1)), round(y * (height - 1))
            radius = max(6, round(min(width, height) * 0.045))
            stroke = max(2, radius // 7)
            draw = ImageDraw.Draw(result)
            for size, color in ((radius + stroke, "white"), (radius, "#d12c42")):
                draw.ellipse((cx - size, cy - size, cx + size, cy + size), outline=color, width=stroke)
        target = path.with_name(f"{uuid.uuid4().hex}.png")
        result.info.clear()
        with result, os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as handle:
            try:
                result.save(handle, format="PNG")
            except OSError:
                target.unlink(missing_ok=True)
                raise
        return target
