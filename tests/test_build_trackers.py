"""Tests for 5_build_trackers.py on small in-memory rows; no network, no AI."""

import importlib
import json
from datetime import datetime
from pathlib import Path

trk = importlib.import_module("5_build_trackers")

ACTORS = {
    "vladimir_lucic": {"actor_id": "vladimir_lucic", "name": "Vladimir Lučić", "type": "person",
                       "role": "CEO of Telekom Srbija", "affiliation": "", "status": "seed"},
    "manja_grcic": {"actor_id": "manja_grcic", "name": "Manja Grčić", "type": "person",
                    "role": "RTS Director General", "affiliation": "", "status": "confirmed"},
    "rik": {"actor_id": "rik", "name": "RIK", "type": "institution", "role": "", "affiliation": "",
            "status": "seed"},
}


def ent(pid: str, action: str, stage: str = "completed", proposed: bool = False, stance: int = 0) -> dict:
    return {"person_or_body": pid, "proposed": proposed, "role": "Role", "action": action, "stage": stage,
            "by_whom": "Student List", "response": "not_addressed", "stance": stance}


def story(sid: str, entities: list[dict], published: str = "2026-11-02T10:00:00+01:00",
          category: str = "resignation_call", actors: list[str] | None = None, thread: str = "",
          relevant: bool = True, severity: int = 1, event: str = "") -> dict:
    return {"story_id": sid, "thread_id": thread, "event_id": event, "published": published, "title": f"T {sid}",
            "source_url": f"https://x.test/{sid}", "outlet_id": "n1", "severity": severity, "n_copies": 1,
            "codebook_version": "0.2.0",
            "extraction": {"relevant": relevant, "category": category, "secondary_category": None,
                           "top_tier": False, "actors": actors or [], "entities": entities,
                           "summary": f"S {sid}.", "why_it_matters": "W.", "evidence_quote": "SECRET QUOTE"}}


def test_status_moves_forward_only() -> None:
    evs = [{"action": "called_to_resign", "stage": "completed"},
           {"action": "resigned", "stage": "completed"},
           {"action": "called_to_resign", "stage": "completed"}]
    assert trk.entry_status(evs) == "gone"
    assert trk.entry_status([{"action": "resigned", "stage": "announced"}]) == "departure_announced"
    assert trk.entry_status([{"action": "dismissal_demanded", "stage": "completed"}]) == "called_to_resign"


def test_resignations_skip_proposed_and_unknown_names() -> None:
    stories = [story("a", [ent("vladimir_lucic", "called_to_resign"), ent("Goran X", "resigned", proposed=True),
                           ent("not_on_list", "resigned")]),
               story("b", [ent("manja_grcic", "resigned")], published="2026-11-01T09:00:00+01:00", severity=2)]
    out = trk.resignation_tracker(trk.relevant(stories), ACTORS)
    assert [e["actor_id"] for e in out] == ["manja_grcic", "vladimir_lucic"]
    assert out[0]["status"] == "gone" and out[0]["actor_status"] == "confirmed" and out[0]["max_severity"] == 2
    assert out[1]["called_by"] == ["Student List"]


def test_emerging_counts_persons_once_per_story_with_change() -> None:
    now = datetime.fromisoformat("2026-11-03T08:00:00+01:00")
    stories = [story("r1", [ent("vladimir_lucic", "statement", stance=-2)], actors=["vladimir_lucic", "rik"]),
               story("r2", [ent("vladimir_lucic", "appointed", stance=2)]),
               story("p1", [], actors=["vladimir_lucic"], published="2026-10-25T10:00:00+01:00"),
               story("old", [], actors=["manja_grcic"], published="2026-10-01T10:00:00+01:00")]
    out = trk.emerging_leaders(trk.relevant(stories), ACTORS, now, 7)
    assert len(out) == 1
    lucic = out[0]
    assert (lucic["stories_recent"], lucic["stories_prior"], lucic["change"]) == (2, 1, 1)
    assert lucic["mean_stance"] == 0
    assert [s["kind"] for s in lucic["signals"]] == ["appointed"]


def test_timeline_one_entry_per_event_without_quotes() -> None:
    stories = [story("m1", [], category="transition_milestone", thread="t1", event="e1",
                     published="2026-11-01T10:00:00+01:00"),
               story("m2", [], category="transition_milestone", thread="t1", event="e1"),
               story("m3", [], category="transition_milestone", thread="t1", event="e3"),
               story("x", [], category="post_change")]
    copies = {"m1": [{"link_id": "l1", "outlet_group": "official", "outlet_id": "rik"}],
              "m2": [{"link_id": "l2", "outlet_group": "serbian_independent", "outlet_id": "n1"}]}
    out = trk.transition_timeline(trk.relevant(stories), copies)
    assert [e["event_id"] for e in out] == ["e1", "e3"]      # same thread, two events
    assert out[0]["date"].startswith("2026-11-01") and out[0]["severity"] == 2
    assert "SECRET QUOTE" not in json.dumps(out)


def test_irrelevant_stories_ignored_and_pending_review_lists_proposed() -> None:
    stories = [story("a", [ent("Goran X", "resigned", proposed=True)]),
               story("b", [ent("Goran X", "statement", proposed=True)]),
               story("c", [ent("vladimir_lucic", "called_to_resign")], relevant=False)]
    rel = trk.relevant(stories)
    assert trk.resignation_tracker(rel, ACTORS) == []
    pending = trk.pending_review(rel)
    assert pending[0]["name"] == "Goran X" and pending[0]["stories"] == 2


def test_run_writes_file_without_quotes(tmp_path: Path) -> None:
    (tmp_path / "coded.jsonl").write_text(json.dumps(story("a", [ent("vladimir_lucic", "called_to_resign")])) + "\n",
                                          encoding="utf-8")
    (tmp_path / "links.csv").write_text("link_id,story_id,outlet_id,outlet_group,published\n", encoding="utf-8")
    fields = ["actor_id", "name", "type", "role", "affiliation", "status"]
    rows = [",".join(fields)] + [",".join(a[f] for f in fields) for a in ACTORS.values()]
    (tmp_path / "actors.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    cfg = {"timezone": "Europe/Belgrade",
           "paths": {k: str(tmp_path / v) for k, v in {"coded_jsonl": "coded.jsonl", "links_csv": "links.csv",
                                                       "actors_csv": "actors.csv",
                                                       "trackers_json": "trackers.json"}.items()}}
    data = trk.run(cfg, now=datetime.fromisoformat("2026-11-03T08:00:00+01:00"))
    text = (tmp_path / "trackers.json").read_text(encoding="utf-8")
    assert len(data["resignations"]) == 1 and "SECRET QUOTE" not in text
