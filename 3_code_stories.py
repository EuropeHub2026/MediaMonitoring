"""Stage 1 coder: code each possibly relevant story once against the codebook.

For each story with extracted text (or a headline-only row) that passed triage and is not
yet in data/coded.jsonl, the fullest copy is sent to the coding model with
codebook.prompt_text() and parsed into codebook.Extraction. The script then:
- corrects actor ids against actors.csv (unknown ids dropped, `proposed` set from the list)
  and records what it corrected in `actor_warnings`;
- computes severity from all copies of the story (codebook.compute_severity);
- assigns a thread_id linking it to a recent story about the same issue.

Each row is written as soon as it is coded; a failed story writes nothing and is retried
on the next run. Every run also refreshes severity for coded stories that gained copies.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import ai_client
import codebook
import config

SCRIPT = "3_code_stories"
log = logging.getLogger(SCRIPT)

STATUS_RANK = {"full": 3, "partial": 2, "headline_only": 1}


# --- Reading inputs ------------------------------------------------------------------------


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV into dicts, or [] if missing."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def read_coded(path: Path) -> list[dict[str, Any]]:
    """Read data/coded.jsonl, or [] if missing."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def latest_articles(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Keep the latest article row per link (later attempts supersede failures)."""
    latest: dict[str, dict[str, str]] = {}
    for row in rows:
        latest[row["link_id"]] = row
    return latest


def best_copy(articles: list[dict[str, str]]) -> dict[str, str] | None:
    """Pick the copy to code: full text over partial over headline-only, then longest."""
    usable = [a for a in articles if a["text_status"] in STATUS_RANK]
    if not usable:
        return None
    return max(usable, key=lambda a: (STATUS_RANK[a["text_status"]], int(a["chars"] or 0)))


# --- Story facts from all copies -----------------------------------------------------------


