"""Stage 2 trackers: resignations and dismissals, emerging leaders, transition timeline.

Built only from coded entity rows and story categories in `data/coded.jsonl` (CLAUDE.md,
Codebook rules). Only relevant stories count. Names the model proposed (`proposed: true`)
never enter a tracker: they go to a `pending_review` list instead, so a reviewer can add them
to `actors.csv`. Every tracker entry carries the actor's `status` from `actors.csv` (`seed`
or `confirmed`) so the web export can decide what to show. Severity of a timeline entry is
computed across all copies of its thread's stories, as in the brief.

Evidence quotes and article text are never written to the output.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

import codebook
import config

SCRIPT = "5_build_trackers"
TRACKERS_VERSION = "0.1.0"

coder = importlib.import_module("3_code_stories")
brief = importlib.import_module("4_draft_brief")
log = logging.getLogger(SCRIPT)

PRESSURE_ACTIONS = ("called_to_resign", "dismissal_demanded")
DEPARTURE_ACTIONS = ("resigned", "dismissed", "suspended")
RESIGNATION_ACTIONS = PRESSURE_ACTIONS + DEPARTURE_ACTIONS
# Order of a tracker entry's status, most advanced last.
STATUS_ORDER = ["called_to_resign", "departure_announced", "suspended", "gone"]


def relevant(coded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Relevant coded stories, oldest first."""
    return sorted((r for r in coded if r["extraction"]["relevant"]), key=lambda r: r["published"])


def source(row: dict[str, Any]) -> dict[str, Any]:
    """The trail for one story: id, date, title, link, severity. No text or quote."""
    return {"story_id": row["story_id"], "published": row["published"], "title": row["title"],
            "url": row["source_url"], "outlet_id": row["outlet_id"], "severity": row["severity"]}


def entity_rows(stories: list[dict[str, Any]], actions: tuple[str, ...] | None = None):
    """Yield (story, entity) pairs, optionally limited to some actions."""
    for story in stories:
        for ent in story["extraction"]["entities"]:
            if actions is None or ent["action"] in actions:
                yield story, ent


def entry_status(events: list[dict[str, Any]]) -> str:
    """Where a person or body stands: called to resign, departure announced, suspended or gone."""
    status = "called_to_resign"
    for ev in events:
        if ev["action"] in ("resigned", "dismissed"):
            now = "gone" if ev["stage"] == "completed" else "departure_announced"
        elif ev["action"] == "suspended":
            now = "suspended" if ev["stage"] == "completed" else "departure_announced"
        else:
            continue
        if STATUS_ORDER.index(now) > STATUS_ORDER.index(status):
            status = now
    return status


