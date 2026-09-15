"""Plain HTTP fetcher built on requests, with retries and backoff."""

from __future__ import annotations

import logging
import random
import time

import requests

from ..config import Settings
from . import BlockedError, FetchError, FetchResult

log = logging.getLogger(__name__)

# Markers of a Cloudflare interstitial served with a 200/403 and no content.
_CHALLENGE_MARKERS = (
    "Just a moment...",
    "cf_chl_opt",
    "Attention Required! | Cloudflare",
    "Enable JavaScript and cookies to continue",
)

_RETRY_STATUS = {408, 425, 500, 502, 503, 504}


def looks_like_challenge(html: str) -> bool:
    """True when the body is a bot-check page rather than the real content."""
    head = html[:4000]
    return any(marker in head for marker in _CHALLENGE_MARKERS)


class HttpFetcher:
    """One requests.Session for the whole run, so cookies persist."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.effective_user_agent(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "az,en;q=0.8,ru;q=0.6",
                "Connection": "keep-alive",
            }
        )
        if settings.proxy:
            self.session.proxies.update({"http": settings.proxy, "https": settings.proxy})

    def get(self, url: str) -> FetchResult:
        last_error: str = "no attempt made"
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                response = self.session.get(url, timeout=self.settings.timeout)
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("fetch failed (%s/%s) %s: %s", attempt, self.settings.max_retries, url, exc)
                self._sleep_backoff(attempt)
                continue

            if response.status_code in (403, 429) or looks_like_challenge(response.text):
                raise BlockedError(
                    url,
                    f"blocked by the site (HTTP {response.status_code}). "
                    "The HTTP fetcher cannot pass a JavaScript bot check; "
                    "try --fetcher browser from an un-blocked network.",
                    status=response.status_code,
                )

            if response.status_code in _RETRY_STATUS:
                last_error = f"HTTP {response.status_code}"
                log.warning("retryable status %s for %s", response.status_code, url)
                self._sleep_backoff(attempt)
                continue

            return FetchResult(
                url=url,
                status=response.status_code,
                html=response.text,
                final_url=response.url,
            )
        raise FetchError(url, f"giving up after {self.settings.max_retries} attempts ({last_error})")

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self.settings.backoff_factor ** (attempt - 1)
        time.sleep(delay + random.uniform(0, self.settings.jitter))

    def close(self) -> None:
        self.session.close()
