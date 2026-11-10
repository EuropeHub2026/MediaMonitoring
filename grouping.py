"""Group coded stories into events and threads, and compute severity per event.

`story_id` groups copies with matching headlines at collection, so one event reported under
different headlines ends up as several stories. This module joins them:

- an **event** (`event_id`) is the set of relevant stories about one happening: published
  within `event_window_days` of the event's first story, sharing a category with it, and with
  English summaries similar to the event's stories on average (IDF-weighted word overlap; two
  summaries sharing fewer than `event_min_shared_words` content words count as dissimilar).
  Averaging over the event's stories, rather than linking to any one of them, stops chains of
  loosely related stories from merging into one event;
- a **thread** (`thread_id`) is a running issue: a chain of events sharing a category and
  named people or bodies (2 points per shared entity, 1 per shared actor, broad actors
  ignored) within `thread_window_days`;
- **severity** is computed by `codebook.compute_severity` across all copies of all stories in
  the event, so one event has one severity.

Everything is recomputed from all coded rows on every run, in publication order, so the result
does not depend on the order in which stories were coded. No AI calls are made.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import codebook

# Words the coding model uses to describe what an article does or lacks ("The headline
# provides no further details"). They say nothing about which event a story is.
BOILERPLATE = frozenset("""
the and for with from that this its his her their they them was were are has have had been
will would said says say also but not into after before about over while which who than
headline headlines article articles text details detail further provides provide provided
available specify specifies specified identify identifies according reports report reported
says does did gives give given offers mentions mention refers refer describes describe
""".split())

TOKEN = re.compile(r"\d+(?:[.,]\d+)*%?|[^\W\d_]{3,}")


def summary_tokens(text: str) -> set[str]:
    """Content words and numbers of an English summary, lower-cased, boilerplate removed."""
    words = TOKEN.findall(text.lower().replace("’", "'"))
    return {w for w in words if w not in BOILERPLATE}


def categories(row: dict[str, Any]) -> set[str]:
    """The story's category and secondary category."""
    ext = row["extraction"]
    return {ext["category"]} | ({ext["secondary_category"]} if ext.get("secondary_category") else set())


class Similarity:
    """IDF-weighted cosine similarity between story summaries."""

    def __init__(self, rows: list[dict[str, Any]], min_shared: int = 1) -> None:
        self.min_shared = min_shared
        self.tokens = {r["story_id"]: summary_tokens(r["extraction"].get("summary", "")) for r in rows}
        df = Counter(t for toks in self.tokens.values() for t in toks)
        n = max(len(rows), 1)
        self.idf = {t: math.log(n / c) for t, c in df.items()}
        self.norm = {sid: math.sqrt(sum(self.idf[t] ** 2 for t in toks)) for sid, toks in self.tokens.items()}

    def __call__(self, a: str, b: str) -> float:
        """Similarity of two stories by id, 0 to 1."""
        if not self.norm.get(a) or not self.norm.get(b):
            return 0.0
        shared = self.tokens[a] & self.tokens[b]
        if len(shared) < self.min_shared:
            return 0.0
        return sum(self.idf[t] ** 2 for t in shared) / (self.norm[a] * self.norm[b])


@dataclass
class Event:
    """Stories about one happening, earliest first."""

    stories: list[dict[str, Any]] = field(default_factory=list)

    @property
    def event_id(self) -> str:
        return f"e-{self.stories[0]['story_id']}"

    @property
    def start(self) -> datetime:
        return published(self.stories[0])

    @property
    def end(self) -> datetime:
        return max(published(s) for s in self.stories)


def published(row: dict[str, Any]) -> datetime:
    """The story's publication time."""
    return datetime.fromisoformat(row["published"])


