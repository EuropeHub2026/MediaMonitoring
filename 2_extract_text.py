"""Stage 1 extractor: triage headlines, then fetch and extract text for possibly relevant stories.

Phase 1 (triage): each story in data/links.csv not yet triaged gets one headline screened
by the coding model in batches (codebook.triage_prompt_text). Results go to
data/triage.csv. A batch that fails writes nothing and is retried on the next run.

Phase 2 (text): for each possibly relevant story, the best direct copies (up to
`extract.max_copies_per_story`) are fetched politely and their text extracted with
trafilatura. A story with only Google News copies gets a headline-only row. Results go to
data/articles.csv; failures from transient errors are retried on the next run.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable

import trafilatura

import ai_client
import codebook
import config
from http_client import PoliteSession, domain_of

SCRIPT = "2_extract_text"
log = logging.getLogger(SCRIPT)

TRIAGE_FIELDS = ["story_id", "possibly_relevant", "title", "language", "model",
                 "triage_prompt_version", "codebook_version", "triaged_at"]

JUNK_MARKERS = [
    "enable javascript", "just a moment", "before you continue", "access denied",
    "cookie settings", "are you a robot", "omogućite javascript",
]
SR_WORDS = {"je", "i", "u", "da", "se", "na", "su", "za", "od", "koji", "što", "sto", "kao", "ali", "iz", "nije", "biti"}
EN_WORDS = {"the", "and", "of", "to", "in", "is", "that", "for", "with", "was", "on", "said", "has", "by"}
RETRYABLE = {"", "500", "502", "503", "504"}


@dataclass
class Article:
    """One row of data/articles.csv."""

    link_id: str
    story_id: str
    url: str
    final_url: str
    outlet_id: str
    language: str
    title: str
    text: str
    text_status: str   # full | partial | headline_only | junk | failed
    chars: int
    http_status: str
    fetched_at: str


ARTICLE_FIELDS = [f.name for f in fields(Article)]


# --- CSV helpers ---------------------------------------------------------------------------


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV into dicts, or [] if missing."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def append_csv(path: Path, field_names: list[str], rows: Iterable[dict[str, Any]]) -> int:
    """Append rows to a CSV, writing the header for a new file; return the count."""
    rows = list(rows)
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=field_names)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)


# --- Phase 1: triage ---------------------------------------------------------------------


def story_headlines(links: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Pick one representative headline per story: real titles over slugs, then highest reach."""
    best: dict[str, dict[str, str]] = {}

    def rank(row: dict[str, str]) -> tuple[int, int, int]:
        return (row["title_source"] != "slug", row["text_route"] == "direct", int(row["reach_tier"] or 0))

    for row in links:
        current = best.get(row["story_id"])
        if current is None or rank(row) > rank(current):
            best[row["story_id"]] = row
    return best


def triage_batch(cfg: dict[str, Any], client: Any, batch: list[dict[str, str]]) -> tuple[dict[str, bool], str]:
    """Triage one batch of headline rows; return ({story_id: possibly_relevant}, model)."""
    numbered = {str(i + 1): row for i, row in enumerate(batch)}
    user_input = "\n".join(f"{i}\t{row['title']}" for i, row in numbered.items())
    result, model = ai_client.parse_structured(
        cfg, client, cfg["triage"]["model_env"], codebook.triage_prompt_text(), user_input, codebook.TriageBatch
    )
    verdicts = {item.id: item.possibly_relevant for item in result.items}
    if set(verdicts) != set(numbered):
        raise ai_client.AIError(f"triage returned ids {sorted(verdicts)} for {len(numbered)} headlines")
    return {numbered[i]["story_id"]: v for i, v in verdicts.items()}, model


