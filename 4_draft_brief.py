"""Stage 1 brief: draft the daily brief and alert focus box from coded stories.

Coded stories in the window are consolidated into developments: stories sharing a
`thread_id` count as one development, so one event under several headlines appears once and
its severity is computed across all its copies. The stronger model writes the brief items
and the focus box lines from the developments and must cite their story ids; it can merge
what threading missed. Severity and rank in the focus box are computed by script from the
cited stories, never by the model, and only alert-category stories qualify. The output is review/brief_YYYY-MM-DD.md with
`status: draft`; a reviewer edits and approves it. An existing brief is never overwritten.

After a pause in briefing, `--window-start` restarts the window at a set time instead of the
end of the last approved brief, and `--catch-up-from` adds a short "Catch-up" section on the
gap (from that time to the window start), written the same way but without a focus box.

Evidence quotes and article text are never passed to the brief or written to the draft.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

import ai_client
import codebook
import config

SCRIPT = "4_draft_brief"
BRIEF_PROMPT_VERSION = "0.2.0"
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MONDAY_LOOKBACK_HOURS = 72

coder = importlib.import_module("3_code_stories")
log = logging.getLogger(SCRIPT)


class BriefItem(BaseModel):
    """One development in the brief."""

    model_config = ConfigDict(extra="forbid")
    headline: str = Field(description="Short factual English headline.")
    paragraph: str = Field(description="One paragraph on what happened, using only the supplied material.")
    why_it_matters: str = Field(description="One sentence for a reader who does not follow Serbian media.")
    story_ids: list[str] = Field(description="The supplied story ids this item rests on.")


class FocusLine(BaseModel):
    """One alert item: the wording is the model's, its severity is computed by script."""

    model_config = ConfigDict(extra="forbid")
    line: str = Field(description="One factual English sentence.")
    story_ids: list[str] = Field(description="The supplied story ids of this alert.")


class Brief(BaseModel):
    """The model's selection of developments, most important first, and the alert lines."""

    model_config = ConfigDict(extra="forbid")
    items: list[BriefItem]
    focus: list[FocusLine]


class CatchUp(BaseModel):
    """The main developments of a period with no brief, most important first."""

    model_config = ConfigDict(extra="forbid")
    items: list[BriefItem]


@dataclass
class Development:
    """One event or running issue: the coded stories of a thread, or a single story."""

    key: str
    stories: list[dict[str, Any]]
    severity: int
    confirming_link_ids: list[str]
    outlet_groups: list[str]
    outlets: list[str] = field(default_factory=list)

    @property
    def lead(self) -> dict[str, Any]:
        """The most widely carried story, used as the development's main text."""
        return max(self.stories, key=lambda s: (s["n_copies"], s["published"]))

    @property
    def categories(self) -> list[str]:
        """Alert categories across the stories, most frequent first."""
        counts: dict[str, int] = {}
        for story in self.stories:
            ext = story["extraction"]
            for cat in (ext["category"], ext["secondary_category"]):
                if cat and cat != "background":
                    counts[cat] = counts.get(cat, 0) + 1
        return sorted(counts, key=lambda c: (-counts[c], c))


def brief_path(cfg: dict[str, Any], day: date) -> Path:
    """Path of the draft for one date."""
    return config.path(cfg, "review_dir") / f"brief_{day.isoformat()}.md"


