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
                "outlets_csv": "outlets.csv", "status_json": "status.json", "coded_jsonl": "coded.jsonl"}.items()}}


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
