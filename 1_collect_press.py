"""Stage 1 collector: find recent press links and group copies of one story.

Sources, in order of preference for each outlet in outlets.csv:
1. the outlet's RSS feed;
2. the outlet's news sitemap;
3. a Google News `site:` search, only when the outlet has neither.
Google News keyword searches (config.yaml) add discovery across all outlets.

Google News links cannot be decoded to the original URL here (Google shows an EU consent
page and the project never works around consent walls). A Google item is therefore matched
by title to a direct item from the same outlet; if there is no match it is kept as a
headline-only row linking to Google News.

Writes data/links.csv. Re-running skips links already collected.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import feedparser
from rapidfuzz import fuzz

import config
from http_client import PoliteSession, domain_of

SCRIPT = "1_collect_press"
log = logging.getLogger(SCRIPT)

GNEWS_HOST = "news.google.com"
SITEMAP_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}
TRACKING_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|ocid$|oc$|cmp$|ref$)")

CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "đ", "е": "e", "ж": "ž",
    "з": "z", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n",
    "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "ћ": "ć", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "č", "џ": "dž", "ш": "š",
}


@dataclass
class Link:
    """One collected copy of a story (a row of data/links.csv)."""

    link_id: str
    story_id: str
    url: str
    outlet_id: str
    outlet_group: str
    reach_tier: str
    language: str
    title: str
    title_source: str   # feed | sitemap | slug | gnews
    published: str
    collected: str
    via: str            # rss | sitemap | gnews_site | gnews_query
    text_route: str     # direct | headline_only
    source_domain: str


LINK_FIELDS = [f.name for f in fields(Link)]


# --- Text helpers --------------------------------------------------------------------------


def to_latin(text: str) -> str:
    """Transliterate Serbian Cyrillic to Latin, keeping other characters."""
    out = []
    for ch in text:
        low = ch.lower()
        if low in CYRILLIC_TO_LATIN:
            lat = CYRILLIC_TO_LATIN[low]
            out.append(lat.capitalize() if ch != low else lat)
        else:
            out.append(ch)
    return "".join(out)


def match_key(title: str) -> str:
    """Return a comparison key: Latin script, no diacritics, lower case, words only."""
    text = unicodedata.normalize("NFKD", to_latin(title).replace("đ", "dj").replace("Đ", "Dj"))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"\w+", text))


def normalize_url(url: str) -> str:
    """Drop fragments and tracking parameters so copies of one URL compare equal."""
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not TRACKING_PARAMS.match(k.lower())])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def link_id_for(url: str) -> str:
    """Stable id for a link, from its normalised URL."""
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:12]


def title_from_slug(url: str) -> str:
    """Make a rough title from the last meaningful URL path segment."""
    segments = [s for s in urlsplit(url).path.split("/") if s and not s.isdigit()]
    slug = re.sub(r"\.\w+$", "", segments[-1]) if segments else ""
    return slug.replace("-", " ").replace("_", " ").strip().capitalize()


def strip_gnews_suffix(title: str, source_title: str) -> str:
    """Remove the ' - Outlet' suffix Google News appends to titles."""
    if source_title and title.endswith(f" - {source_title}"):
        return title[: -len(source_title) - 3].strip()
    return re.sub(r"\s+-\s+[^-]{1,40}$", "", title).strip()


def mentions_serbia(text: str, keywords: Iterable[str]) -> bool:
    """True if any Serbia keyword appears in `text` (case- and script-insensitive)."""
    key = match_key(text)
    return any(match_key(k) in key for k in keywords)


# --- Parsing -------------------------------------------------------------------------------


def parse_when(value: Any) -> datetime | None:
    """Parse an RSS struct_time, RFC 822 or ISO 8601 date into an aware UTC datetime."""
    if not value:
        return None
    try:
        if hasattr(value, "tm_year"):
            return datetime(*value[:6], tzinfo=timezone.utc)
        text = str(value).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            dt = parsedate_to_datetime(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


@dataclass
class Item:
    """A raw item from any source, before crediting and grouping."""

    url: str
    title: str
    title_source: str
    published: datetime
    summary: str = ""
    source_href: str = ""
    source_title: str = ""


def parse_feed(content: bytes) -> list[Item]:
    """Parse RSS or Atom bytes into items; undated entries are dropped."""
    parsed = feedparser.parse(content)
    items = []
    for e in parsed.entries:
        when = parse_when(e.get("published_parsed") or e.get("updated_parsed"))
        url = e.get("link", "")
        if not when or not url:
            continue
        source = e.get("source") or {}
        items.append(Item(
            url=url,
            title=(e.get("title") or "").strip(),
            title_source="feed",
            published=when,
            summary=re.sub(r"<[^>]+>", " ", e.get("summary", "")),
            source_href=source.get("href", ""),
            source_title=source.get("title", ""),
        ))
    return items


def parse_news_sitemap(content: bytes) -> list[Item]:
    """Parse a (Google News) sitemap into items, using news:title or the URL slug."""
    root = ET.fromstring(content)
    items = []
    for url_el in root.findall("sm:url", SITEMAP_NS):
        loc = (url_el.findtext("sm:loc", "", SITEMAP_NS) or "").strip()
        title = (url_el.findtext("news:news/news:title", "", SITEMAP_NS) or "").strip()
        when = parse_when(
            url_el.findtext("news:news/news:publication_date", "", SITEMAP_NS)
            or url_el.findtext("sm:lastmod", "", SITEMAP_NS)
        )
        if not loc or not when:
            continue
        items.append(Item(
            url=loc,
            title=title or title_from_slug(loc),
            title_source="sitemap" if title else "slug",
            published=when,
        ))
    return items


# --- Sources -------------------------------------------------------------------------------


def gnews_search_url(query: str, edition: dict[str, str]) -> str:
    """Build a Google News RSS search URL for one edition."""
    return (
        f"https://{GNEWS_HOST}/rss/search?q={quote_plus(query)}"
        f"&hl={edition['hl']}&gl={edition['gl']}&ceid={edition['ceid']}"
    )


def fetch_items(session: PoliteSession, url: str, kind: str) -> list[Item]:
    """Fetch and parse one feed or sitemap; return [] on any failure."""
    response = session.get(url)
    if response is None or response.status_code != 200:
        status = response.status_code if response is not None else "no response"
        log.warning("Could not fetch %s (%s)", url, status)
        return []
    try:
        return parse_news_sitemap(response.content) if kind == "sitemap" else parse_feed(response.content)
    except ET.ParseError as exc:
        log.warning("Could not parse %s: %s", url, exc)
        return []


def load_outlets(path: Path) -> list[dict[str, str]]:
    """Read active outlets from outlets.csv."""
    with path.open(encoding="utf-8", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r["active"] == "yes"]


def outlet_for_domain(domain: str, outlets: list[dict[str, str]]) -> dict[str, str] | None:
    """Return the outlet whose domain matches `domain` (or a parent of it)."""
    best = None
    for o in outlets:
        od = o["domain"].lower()
        if domain == od or domain.endswith("." + od):
            if best is None or len(od) > len(best["domain"]):
                best = o
    return best


def make_link(item: Item, outlet: dict[str, str], via: str, collected: str, cfg: dict[str, Any],
              text_route: str = "direct", language: str | None = None) -> Link:
    """Build a Link from an item credited to `outlet`."""
    return Link(
        link_id=link_id_for(item.url),
        story_id="",
        url=item.url,
        outlet_id=outlet["outlet_id"],
        outlet_group=outlet["outlet_group"],
        reach_tier=outlet["reach_tier"],
        language=language or outlet["language"],
        title=item.title,
        title_source=item.title_source,
        published=config.iso(item.published, cfg),
        collected=collected,
        via=via,
        text_route=text_route,
        source_domain=domain_of(item.source_href or item.url),
    )


def collect_direct(session: PoliteSession, outlets: list[dict[str, str]], since: datetime,
                   collected: str, cfg: dict[str, Any]) -> list[Link]:
    """Collect from each outlet's RSS feed, or its news sitemap when there is no feed."""
    keywords = cfg["collection"]["serbia_keywords"]
    links = []
    for o in outlets:
        if o["rss_url"]:
            url, kind, via = o["rss_url"], "feed", "rss"
        elif o["sitemap_url"]:
            url, kind, via = o["sitemap_url"], "sitemap", "sitemap"
        else:
            continue
        items = [i for i in fetch_items(session, url, kind) if i.published >= since]
        if o["needs_keyword_filter"] == "yes":
            items = [i for i in items if mentions_serbia(f"{i.title} {i.summary} {i.url}", keywords)]
        links += [make_link(i, o, via, collected, cfg) for i in items]
        log.info("%s: %d recent items via %s", o["outlet_id"], len(items), via)
    return links


