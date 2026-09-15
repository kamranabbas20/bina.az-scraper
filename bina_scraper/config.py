"""Runtime configuration, loaded from YAML and overridable per CLI flag."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from . import selectors as sel

DEFAULT_USER_AGENT = (
    "bina-az-scraper/0.1 (+https://github.com/kamranabbas20/bina.az-scraper; "
    "contact: set contact_email in config)"
)


@dataclass
class Settings:
    """Everything that changes between runs.

    Defaults are deliberately slow and shallow: a first run should be cheap for
    the site, and widening it should be an explicit choice.
    """

    # What to crawl
    deal_type: str = "sale"
    search_path: str | None = None  # overrides deal_type when set
    query_params: dict[str, Any] = field(default_factory=dict)
    start_page: int = 1
    max_pages: int = 1
    max_items: int | None = None
    fetch_details: bool = True
    # Pagination follows the "page" query parameter by default; set this to
    # follow the site's own "next" link instead (one fewer assumption about the
    # URL scheme, one more selector that can go stale).
    follow_next_link: bool = False

    # Transport
    fetcher: str = "http"  # "http" | "browser"
    base_url: str = sel.BASE_URL
    user_agent: str = DEFAULT_USER_AGENT
    contact_email: str | None = None
    timeout: float = 30.0
    proxy: str | None = None

    # Politeness
    delay: float = 2.0
    jitter: float = 1.0
    max_retries: int = 3
    backoff_factor: float = 2.0
    respect_robots: bool = True

    # Output
    output: str = "data/listings.jsonl"
    seen_file: str | None = None
    resume: bool = True
    save_html_dir: str | None = None

    # Browser fetcher only
    headless: bool = True
    browser_executable: str | None = None
    browser_wait_selector: str | None = None
    browser_wait_ms: int = 1500

    log_level: str = "INFO"

    def search_url_path(self) -> str:
        if self.search_path:
            return self.search_path
        try:
            return sel.SEARCH_PATHS[self.deal_type]
        except KeyError:
            raise ValueError(
                f"unknown deal_type {self.deal_type!r}; "
                f"expected one of {sorted(sel.SEARCH_PATHS)}"
            ) from None

    def effective_user_agent(self) -> str:
        if self.contact_email:
            return (
                "bina-az-scraper/0.1 "
                f"(+https://github.com/kamranabbas20/bina.az-scraper; contact: {self.contact_email})"
            )
        return self.user_agent

    def validate(self) -> None:
        self.search_url_path()
        if self.fetcher not in {"http", "browser"}:
            raise ValueError(f"unknown fetcher {self.fetcher!r}; expected 'http' or 'browser'")
        if self.delay < 0 or self.jitter < 0:
            raise ValueError("delay and jitter must be >= 0")
        if self.max_pages < 1:
            raise ValueError("max_pages must be >= 1")
        if self.start_page < 1:
            raise ValueError("start_page must be >= 1")


def _coerce(name: str, value: Any) -> Any:
    """Coerce a YAML/CLI value to the declared field type."""
    types = {f.name: f.type for f in fields(Settings)}
    declared = str(types.get(name, ""))
    if value is None or "dict" in declared:
        return value
    if "bool" in declared and not isinstance(value, bool):
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if "int" in declared and "dict" not in declared:
        return int(value)
    if "float" in declared:
        return float(value)
    return value


def load_settings(path: str | os.PathLike[str] | None = None, **overrides: Any) -> Settings:
    """Build Settings from an optional YAML file plus keyword overrides.

    Unknown keys in the file are rejected rather than ignored, so a typo in
    ``config.yml`` fails loudly instead of silently changing nothing.
    """
    data: dict[str, Any] = {}
    if path:
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"config file not found: {config_path}")
        import yaml

        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{config_path} must contain a YAML mapping")
        data.update(loaded)

    data.update({k: v for k, v in overrides.items() if v is not None})

    known = {f.name for f in fields(Settings)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(f"unknown config keys: {', '.join(unknown)}")

    settings = Settings(**{k: _coerce(k, v) for k, v in data.items()})
    settings.validate()
    return settings
