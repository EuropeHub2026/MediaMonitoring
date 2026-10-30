"""Tests for http_client.PoliteSession: spacing, retries and the 403/429 rule."""

from types import SimpleNamespace

import pytest

import http_client


class FakeRequests:
    """Stands in for requests.Session; returns queued status codes per call."""

    def __init__(self, statuses: list[int]) -> None:
        self.statuses = list(statuses)
        self.calls: list[str] = []
        self.headers: dict[str, str] = {}

    def request(self, method: str, url: str, **kwargs):
        self.calls.append(url)
        return SimpleNamespace(status_code=self.statuses.pop(0), content=b"")


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


@pytest.fixture
def cfg() -> dict:
    return {
        "project": {"user_agent_name": "Test/0", "repo_url": "https://x.test", "contact_email": "a@b.test"},
        "http": {"min_seconds_between_requests_per_domain": 2, "retry_statuses": [503, 429], "max_retries": 2},
    }


def make(cfg: dict, statuses: list[int]):
    fake, clock = FakeRequests(statuses), Clock()
    return http_client.PoliteSession(cfg, session=fake, sleep=clock.sleep, clock=clock.now), fake, clock


def test_domain_of() -> None:
    assert http_client.domain_of("https://www.N1info.rs:443/x") == "n1info.rs"


def test_user_agent_set(cfg: dict) -> None:
    s, fake, _ = make(cfg, [])
    assert "a@b.test" in fake.headers["User-Agent"]


def test_spacing_per_domain(cfg: dict) -> None:
    s, fake, clock = make(cfg, [200, 200, 200])
    s.get("https://a.test/1")
    s.get("https://b.test/1")
    s.get("https://a.test/2")
    assert clock.slept == [2.0]


def test_no_retry_on_403_and_domain_blocked(cfg: dict) -> None:
    s, fake, _ = make(cfg, [403])
    assert s.get("https://a.test/1").status_code == 403
    assert s.get("https://a.test/2") is None
    assert fake.calls == ["https://a.test/1"]
    assert "a.test" in s.blocked


def test_429_never_retried_even_if_configured(cfg: dict) -> None:
    s, fake, _ = make(cfg, [429])
    s.get("https://a.test/1")
    assert len(fake.calls) == 1


def test_retry_on_503_then_success(cfg: dict) -> None:
    s, fake, clock = make(cfg, [503, 200])
    assert s.get("https://a.test/1").status_code == 200
    assert len(fake.calls) == 2
    assert clock.slept == [2.0]


def test_gives_up_after_max_retries(cfg: dict) -> None:
    s, fake, _ = make(cfg, [503, 503, 503])
    assert s.get("https://a.test/1").status_code == 503
    assert len(fake.calls) == 3
