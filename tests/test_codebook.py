"""Tests for codebook.py: sync with codebook.md, schema rules, severity and prompt."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import codebook as cb

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def good() -> dict:
    return json.loads((FIXTURES / "extraction_ok.json").read_text(encoding="utf-8"))


@pytest.fixture
def actors() -> list[dict[str, str]]:
    return cb.load_actors(FIXTURES / "actors_small.csv")


# --- Sync with codebook.md ---------------------------------------------------------------


def test_codebook_md_has_version() -> None:
    md = (ROOT / "codebook.md").read_text(encoding="utf-8")
    assert f"**Version {cb.CODEBOOK_VERSION}**" in md
    assert f"Prompt version {cb.PROMPT_VERSION}" in md
    assert f"Triage prompt version {cb.TRIAGE_PROMPT_VERSION}" in md


@pytest.mark.parametrize(
    "codes",
    [cb.CATEGORIES, cb.ACTIONS, cb.ARTICLE_TYPES, cb.STAGES],
    ids=["categories", "actions", "article_types", "stages"],
)
def test_codebook_md_defines_every_code(codes: list[str]) -> None:
    md = (ROOT / "codebook.md").read_text(encoding="utf-8")
    missing = [c for c in codes if f"- `{c}`:" not in md]
    assert not missing


def test_codebook_md_lists_top_tier_posts() -> None:
    md = (ROOT / "codebook.md").read_text(encoding="utf-8")
    assert all(f"- {p}" in md for p in cb.TOP_TIER_POSTS)


def test_alert_categories_exclude_background() -> None:
    assert "background" not in cb.ALERT_CATEGORIES
    assert cb.CATEGORIES == cb.ALERT_CATEGORIES + ["background"]


# --- Schema --------------------------------------------------------------------------------


def test_good_extraction_validates(good: dict) -> None:
    ext = cb.Extraction.model_validate(good)
    assert ext.entities[0].action == "dismissal_demanded"


def test_schema_is_strict_compatible() -> None:
    """Strict structured outputs need every property listed as required."""
    schema = cb.Extraction.model_json_schema()
    assert set(schema["required"]) == set(schema["properties"])
    entity = schema["$defs"]["EntityRow"]
    assert set(entity["required"]) == set(entity["properties"])


@pytest.mark.parametrize(
    "change",
    [
        {"category": "invented_category"},
        {"secondary_category": "resignation_call"},
        {"secondary_category": "background"},
        {"evidence_quote": " ".join(["riječ"] * 26)},
        {"relevant": False},
    ],
    ids=["unknown-category", "secondary-equals-primary", "secondary-background", "long-quote", "irrelevant-with-entities"],
)
def test_bad_extractions_rejected(good: dict, change: dict) -> None:
    with pytest.raises(ValidationError):
        cb.Extraction.model_validate({**good, **change})


def test_too_many_entities_rejected(good: dict) -> None:
    good["entities"] = good["entities"] * (cb.MAX_ENTITIES + 1)
    with pytest.raises(ValidationError):
        cb.Extraction.model_validate(good)


def test_unknown_action_and_stance_rejected(good: dict) -> None:
    for field, value in (("action", "fired"), ("stance", 3), ("stage", "rumoured")):
        bad = json.loads(json.dumps(good))
        bad["entities"][0][field] = value
        with pytest.raises(ValidationError):
            cb.Extraction.model_validate(bad)


def test_irrelevant_story_valid_when_clean(good: dict) -> None:
    clean = {**good, "relevant": False, "category": "background", "secondary_category": None, "entities": []}
    assert cb.Extraction.model_validate(clean).relevant is False


def test_check_actor_ids(good: dict, actors: list[dict[str, str]]) -> None:
    known = {a["actor_id"] for a in actors}
    ext = cb.Extraction.model_validate(good)
    assert cb.check_actor_ids(ext, known) == []
    ext.actors.append("nobody")
    ext.entities[0].proposed = True
    problems = cb.check_actor_ids(ext, known)
    assert len(problems) == 2


# --- Severity ------------------------------------------------------------------------------

A = cb.ArticleRef


def test_severity_single_group() -> None:
    arts = [A("a1", "serbian_independent"), A("a2", "serbian_independent")]
    assert cb.compute_severity(arts, top_tier=True) == (1, [])


def test_severity_two_groups() -> None:
    arts = [A("a1", "serbian_independent"), A("a2", "serbian_independent"), A("a3", "international")]
    assert cb.compute_severity(arts, top_tier=False) == (2, ["a1", "a3"])


def test_severity_official_confirms_alone() -> None:
    arts = [A("a1", "serbian_pro_government"), A("a2", "official")]
    assert cb.compute_severity(arts, top_tier=True) == (3, ["a2"])


def test_severity_ignores_primary_nonstate() -> None:
    """A party or union site confirming its own statement does not raise severity."""
    arts = [A("a1", "serbian_independent"), A("a2", "primary_nonstate")]
    assert cb.compute_severity(arts, top_tier=True) == (1, [])


def test_prompt_lists_stages(actors: list[dict[str, str]]) -> None:
    text = cb.prompt_text(actors)
    assert all(f"- {s}:" in text for s in cb.STAGES)


def test_severity_ignores_uncredited_aggregator() -> None:
    arts = [A("a1", "serbian_independent"), A("a2", "aggregator")]
    assert cb.compute_severity(arts, top_tier=True) == (1, [])


# --- Actors and prompt ---------------------------------------------------------------------


def test_load_actors_drops_proposed(actors: list[dict[str, str]]) -> None:
    assert "someone_new" not in {a["actor_id"] for a in actors}


def test_prompt_lists_codes_and_actors(actors: list[dict[str, str]]) -> None:
    text = cb.prompt_text(actors)
    for code in cb.CATEGORIES + cb.ACTIONS + cb.ARTICLE_TYPES:
        assert f"- {code}:" in text
    assert "- vladimir_lucic: Vladimir Lučić (CEO of Telekom Srbija)" in text
    assert "someone_new" not in text


def test_prompt_works_with_repo_actors() -> None:
    text = cb.prompt_text(cb.load_actors(ROOT / "actors.csv"))
    assert "- aleksandar_vucic:" in text


def test_extra_keys_rejected(good: dict) -> None:
    with pytest.raises(ValidationError):
        cb.Extraction.model_validate({**good, "severity": 3})
