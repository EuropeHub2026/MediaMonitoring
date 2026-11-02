"""Tests for 4_draft_brief.py with a fake AI client; no API calls."""

import csv
import importlib
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_client

brief = importlib.import_module("4_draft_brief")

UTC = timezone.utc


def story(sid: str, thread: str = "", category: str = "post_change", top: bool = False, copies: int = 1,
          relevant: bool = True, published: str = "2026-11-02T08:00:00+01:00") -> dict:
    return {"story_id": sid, "thread_id": thread, "title": f"Title {sid}", "published": published,
            "n_copies": copies, "outlet_id": f"outlet_{sid}", "source_url": f"https://x.test/{sid}",
            "extraction": {"relevant": relevant, "category": category, "secondary_category": None,
                           "top_tier": top, "summary": f"Summary {sid}.", "why_it_matters": "Matters.",
                           "evidence_quote": "SECRET QUOTE"}}


def copy(link: str, group: str, outlet: str = "o") -> dict:
    return {"link_id": link, "outlet_group": group, "outlet_id": outlet}


class Client:
    """Fake client returning a fixed brief and recording the call."""

    def __init__(self, items: list[brief.BriefItem], focus: list[brief.FocusLine] | None = None) -> None:
        self.items, self.kwargs = items, None
        self.focus = [brief.FocusLine(line="Alert.", story_ids=["a"])] if focus is None else focus
        self.responses = self

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=brief.Brief(items=self.items, focus=self.focus))


def item(*ids: str) -> brief.BriefItem:
    return brief.BriefItem(headline="H", paragraph="P.", why_it_matters="W.", story_ids=list(ids))


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv("OPENAI_MODEL_BRIEF", "brief-model")
    monkeypatch.setattr(brief.config, "now",
                        lambda c: datetime(2026, 11, 2, 7, 0, tzinfo=UTC))
    return {"timezone": "Europe/Belgrade",
            "paths": {"review_dir": str(tmp_path / "review"), "coded_jsonl": str(tmp_path / "coded.jsonl"),
                      "links_csv": str(tmp_path / "links.csv"), "status_json": str(tmp_path / "status.json")},
            "schedule": {"brief_weekdays": ["mon", "tue", "wed", "thu", "fri"]},
            "collection": {"default_lookback_hours": 26},
            "brief": {"min_items": 1, "max_items": 2, "max_input_developments": 60, "focus_max_items": 12},
            "coding": {"brief_model_env": "OPENAI_MODEL_BRIEF", "temperature": None}}


def test_thread_merges_stories_and_raises_severity() -> None:
    copies = {"a": [copy("1", "serbian_independent")], "b": [copy("2", "serbian_pro_government")]}
    devs = brief.consolidate([story("a", "t1", top=True), story("b", "t1")], copies)
    assert len(devs) == 1 and devs[0].severity == 3
    assert devs[0].confirming_link_ids == ["1", "2"]


def test_stories_without_thread_stay_separate() -> None:
    devs = brief.consolidate([story("a"), story("b")], {"a": [copy("1", "international")],
                                                       "b": [copy("2", "international")]})
    assert len(devs) == 2 and all(d.severity == 1 for d in devs)


def test_ranked_by_severity() -> None:
    copies = {"low": [copy("1", "international")], "high": [copy("2", "official")]}
    devs = brief.consolidate([story("low"), story("high")], copies)
    assert [d.key for d in devs] == ["high", "low"]


def focus_brief(*lines: brief.FocusLine) -> brief.Brief:
    return brief.Brief(items=[], focus=list(lines))


def test_focus_drops_lines_with_no_alert_category() -> None:
    by_id = {"a": story("a", category="background"), "b": story("b")}
    copies = {"a": [copy("1", "official")], "b": [copy("2", "official")]}
    lines = focus_brief(brief.FocusLine(line="A", story_ids=["a"]), brief.FocusLine(line="B", story_ids=["b"]))
    assert [e.line for e, _ in brief.focus_entries(lines, by_id, copies, 12)] == ["B"]


def test_focus_severity_is_computed_across_merged_stories_and_ranked() -> None:
    by_id = {"a": story("a", top=True), "b": story("b"), "c": story("c")}
    copies = {"a": [copy("1", "serbian_independent")], "b": [copy("2", "serbian_pro_government")],
              "c": [copy("3", "international")]}
    lines = focus_brief(brief.FocusLine(line="Low", story_ids=["c"]),
                        brief.FocusLine(line="High", story_ids=["a", "b"]))
    entries = brief.focus_entries(lines, by_id, copies, 12)
    assert [(e.line, d.severity) for e, d in entries] == [("High", 3), ("Low", 1)]