def resignation_tracker(stories: list[dict[str, Any]], actors: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """One entry per listed actor who was called to resign, or resigned, was dismissed or suspended."""
    events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for story, ent in entity_rows(stories, RESIGNATION_ACTIONS):
        if ent["proposed"] or ent["person_or_body"] not in actors:
            continue
        events[ent["person_or_body"]].append({
            "action": ent["action"], "stage": ent["stage"], "role": ent["role"], "by_whom": ent["by_whom"],
            "response": ent["response"], **source(story)})
    entries = []
    for actor_id, evs in events.items():
        actor = actors[actor_id]
        entries.append({
            "actor_id": actor_id, "name": actor["name"], "actor_status": actor["status"],
            "role": evs[-1]["role"] or actor["role"], "status": entry_status(evs),
            "first_reported": evs[0]["published"], "last_reported": evs[-1]["published"],
            "max_severity": max(e["severity"] for e in evs),
            "called_by": sorted({e["by_whom"] for e in evs
                                 if e["action"] in PRESSURE_ACTIONS and e["by_whom"] != codebook.NOT_ADDRESSED}),
            "events": evs})
    return sorted(entries, key=lambda e: (STATUS_ORDER.index(e["status"]), e["last_reported"]), reverse=True)


def emerging_leaders(stories: list[dict[str, Any]], actors: dict[str, dict[str, str]], now: datetime,
                     days: int) -> list[dict[str, Any]]:
    """Listed persons ranked by stories in the last `days` days, with change and mean stance.

    A person counts once per story, whether named in `actors` or an entity row. Stance is the
    mean over their entity rows in the period. Appointments and `new_actor` stories are listed.
    """
    recent_start, prior_start = now - timedelta(days=days), now - timedelta(days=2 * days)
    recent, prior = Counter(), Counter()
    stances: dict[str, list[int]] = defaultdict(list)
    notes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for story in stories:
        published = datetime.fromisoformat(story["published"])
        ext = story["extraction"]
        ents = [e for e in ext["entities"] if not e["proposed"] and e["person_or_body"] in actors]
        people = {a for a in ext["actors"] if a in actors} | {e["person_or_body"] for e in ents}
        people = {p for p in people if actors[p]["type"] == "person"}
        if published >= recent_start:
            recent.update(people)
            for e in ents:
                if e["person_or_body"] in people:
                    stances[e["person_or_body"]].append(int(e["stance"]))
        elif published >= prior_start:
            prior.update(people)
        if published >= recent_start:
            for p in people:
                appointed = any(e["person_or_body"] == p and e["action"] == "appointed" for e in ents)
                if appointed or "new_actor" in (ext["category"], ext["secondary_category"]):
                    notes[p].append({"kind": "appointed" if appointed else "new_actor", **source(story)})
    entries = []
    for p, n in recent.items():
        actor = actors[p]
        entries.append({
            "actor_id": p, "name": actor["name"], "actor_status": actor["status"], "role": actor["role"],
            "affiliation": actor["affiliation"], "stories_recent": n, "stories_prior": prior[p],
            "change": n - prior[p],
            "mean_stance": round(mean(stances[p]), 2) if stances[p] else None, "stance_rows": len(stances[p]),
            "signals": notes[p]})
    return sorted(entries, key=lambda e: (-e["change"], -e["stories_recent"], e["actor_id"]))


def transition_timeline(stories: list[dict[str, Any]], copies: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    """Transition milestones, one entry per thread, dated by its first story, oldest first."""
    milestones = [s for s in stories
                  if "transition_milestone" in (s["extraction"]["category"], s["extraction"]["secondary_category"])]
    entries = []
    for dev in brief.consolidate(milestones, copies):
        lead = dev.lead
        stages = {e["stage"] for _, e in entity_rows(dev.stories)}
        entries.append({
            "thread_id": dev.key, "date": min(s["published"] for s in dev.stories),
            "last_update": max(s["published"] for s in dev.stories),
            "title": lead["title"], "summary": lead["extraction"]["summary"],
            "why_it_matters": lead["extraction"]["why_it_matters"],
            "announced_only": stages == {"announced"},
            "severity": dev.severity, "confirming_link_ids": dev.confirming_link_ids,
            "outlet_groups": dev.outlet_groups, "sources": [source(s) for s in dev.stories]})
    return sorted(entries, key=lambda e: e["date"])


def pending_review(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Proposed names with their story counts and actions, for a reviewer to confirm or ignore."""
    seen: dict[str, dict[str, Any]] = {}
    for story, ent in entity_rows(stories):
        if not ent["proposed"]:
            continue
        item = seen.setdefault(ent["person_or_body"], {"name": ent["person_or_body"], "roles": Counter(),
                                                      "actions": Counter(), "story_ids": set()})
        item["roles"][ent["role"]] += 1
        item["actions"][ent["action"]] += 1
        item["story_ids"].add(story["story_id"])
    out = [{"name": i["name"], "stories": len(i["story_ids"]), "roles": [r for r, _ in i["roles"].most_common(3)],
            "actions": dict(i["actions"]), "story_ids": sorted(i["story_ids"])} for i in seen.values()]
    return sorted(out, key=lambda i: (-i["stories"], i["name"]))


def build(cfg: dict[str, Any], now: datetime) -> dict[str, Any]:
    """All trackers from the coded stories, links and actor list."""
    coded = coder.read_coded(config.path(cfg, "coded_jsonl"))
    copies = coder.story_copies(coder.read_csv(config.path(cfg, "links_csv")))
    actors = {a["actor_id"]: a for a in coder.read_csv(config.path(cfg, "actors_csv"))}
    stories = relevant(coded)
    days = int(cfg.get("trackers", {}).get("emerging_window_days", 7))
    return {
        "built_at": config.iso(now, cfg), "trackers_version": TRACKERS_VERSION,
        "codebook_versions": sorted({r["codebook_version"] for r in stories}),
        "stories_used": len(stories),
        "resignations": resignation_tracker(stories, actors),
        "emerging_leaders": emerging_leaders(stories, actors, now, days),
        "emerging_window_days": days,
        "transition_timeline": transition_timeline(stories, copies),
        "pending_review": pending_review(stories)}


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Write the trackers file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def run(cfg: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Build and write `data/trackers.json`; return the data."""
    data = build(cfg, now or config.now(cfg))
    write_json(config.path(cfg, "trackers_json"), data)
    log.info("Trackers from %d stories: %d resignation entries, %d emerging, %d milestones, %d names to review",
             data["stories_used"], len(data["resignations"]), len(data["emerging_leaders"]),
             len(data["transition_timeline"]), len(data["pending_review"]))
    return data


def main() -> None:
    """Command-line entry point."""
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    cfg = config.get_config()
    config.setup_logging(SCRIPT, cfg)
    run(cfg)


if __name__ == "__main__":
    main()