def story_copies(links: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Group link rows by story_id."""
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in links:
        grouped[row["story_id"]].append(row)
    return grouped


def copy_facts(copies: list[dict[str, str]], top_tier: bool, relevant: bool) -> dict[str, Any]:
    """Outlets, groups, copy count and severity for one story's copies."""
    refs = [codebook.ArticleRef(c["link_id"], c["outlet_group"]) for c in copies]
    severity, confirming = codebook.compute_severity(refs, top_tier) if relevant else (None, [])
    return {
        "n_copies": len(copies),
        "outlets": sorted({c["outlet_id"] for c in copies}),
        "outlet_groups": sorted({c["outlet_group"] for c in copies}),
        "severity": severity,
        "confirming_link_ids": confirming,
    }


# --- Actor corrections ---------------------------------------------------------------------


def correct_actors(extraction: codebook.Extraction, known_ids: set[str]) -> list[str]:
    """Drop unknown actor ids and set `proposed` from the list; return what was changed."""
    warnings = codebook.check_actor_ids(extraction, known_ids)
    extraction.actors = [a for a in extraction.actors if a in known_ids]
    for row in extraction.entities:
        row.proposed = row.person_or_body not in known_ids
    return warnings


# --- Threads -------------------------------------------------------------------------------


def thread_keys(row: dict[str, Any], ignore: set[str]) -> tuple[set[str], set[str], set[str]]:
    """Return (categories, entity ids, actor ids) used to match a story to a thread."""
    ext = row["extraction"]
    cats = {ext["category"]} | ({ext["secondary_category"]} if ext.get("secondary_category") else set())
    entities = {e["person_or_body"] for e in ext["entities"] if not e["proposed"]} - ignore
    actors = set(ext["actors"]) - ignore
    return cats, entities, actors


def assign_thread(row: dict[str, Any], coded: list[dict[str, Any]], cfg: dict[str, Any]) -> str:
    """Return the thread_id of the best-matching recent story, or a new thread id.

    A candidate must share a category and be within the thread window. Score: 2 per shared
    entity, 1 per shared actor (broad actors ignored). Reviewers can re-thread by hand.
    """
    coding = cfg["coding"]
    ignore = set(coding.get("thread_ignore_actors", []))
    window = timedelta(days=int(coding.get("thread_window_days", 10)))
    when = datetime.fromisoformat(row["published"])
    cats, entities, actors = thread_keys(row, ignore)
    best_score, best_thread = 0, ""
    for other in coded:
        if not other["extraction"]["relevant"] or other["story_id"] == row["story_id"]:
            continue
        if abs(when - datetime.fromisoformat(other["published"])) > window:
            continue
        o_cats, o_entities, o_actors = thread_keys(other, ignore)
        if not cats & o_cats:
            continue
        score = 2 * len(entities & o_entities) + len(actors & o_actors)
        if score > best_score:
            best_score, best_thread = score, other["thread_id"]
    if best_score >= int(coding.get("thread_min_score", 2)):
        return best_thread
    return f"t-{row['story_id']}"


# --- Coding one story ----------------------------------------------------------------------


def story_input(article: dict[str, str], outlet: dict[str, str], max_chars: int) -> str:
    """Build the user message for one story."""
    text = article["text"][:max_chars] if article["text"] else "(no text available; code from the headline only)"
    return (
        f"Outlet: {outlet.get('name', article['outlet_id'])} ({outlet.get('outlet_group', 'unknown group')})\n"
        f"Language: {article['language']}\n"
        f"Text status: {article['text_status']}\n"
        f"Headline: {article['title']}\n\n{text}"
    )


def code_story(cfg: dict[str, Any], client: Any, instructions: str, article: dict[str, str],
               link: dict[str, str], outlet: dict[str, str], copies: list[dict[str, str]],
               known_ids: set[str], coded: list[dict[str, Any]]) -> dict[str, Any]:
    """Code one story and return the full row; raises ai_client.AIError on failure."""
    extraction, model = ai_client.parse_structured(
        cfg, client, cfg["coding"]["model_env"], instructions,
        story_input(article, outlet, int(cfg["coding"]["max_text_chars"])), codebook.Extraction,
    )
    warnings = correct_actors(extraction, known_ids)
    row: dict[str, Any] = {
        "story_id": article["story_id"],
        "thread_id": "",
        "coded_at": config.iso(config.now(cfg), cfg),
        "model": model,
        "prompt_version": codebook.PROMPT_VERSION,
        "codebook_version": codebook.CODEBOOK_VERSION,
        "source_link_id": article["link_id"],
        "source_url": link.get("url", article["url"]),
        "outlet_id": article["outlet_id"],
        "language": article["language"],
        "title": article["title"],
        "published": link.get("published") or article["fetched_at"],
        "text_status": article["text_status"],
        **copy_facts(copies, extraction.top_tier, extraction.relevant),
        "actor_warnings": warnings,
        "extraction": extraction.model_dump(),
    }
    row["thread_id"] = assign_thread(row, coded, cfg) if extraction.relevant else ""
    return row


# --- Storage -------------------------------------------------------------------------------


def append_row(path: Path, row: dict[str, Any]) -> None:
    """Append one coded row to data/coded.jsonl and flush it to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def rewrite_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Replace data/coded.jsonl atomically."""
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    tmp.replace(path)


def refresh_severity(path: Path, coded: list[dict[str, Any]], copies: dict[str, list[dict[str, str]]]) -> int:
    """Recompute copy facts and severity for coded stories that gained copies; return changes."""
    changed = 0
    for row in coded:
        story_rows = copies.get(row["story_id"])
        if not story_rows or len(story_rows) == row["n_copies"]:
            continue
        ext = row["extraction"]
        row.update(copy_facts(story_rows, ext["top_tier"], ext["relevant"]))
        changed += 1
    if changed:
        rewrite_rows(path, coded)
    return changed


def write_check_file(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write a readable summary of this run's coding for a reviewer to eyeball (stays in data/)."""
    lines = ["# Coding check", "", f"{len(rows)} stories coded in this run.", ""]
    for r in rows:
        ext = r["extraction"]
        flag = "" if ext["relevant"] else " — NOT RELEVANT"
        lines += [
            f"## {r['title']}{flag}",
            f"- story `{r['story_id']}`, thread `{r['thread_id']}`, {r['outlet_id']}, {r['text_status']}, "
            f"{r['n_copies']} copies from {', '.join(r['outlet_groups'])}",
            f"- category **{ext['category']}**" + (f" + {ext['secondary_category']}" if ext["secondary_category"] else "")
            + f", top tier {ext['top_tier']}, severity {r['severity']}, {ext['article_type']}",
            f"- actors: {', '.join(ext['actors']) or 'none'}",
            f"- summary: {ext['summary']}",
            f"- why it matters: {ext['why_it_matters']}",
            f"- quote: {ext['evidence_quote']}",
        ]
        for e in ext["entities"]:
            lines.append(f"  - {e['person_or_body']}{' (proposed)' if e['proposed'] else ''}, {e['role']}: "
                         f"{e['action']} ({e.get('stage', 'not_addressed')}) by {e['by_whom']}; response: {e['response']}; stance {e['stance']}")
        if r["actor_warnings"]:
            lines.append(f"- actor corrections: {'; '.join(r['actor_warnings'])}")
        lines += [f"- {r['source_url']}", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


# --- Main ----------------------------------------------------------------------------------


def pending_stories(cfg: dict[str, Any], links: list[dict[str, str]], coded_ids: set[str]) -> list[str]:
    """Story ids to code: triaged possibly relevant (if triage ran), with articles, not coded.

    Ordered by number of distinct outlets, then most recent, so a spend cap or the per-run
    limit drops the least-reported stories.
    """
    triage = read_csv(config.path(cfg, "triage_csv"))
    allowed = {t["story_id"] for t in triage if t["possibly_relevant"] == "yes"} if triage else None
    articles = latest_articles(read_csv(config.path(cfg, "articles_csv")))
    with_articles = {a["story_id"] for a in articles.values() if a["text_status"] in STATUS_RANK}
    copies = story_copies(links)
    ids = [s for s in with_articles if s not in coded_ids and (allowed is None or s in allowed)]
    return sorted(ids, key=lambda s: (len({c["outlet_id"] for c in copies.get(s, [])}),
                                      max((c["published"] for c in copies.get(s, [])), default="")), reverse=True)


def run(cfg: dict[str, Any], client: Any = None, limit: int | None = None) -> int:
    """Code pending stories and refresh severity; return how many stories were coded."""
    links = read_csv(config.path(cfg, "links_csv"))
    links_by_id = {l["link_id"]: l for l in links}
    copies = story_copies(links)
    coded_path = config.path(cfg, "coded_jsonl")
    coded = read_coded(coded_path)
    refreshed = refresh_severity(coded_path, coded, copies)

    pending = pending_stories(cfg, links, {r["story_id"] for r in coded})
    cap = min(limit or 10**9, int(cfg["coding"]["max_stories_per_run"]))
    if len(pending) > cap:
        log.warning("%d stories pending; coding the %d most reported this run", len(pending), cap)
    pending = pending[:cap]

    actors = codebook.load_actors(config.path(cfg, "actors_csv"))
    known_ids = {a["actor_id"] for a in actors}
    instructions = codebook.prompt_text(actors)
    outlets = {o["outlet_id"]: o for o in read_csv(config.path(cfg, "outlets_csv"))}
    articles = latest_articles(read_csv(config.path(cfg, "articles_csv")))
    by_story: dict[str, list[dict[str, str]]] = defaultdict(list)
    for a in articles.values():
        by_story[a["story_id"]].append(a)

    client = client or (ai_client.make_client() if pending else None)
    new_rows, failed = [], 0
    for story_id in pending:
        article = best_copy(by_story[story_id])
        link = links_by_id.get(article["link_id"], {})
        try:
            row = code_story(cfg, client, instructions, article, link, outlets.get(article["outlet_id"], {}),
                             copies.get(story_id, [link] if link else []), known_ids, coded)
        except ai_client.SpendCapHit:
            log.error("Spend cap hit; coding stopped after %d stories", len(new_rows))
            break
        except ai_client.AIError as exc:
            failed += 1
            log.warning("Story %s not coded (%s); retried next run", story_id, exc)
            continue
        append_row(coded_path, row)
        coded.append(row)
        new_rows.append(row)

    if new_rows:
        write_check_file(config.path(cfg, "coding_check_md"), new_rows)
    relevant = sum(r["extraction"]["relevant"] for r in new_rows)
    log.info("Coded %d stories (%d relevant), %d failed, %d severities refreshed",
             len(new_rows), relevant, failed, refreshed)
    return len(new_rows)


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="code at most this many stories")
    args = parser.parse_args()
    cfg = config.get_config()
    config.setup_logging(SCRIPT, cfg)
    run(cfg, limit=args.limit)


if __name__ == "__main__":
    main()
