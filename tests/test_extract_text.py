"""Tests for 2_extract_text.py: triage with a fake AI client, text extraction from fixtures."""

import csv
import importlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import codebook

extract = importlib.import_module("2_extract_text")

FIXTURES = Path(__file__).parent / "fixtures"
HTML = (FIXTURES / "article_n1.html").read_bytes()


class FakeResponses:
    """Marks headlines containing 'ostavk' as possibly relevant; can be told to fail or drop ids."""

    def __init__(self, drop_id: bool = False) -> None:
        self.calls = 0
        self.drop_id = drop_id

    def parse(self, model, instructions, input, text_format, **kwargs):
        self.calls += 1
        lines = [line.split("\t", 1) for line in input.splitlines()]
        items = [codebook.TriageItem(id=i, possibly_relevant="ostavk" in t.lower()) for i, t in lines]
        if self.drop_id:
            items = items[1:]
        return SimpleNamespace(output_parsed=text_format(items=items))


class FakeClient:
    def __init__(self, **kw) -> None:
        self.responses = FakeResponses(**kw)


class FakeSession:
    """Serves the fixture page for n1 and danas URLs; 403 for kurir; 503 for alo."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.blocked: set[str] = set()

    def get(self, url: str):
        self.calls.append(url)
        if "kurir" in url:
            return SimpleNamespace(status_code=403, content=b"", url=url)
        if "alo.rs" in url:
            return SimpleNamespace(status_code=503, content=b"", url=url)
        return SimpleNamespace(status_code=200, content=HTML, url=url)


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    shutil.copy(FIXTURES / "links_small.csv", tmp_path / "links.csv")
    return {
        "timezone": "Europe/Belgrade",
        "paths": {
            "links_csv": str(tmp_path / "links.csv"),
            "triage_csv": str(tmp_path / "triage.csv"),
            "articles_csv": str(tmp_path / "articles.csv"),
            "outlets_csv": str(FIXTURES / "outlets_small.csv"),
            "status_json": str(tmp_path / "status.json"),
        },
        "triage": {"model_env": "OPENAI_MODEL", "batch_size": 2},
        "extract": {"max_copies_per_story": 2, "min_text_chars": 400, "max_html_bytes": 3000000},
        "coding": {"temperature": None},
    }


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# --- Helpers -------------------------------------------------------------------------------


def test_detect_language() -> None:
    assert extract.detect_language("Ово је вест " * 20, "en") == "sr"
    assert extract.detect_language("The minister said that the government is in talks with the EU " * 3, "sr") == "en"
    assert extract.detect_language("Generalna direktorka je podnela ostavku i to je za javni servis od značaja kao i da se " * 2, "en") == "sr"
    assert extract.detect_language("RTS", "sr") == "sr"


def test_text_status() -> None:
    assert extract.text_status("x" * 500, "no", 400) == "full"
    assert extract.text_status("x" * 100, "no", 400) == "partial"
    assert extract.text_status("x" * 500, "yes", 400) == "partial"
    assert extract.text_status("Before you continue to Google" + "x" * 500, "no", 400) == "junk"


def test_extract_from_fixture() -> None:
    title, text = extract.extract(HTML, "https://n1info.rs/vesti/grcic-ostavka/")
    assert title == "Manja Grčić podnela ostavku na mesto generalne direktorke RTS-a"
    assert "primopredaja" in text and "Početna" not in text


def test_story_headline_prefers_reach_and_real_titles() -> None:
    links = read(FIXTURES / "links_small.csv")
    assert extract.story_headlines(links)["s-rts"]["link_id"] == "l1"


def test_interleave_by_domain() -> None:
    rows = [{"url": u} for u in ["https://a.test/1", "https://a.test/2", "https://b.test/1"]]
    assert [r["url"] for r in extract.interleave_by_domain(rows)] == ["https://a.test/1", "https://b.test/1", "https://a.test/2"]


# --- Triage --------------------------------------------------------------------------------


def test_triage_writes_versions_and_skips_done(cfg: dict, tmp_path: Path) -> None:
    links = read(tmp_path / "links.csv")
    client = FakeClient()
    assert extract.run_triage(cfg, links, client) == 4
    rows = {r["story_id"]: r for r in read(tmp_path / "triage.csv")}
    assert rows["s-rts"]["possibly_relevant"] == "yes" and rows["s-sport"]["possibly_relevant"] == "no"
    assert rows["s-rts"]["model"] == "test-model"
    assert rows["s-rts"]["codebook_version"] == codebook.CODEBOOK_VERSION
    assert rows["s-rts"]["triage_prompt_version"] == codebook.TRIAGE_PROMPT_VERSION
    calls = client.responses.calls
    assert extract.run_triage(cfg, links, client) == 0
    assert client.responses.calls == calls


def test_triage_batch_with_missing_ids_writes_nothing(cfg: dict, tmp_path: Path) -> None:
    links = read(tmp_path / "links.csv")
    assert extract.run_triage(cfg, links, FakeClient(drop_id=True)) == 0
    assert not (tmp_path / "triage.csv").exists()


# --- Text ----------------------------------------------------------------------------------


def test_run_end_to_end(cfg: dict, tmp_path: Path) -> None:
    session = FakeSession()
    extract.run(cfg, client=FakeClient(), session=session)
    arts = read(tmp_path / "articles.csv")
    by_link = {a["link_id"]: a for a in arts}

    # Sport story not fetched; RTS story: best two copies (n1 reach 3, then alo/kurir reach 2).
    assert "l4" not in by_link
    assert by_link["l1"]["text_status"] == "full" and by_link["l1"]["language"] == "sr"
    assert int(by_link["l1"]["chars"]) > 400
    assert len([a for a in arts if a["story_id"] == "s-rts"]) == 2
    # Google-only story gets a headline-only row; nothing fetched from news.google.com.
    assert by_link["l5"]["text_status"] == "headline_only"
    assert not any("news.google.com" in c for c in session.calls)


def test_rerun_retries_transient_failures_only(cfg: dict, tmp_path: Path) -> None:
    extract.run(cfg, client=FakeClient(), session=FakeSession())
    failed = {a["link_id"]: a["http_status"] for a in read(tmp_path / "articles.csv") if a["text_status"] == "failed"}
    second = FakeSession()
    extract.run(cfg, client=FakeClient(), session=second)
    retried = {c for c in second.calls}
    for lid, status in failed.items():
        url = next(r["url"] for r in read(tmp_path / "links.csv") if r["link_id"] == lid)
        assert (url in retried) == (status == "503")
    assert not any("n1info.rs/vesti" in c for c in second.calls)


def test_skip_triage_needs_no_client(cfg: dict, tmp_path: Path) -> None:
    extract.run(cfg, session=FakeSession(), skip_triage=True, limit=1)
    assert not (tmp_path / "triage.csv").exists()
    assert len([a for a in read(tmp_path / "articles.csv") if a["text_status"] != "headline_only"]) == 1
