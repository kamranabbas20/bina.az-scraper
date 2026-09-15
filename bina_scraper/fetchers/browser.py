"""Playwright fetcher, for pages that need JavaScript to render.

This drives a normal Chromium build and nothing more: no fingerprint patching,
no challenge solvers. If bina.az blocks the network you run from, this fetcher
will report that block rather than work around it.
"""

from __future__ import annotations

import logging
import random
import time

from ..config import Settings
from . import BlockedError, FetchError, FetchResult
from .http import looks_like_challenge

log = logging.getLogger(__name__)


class BrowserFetcher:
    """Lazily starts one browser context and reuses it for every page."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._playwright = None
        self._browser = None
        self._context = None

    def _ensure_started(self) -> None:
        if self._context is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise FetchError(
                "-",
                "the browser fetcher needs Playwright: "
                "pip install -r requirements-browser.txt && playwright install chromium",
            ) from exc

        self._playwright = sync_playwright().start()
        launch_kwargs: dict[str, object] = {"headless": self.settings.headless}
        if self.settings.browser_executable:
            launch_kwargs["executable_path"] = self.settings.browser_executable
        if self.settings.proxy:
            launch_kwargs["proxy"] = {"server": self.settings.proxy}
        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(
            locale="az-AZ",
            user_agent=self.settings.effective_user_agent(),
            viewport={"width": 1366, "height": 900},
        )
        self._context.set_default_timeout(self.settings.timeout * 1000)

    def get(self, url: str) -> FetchResult:
        self._ensure_started()
        assert self._context is not None
        last_error = "no attempt made"
        for attempt in range(1, self.settings.max_retries + 1):
            page = self._context.new_page()
            try:
                response = page.goto(url, wait_until="domcontentloaded")
                status = response.status if response else 0
                if self.settings.browser_wait_selector:
                    try:
                        page.wait_for_selector(self.settings.browser_wait_selector)
                    except Exception:
                        log.warning("wait selector never appeared on %s", url)
                if self.settings.browser_wait_ms:
                    page.wait_for_timeout(self.settings.browser_wait_ms)
                html = page.content()
                final_url = page.url
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("browser fetch failed (%s/%s) %s: %s", attempt, self.settings.max_retries, url, exc)
                page.close()
                self._sleep_backoff(attempt)
                continue
            finally:
                if not page.is_closed():
                    page.close()

            if status in (403, 429) or looks_like_challenge(html):
                raise BlockedError(
                    url,
                    f"the site refused the request (HTTP {status}). "
                    "This is an IP/network-level block or an unsolved bot check; "
                    "run from a network bina.az serves.",
                    status=status,
                )
            return FetchResult(url=url, status=status or 200, html=html, final_url=final_url)
        raise FetchError(url, f"giving up after {self.settings.max_retries} attempts ({last_error})")

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self.settings.backoff_factor ** (attempt - 1)
        time.sleep(delay + random.uniform(0, self.settings.jitter))

    def close(self) -> None:
        for resource in (self._context, self._browser, self._playwright):
            if resource is None:
                continue
            try:
                closer = getattr(resource, "close", None) or getattr(resource, "stop", None)
                if closer:
                    closer()
            except Exception:  # pragma: no cover - best-effort teardown
                log.debug("failed to close %r", resource, exc_info=True)
        self._context = self._browser = self._playwright = None
