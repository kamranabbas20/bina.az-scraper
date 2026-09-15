"""Transport layer: swap how pages are fetched without touching the parsers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..config import Settings


@dataclass(slots=True)
class FetchResult:
    url: str
    status: int
    html: str
    final_url: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and bool(self.html)


class FetchError(RuntimeError):
    """Raised when a URL could not be fetched after all retries."""

    def __init__(self, url: str, message: str, status: int | None = None):
        super().__init__(f"{url}: {message}")
        self.url = url
        self.status = status


class BlockedError(FetchError):
    """Raised when the site actively refuses us (403/429, bot challenge).

    Kept separate from FetchError so the crawler can stop the run instead of
    hammering a site that has already said no.
    """


@runtime_checkable
class Fetcher(Protocol):
    def get(self, url: str) -> FetchResult: ...
    def close(self) -> None: ...


def build_fetcher(settings: Settings) -> Fetcher:
    """Instantiate the fetcher named in settings."""
    if settings.fetcher == "browser":
        from .browser import BrowserFetcher

        return BrowserFetcher(settings)
    from .http import HttpFetcher

    return HttpFetcher(settings)


__all__ = [
    "BlockedError",
    "FetchError",
    "FetchResult",
    "Fetcher",
    "build_fetcher",
]