def front_matter(text: str) -> dict[str, str]:
    """Read the simple `key: value` front matter of a brief."""
    match = re.match(r"---\n(.*?)\n---", text, re.S)
    if not match:
        return {}
    pairs = (line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    return {k.strip(): v.strip() for k, v in pairs}


def window_start(cfg: dict[str, Any], day: date, now: datetime) -> datetime:
    """Start of the window: the end of the last approved brief, else a fallback lookback."""
    review_dir = config.path(cfg, "review_dir")
    earlier = sorted(p for p in review_dir.glob("brief_*.md") if p.stem[6:] < day.isoformat())
    for candidate in reversed(earlier):
        meta = front_matter(candidate.read_text(encoding="utf-8"))
        if meta.get("status") == "approved" and meta.get("window_end"):
            return datetime.fromisoformat(meta["window_end"])
    is_monday = day.weekday() == 0
    hours = MONDAY_LOOKBACK_HOURS if is_monday else int(cfg["collection"]["default_lookback_hours"])
    return now - timedelta(hours=hours)


def stories_in_window(coded: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Relevant coded stories published inside the window."""
    return [r for r in coded if r["extraction"]["relevant"]
            and start <= datetime.fromisoformat(r["published"]) <= end]


def consolidate_one(key: str, members: list[dict[str, Any]],
                    copies: dict[str, list[dict[str, str]]]) -> Development:
    """One development from its stories, with severity computed across all their copies."""
    rows = [c for s in members for c in copies.get(s["story_id"], [])]
    refs = [codebook.ArticleRef(c["link_id"], c["outlet_group"]) for c in rows]
    top_tier = any(s["extraction"]["top_tier"] for s in members)
    severity, confirming = codebook.compute_severity(refs, top_tier)
    return Development(key, members, severity, confirming, sorted({c["outlet_group"] for c in rows}),
                       sorted({c["outlet_id"] for c in rows}))


def consolidate(stories: list[dict[str, Any]], copies: dict[str, list[dict[str, str]]]) -> list[Development]:
    """Group stories by thread and compute each development's severity across all copies."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for story in stories:
        groups.setdefault(story["thread_id"] or story["story_id"], []).append(story)
    developments = [consolidate_one(key, members, copies) for key, members in groups.items()]
    return sorted(developments, key=lambda d: (-d.severity, -len(d.outlets), d.key))


def focus_entries(brief: Brief, by_id: dict[str, dict[str, Any]], copies: dict[str, list[dict[str, str]]],
                  limit: int) -> list[tuple[FocusLine, Development]]:
    """The model's alert lines with script-computed severity, most severe first.

    Lines resting on no alert-category story are dropped.
    """
    entries = []
    for focus in brief.focus:
        stories = [by_id[s] for s in focus.story_ids]
        dev = consolidate_one(focus.story_ids[0], stories, copies)
        if dev.categories:
            entries.append((focus, dev))
    return sorted(entries, key=lambda e: (-e[1].severity, -len(e[1].outlets)))[:limit]


def brief_instructions(min_items: int, max_items: int, focus_max: int) -> str:
    """The system prompt for the brief."""
    return f"""You write a morning brief on political change in Serbia after the 25 October 2026 parliamentary election, for business people and international officials who do not read Serbian media. Answer in English.

Choose {min_items} to {max_items} developments, most important first, from the numbered material. Prefer formal steps, changes of post, legal action and matters of state over commentary. Merge material about the same event into one item.

Rules:
- Use only the supplied material. Add no facts, dates, names, numbers or background of your own.
- One paragraph per item, plain and neutral. Attribute every accusation to whoever made it and give the response if the material has one. An allegation is never stated as fact.
- Where sources are from one outlet group only, say the report comes from that side of the media.
- why_it_matters is one sentence for an outsider, and must follow from the material.
- story_ids must list only ids from the material, at least one per item.

Also write focus: up to {focus_max} alert items since the last brief, from material with an alert category. Each is one factual sentence stating the current position, not a past one (if a vote has since happened, report the outcome). Each distinct event appears once: merge all material on it and cite all its story ids. Do not rank them or give a severity. Attribute allegations in the same way."""


def catch_up_instructions(min_items: int, max_items: int) -> str:
    """The system prompt for the catch-up section on a period with no brief."""
    return f"""You write a short catch-up on political change in Serbia after the 25 October 2026 parliamentary election, covering a period when no brief was published, for business people and international officials who do not read Serbian media. Answer in English.

Choose {min_items} to {max_items} developments of that period that a reader still needs to know about, most important first, from the numbered material. Prefer formal steps, changes of post, legal action and matters of state over commentary. Merge material about the same event into one item. Coverage of the period is incomplete, so do not describe anything as the only or the main event of the period.

Rules:
- Use only the supplied material. Add no facts, dates, names, numbers or background of your own.
- One short paragraph per item, plain and neutral, with the date where the material gives it. Attribute every accusation to whoever made it and give the response if the material has one. An allegation is never stated as fact.
- Where sources are from one outlet group only, say the report comes from that side of the media.
- why_it_matters is one sentence for an outsider, and must follow from the material.
- story_ids must list only ids from the material, at least one per item."""


def development_input(devs: list[Development]) -> str:
    """Numbered material for the model: summaries only, no article text or evidence quotes."""
    blocks = []
    for n, dev in enumerate(devs, 1):
        lines = [f"[{n}] severity {dev.severity}; categories: {', '.join(dev.categories) or 'background'}; "
                 f"outlet groups: {', '.join(dev.outlet_groups)}; {len(dev.outlets)} outlets"]
        for story in sorted(dev.stories, key=lambda s: -s["n_copies"])[:6]:
            ext = story["extraction"]
            lines.append(f"- id {story['story_id']} ({story['published'][:10]}): {ext['summary']} "
                         f"Why it matters: {ext['why_it_matters']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def draft_items(cfg: dict[str, Any], client: Any, devs: list[Development]) -> tuple[Brief, str]:
    """Ask the model for the brief and check its item count and story ids; raise AIError if wrong."""
    wanted_max = int(cfg["brief"]["max_items"])
    wanted_min = min(int(cfg["brief"]["min_items"]), len(devs))
    brief, model = ai_client.parse_structured(
        cfg, client, cfg["coding"]["brief_model_env"],
        brief_instructions(wanted_min, wanted_max, int(cfg["brief"]["focus_max_items"])),
        development_input(devs), Brief,
    )
    known = {s["story_id"] for d in devs for s in d.stories}
    check_items(brief.items, known, wanted_min, wanted_max)
    for focus in brief.focus:
        unknown = set(focus.story_ids) - known
        if unknown or not focus.story_ids:
            raise ai_client.AIError(f"{focus.line!r} cites bad story ids: {sorted(unknown) or 'none given'}")
    return brief, model


def check_items(items: list[BriefItem], known: set[str], wanted_min: int, wanted_max: int) -> None:
    """Raise AIError if the item count is out of range or an item cites no or unknown story ids."""
    if not wanted_min <= len(items) <= wanted_max:
        raise ai_client.AIError(f"{len(items)} items, wanted {wanted_min} to {wanted_max}")
    for entry in items:
        unknown = set(entry.story_ids) - known
        if unknown or not entry.story_ids:
            raise ai_client.AIError(f"{entry.headline!r} cites bad story ids: {sorted(unknown) or 'none given'}")


def draft_catch_up(cfg: dict[str, Any], client: Any, devs: list[Development]) -> list[BriefItem]:
    """Ask the model for the catch-up items and check them; raise AIError if wrong."""
    wanted_max = int(cfg["brief"].get("catch_up_max_items", 5))
    wanted_min = min(int(cfg["brief"].get("catch_up_min_items", 3)), len(devs))
    catch_up, _ = ai_client.parse_structured(
        cfg, client, cfg["coding"]["brief_model_env"], catch_up_instructions(wanted_min, wanted_max),
        development_input(devs), CatchUp,
    )
    check_items(catch_up.items, {s["story_id"] for d in devs for s in d.stories}, wanted_min, wanted_max)
    return catch_up.items


def source_lines(stories: list[dict[str, Any]], limit: int = 4) -> list[str]:
    """Markdown links to the sources of some stories, one per outlet."""
    seen: dict[str, str] = {}
    for story in sorted(stories, key=lambda s: -s["n_copies"]):
        seen.setdefault(story["outlet_id"], story["source_url"])
    return [f"[{outlet}]({url})" for outlet, url in list(seen.items())[:limit]]


def item_lines(items: list[BriefItem], by_id: dict[str, dict[str, Any]]) -> list[str]:
    """Markdown for brief or catch-up items."""
    lines: list[str] = []
    for item in items:
        stories = [by_id[s] for s in item.story_ids]
        lines += [f"### {item.headline}", "", item.paragraph, "",
                  f"**Why it matters:** {item.why_it_matters}", "",
                  f"Sources: {' · '.join(source_lines(stories))}", "",
                  f"Stories: {', '.join(item.story_ids)}", ""]
    return lines


def render(day: date, start: datetime, end: datetime, model: str, focus: list[tuple[FocusLine, Development]],
           brief: Brief, by_id: dict[str, dict[str, Any]], counts: dict[str, int], cfg: dict[str, Any],
           catch_up: tuple[datetime, list[BriefItem]] | None = None) -> str:
    """The draft as Markdown with `status: draft` front matter."""
    lines = ["---", "status: draft", "reviewed_by:", f"date: {day.isoformat()}",
             f"window_start: {config.iso(start, cfg)}", f"window_end: {config.iso(end, cfg)}"]
    if catch_up:
        lines.append(f"catch_up_start: {config.iso(catch_up[0], cfg)}")
    lines += [f"model: {model}", f"brief_prompt_version: {BRIEF_PROMPT_VERSION}",
              f"codebook_version: {codebook.CODEBOOK_VERSION}",
              f"stories_in_window: {counts['stories']}", f"developments: {counts['developments']}", "---", "",
             f"# Brief for {day:%A %-d %B %Y}", "", "## Alert focus box", ""]
    if not focus:
        lines += ["No alert items in this window.", ""]
    for entry, dev in focus:
        lines.append(f"- **Severity {dev.severity}** · {', '.join(dev.categories)} · {entry.line}")
        lines.append(f"  - {len(dev.outlets)} outlets: {', '.join(dev.outlet_groups)}")
        lines.append(f"  - Sources: {' · '.join(source_lines(dev.stories))}")
        lines.append(f"  - Stories: {', '.join(s['story_id'] for s in dev.stories)}")
    lines += ["", "## Daily brief", ""] + item_lines(brief.items, by_id)
    if catch_up:
        lines += ["## Catch-up", ""] + item_lines(catch_up[1], by_id)
    return "\n".join(lines)


def run(cfg: dict[str, Any], client: Any = None, day: date | None = None, force_day: bool = False,
        start: datetime | None = None, catch_up_from: datetime | None = None) -> Path | None:
    """Write the draft for one date; return its path, or None if nothing was written.

    `start` overrides the window start; with `catch_up_from`, stories from then until the
    window start are drafted into a catch-up section.
    """
    now = config.now(cfg)
    day = day or now.date()
    if not force_day and WEEKDAYS[day.weekday()] not in cfg["schedule"]["brief_weekdays"]:
        log.info("No brief on %s", day.isoformat())
        return None
    path = brief_path(cfg, day)
    if path.exists():
        log.info("%s already exists; left as it is", path)
        return None
    start = start or window_start(cfg, day, now)
    coded = coder.read_coded(config.path(cfg, "coded_jsonl"))
    stories = stories_in_window(coded, start, now)
    if not stories:
        log.warning("No relevant coded stories since %s; no draft written", start.isoformat())
        return None
    links = coder.read_csv(config.path(cfg, "links_csv"))
    copies = coder.story_copies(links)
    devs = consolidate(stories, copies)
    material = devs[: int(cfg["brief"]["max_input_developments"])]
    try:
        brief, model = draft_items(cfg, client or ai_client.make_client(), material)
    except ai_client.AIError as exc:
        log.error("Brief not drafted (%s); no file written", exc)
        return None
    by_id = {s["story_id"]: s for s in stories}
    focus = focus_entries(brief, by_id, copies, int(cfg["brief"]["focus_max_items"]))
    catch_up = None
    if catch_up_from:
        gap_stories = [s for s in stories_in_window(coded, catch_up_from, start) if s["story_id"] not in by_id]
        if gap_stories:
            gap_devs = consolidate(gap_stories, copies)[: int(cfg["brief"]["max_input_developments"])]
            try:
                catch_up = (catch_up_from, draft_catch_up(cfg, client or ai_client.make_client(), gap_devs))
            except ai_client.AIError as exc:
                log.error("Catch-up not drafted (%s); no file written", exc)
                return None
            by_id.update({s["story_id"]: s for s in gap_stories})
        else:
            log.warning("No relevant coded stories between %s and %s; no catch-up section",
                        catch_up_from.isoformat(), start.isoformat())
    text = render(day, start, now, model, focus, brief, by_id,
                  {"stories": len(stories), "developments": len(devs)}, cfg, catch_up)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    log.info("Draft %s: %d items, %d focus items from %d stories in %d developments",
             path, len(brief.items), len(focus), len(stories), len(devs))
    return path


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", type=date.fromisoformat, help="brief date (default today); also allows non-brief days")
    parser.add_argument("--window-start", type=datetime.fromisoformat,
                        help="start the window here (ISO 8601 with offset) instead of at the last approved brief")
    parser.add_argument("--catch-up-from", type=datetime.fromisoformat,
                        help="add a catch-up section on stories from this time to the window start")
    args = parser.parse_args()
    cfg = config.get_config()
    config.setup_logging(SCRIPT, cfg)
    run(cfg, day=args.date, force_day=args.date is not None, start=args.window_start, catch_up_from=args.catch_up_from)


if __name__ == "__main__":
    main()