def run_triage(cfg: dict[str, Any], links: list[dict[str, str]], client: Any) -> int:
    """Triage every story not yet in data/triage.csv; return how many were written."""
    triage_path = config.path(cfg, "triage_csv")
    done = {row["story_id"] for row in read_csv(triage_path)}
    pending = [row for sid, row in story_headlines(links).items() if sid not in done]
    size = int(cfg["triage"]["batch_size"])
    written = 0
    for start in range(0, len(pending), size):
        batch = pending[start:start + size]
        try:
            verdicts, model = triage_batch(cfg, client, batch)
        except ai_client.SpendCapHit:
            log.error("Spend cap hit; triage stopped after %d stories", written)
            break
        except ai_client.AIError as exc:
            log.warning("Triage batch %d failed (%s); retried next run", start // size + 1, exc)
            continue
        stamp = config.iso(config.now(cfg), cfg)
        written += append_csv(triage_path, TRIAGE_FIELDS, (
            {"story_id": row["story_id"], "possibly_relevant": "yes" if verdicts[row["story_id"]] else "no",
             "title": row["title"], "language": row["language"], "model": model,
             "triage_prompt_version": codebook.TRIAGE_PROMPT_VERSION,
             "codebook_version": codebook.CODEBOOK_VERSION, "triaged_at": stamp}
            for row in batch
        ))
    log.info("Triage: %d stories pending, %d written", len(pending), written)
    return written


# --- Phase 2: text -------------------------------------------------------------------------


def detect_language(text: str, default: str) -> str:
    """Guess 'sr' or 'en' from script and common words; fall back to `default`."""
    sample = text[:3000]
    if len(re.findall(r"[Ѐ-ӿ]", sample)) > 50:
        return "sr"
    words = re.findall(r"[a-zčćšžđ]+", sample.lower())
    sr, en = sum(w in SR_WORDS for w in words), sum(w in EN_WORDS for w in words)
    if max(sr, en) < 5:
        return default
    return "sr" if sr > en else "en"


def is_junk(text: str) -> bool:
    """True if the extracted text looks like a consent page, bot wall or error page."""
    head = text[:600].lower()
    return any(marker in head for marker in JUNK_MARKERS)


def text_status(text: str, paywall: str, min_chars: int) -> str:
    """Classify extracted text as full, partial or junk."""
    if is_junk(text):
        return "junk"
    if paywall == "yes" or len(text) < min_chars:
        return "partial"
    return "full"


def extract(raw: bytes, url: str) -> tuple[str, str]:
    """Return (title, text) extracted from raw page bytes with trafilatura (it detects the encoding)."""
    tree = trafilatura.load_html(raw)
    if tree is None:
        return "", ""
    text = trafilatura.extract(tree, url=url, include_comments=False, include_tables=False,
                               favor_recall=True, output_format="txt") or ""
    meta = trafilatura.extract_metadata(tree, default_url=url)
    return (meta.title or "") if meta else "", text.strip()


def choose_copies(rows: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    """Pick the best direct copies of a story: highest reach first, then non-slug titles."""
    direct = [r for r in rows if r["text_route"] == "direct"]
    direct.sort(key=lambda r: (-int(r["reach_tier"] or 0), r["title_source"] == "slug", r["published"]))
    return direct[:limit]


def interleave_by_domain(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Order rows round-robin across domains so per-domain waits overlap."""
    queues: dict[str, deque] = defaultdict(deque)
    for row in rows:
        queues[domain_of(row["url"])].append(row)
    ordered = []
    while queues:
        for domain in list(queues):
            ordered.append(queues[domain].popleft())
            if not queues[domain]:
                del queues[domain]
    return ordered


def fetch_article(session: PoliteSession, row: dict[str, str], outlet: dict[str, str],
                  cfg: dict[str, Any]) -> Article:
    """Fetch one link and extract its text; never raises."""
    stamp = config.iso(config.now(cfg), cfg)
    base = dict(link_id=row["link_id"], story_id=row["story_id"], url=row["url"], outlet_id=row["outlet_id"],
                fetched_at=stamp)
    response = session.get(row["url"])
    if response is None or response.status_code != 200:
        status = str(response.status_code) if response is not None else ""
        return Article(**base, final_url="", language=row["language"], title=row["title"], text="",
                       text_status="failed", chars=0, http_status=status)
    title, text = extract(response.content[: int(cfg["extract"]["max_html_bytes"])], row["url"])
    status = text_status(text, outlet.get("paywall", "no"), int(cfg["extract"]["min_text_chars"])) if text else "junk"
    return Article(**base, final_url=str(getattr(response, "url", "") or row["url"]),
                   language=detect_language(text, row["language"]), title=title or row["title"],
                   text=text if status != "junk" else "", text_status=status,
                   chars=len(text) if status != "junk" else 0, http_status="200")


def headline_only(row: dict[str, str], cfg: dict[str, Any]) -> Article:
    """An article row for a story that has only Google News copies."""
    return Article(link_id=row["link_id"], story_id=row["story_id"], url=row["url"], final_url="",
                   outlet_id=row["outlet_id"], language=row["language"], title=row["title"], text="",
                   text_status="headline_only", chars=0, http_status="",
                   fetched_at=config.iso(config.now(cfg), cfg))


def done_link_ids(articles: list[dict[str, str]]) -> set[str]:
    """Links that need no further attempt: latest row is not a retryable failure."""
    latest: dict[str, dict[str, str]] = {}
    for row in articles:
        latest[row["link_id"]] = row
    return {lid for lid, r in latest.items() if not (r["text_status"] == "failed" and r["http_status"] in RETRYABLE)}


def run_text(cfg: dict[str, Any], links: list[dict[str, str]], story_ids: set[str],
             session: PoliteSession, limit: int | None = None) -> int:
    """Extract text for the chosen stories; return how many article rows were written."""
    outlets = {o["outlet_id"]: o for o in read_csv(config.path(cfg, "outlets_csv"))}
    articles_path = config.path(cfg, "articles_csv")
    done = done_link_ids(read_csv(articles_path))
    done_stories = {r["story_id"] for r in read_csv(articles_path)}
    by_story: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in links:
        if row["story_id"] in story_ids:
            by_story[row["story_id"]].append(row)

    to_fetch, headline_rows = [], []
    max_copies = int(cfg["extract"]["max_copies_per_story"])
    for sid, rows in by_story.items():
        copies = choose_copies(rows, max_copies)
        if copies:
            to_fetch += [r for r in copies if r["link_id"] not in done]
        elif sid not in done_stories:
            headline_rows.append(headline_only(rows[0], cfg))
    to_fetch = interleave_by_domain(to_fetch)[:limit] if limit else interleave_by_domain(to_fetch)

    written = append_csv(articles_path, ARTICLE_FIELDS, (asdict(a) for a in headline_rows))
    counts: dict[str, int] = defaultdict(int)
    for i, row in enumerate(to_fetch, 1):
        article = fetch_article(session, row, outlets.get(row["outlet_id"], {}), cfg)
        counts[article.text_status] += 1
        written += append_csv(articles_path, ARTICLE_FIELDS, [asdict(article)])
        if i % 50 == 0:
            log.info("Fetched %d of %d", i, len(to_fetch))
    log.info("Text: %d fetched (%s), %d headline-only stories; blocked domains: %s",
             len(to_fetch), ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none",
             len(headline_rows), ", ".join(sorted(session.blocked)) or "none")
    return written


# --- Main ----------------------------------------------------------------------------------


def run(cfg: dict[str, Any], client: Any = None, session: PoliteSession | None = None,
        skip_triage: bool = False, limit: int | None = None) -> int:
    """Triage new stories, then extract text for possibly relevant ones."""
    links = read_csv(config.path(cfg, "links_csv"))
    if not links:
        log.warning("No links yet; run 1_collect_press.py first")
        return 0
    if skip_triage:
        story_ids = {row["story_id"] for row in links}
        log.warning("Triage skipped: extracting text for all %d stories", len(story_ids))
    else:
        run_triage(cfg, links, client or ai_client.make_client())
        story_ids = {r["story_id"] for r in read_csv(config.path(cfg, "triage_csv")) if r["possibly_relevant"] == "yes"}
    return run_text(cfg, links, story_ids, session or PoliteSession(cfg), limit=limit)


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-triage", action="store_true", help="extract all stories without the AI triage (testing only)")
    parser.add_argument("--limit", type=int, help="fetch at most this many pages (testing)")
    args = parser.parse_args()
    cfg = config.get_config()
    config.setup_logging(SCRIPT, cfg)
    run(cfg, skip_triage=args.skip_triage, limit=args.limit)


if __name__ == "__main__":
    main()