def test_window_excludes_irrelevant_and_old() -> None:
    start, end = datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 3, tzinfo=UTC)
    rows = [story("in"), story("off", relevant=False), story("old", published="2026-10-20T08:00:00+01:00")]
    assert [r["story_id"] for r in brief.stories_in_window(rows, start, end)] == ["in"]


def test_monday_fallback_is_72_hours(cfg: dict) -> None:
    now = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)
    assert (now - brief.window_start(cfg, date(2026, 11, 2), now)).total_seconds() == 72 * 3600


def test_window_starts_at_last_approved_brief(cfg: dict) -> None:
    review = Path(cfg["paths"]["review_dir"])
    review.mkdir()
    (review / "brief_2026-10-30.md").write_text(
        "---\nstatus: approved\nwindow_end: 2026-10-30T07:00:00+01:00\n---\n", encoding="utf-8")
    (review / "brief_2026-10-31.md").write_text(
        "---\nstatus: draft\nwindow_end: 2026-10-31T07:00:00+01:00\n---\n", encoding="utf-8")
    now = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)
    assert brief.window_start(cfg, date(2026, 11, 2), now).isoformat() == "2026-10-30T07:00:00+01:00"


def test_input_has_no_evidence_quote() -> None:
    devs = brief.consolidate([story("a")], {"a": [copy("1", "official")]})
    assert "SECRET QUOTE" not in brief.development_input(devs)


def test_invented_story_id_rejected(cfg: dict) -> None:
    devs = brief.consolidate([story("a")], {"a": [copy("1", "official")]})
    with pytest.raises(ai_client.AIError):
        brief.draft_items(cfg, Client([item("invented")]), devs)


def test_invented_focus_id_rejected(cfg: dict) -> None:
    devs = brief.consolidate([story("a")], {"a": [copy("1", "official")]})
    with pytest.raises(ai_client.AIError):
        brief.draft_items(cfg, Client([item("a")], [brief.FocusLine(line="X", story_ids=["invented"])]), devs)


def test_too_many_items_rejected(cfg: dict) -> None:
    devs = brief.consolidate([story("a")], {"a": [copy("1", "official")]})
    with pytest.raises(ai_client.AIError):
        brief.draft_items(cfg, Client([item("a"), item("a"), item("a")]), devs)


def write_inputs(cfg: dict) -> None:
    import json
    with open(cfg["paths"]["coded_jsonl"], "w", encoding="utf-8") as fh:
        fh.write(json.dumps(story("a", top=True)) + "\n")
    with open(cfg["paths"]["links_csv"], "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, ["link_id", "story_id", "outlet_group", "outlet_id"])
        writer.writeheader()
        writer.writerow({"link_id": "1", "story_id": "a", "outlet_group": "official", "outlet_id": "rik"})


def test_run_writes_draft_without_quote(cfg: dict) -> None:
    write_inputs(cfg)
    path = brief.run(cfg, Client([item("a")]), date(2026, 11, 2))
    text = path.read_text(encoding="utf-8")
    assert "status: draft" in text and "Severity 3" in text and "https://x.test/a" in text
    assert "SECRET QUOTE" not in text


def test_existing_brief_is_never_overwritten(cfg: dict) -> None:
    write_inputs(cfg)
    review = Path(cfg["paths"]["review_dir"])
    review.mkdir()
    existing = review / "brief_2026-11-02.md"
    existing.write_text("reviewer edits", encoding="utf-8")
    assert brief.run(cfg, Client([item("a")]), date(2026, 11, 2)) is None
    assert existing.read_text(encoding="utf-8") == "reviewer edits"


def test_failed_call_writes_nothing(cfg: dict) -> None:
    write_inputs(cfg)
    assert brief.run(cfg, Client([item("invented")]), date(2026, 11, 2)) is None
    assert not (Path(cfg["paths"]["review_dir"]) / "brief_2026-11-02.md").exists()


def test_weekend_skipped_unless_forced(cfg: dict) -> None:
    write_inputs(cfg)
    assert brief.run(cfg, Client([item("a")]), date(2026, 11, 1)) is None
