"""Build docs/data.js from approved briefs, trackers and coded stories: headlines, summaries and links only.

Only briefs with `status: approved` and a named reviewer are read. Tracker entries are cut
at the end of the latest approved brief's window, so nothing newer than a reviewed brief
reaches the page; names the model proposed (`pending_review`) are never exported. Story ids,
thread ids, article text and evidence quotes are not exported. `publish.py` calls this
after its approval gate.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from collections import Counter
from datetime import datetime
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
    has_catch_up = "\n## Catch-up" in body
    data = {"date": meta["date"], "reviewed_by": meta["reviewed_by"],
            "window_start": meta.get("window_start", ""), "window_end": meta.get("window_end", ""),
            "focus": parse_focus(section(body, "Alert focus box", "Daily brief"), names),
            "items": parse_items(section(body, "Daily brief", "Catch-up" if has_catch_up else None), names)}
    if has_catch_up:
        data["catch_up"] = {"start": meta.get("catch_up_start", ""), "end": data["window_start"],
                            "items": parse_items(section(body, "Catch-up", None), names)}
    return data


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
            "outlet_names": {g: sorted({o["name"] for o in outlets if o["outlet_group"] == g}, key=str.casefold)
                             for g in sorted({o["outlet_group"] for o in outlets})},
            "known_gaps": cfg["method"]["known_gaps"], "validation": cfg["method"]["validation"],
            "takedown_contact": cfg["project"]["contact_email"],
            "service_notes": [v["detail"] for v in status.values() if v.get("state") == "cap_hit"]}


def read_actor_names(cfg: dict[str, Any]) -> dict[str, str]:
    """Actor id to display name, from actors.csv."""
    with config.path(cfg, "actors_csv").open(encoding="utf-8", newline="") as fh:
        return {row["actor_id"]: row["name"] for row in csv.DictReader(fh)}


def page_source(src: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    """A tracker source for the page: date, headline, outlet name, link, severity."""
    return {"published": src["published"], "title": src["title"], "url": src["url"],
            "outlet": names.get(src["outlet_id"], src["outlet_id"]), "severity": src["severity"]}


def until(items: list[dict[str, Any]], cutoff: str) -> list[dict[str, Any]]:
    """Items published at or before the cutoff (ISO 8601 with offset)."""
    end = datetime.fromisoformat(cutoff)
    return [i for i in items if datetime.fromisoformat(i["published"]) <= end]


def tracker_data(cfg: dict[str, Any], cutoff: str, outlets: dict[str, str]) -> dict[str, Any] | None:
    """Tracker panels for the page, or None when trackers.json does not exist yet."""
    path = config.path(cfg, "trackers_json")
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    actors = read_actor_names(cfg)
    def who(value: str) -> str:
        return actors.get(value, value)
    resignations = []
    for entry in raw["resignations"]:
        events = until(entry["events"], cutoff)
        if not events:
            continue
        resignations.append({
            "name": entry["name"], "role": entry["role"], "status": entry["status"],
            "unconfirmed": entry["actor_status"] != "confirmed",
            "max_severity": max(e["severity"] for e in events),
            "called_by": sorted({who(e["by_whom"]) for e in events
                                 if e["action"] in ("called_to_resign", "dismissal_demanded")
                                 and e["by_whom"] != codebook.NOT_ADDRESSED}),
            "events": [{"action": e["action"], "stage": e["stage"],
                        "by_whom": "" if e["by_whom"] == codebook.NOT_ADDRESSED else who(e["by_whom"]),
                        "response": "" if e["response"] == codebook.NOT_ADDRESSED else e["response"],
                        **page_source(e, outlets)} for e in events]})
    leaders = [{"name": e["name"], "role": e["role"], "unconfirmed": e["actor_status"] != "confirmed",
                "stories_recent": e["stories_recent"], "stories_prior": e["stories_prior"],
                "mean_stance": e["mean_stance"], "stance_rows": e["stance_rows"],
                "signals": [page_source(s, outlets) for s in until(e["signals"], cutoff)]}
               for e in raw["emerging_leaders"]]
    timeline = []
    for entry in raw["transition_timeline"]:
        if datetime.fromisoformat(entry["date"]) > datetime.fromisoformat(cutoff):
            continue
        timeline.append({"date": entry["date"], "summary": entry["summary"],
                         "why_it_matters": entry["why_it_matters"], "announced_only": entry["announced_only"],
                         "severity": entry["severity"], "outlet_groups": entry["outlet_groups"],
                         "sources": [page_source(s, outlets) for s in until(entry["sources"], cutoff)]})
    return {"built_at": raw["built_at"], "cutoff": cutoff, "window_days": raw["emerging_window_days"],
            "resignations": resignations, "emerging_leaders": leaders, "transition_timeline": timeline}


def read_page_actors(cfg: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Actors that may appear on the page (seed or confirmed, never proposed), by id."""
    path = config.path(cfg, "actors_csv")
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["actor_id"]: row for row in csv.DictReader(fh) if row.get("status") != "proposed"}


def article_list(cfg: dict[str, Any], cutoff: str, outlets: dict[str, str]) -> list[dict[str, Any]]:
    """Relevant coded stories published up to the cutoff, newest first: headline, summary, link.

    Only listed actors are named; no story ids, entity rows, text or evidence quotes.
    """
    path = config.path(cfg, "coded_jsonl")
    if not path.exists():
        return []
    actors = read_page_actors(cfg)
    end = datetime.fromisoformat(cutoff)
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            ext = row["extraction"]
            if not ext.get("relevant") or datetime.fromisoformat(row["published"]) > end:
                continue
            ids = [a for a in ext.get("actors", []) if a in actors]
            rows.append({
                "published": row["published"], "title": row["title"], "url": row["source_url"],
                "outlet": outlets.get(row["outlet_id"], row["outlet_id"]),
                "summary": ext["summary"],
                "categories": [c for c in (ext["category"], ext.get("secondary_category")) if c],
                "actors": [actors[a]["name"] for a in ids],
                "unconfirmed": [actors[a]["name"] for a in ids if actors[a].get("status") != "confirmed"],
                "outlet_groups": row["outlet_groups"], "n_copies": row.get("n_copies", 1),
                "severity": row["severity"]})
    rows.sort(key=lambda r: r["published"], reverse=True)
    return rows


def build(cfg: dict[str, Any]) -> dict[str, Any]:
    """The page data; raises ValueError when no brief is approved."""
    paths = approved_paths(cfg)
    if not paths:
        raise ValueError("no approved brief to export")
    outlets = read_outlets(cfg)
    names = {o["outlet_id"]: o["name"] for o in outlets}
    briefs = [parse_brief(p.read_text(encoding="utf-8"), names) for p in paths]
    data = {"generated": config.iso(config.now(cfg), cfg), "timezone": cfg["timezone"],
            "briefs": briefs[::-1], "method": method_notes(cfg, outlets)}
    cutoff = briefs[-1]["window_end"]
    trackers = tracker_data(cfg, cutoff, names) if cutoff else None
    if trackers:
        data["trackers"] = trackers
    if cutoff:
        data["articles"] = article_list(cfg, cutoff, names)
    return data


def write(cfg: dict[str, Any], data: dict[str, Any]) -> Path:
    """Write docs/data.js. Called only by publish.py, after its gate."""
    path = config.path(cfg, "docs_dir") / "data.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("window.SITE_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    log.info("Wrote %s with %d briefs", path, len(data["briefs"]))
    return path
