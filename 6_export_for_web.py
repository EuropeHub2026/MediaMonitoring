"""Build docs/data.js from approved briefs: headlines, summaries and links only.

Only briefs with `status: approved` and a named reviewer are read. Story ids, article text
and evidence quotes are not exported. `publish.py` calls this after its approval gate.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

import codebook
import config

SCRIPT = "6_export_for_web"
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
FOCUS = re.compile(r"- \*\*Severity (\d)\*\* · (.*?) · (.*)")
log = logging.getLogger(SCRIPT)


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Return (front matter, body) of a brief."""
    match = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not match:
        return {}, text
    pairs = (line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    return {k.strip(): v.strip() for k, v in pairs}, match.group(2)


def is_approved(meta: dict[str, str]) -> bool:
    """A brief counts only with status approved and a named reviewer."""
    return meta.get("status") == "approved" and bool(meta.get("reviewed_by"))


def sources(line: str, names: dict[str, str]) -> list[dict[str, str]]:
    """Links in a line, with outlet ids replaced by outlet names."""
    return [{"name": names.get(label, label), "url": url} for label, url in LINK.findall(line)]


def section(body: str, title: str, next_title: str | None) -> str:
    """Text between two level-two headings."""
    start = body.index(f"## {title}") + len(title) + 3
    return body[start:body.index(f"## {next_title}")] if next_title else body[start:]


def parse_focus(text: str, names: dict[str, str]) -> list[dict[str, Any]]:
    """Alert items from the focus box section."""
    items: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = FOCUS.match(line)
        if match:
            items.append({"severity": int(match.group(1)), "categories": match.group(2).split(", "),
                          "text": match.group(3).strip(), "sources": []})
        elif items and line.strip().startswith("- Sources:"):
            items[-1]["sources"] = sources(line, names)
    return items


def parse_items(text: str, names: dict[str, str]) -> list[dict[str, Any]]:
    """Brief items from the daily brief section. Lines starting `Stories:` are left out."""
    items = []
    for block in re.split(r"^### ", text, flags=re.M)[1:]:
        headline, _, rest = block.partition("\n")
        item: dict[str, Any] = {"headline": headline.strip(), "paragraphs": [], "why": "", "sources": []}
        for para in (p.strip() for p in rest.split("\n\n")):
            if para.startswith("**Why it matters:**"):
                item["why"] = para.removeprefix("**Why it matters:**").strip()
            elif para.startswith("Sources:"):
                item["sources"] = sources(para, names)
            elif para and not para.startswith("Stories:"):
                item["paragraphs"].append(para)
        items.append(item)
    return items


def parse_brief(text: str, names: dict[str, str]) -> dict[str, Any]:
    """One approved brief as page data."""
    meta, body = split_front_matter(text)
    return {"date": meta["date"], "reviewed_by": meta["reviewed_by"],
            "window_start": meta.get("window_start", ""), "window_end": meta.get("window_end", ""),
            "focus": parse_focus(section(body, "Alert focus box", "Daily brief"), names),
            "items": parse_items(section(body, "Daily brief", None), names)}


def read_outlets(cfg: dict[str, Any]) -> list[dict[str, str]]:
    """Rows of outlets.csv."""
    with config.path(cfg, "outlets_csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def approved_paths(cfg: dict[str, Any]) -> list[Path]:
    """Approved brief files, oldest first."""
    paths = sorted(config.path(cfg, "review_dir").glob("brief_*.md"))
    return [p for p in paths if is_approved(split_front_matter(p.read_text(encoding="utf-8"))[0])]


def method_notes(cfg: dict[str, Any], outlets: list[dict[str, str]]) -> dict[str, Any]:
    """Facts for the method notes panel."""
    status_path = config.path(cfg, "status_json")
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    return {"codebook_version": codebook.CODEBOOK_VERSION, "prompt_version": codebook.PROMPT_VERSION,
            "outlets_by_group": dict(sorted(Counter(o["outlet_group"] for o in outlets).items())),
            "known_gaps": cfg["method"]["known_gaps"], "validation": cfg["method"]["validation"],
            "takedown_contact": cfg["project"]["contact_email"],
            "service_notes": [v["detail"] for v in status.values() if v.get("state") == "cap_hit"]}


def build(cfg: dict[str, Any]) -> dict[str, Any]:
    """The page data; raises ValueError when no brief is approved."""
    paths = approved_paths(cfg)
    if not paths:
        raise ValueError("no approved brief to export")
    outlets = read_outlets(cfg)
    names = {o["outlet_id"]: o["name"] for o in outlets}
    briefs = [parse_brief(p.read_text(encoding="utf-8"), names) for p in paths]
    return {"generated": config.iso(config.now(cfg), cfg), "timezone": cfg["timezone"],
            "briefs": briefs[::-1], "method": method_notes(cfg, outlets)}


def write(cfg: dict[str, Any], data: dict[str, Any]) -> Path:
    """Write docs/data.js. Called only by publish.py, after its gate."""
    path = config.path(cfg, "docs_dir") / "data.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("window.SITE_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    log.info("Wrote %s with %d briefs", path, len(data["briefs"]))
    return path
