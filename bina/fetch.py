"""HTTP fetching: polite by default, stdlib only.

Defaults chosen so a run cannot accidentally hammer the site: one request per
second with jitter, a real User-Agent, bounded retries with exponential
backoff, and ``robots.txt`` honoured unless explicitly overridden.
"""

from __future__ import annotations

import gzip
import logging
import random
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

log = logging.getLogger("bina.fetch")

DEFAULT_USER_AGENT = (
    "bina-az-scraper/1.0 (+https://github.com/kamranabbas20/bina.az-scraper) "
    "Python-urllib"
)

RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """A request failed after exhausting retries, or was refused outright."""


class RobotsDisallowed(FetchError):
    """robots.txt forbids this path for our User-Agent."""


@dataclass
class FetchConfig:
    user_agent: str = DEFAULT_USER_AGENT
    delay: float = 1.0  # seconds between requests
    jitter: float = 0.4  # +/- fraction of delay
    timeout: float = 30.0
    max_retries: int = 4
    backoff_base: float = 2.0
    obey_robots: bool = True
    accept_language: str = "az,en;q=0.8,ru;q=0.6"


class Fetcher:
    """A rate-limited, retrying GET client for one site."""

    def __init__(self, config: Optional[FetchConfig] = None):
        self.config = config or FetchConfig()
        self._last_request = 0.0
        self._robots: dict[str, Optional[RobotFileParser]] = {}
        self.requests_made = 0

    # -- public ----------------------------------------------------------

    def get(self, url: str) -> str:
        if self.config.obey_robots and not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")

        last_error: Optional[Exception] = None
        for attempt in range(self.config.max_retries + 1):
            self._wait_turn()
            try:
                return self._request(url)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in RETRY_STATUS:
                    raise FetchError(f"HTTP {exc.code} for {url}") from exc
                wait = self._retry_wait(attempt, exc.headers.get("Retry-After"))
                log.warning("HTTP %s for %s — retrying in %.1fs", exc.code, url, wait)
                time.sleep(wait)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = exc
                wait = self._retry_wait(attempt, None)
                log.warning("%s for %s — retrying in %.1fs", exc, url, wait)
                time.sleep(wait)

        raise FetchError(f"gave up on {url} after {self.config.max_retries} retries: {last_error}")

    def allowed(self, url: str) -> bool:
        robots = self._robots_for(url)
        if robots is None:
            # robots.txt unreachable: treat as permissive, matching the
            # convention, but the caller has already been rate-limited.
            return True
        return robots.can_fetch(self.config.user_agent, url)

    def crawl_delay(self, url: str) -> Optional[float]:
        robots = self._robots_for(url)
        if robots is None:
            return None
        try:
            value = robots.crawl_delay(self.config.user_agent)
        except Exception:  # pragma: no cover - defensive
            return None
        return float(value) if value else None

    def apply_robots_delay(self, url: str) -> None:
        """Raise our delay to robots.txt's Crawl-delay when it asks for more."""
        wanted = self.crawl_delay(url)
        if wanted and wanted > self.config.delay:
            log.info("robots.txt Crawl-delay=%ss — slowing down", wanted)
            self.config.delay = wanted

    # -- internals -------------------------------------------------------

    def _request(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.config.user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": self.config.accept_language,
                "Accept-Encoding": "gzip, deflate",
                "Connection": "close",
            },
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
            raw = response.read()
            encoding = (response.headers.get("Content-Encoding") or "").lower()
            charset = response.headers.get_content_charset() or "utf-8"
        self.requests_made += 1

        if encoding == "gzip":
            raw = gzip.decompress(raw)
        elif encoding == "deflate":
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)

        return raw.decode(charset, errors="replace")

    def _wait_turn(self) -> None:
        if self.config.delay <= 0:
            return
        spread = self.config.delay * self.config.jitter
        target = self.config.delay + random.uniform(-spread, spread)
        elapsed = time.monotonic() - self._last_request
        if elapsed < target:
            time.sleep(target - elapsed)
        self._last_request = time.monotonic()

    def _retry_wait(self, attempt: int, retry_after: Optional[str]) -> float:
        if retry_after:
            try:
                return min(float(retry_after), 120.0)
            except ValueError:
                pass
        return self.config.backoff_base ** attempt

    def _robots_for(self, url: str) -> Optional[RobotFileParser]:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]

        parser = RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        try:
            # read() goes through urllib directly; give it our UA via opener.
            request = urllib.request.Request(
                f"{origin}/robots.txt", headers={"User-Agent": self.config.user_agent}
            )
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                parser.parse(response.read().decode("utf-8", errors="replace").splitlines())
        except Exception as exc:
            log.warning("could not read %s/robots.txt (%s) — proceeding", origin, exc)
            self._robots[origin] = None
            return None

        self._robots[origin] = parser
        return parser
