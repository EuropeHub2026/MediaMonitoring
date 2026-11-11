"""Tests for publish.py and 6_export_for_web.py; no network, no git."""

import csv
import importlib
import json
from datetime import date
from pathlib import Path

import pytest

import codebook

publish = importlib.import_module("publish")
export = importlib.import_module("6_export_for_web")

DRAFT = """---
status: {status}
reviewed_by: {reviewer}
date: 2026-11-02
window_start: 2026-10-30T12:00:00+01:00
window_end: 2026-11-02T12:00:00+01:00
---

# Brief

## Alert focus box

- **Severity 3** · post_change, legal_action · A minister resigned.
  - 3 outlets: official
  - Sources: [rik](https://x.test/1) · [other](https://x.test/2)
  - Stories: 20261102-a

## Daily brief

### A headline

First paragraph.

Second paragraph.

**Why it matters:** It matters.

Sources: [rik](https://x.test/1)

Stories: 20261102-a

### Another

Text.

**Why it matters:** Also.

Sources: [other](https://x.test/2)

Stories: 20261102-b
"""


@pytest.fixture
def cfg(tmp_path: Path) -> dict:
    (tmp_path / "review").mkdir()
    (tmp_path / "web.html").write_text("<title>t</title>", encoding="utf-8")
    with (tmp_path / "outlets.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["outlet_id", "name", "outlet_group"])
        w.writerow(["rik", "RIK", "official"])
    return {"timezone": "Europe/Belgrade",
            "project": {"contact_email": "a@b.test"},
            "method": {"validation": "None yet.", "known_gaps": ["A gap."]},
            "paths": {k: str(tmp_path / v) for k, v in {
                "review_dir": "review", "docs_dir": "docs", "web_template": "web.html",
                "outlets_csv": "outlets.csv", "status_json": "status.json", "coded_jsonl": "coded.jsonl",
                "trackers_json": "trackers.json", "actors_csv": "actors.csv"}.items()}}


def write_brief(cfg: dict, status: str = "approved", reviewer: str = "A Reviewer", day: str = "2026-11-02") -> None:
    path = Path(cfg["paths"]["review_dir"]) / f"brief_{day}.md"
    path.write_text(DRAFT.format(status=status, reviewer=reviewer), encoding="utf-8")


def data_js(cfg: dict) -> str:
    return (Path(cfg["paths"]["docs_dir"]) / "data.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("status,reviewer", [("draft", "A Reviewer"), ("approved", ""), ("draft", "")])
def test_gate_refuses_unapproved(cfg: dict, status: str, reviewer: str) -> None:
    write_brief(cfg, status, reviewer)
    with pytest.raises(publish.GateError):
        publish.run(cfg, date(2026, 11, 2), do_commit=False)
    assert not Path(cfg["paths"]["docs_dir"]).exists()


def test_gate_refuses_missing_brief(cfg: dict) -> None:
    with pytest.raises(publish.GateError):
        publish.run(cfg, date(2026, 11, 2), do_commit=False)


def test_publish_writes_page_and_data(cfg: dict) -> None:
    write_brief(cfg)
    publish.run(cfg, date(2026, 11, 2), do_commit=False)
    docs = Path(cfg["paths"]["docs_dir"])
    assert (docs / "index.html").exists() and data_js(cfg).startswith("window.SITE_DATA = ")


def test_parsed_content(cfg: dict) -> None:
    write_brief(cfg)
    data = export.build(cfg)
    brief = data["briefs"][0]
    assert brief["reviewed_by"] == "A Reviewer"
    assert brief["focus"][0]["severity"] == 3
    assert brief["focus"][0]["categories"] == ["post_change", "legal_action"]
    assert brief["focus"][0]["sources"][0] == {"name": "RIK", "url": "https://x.test/1"}
    assert [i["headline"] for i in brief["items"]] == ["A headline", "Another"]
    assert brief["items"][0]["paragraphs"] == ["First paragraph.", "Second paragraph."]
    assert brief["items"][0]["why"] == "It matters."


def test_story_ids_not_exported(cfg: dict) -> None:
    write_brief(cfg)
    assert "20261102" not in json.dumps(export.build(cfg))


def test_drafts_on_other_dates_are_not_exported(cfg: dict) -> None:
    write_brief(cfg)
    write_brief(cfg, "draft", "", "2026-11-03")
    assert [b["date"] for b in export.build(cfg)["briefs"]] == ["2026-11-02"]
    assert len(export.approved_paths(cfg)) == 1


def test_method_notes_carry_takedown_and_versions(cfg: dict) -> None:
    write_brief(cfg)
    method = export.build(cfg)["method"]
    assert method["takedown_contact"] == "a@b.test"
    assert method["codebook_version"] == codebook.CODEBOOK_VERSION
    assert method["outlets_by_group"] == {"official": 1}


def test_spend_cap_is_surfaced(cfg: dict) -> None:
    write_brief(cfg)
    Path(cfg["paths"]["status_json"]).write_text(
        json.dumps({"openai": {"state": "cap_hit", "detail": "Budget reached."}}), encoding="utf-8")
    assert export.build(cfg)["method"]["service_notes"] == ["Budget reached."]


def test_evidence_quote_blocks_publication(cfg: dict) -> None:
    write_brief(cfg)
    path = Path(cfg["paths"]["review_dir"]) / "brief_2026-11-02.md"
    quote = "ovo je citat iz clanka koji ne sme da izadje"
    path.write_text(path.read_text(encoding="utf-8").replace("First paragraph.", quote), encoding="utf-8")
    Path(cfg["paths"]["coded_jsonl"]).write_text(
        json.dumps({"extraction": {"evidence_quote": quote}}) + "\n", encoding="utf-8")
    with pytest.raises(publish.GateError):
        publish.run(cfg, date(2026, 11, 2), do_commit=False)
    assert not Path(cfg["paths"]["docs_dir"]).exists()


def test_quote_equal_to_own_headline_does_not_block(cfg: dict) -> None:
    """Headline-only stories quote their headline, which may be published."""
    write_brief(cfg)
    path = Path(cfg["paths"]["review_dir"]) / "brief_2026-11-02.md"
    headline = "Danas se ponavljaju izbori na 53 biracka mesta"
    path.write_text(path.read_text(encoding="utf-8").replace("First paragraph.", headline), encoding="utf-8")
    Path(cfg["paths"]["coded_jsonl"]).write_text(
        json.dumps({"title": headline, "extraction": {"evidence_quote": headline}}) + "\n", encoding="utf-8")
    publish.run(cfg, date(2026, 11, 2), do_commit=False)
    assert (Path(cfg["paths"]["docs_dir"]) / "data.js").exists()


def tracker_src(day: str, story: str = "20261101-a") -> dict:
    return {"story_id": story, "published": f"{day}T10:00:00+01:00", "title": "Naslov",
            "url": "https://x.test/t", "outlet_id": "rik", "severity": 2}


def write_trackers(cfg: dict, actor_status: str = "seed") -> None:
    """A small trackers.json with one entry inside and one after the brief's window."""
    with (Path(cfg["paths"]["outlets_csv"]).parent / "actors.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["actor_id", "name"])
        w.writerow(["student_list", "Student List"])
    cfg["paths"]["actors_csv"] = str(Path(cfg["paths"]["outlets_csv"]).parent / "actors.csv")
    cfg["paths"]["trackers_json"] = str(Path(cfg["paths"]["outlets_csv"]).parent / "trackers.json")
    event = {"action": "called_to_resign", "stage": "completed", "role": "Director",
             "by_whom": "student_list", "response": "not_addressed", **tracker_src("2026-11-01")}
    late = {**event, **tracker_src("2026-11-03", "20261103-z"), "action": "resigned", "by_whom": "not_addressed"}
    data = {"built_at": "2026-11-03T12:00:00+01:00", "emerging_window_days": 7,
            "resignations": [
                {"actor_id": "a_b", "name": "A B", "actor_status": actor_status, "role": "Director",
                 "status": "gone", "max_severity": 2, "called_by": ["student_list"], "events": [event, late]},
                {"actor_id": "c_d", "name": "C D", "actor_status": "seed", "role": "Minister",
                 "status": "gone", "max_severity": 2, "called_by": [], "events": [late]}],
            "emerging_leaders": [
                {"actor_id": "a_b", "name": "A B", "actor_status": actor_status, "role": "Director",
                 "stories_recent": 3, "stories_prior": 0, "change": 3, "mean_stance": 0.5, "stance_rows": 3,
                 "signals": [{"kind": "new_actor", **tracker_src("2026-11-01")}, {"kind": "new_actor", **tracker_src("2026-11-03")}]}],
            "transition_timeline": [
                {"thread_id": "t-1", "date": "2026-11-01T10:00:00+01:00", "title": "Naslov", "summary": "S.",
                 "why_it_matters": "W.", "announced_only": False, "severity": 2, "confirming_link_ids": ["abc"],
                 "outlet_groups": ["official"], "sources": [tracker_src("2026-11-01")]},
                {"thread_id": "t-2", "date": "2026-11-03T10:00:00+01:00", "title": "Kasnije", "summary": "Late.",
                 "why_it_matters": "W.", "announced_only": False, "severity": 1, "confirming_link_ids": [],
                 "outlet_groups": ["official"], "sources": [tracker_src("2026-11-03")]}],
            "pending_review": [{"name": "Proposed Person", "stories": 1, "story_ids": ["20261101-a"]}]}
    Path(cfg["paths"]["trackers_json"]).write_text(json.dumps(data), encoding="utf-8")


def test_no_trackers_file_means_no_tracker_panels(cfg: dict) -> None:
    write_brief(cfg)
    cfg["paths"]["trackers_json"] = str(Path(cfg["paths"]["review_dir"]) / "missing.json")
    assert "trackers" not in export.build(cfg)


def test_trackers_cut_at_latest_approved_window(cfg: dict) -> None:
    write_brief(cfg)
    write_trackers(cfg)
    trackers = export.build(cfg)["trackers"]
    assert trackers["cutoff"] == "2026-11-02T12:00:00+01:00"
    assert [e["name"] for e in trackers["resignations"]] == ["A B"]
    assert [e["action"] for e in trackers["resignations"][0]["events"]] == ["called_to_resign"]
    assert [m["summary"] for m in trackers["transition_timeline"]] == ["S."]
    assert len(trackers["emerging_leaders"][0]["signals"]) == 1


def test_trackers_map_names_and_drop_ids(cfg: dict) -> None:
    write_brief(cfg)
    write_trackers(cfg)
    trackers = export.build(cfg)["trackers"]
    entry = trackers["resignations"][0]
    assert entry["called_by"] == ["Student List"] and entry["unconfirmed"] is True
    assert entry["events"][0]["outlet"] == "RIK" and entry["events"][0]["response"] == ""
    payload = json.dumps(trackers)
    for hidden in ("story_id", "thread_id", "confirming_link_ids", "20261101-a", "Proposed Person", "actor_id"):
        assert hidden not in payload


def test_confirmed_actor_is_not_flagged(cfg: dict) -> None:
    write_brief(cfg)
    write_trackers(cfg, actor_status="confirmed")
    assert export.build(cfg)["trackers"]["resignations"][0]["unconfirmed"] is False


def test_catch_up_section_is_exported_separately(cfg: dict) -> None:
    write_brief(cfg)
    path = Path(cfg["paths"]["review_dir"]) / "brief_2026-11-02.md"
    text = path.read_text(encoding="utf-8").replace("date: 2026-11-02", "date: 2026-11-02\ncatch_up_start: 2026-10-28T12:00:00+01:00")
    text += "\n## Catch-up\n\n### Gap item\n\nGap paragraph.\n\n**Why it matters:** Gap.\n\nSources: [rik](https://x.test/9)\n\nStories: s9\n"
    path.write_text(text, encoding="utf-8")
    brief = export.build(cfg)["briefs"][0]
    assert "Gap item" not in [i["headline"] for i in brief["items"]]
    assert brief["catch_up"]["start"] == "2026-10-28T12:00:00+01:00"
    assert [i["headline"] for i in brief["catch_up"]["items"]] == ["Gap item"]
    assert brief["catch_up"]["items"][0]["sources"] == [{"name": "RIK", "url": "https://x.test/9"}]
    assert "s9" not in json.dumps(brief)


def coded_row(story: str, published: str, relevant: bool = True, actors: list | None = None) -> dict:
    return {"story_id": story, "thread_id": "t-x", "event_id": "e-x", "published": published,
            "title": f"Naslov {story}", "source_url": f"https://x.test/{story}", "outlet_id": "rik",
            "outlet_groups": ["official"], "n_copies": 2, "severity": 2,
            "extraction": {"relevant": relevant, "category": "post_change", "secondary_category": None,
                           "actors": actors or [], "summary": f"Summary {story}.", "why_it_matters": "W.",
                           "evidence_quote": "tajni citat koji nikad ne izlazi na stranicu",
                           "entities": [{"person_or_body": "Proposed Person", "proposed": True}]}}


def write_coded(cfg: dict, rows: list[dict]) -> None:
    with (Path(cfg["paths"]["outlets_csv"]).parent / "actors.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["actor_id", "name", "status"])
        w.writerow(["student_list", "Student List", "seed"])
        w.writerow(["rts", "RTS", "confirmed"])
        w.writerow(["new_one", "New One", "proposed"])
    Path(cfg["paths"]["coded_jsonl"]).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_article_list_relevant_up_to_cutoff_newest_first(cfg: dict) -> None:
    write_brief(cfg)
    write_coded(cfg, [coded_row("a", "2026-11-01T10:00:00+01:00"), coded_row("b", "2026-11-02T09:00:00+01:00"),
                      coded_row("late", "2026-11-03T09:00:00+01:00"),
                      coded_row("no", "2026-11-01T11:00:00+01:00", relevant=False)])
    articles = export.build(cfg)["articles"]
    assert [a["title"] for a in articles] == ["Naslov b", "Naslov a"]
    assert articles[0]["outlet"] == "RIK" and articles[0]["categories"] == ["post_change"]


def test_article_list_names_listed_actors_only_and_hides_ids_and_quotes(cfg: dict) -> None:
    write_brief(cfg)
    write_coded(cfg, [coded_row("a", "2026-11-01T10:00:00+01:00", actors=["student_list", "rts", "new_one", "ghost"])])
    article = export.build(cfg)["articles"][0]
    assert article["actors"] == ["Student List", "RTS"] and article["unconfirmed"] == ["Student List"]
    payload = json.dumps(article)
    for hidden in ("story_id", "event_id", "thread_id", "tajni citat", "Proposed Person", "new_one"):
        assert hidden not in payload
    publish.run(cfg, date(2026, 11, 2), do_commit=False)


def test_quote_equal_to_another_storys_headline_does_not_block(cfg: dict) -> None:
    write_brief(cfg)
    quote = "Savet je zabranio emitovanje Dnevnika na jedan dan"
    own, other = coded_row("a", "2026-11-01T10:00:00+01:00"), coded_row("b", "2026-11-01T11:00:00+01:00")
    own["extraction"]["evidence_quote"] = quote
    other["title"] = quote
    write_coded(cfg, [own, other])
    publish.run(cfg, date(2026, 11, 2), do_commit=False)
    assert quote in data_js(cfg)
