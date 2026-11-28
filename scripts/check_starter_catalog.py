#!/usr/bin/env python3
"""Check reviewed starter downloads and flag upstream changes for the next review."""
import json
import re
import sys
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen
from xml.etree import ElementTree

CATALOG = Path(__file__).resolve().parents[1] / "src/happy_bot/starter_models.json"
LIBRARY = "https://ollama.com/library/"
REGISTRY = "https://registry.ollama.ai/v2/library/"
FAMILY = r"[a-z0-9][a-z0-9._-]{0,63}"


def fetch(url, limit):
    with urlopen(url, timeout=15) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Metadata exceeded its size limit at {url}")
    return data


class ToolModels(HTMLParser):
    """Collect official library links whose badges advertise tool calling."""
    def __init__(self):
        super().__init__()
        self.family = ""
        self.badge = False
        self.families = set()

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            link = re.fullmatch("/library/(" + FAMILY + ")", dict(attrs).get("href") or "")
            self.family = link[1] if link else ""
        if tag == "span":
            self.badge = True

    def handle_endtag(self, tag):
        if tag == "a":
            self.family = ""
        if tag == "span":
            self.badge = False

    def handle_data(self, data):
        if self.family and self.badge and data.strip() == "tools":
            self.families.add(self.family)


def tool_families(library):
    parser = ToolModels()
    parser.feed(library)
    if not parser.families:
        raise ValueError("Ollama's library returned no tool-capable models")
    return parser.families


def changed_families(families, sitemap, reviewed):
    dated = {}
    for node in ElementTree.fromstring(sitemap).findall("{*}url"):
        link = node.findtext("{*}loc", "")
        family = link.removeprefix(LIBRARY)
        if link.startswith(LIBRARY) and family in families:
            dated[family] = date.fromisoformat(node.findtext("{*}lastmod", ""))
    if not dated:
        raise ValueError("Ollama's sitemap returned no dated tool-capable models")
    return sorted(family for family, modified in dated.items() if modified > reviewed)


def main():
    catalog = json.loads(CATALOG.read_bytes())
    reviewed = date.fromisoformat(catalog["reviewed_on"])
    today = datetime.now(timezone.utc).date()
    issues = []
    if not 0 <= (today - reviewed).days <= 30:
        issues.append(f"The last catalog review was {reviewed}. Check the available local models.")
    supported = tool_families(fetch(LIBRARY.rstrip("/"), 4_000_000).decode())
    tags = [item["model"] for item in catalog["models"]]
    if len(set(tags)) != len(tags):
        issues.append("Duplicate model tags in the catalog.")
    for family in sorted({tag.split(":")[0] for tag in tags} - supported):
        issues.append(f"Check tool support for {LIBRARY}{family} before recommending it.")
    for model in catalog["models"]:
        family, tag = model["model"].split(":")
        if not re.fullmatch(FAMILY, family) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,64}", tag):
            raise ValueError("Invalid model tag in catalog")
        manifest = json.loads(fetch(f"{REGISTRY}{family}/manifests/{tag}", 65536))
        layers = manifest["layers"]
        if not any(layer.get("mediaType") == "application/vnd.ollama.image.model" for layer in layers):
            issues.append(f"{model['model']} has no local model weights.")
        size = sum(layer["size"] for layer in layers) / 1e9
        if abs(size - model["download_gb"]) > max(0.5, 0.05 * size):
            issues.append(f"{model['model']} now downloads {size:.1f} GB. Recheck its memory estimate.")
    families = changed_families(supported,
                                fetch("https://ollama.com/sitemap.xml", 2_000_000), reviewed)
    for family in families:
        issues.append(f"Review new or changed tool-capable family: {LIBRARY}{family}")
    for issue in issues:
        print(issue)
    if issues:
        print("Review the candidates and hardware tiers, update reviewed_on, and increment revision when publishing.")
    else:
        print(f"Checked {len(catalog['models'])} starter downloads and upstream tool-model changes since {reviewed}.")
    return bool(issues)


if __name__ == "__main__":
    sys.exit(main())