def gnews_queries(outlets: list[dict[str, str]], cfg: dict[str, Any], days: int) -> list[tuple[str, str, str]]:
    """Return (query, language, via) for site searches and keyword searches."""
    queries = []
    for o in outlets:
        if o["google_news"] == "yes" and not o["rss_url"] and not o["sitemap_url"]:
            extra = " Serbia" if o["needs_keyword_filter"] == "yes" else ""
            queries.append((f"site:{o['domain']}{extra} when:{days}d", o["language"], "gnews_site"))
    for lang, terms in cfg["collection"]["google_news"]["queries"].items():
        if lang in cfg["languages"]["active"]:
            queries += [(f"{t} when:{days}d", lang, "gnews_query") for t in terms]
    return queries


def collect_gnews(session: PoliteSession, outlets: list[dict[str, str]], since: datetime,
                  collected: str, cfg: dict[str, Any], days: int) -> list[Link]:
    """Run Google News searches; credit each item to its outlet by the source element."""
    editions = cfg["collection"]["google_news"]["editions"]
    aggregator = next(o for o in outlets if o["outlet_id"] == "google_news")
    links = []
    for query, lang, via in gnews_queries(outlets, cfg, days):
        if lang not in editions:
            continue
        items = [i for i in fetch_items(session, gnews_search_url(query, editions[lang]), "feed") if i.published >= since]
        for i in items:
            i.title = strip_gnews_suffix(i.title, i.source_title)
            i.title_source = "gnews"
            outlet = outlet_for_domain(domain_of(i.source_href), outlets) if i.source_href else None
            links.append(make_link(i, outlet or aggregator, via, collected, cfg,
                                   text_route="headline_only", language=lang if outlet is None else None))
        log.info("Google News %r: %d recent items", query, len(items))
    return links