def build_events(rows: list[dict[str, Any]], cfg: dict[str, Any]) -> list[Event]:
    """Group relevant stories into events, oldest event first."""
    coding = cfg["coding"]
    window = timedelta(days=float(coding.get("event_window_days", 2)))
    threshold = float(coding.get("event_min_similarity", 0.2))
    sim = Similarity(rows, int(coding.get("event_min_shared_words", 3)))
    events: list[Event] = []
    for row in sorted(rows, key=lambda r: (published(r), r["story_id"])):
        when, cats = published(row), categories(row)
        best, best_score = None, threshold
        for event in reversed(events):
            if when - event.start > window:
                break
            if not cats & categories(event.stories[0]):
                continue
            score = sum(sim(row["story_id"], s["story_id"]) for s in event.stories) / len(event.stories)
            if score >= best_score:
                best, best_score = event, score
        if best is None:
            events.append(Event([row]))
        else:
            best.stories.append(row)
    return events


def event_keys(event: Event, ignore: set[str]) -> tuple[set[str], set[str], set[str]]:
    """(categories, confirmed entity ids, actor ids) across an event's stories."""
    cats: set[str] = set()
    entities: set[str] = set()
    actors: set[str] = set()
    for row in event.stories:
        ext = row["extraction"]
        cats |= categories(row)
        entities |= {e["person_or_body"] for e in ext["entities"] if not e.get("proposed")}
        actors |= set(ext["actors"])
    return cats, entities - ignore, actors - ignore


def assign_threads(events: list[Event], cfg: dict[str, Any]) -> dict[str, str]:
    """Map event_id to thread_id: each event joins the best-matching earlier thread or starts one."""
    coding = cfg["coding"]
    ignore = set(coding.get("thread_ignore_actors", []))
    window = timedelta(days=int(coding.get("thread_window_days", 10)))
    min_score = int(coding.get("thread_min_score", 2))
    keys = {e.event_id: event_keys(e, ignore) for e in events}
    threads: dict[str, str] = {}
    for i, event in enumerate(events):
        cats, entities, actors = keys[event.event_id]
        best_score, best_thread = 0, ""
        for other in events[:i]:
            if event.start - other.end > window:
                continue
            o_cats, o_entities, o_actors = keys[other.event_id]
            if not cats & o_cats:
                continue
            score = 2 * len(entities & o_entities) + len(actors & o_actors)
            if score > best_score:
                best_score, best_thread = score, threads[other.event_id]
        threads[event.event_id] = best_thread if best_score >= min_score else f"t-{event.stories[0]['story_id']}"
    return threads


def event_severity(event: Event, copies: dict[str, list[dict[str, str]]]) -> tuple[int, list[str]]:
    """Severity and confirming link ids across all copies of the event's stories."""
    refs = [codebook.ArticleRef(c["link_id"], c["outlet_group"])
            for s in event.stories for c in copies.get(s["story_id"], [])]
    top_tier = any(s["extraction"]["top_tier"] for s in event.stories)
    return codebook.compute_severity(refs, top_tier)


def regroup(coded: list[dict[str, Any]], copies: dict[str, list[dict[str, str]]], cfg: dict[str, Any]) -> int:
    """Set event_id, thread_id, severity and confirming_link_ids on every row; return rows changed.

    Rows that are not relevant get empty ids and no severity. Rows are changed in place.
    """
    relevant = [r for r in coded if r["extraction"]["relevant"]]
    events = build_events(relevant, cfg)
    threads = assign_threads(events, cfg)
    wanted: dict[str, dict[str, Any]] = {}
    for event in events:
        severity, confirming = event_severity(event, copies)
        for row in event.stories:
            wanted[row["story_id"]] = {"event_id": event.event_id, "thread_id": threads[event.event_id],
                                       "severity": severity, "confirming_link_ids": confirming}
    changed = 0
    for row in coded:
        new = wanted.get(row["story_id"],
                         {"event_id": "", "thread_id": "", "severity": None, "confirming_link_ids": []})
        if any(row.get(k) != v for k, v in new.items()):
            row.update(new)
            changed += 1
    return changed
