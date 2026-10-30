"""Tests for 1_collect_press.py with fixture feeds; no network."""

import csv
import importlib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

collect = importlib.import_module("1_collect_press")

FIXTURES = Path(__file__).parent / "fixtures"
CET = ZoneInfo("Europe/Belgrade")
NOW = datetime(2026, 10, 29, 14, 0, tzinfo=CET)


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeSession:
    """Serves fixture files by URL; records requests."""

    routes = {
        "https://n1info.rs/feed/": "rss_n1.xml",
        "https://www.alo.rs/sitemap/news.xml": "sitemap_alo.xml",
        "https://www.theguardian.com/feed": "rss_guardian.xml",
    }

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.blocked: set[str] = set()

    def get(self, url: str):
        self.calls.append(url)
        if url.startswith("https://news.google.com/"):
            return SimpleNamespace(status_code=200, content=fixture_bytes("gnews_search.xml"))
        name = self.routes.get(url)
        return SimpleNamespace(status_code=200 if name else 404, content=fixture_bytes(name) if name else b"")


@pytest.fixture
def cfg(tmp_path: Path) -> dict:
    return {
        "timezone": "Europe/Belgrade",
        "paths": {"outlets_csv": str(FIXTURES / "outlets_small.csv"), "links_csv": str(tmp_path / "links.csv")},
        "languages": {"active": ["sr", "en"]},
        "collection": {
            "default_lookback_hours": 26,
            "serbia_keywords": ["Serbia", "Belgrade"],
            "google_news": {
                "editions": {"sr": {"hl": "sr", "gl": "RS", "ceid": "RS:sr"}, "en": {"hl": "en-US", "gl": "US", "ceid": "US:en"}},
                "queries": {"sr": ["Studentska lista"], "en": []},
            },
        },
        "grouping": {"title_similarity_threshold": 85, "window_hours": 48},
    }


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# --- Helpers -------------------------------------------------------------------------------


def test_cyrillic_and_latin_titles_share_a_key() -> None:
    cyr = collect.match_key("Манја Грчић поднела оставку на место генералне директорке РТС-а")
    lat = collect.match_key("Grčić podnela ostavku na mesto generalne direktorke RTS-a")
    assert collect.fuzz.token_sort_ratio(cyr, lat) >= 85
    assert collect.match_key("Đilas i Ђилас") == "djilas i djilas"


def test_normalize_url_drops_tracking() -> None:
    a = collect.normalize_url("https://n1info.rs/vesti/x/?utm_source=rss#top")
    assert a == collect.normalize_url("https://N1INFO.rs/vesti/x")


def test_strip_gnews_suffix() -> None:
    assert collect.strip_gnews_suffix("Naslov vesti - N1", "N1") == "Naslov vesti"
    assert collect.strip_gnews_suffix("Naslov - RTS", "") == "Naslov"


def test_title_from_slug() -> None:
    assert collect.title_from_slug("https://informer.rs/vesti/1165347/neka-vest-danas") == "Neka vest danas"


def test_parse_feed_drops_undated() -> None:
    items = collect.parse_feed(fixture_bytes("rss_n1.xml"))
    assert [i.title for i in items] == ["Grčić podnela ostavku na mesto generalne direktorke RTS-a", "Stara vest"]


def test_parse_sitemap_titles_and_slugs() -> None:
    items = collect.parse_news_sitemap(fixture_bytes("sitemap_alo.xml"))
    assert [i.title_source for i in items] == ["sitemap", "slug"]
    assert items[1].title == "Neki estradni skandal"


def test_gnews_queries_only_for_outlets_without_direct_source(cfg: dict) -> None:
    outlets = collect.load_outlets(FIXTURES / "outlets_small.csv")
    queries = collect.gnews_queries(outlets, cfg, days=2)
    assert ("site:tanjug.rs when:2d", "sr", "gnews_site") in queries
    assert not any("n1info" in q for q, _, _ in queries)
    assert ("Studentska lista when:2d", "sr", "gnews_query") in queries


# --- End to end ----------------------------------------------------------------------------


def test_run_collects_credits_and_groups(cfg: dict, tmp_path: Path) -> None:
    added = collect.run(cfg, session=FakeSession(), now=NOW)
    rows = read(tmp_path / "links.csv")
    assert added == len(rows) == 6
    by_outlet = {}
    for r in rows:
        by_outlet.setdefault(r["outlet_id"], []).append(r)

    # Old items filtered; keyword filter on the international feed; inactive outlet skipped.
    assert len(by_outlet["n1"]) == 1
    assert [r["title"] for r in by_outlet["guardian"]] == ["Serbia's new majority demands TV chief go"]
    assert "inactive" not in by_outlet

    # The Google copy of the N1 story is dropped; Tanjug is headline-only; unknown site is aggregator.
    assert by_outlet["n1"][0]["via"] == "rss"
    assert by_outlet["tanjug"][0]["text_route"] == "headline_only"
    agg = by_outlet["google_news"][0]
    assert agg["outlet_group"] == "aggregator" and agg["source_domain"] == "portal-x.example"

    # The Cyrillic Alo copy and the Latin N1 copy share one story.
    alo_grcic = next(r for r in by_outlet["alo"] if r["title_source"] == "sitemap")
    assert alo_grcic["story_id"] == by_outlet["n1"][0]["story_id"]
    assert by_outlet["n1"][0]["published"] == "2026-10-29T10:00:00+01:00"


def test_rerun_adds_nothing(cfg: dict, tmp_path: Path) -> None:
    collect.run(cfg, session=FakeSession(), now=NOW)
    assert collect.run(cfg, session=FakeSession(), now=NOW) == 0
    assert len(read(tmp_path / "links.csv")) == 6


def test_generic_short_titles_not_grouped() -> None:
    def link(lid: str, title: str) -> "collect.Link":
        return collect.Link(lid, "", f"https://x.test/{lid}", "mup", "official", "2", "sr", title, "feed",
                            "2026-10-29T10:00:00+01:00", "", "rss", "direct", "x.test")
    a, b = link("aaaaaaaaaaaa", "Saopštenje"), link("bbbbbbbbbbbb", "САОПШТЕЊЕ")
    collect.assign_stories([a, b], [], threshold=85, window_hours=48, min_words=4)
    assert a.story_id != b.story_id


def test_headline_only_repeat_with_new_google_link_skipped(cfg: dict, tmp_path: Path) -> None:
    collect.run(cfg, session=FakeSession(), now=NOW)
    original = fixture_bytes("gnews_search.xml")

    class ReshuffledLinks(FakeSession):
        def get(self, url: str):
            if url.startswith("https://news.google.com/"):
                return SimpleNamespace(status_code=200, content=original.replace(b"CBMi", b"CBMj"))
            return super().get(url)

    assert collect.run(cfg, session=ReshuffledLinks(), now=NOW) == 0
