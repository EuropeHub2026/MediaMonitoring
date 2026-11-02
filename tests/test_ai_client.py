"""Tests for ai_client.parse_structured with fake clients; no API calls."""

import json
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest

import ai_client
import codebook


def make_error(cls, message: str):
    exc = cls.__new__(cls)
    Exception.__init__(exc, message)
    return exc


class Client:
    def __init__(self, result=None, error=None) -> None:
        self.result, self.error, self.kwargs = result, error, None
        self.responses = self

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(output_parsed=self.result)


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    return {"timezone": "Europe/Belgrade", "paths": {"status_json": str(tmp_path / "status.json")},
            "coding": {"temperature": None}}


def test_returns_parsed_and_model(cfg: dict) -> None:
    batch = codebook.TriageBatch(items=[])
    client = Client(result=batch)
    parsed, model = ai_client.parse_structured(cfg, client, "OPENAI_MODEL", "i", "u", codebook.TriageBatch)
    assert parsed is batch and model == "test-model"
    assert "temperature" not in client.kwargs


def test_usage_logged(caplog: pytest.LogCaptureFixture) -> None:
    usage = SimpleNamespace(input_tokens=100, output_tokens=50,
                            input_tokens_details=SimpleNamespace(cached_tokens=10),
                            output_tokens_details=SimpleNamespace(reasoning_tokens=20))
    with caplog.at_level("INFO", logger="ai_client"):
        ai_client.log_usage("test-model", SimpleNamespace(usage=usage))
    assert "usage model=test-model input=100 cached=10 output=50 reasoning=20" in caplog.text


def test_response_without_usage_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="ai_client"):
        ai_client.log_usage("test-model", SimpleNamespace())
    assert not caplog.text


def test_temperature_passed_when_set(cfg: dict) -> None:
    cfg["coding"]["temperature"] = 0
    client = Client(result=codebook.TriageBatch(items=[]))
    ai_client.parse_structured(cfg, client, "OPENAI_MODEL", "i", "u", codebook.TriageBatch)
    assert client.kwargs["temperature"] == 0


def test_spend_cap_recorded(cfg: dict, tmp_path: Path) -> None:
    client = Client(error=make_error(openai.RateLimitError, "Error code: 429 insufficient_quota"))
    with pytest.raises(ai_client.SpendCapHit):
        ai_client.parse_structured(cfg, client, "OPENAI_MODEL", "i", "u", codebook.TriageBatch)
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["openai"]["state"] == "cap_hit"


def test_plain_rate_limit_is_ai_error_not_cap(cfg: dict, tmp_path: Path) -> None:
    client = Client(error=make_error(openai.RateLimitError, "Rate limit reached for requests"))
    with pytest.raises(ai_client.AIError) as info:
        ai_client.parse_structured(cfg, client, "OPENAI_MODEL", "i", "u", codebook.TriageBatch)
    assert not isinstance(info.value, ai_client.SpendCapHit)
    assert not (tmp_path / "status.json").exists()


def test_refusal_is_ai_error(cfg: dict) -> None:
    with pytest.raises(ai_client.AIError):
        ai_client.parse_structured(cfg, Client(result=None), "OPENAI_MODEL", "i", "u", codebook.TriageBatch)


def test_missing_model_env_raises(cfg: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_MODEL")
    with pytest.raises(Exception):
        ai_client.parse_structured(cfg, Client(), "OPENAI_MODEL", "i", "u", codebook.TriageBatch)