# --- Merging and grouping ------------------------------------------------------------------


def drop_gnews_duplicates(direct: list[Link], gnews: list[Link], threshold: int) -> list[Link]:
    """Keep only Google items with no direct copy from the same outlet (title match)."""
    by_outlet: dict[str, list[str]] = {}
    for d in direct:
        by_outlet.setdefault(d.outlet_id, []).append(match_key(d.title))
    kept = []
    for g in gnews:
        key = match_key(g.title)
        if any(fuzz.token_sort_ratio(key, k) >= threshold for k in by_outlet.get(g.outlet_id, [])):
            continue
        kept.append(g)
    return kept


def dedupe(links: list[Link]) -> list[Link]:
    """Remove repeated links (same id), keeping the first; Google repeats across queries."""
    seen: set[str] = set()
    out = []
    for link in links:
        if link.link_id not in seen:
            seen.add(link.link_id)
            out.append(link)
    return out


def assign_stories(new: list[Link], existing: list[dict[str, str]], threshold: int, window_hours: int,
                   min_words: int = 4) -> None:
    """Give each new link the story_id of its best title match in the window, or a new id.

    Compares only links in the same language; titles are compared in Latin script without
    diacritics, so Cyrillic and Latin copies of one Serbian story group together. Titles
    shorter than `min_words` (e.g. "Saopštenje") are too generic to group and get their own id.
    """
    pool = [(match_key(e["title"]), e["language"], datetime.fromisoformat(e["published"]), e["story_id"])
            for e in existing if e.get("story_id") and len(match_key(e["title"]).split()) >= min_words]
    window = timedelta(hours=window_hours)
    for link in sorted(new, key=lambda x: x.published):
        key, when = match_key(link.title), datetime.fromisoformat(link.published)
        best_score, best_story = 0.0, ""
        for p_key, p_lang, p_when, p_story in (pool if len(key.split()) >= min_words else []):
            if p_lang != link.language or abs(when - p_when) > window:
                continue
            score = fuzz.token_sort_ratio(key, p_key)
            if score > best_score:
                best_score, best_story = score, p_story
        link.story_id = best_story if best_score >= threshold else f"{when:%Y%m%d}-{link.link_id[:8]}"
        if len(key.split()) >= min_words:
            pool.append((key, link.language, when, link.story_id))


# --- Storage ---------------------------------------------------------------------------------


def read_links(path: Path) -> list[dict[str, str]]:
    """Read data/links.csv, or [] if it does not exist yet."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def append_links(path: Path, links: list[Link]) -> None:
    """Append links to data/links.csv, writing the header for a new file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=LINK_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(asdict(link) for link in links)


# --- Main ----------------------------------------------------------------------------------


def run(cfg: dict[str, Any], hours: int | None = None, session: PoliteSession | None = None,
        now: datetime | None = None) -> int:
    """Collect, merge, group and store new links; return how many were added."""
    session = session or PoliteSession(cfg)
    outlets = load_outlets(config.path(cfg, "outlets_csv"))
    hours = hours or int(cfg["collection"]["default_lookback_hours"])
    now = now or config.now(cfg)
    since, collected = now - timedelta(hours=hours), config.iso(now, cfg)
    threshold = int(cfg["grouping"]["title_similarity_threshold"])

    direct = collect_direct(session, outlets, since, collected, cfg)
    days = -(-hours // 24)
    gnews = drop_gnews_duplicates(direct, collect_gnews(session, outlets, since, collected, cfg, days), threshold)

    links_path = config.path(cfg, "links_csv")
    existing = read_links(links_path)
    known = {row["link_id"] for row in existing}
    known_headlines = {(r["source_domain"], match_key(r["title"])) for r in existing if r["text_route"] == "headline_only"}
    new = [
        link for link in dedupe(direct + gnews)
        if link.link_id not in known
        and not (link.text_route == "headline_only" and (link.source_domain, match_key(link.title)) in known_headlines)
    ]
    grouping = cfg["grouping"]
    assign_stories(new, existing, threshold, int(grouping["window_hours"]), int(grouping.get("min_title_words", 4)))
    append_links(links_path, new)

    stories = {link.story_id for link in new}
    log.info("Added %d links (%d direct, %d headline-only) in %d stories; %d repeats skipped; blocked domains: %s",
             len(new), sum(l.text_route == "direct" for l in new), sum(l.text_route == "headline_only" for l in new),
             len(stories), len(direct) + len(gnews) - len(new), ", ".join(sorted(session.blocked)) or "none")
    return len(new)


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=int, help="look back this many hours (default from config.yaml)")
    args = parser.parse_args()
    cfg = config.get_config()
    config.setup_logging(SCRIPT, cfg)
    run(cfg, hours=args.hours)


if __name__ == "__main__":
    main()
