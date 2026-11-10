"""Tests for 3_code_stories.py with a fake AI client; no API calls."""

from datetime import datetime
import csv
import importlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_client
import codebook

code = importlib.import_module("3_code_stories")

FIXTURES = Path(__file__).parent / "fixtures"
ARTICLE_FIELDS = ["link_id", "story_id", "url", "final_url", "outlet_id", "language", "title", "text",
                  "text_status", "chars", "http_status", "fetched_at"]


def extraction(**over) -> codebook.Extraction:
    base = dict(relevant=True, category="background", secondary_category=None, top_tier=False,
                article_type="news", actors=[], entities=[], summary="S one. S two.",
                why_it_matters="It matters.", evidence_quote="citat")
    return codebook.Extraction(**{**base, **over})


def entity(pid: str, action: str, proposed: bool = False) -> codebook.EntityRow:
    return codebook.EntityRow(person_or_body=pid, proposed=proposed, role="role", action=action,
                              stage="completed", by_whom="not_addressed", response="not_addressed", stance=0)


class FakeResponses:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def parse(self, model, instructions, input, text_format, **kwargs):
        self.inputs.append(input)
        if "Grčić" in input:
            ext = extraction(category="post_change", top_tier=True, actors=["student_list", "invented_id"],
                             entities=[entity("Manja Grčić", "resigned", proposed=False)])
        elif "Banka" in input:
            ext = extraction(category="economic_stability", actors=["vladimir_lucic"],
                             entities=[entity("vladimir_lucic", "accused", proposed=True)])
        elif "FAIL" in input:
            raise ai_client.AIError("boom")
        else:
            ext = extraction(category="legal_action", actors=["vladimir_lucic"],
                             entities=[entity("vladimir_lucic", "investigated")])
        return SimpleNamespace(output_parsed=ext)


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def article(link_id: str, story_id: str, title: str, status: str, text: str = "") -> dict:
    return dict(link_id=link_id, story_id=story_id, url=f"https://x.test/{link_id}", final_url="",
                outlet_id="n1", language="sr", title=title, text=text, text_status=status,
                chars=str(len(text)), http_status="200", fetched_at="2026-10-29T12:00:00+01:00")


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    shutil.copy(FIXTURES / "links_small.csv", tmp_path / "links.csv")
    write_csv(tmp_path / "articles.csv", ARTICLE_FIELDS, [
        article("l1", "s-rts", "Grčić podnela ostavku", "full", "Duži tekst o ostavci. " * 30),
        article("l2", "s-rts", "Grčić ostavka", "partial", "Kratko."),
        article("l5", "s-tok", "Tužilaštvo otvorilo predmet", "headline_only"),
        article("l6", "s-bank", "Banka i ostavka guvernera", "full", "Tekst o banci. " * 40),
        article("l4", "s-sport", "Đoković pobedio", "full", "Sport " * 100),
    ])
    write_csv(tmp_path / "triage.csv", ["story_id", "possibly_relevant"], [
        {"story_id": "s-rts", "possibly_relevant": "yes"}, {"story_id": "s-tok", "possibly_relevant": "yes"},
        {"story_id": "s-bank", "possibly_relevant": "yes"}, {"story_id": "s-sport", "possibly_relevant": "no"},
    ])
    return {
        "timezone": "Europe/Belgrade",
        "paths": {name: str(tmp_path / f) for name, f in {
            "links_csv": "links.csv", "articles_csv": "articles.csv", "triage_csv": "triage.csv",
            "coded_jsonl": "coded.jsonl", "coding_check_md": "coding_check.md", "status_json": "status.json"}.items()}
        | {"actors_csv": str(FIXTURES / "actors_small.csv"), "outlets_csv": str(FIXTURES / "outlets_small.csv")},
        "coding": {"model_env": "OPENAI_MODEL", "max_text_chars": 500, "max_stories_per_run": 400,
                   "temperature": None, "thread_window_days": 10, "thread_min_score": 2,
                   "thread_ignore_actors": ["student_list"]},
    }


def coded(tmp_path: Path) -> dict[str, dict]:
    with (tmp_path / "coded.jsonl").open(encoding="utf-8") as fh:
        return {r["story_id"]: r for r in map(json.loads, fh)}


def test_best_copy_prefers_full_then_longest() -> None:
    rows = [article("a", "s", "t", "partial", "x" * 900), article("b", "s", "t", "full", "x" * 500),
            article("c", "s", "t", "failed")]
    assert code.best_copy(rows)["link_id"] == "b"


def test_run_codes_triaged_stories_with_versions(cfg: dict, tmp_path: Path) -> None:
    client = FakeClient()
    assert code.run(cfg, client=client) == 3
    rows = coded(tmp_path)
    assert set(rows) == {"s-rts", "s-tok", "s-bank"}           # sport excluded by triage
    r = rows["s-rts"]
    assert (r["model"], r["prompt_version"], r["codebook_version"]) == (
        "test-model", codebook.PROMPT_VERSION, codebook.CODEBOOK_VERSION)
    assert r["source_link_id"] == "l1"                           # full copy chosen over partial
    assert "Duži tekst" in client.responses.inputs[0] or any("Duži tekst" in i for i in client.responses.inputs)
    assert all(len(i.split("\n\n", 1)[1]) <= 500 for i in client.responses.inputs)
    assert (tmp_path / "coding_check.md").exists()


