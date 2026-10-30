"""Checks on outlets.csv and actors.csv so bad rows are caught before a run."""

import csv
from pathlib import Path

import pytest

import config

ROOT = Path(__file__).resolve().parents[1]
YES_NO = {"yes", "no"}


def read_rows(name: str) -> list[dict[str, str]]:
    with (ROOT / name).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def outlets() -> list[dict[str, str]]:
    return read_rows("outlets.csv")


@pytest.fixture(scope="module")
def actors() -> list[dict[str, str]]:
    return read_rows("actors.csv")


def test_outlet_ids_unique(outlets: list[dict[str, str]]) -> None:
    ids = [r["outlet_id"] for r in outlets]
    assert len(ids) == len(set(ids))


def test_outlet_fields_valid(outlets: list[dict[str, str]]) -> None:
    groups = set(config.load_config()["outlet_groups"])
    for r in outlets:
        assert r["outlet_group"] in groups, r["outlet_id"]
        assert r["reach_tier"] in {"1", "2", "3"}, r["outlet_id"]
        assert r["language"] in {"sr", "en", "fr", "de"}, r["outlet_id"]
        assert r["script"] in {"cyrl", "latn", "mixed"}, r["outlet_id"]
        assert r["paywall"] in {"yes", "no", "partial"}, r["outlet_id"]
        for col in ("google_news", "needs_keyword_filter", "active"):
            assert r[col] in YES_NO, (r["outlet_id"], col)


def test_every_outlet_has_a_route(outlets: list[dict[str, str]]) -> None:
    """Each outlet is reachable by RSS or Google News, except the Google News row itself."""
    for r in outlets:
        if r["outlet_id"] == "google_news":
            continue
        assert r["rss_url"].startswith("https://") or r["google_news"] == "yes", r["outlet_id"]


def test_all_outlet_groups_used(outlets: list[dict[str, str]]) -> None:
    used = {r["outlet_group"] for r in outlets}
    assert used == set(config.load_config()["outlet_groups"])


def test_actor_ids_unique(actors: list[dict[str, str]]) -> None:
    ids = [r["actor_id"] for r in actors]
    assert len(ids) == len(set(ids))


def test_actor_fields_valid(actors: list[dict[str, str]]) -> None:
    types = {
        "person", "party", "list", "movement", "institution", "state_company",
        "company", "media", "civil_society", "foreign", "international_org",
    }
    ids = {r["actor_id"] for r in actors}
    for r in actors:
        assert r["type"] in types, r["actor_id"]
        assert r["top_tier"] in YES_NO, r["actor_id"]
        assert r["status"] in {"seed", "confirmed", "proposed"}, r["actor_id"]
        if r["affiliation"]:
            assert r["affiliation"] in ids, (r["actor_id"], r["affiliation"])
