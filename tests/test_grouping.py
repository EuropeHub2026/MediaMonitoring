"""Tests for grouping.py: same-event groups, threads and per-event severity. No network."""

import grouping

CFG = {"coding": {"event_window_days": 2, "event_min_similarity": 0.2, "event_min_shared_words": 3,
                  "thread_window_days": 10,
                  "thread_min_score": 2, "thread_ignore_actors": ["student_list"]}}


def row(sid: str, summary: str, category: str = "transition_milestone", published: str = "2026-11-02T10:00:00+01:00",
        entities: tuple[str, ...] = (), actors: tuple[str, ...] = (), top_tier: bool = False,
        relevant: bool = True) -> dict:
    return {"story_id": sid, "published": published, "n_copies": 1,
            "extraction": {"relevant": relevant, "category": category, "secondary_category": None,
                           "top_tier": top_tier, "summary": summary, "actors": list(actors),
                           "entities": [{"person_or_body": e, "proposed": False} for e in entities]}}


FILLER = [row(f"f{i}", s, category="background") for i, s in enumerate([
    "Belgrade city council adopted a budget revision for schools.",
    "A columnist argues the opposition lacks a programme on pensions.",
    "Farmers in Vojvodina protested over milk prices near Novi Sad.",
    "The football federation appointed a new national team coach.",
    "Air pollution in Niš exceeded limits for the third day.",
    "Telekom announced new tariffs for mobile internet packages.",
])]


def ids(rows: list[dict]) -> dict[str, tuple[str, str]]:
    return {r["story_id"]: (r.get("event_id"), r.get("thread_id")) for r in rows}


def test_boilerplate_is_ignored() -> None:
    assert grouping.summary_tokens("The headline provides no further details on RIK.") == {"rik"}


def test_same_event_under_different_headlines_is_one_event() -> None:
    rows = [row("a", "RIK published results from all 8,392 polling stations; Student List 53.01%."),
            row("b", "The electoral commission published results: Student List 53.01%, United Serbia 38.98%.",
                published="2026-11-02T15:00:00+01:00"),
            row("c", "Brnabić scheduled the constituent session of the National Assembly for 17 November.",
                published="2026-11-02T16:00:00+01:00")] + FILLER
    grouping.regroup(rows, {}, CFG)
    got = ids(rows)
    assert got["a"][0] == got["b"][0] == "e-a"
    assert got["c"][0] == "e-c"


def test_event_needs_shared_category_and_window() -> None:
    text = "RIK published results from all 8,392 polling stations; Student List 53.01%."
    rows = [row("a", text), row("b", text, category="protest_incident"),
            row("c", text, published="2026-11-06T10:00:00+01:00")] + FILLER
    grouping.regroup(rows, {}, CFG)
    assert len({r["event_id"] for r in rows[:3]}) == 3


def test_threads_chain_events_by_shared_names() -> None:
    rows = [row("a", "Calls for Lučić to resign grow.", category="resignation_call", entities=("vladimir_lucic",)),
            row("b", "Telekom board meets on management changes.", category="resignation_call",
                entities=("vladimir_lucic",), published="2026-11-06T10:00:00+01:00"),
            row("c", "Students rally in Kragujevac.", category="resignation_call", actors=("student_list",),
                published="2026-11-06T11:00:00+01:00"),
            row("d", "Lučić still in post.", category="resignation_call", entities=("vladimir_lucic",),
                published="2026-11-20T10:00:00+01:00")] + FILLER
    grouping.regroup(rows, {}, CFG)
    got = ids(rows)
    assert got["a"][1] == got["b"][1] == "t-a"
    assert got["c"][1] == "t-c"                 # broad actor only
    assert got["d"][1] == "t-d"                 # outside the thread window


def test_severity_is_computed_across_the_event() -> None:
    rows = [row("a", "RIK published results from all 8,392 polling stations; Student List 53.01%.", top_tier=True),
            row("b", "Electoral commission results: Student List 53.01%, United Serbia 38.98%.")] + FILLER
    copies = {"a": [{"link_id": "1", "outlet_group": "serbian_independent"}],
              "b": [{"link_id": "2", "outlet_group": "serbian_pro_government"}]}
    grouping.regroup(rows, copies, CFG)
    assert rows[0]["severity"] == rows[1]["severity"] == 3
    assert rows[0]["confirming_link_ids"] == ["1", "2"]


def test_irrelevant_rows_get_no_ids() -> None:
    rows = [row("x", "Sport.", relevant=False)] + FILLER
    grouping.regroup(rows, {}, CFG)
    assert rows[0]["event_id"] == "" and rows[0]["thread_id"] == "" and rows[0]["severity"] is None


def test_regroup_reports_no_change_on_rerun() -> None:
    rows = [row("a", "RIK published results.")] + FILLER
    assert grouping.regroup(rows, {}, CFG) > 0
    assert grouping.regroup(rows, {}, CFG) == 0


def test_two_shared_words_are_not_enough() -> None:
    rows = [row("a", "The headline asks whether Serbia moves toward two parties."),
            row("b", "The headline asks whether the lists can cooperate.")] + FILLER
    grouping.regroup(rows, {}, CFG)
    assert rows[0]["event_id"] != rows[1]["event_id"]