def test_most_reported_story_coded_first(cfg: dict, tmp_path: Path) -> None:
    code.run(cfg, client=FakeClient(), limit=1)
    assert set(coded(tmp_path)) == {"s-rts"}                     # 3 outlets beats 1


def test_severity_from_all_copies(cfg: dict, tmp_path: Path) -> None:
    code.run(cfg, client=FakeClient())
    rows = coded(tmp_path)
    # s-rts: independent + pro-government copies, top tier -> 3, confirmed by one of each group.
    assert rows["s-rts"]["severity"] == 3 and rows["s-rts"]["confirming_link_ids"] == ["l1", "l2"]
    assert rows["s-rts"]["n_copies"] == 3
    # s-bank: one outlet group only.
    assert rows["s-bank"]["severity"] == 1


def test_actor_corrections(cfg: dict, tmp_path: Path) -> None:
    code.run(cfg, client=FakeClient())
    rts = coded(tmp_path)["s-rts"]
    assert rts["extraction"]["actors"] == ["student_list"]
    assert rts["extraction"]["entities"][0]["proposed"] is True
    assert any("invented_id" in w for w in rts["actor_warnings"])
    bank = coded(tmp_path)["s-bank"]
    assert bank["extraction"]["entities"][0]["proposed"] is False


def test_failed_story_writes_nothing_and_is_retried(cfg: dict, tmp_path: Path) -> None:
    rows = list(csv.DictReader((tmp_path / "articles.csv").open(encoding="utf-8")))
    rows[3]["title"] = "FAIL banka"
    write_csv(tmp_path / "articles.csv", ARTICLE_FIELDS, rows)
    assert code.run(cfg, client=FakeClient()) == 2
    assert "s-bank" not in coded(tmp_path)
    rows[3]["title"] = "Banka"
    write_csv(tmp_path / "articles.csv", ARTICLE_FIELDS, rows)
    assert code.run(cfg, client=FakeClient()) == 1
    assert "s-bank" in coded(tmp_path)


def test_rerun_codes_nothing_new_but_refreshes_severity(cfg: dict, tmp_path: Path) -> None:
    code.run(cfg, client=FakeClient())
    with (tmp_path / "links.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write("l9,s-bank,https://www.politika.rs/banka,politika,serbian_pro_government,3,sr,Banka,feed,"
                 "2026-10-29T13:00:00+01:00,2026-10-29T14:00:00+01:00,rss,direct,politika.rs\n")
    client = FakeClient()
    assert code.run(cfg, client=client) == 0
    assert client.responses.inputs == []
    assert coded(tmp_path)["s-bank"]["severity"] == 2 and coded(tmp_path)["s-bank"]["n_copies"] == 2


def test_spend_cap_stops_run(cfg: dict, tmp_path: Path) -> None:
    class CapClient:
        class responses:
            @staticmethod
            def parse(**kwargs):
                raise ai_client.SpendCapHit("quota")
    assert code.run(cfg, client=CapClient()) == 0
    assert not (tmp_path / "coded.jsonl").exists()


def test_rows_get_event_and_thread_ids(cfg: dict, tmp_path: Path) -> None:
    code.run(cfg, client=FakeClient())
    for row in coded(tmp_path).values():
        assert row["event_id"].startswith("e-") and row["thread_id"].startswith("t-")


def test_group_only_codes_nothing(cfg: dict, tmp_path: Path) -> None:
    code.run(cfg, client=FakeClient(), limit=1)
    client = FakeClient()
    assert code.run(cfg, client=client, group_only=True) == 0
    assert client.responses.inputs == [] and set(coded(tmp_path)) == {"s-rts"}


def test_recode_stale_replaces_old_rows_only(cfg: dict, tmp_path: Path) -> None:
    code.run(cfg, client=FakeClient())
    path = tmp_path / "coded.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["codebook_version"] = "0.0.1"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert code.run(cfg, client=FakeClient(), recode_stale=True) == 1
    after = coded(tmp_path)
    assert len(after) == 3
    assert all(r["codebook_version"] == codebook.CODEBOOK_VERSION for r in after.values())


def test_published_since_keeps_recent_stories() -> None:
    copies = {"old": [{"published": "2026-11-01T10:00:00+01:00"}],
              "new": [{"published": "2026-11-01T10:00:00+01:00"}, {"published": "2026-11-03T08:00:00+01:00"}],
              "undated": [{"published": ""}]}
    since = datetime.fromisoformat("2026-11-02T12:00:00+01:00")
    assert code.published_since(["new", "old", "undated"], copies, since) == ["new"]
