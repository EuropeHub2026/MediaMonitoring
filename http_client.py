"""Polite HTTP access shared by the collectors and the text extractor.

Enforces the CLAUDE.md rules: a User-Agent naming the project and a contact address, at
least `min_seconds_between_requests_per_domain` between requests to one domain, retries
only on transient server errors, and no retries on 403 or 429. After a 403 or 429 the
domain is left alone for the rest of the run.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

import config

log = logging.getLogger(__name__)

NO_RETRY_STATUSES = frozenset({403, 429})


def domain_of(url: str) -> str:
    """Return the host of `url`, lower-cased, without a leading 'www.'."""
    host = urlsplit(url).netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


class PoliteSession:
    """A requests session with per-domain spacing, limited retries and a run-level block list."""

    def __init__(
        self,
        cfg: dict[str, Any],
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        http = cfg["http"]
        self.min_interval = float(http["min_seconds_between_requests_per_domain"])
        self.timeout = float(http.get("timeout_seconds", 20))
        self.retry_statuses = set(http.get("retry_statuses", [])) - NO_RETRY_STATUSES
        self.max_retries = int(http.get("max_retries", 0))
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = config.user_agent(cfg)
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}
        self.blocked: set[str] = set()

    def _wait_for(self, domain: str) -> None:
        """Sleep until the minimum interval for `domain` has passed."""
        last = self._last_request.get(domain)
        if last is not None:
            remaining = self.min_interval - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[domain] = self._clock()

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response | None:
        """Send a request politely; return the response, or None if skipped or failed."""
        domain = domain_of(url)
        if domain in self.blocked:
            log.info("Skipping %s: %s refused an earlier request this run", url, domain)
            return None
        kwargs.setdefault("timeout", self.timeout)
        for attempt in range(self.max_retries + 1):
            self._wait_for(domain)
            try:
                response = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                log.warning("%s %s failed: %s", method, url, exc)
                return None
            if response.status_code in NO_RETRY_STATUSES:
                log.warning("%s returned %s; no retry, leaving %s alone this run", url, response.status_code, domain)
                self.blocked.add(domain)
                return response
            if response.status_code in self.retry_statuses and attempt < self.max_retries:
                log.info("%s returned %s; retry %d", url, response.status_code, attempt + 1)
                continue
            return response
        return None

    def get(self, url: str, **kwargs: Any) -> requests.Response | None:
        """GET `url` politely."""
        return self.request("GET", url, **kwargs)
