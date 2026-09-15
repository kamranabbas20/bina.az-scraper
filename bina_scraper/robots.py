"""robots.txt handling.

Fetched through the configured fetcher so it goes over the same transport and
User-Agent as the crawl itself.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from .fetchers import BlockedError, FetchError, Fetcher

log = logging.getLogger(__name__)


class RobotsPolicy:
    """Allow/deny decisions for one host.

    ``strict`` decides what happens when robots.txt cannot be read at all: the
    default is to refuse, because a crawl that silently ignores an unreadable
    policy is the thing robots.txt exists to prevent.
    """

    def __init__(self, user_agent: str, *, enabled: bool = True, strict: bool = True):
        self.user_agent = user_agent
        self.enabled = enabled
        self.strict = strict
        self._parsers: dict[str, RobotFileParser | None] = {}

    def _parser_for(self, url: str, fetcher: Fetcher) -> RobotFileParser | None:
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        if root in self._parsers:
            return self._parsers[root]

        parser: RobotFileParser | None = None
        try:
            result = fetcher.get(urljoin(root, "/robots.txt"))
            if result.status == 404:
                # No robots.txt means no restrictions.
                parser = RobotFileParser()
                parser.parse([])
            elif result.ok:
                parser = RobotFileParser()
                parser.parse(result.html.splitlines())
            else:
                log.warning("robots.txt for %s returned HTTP %s", root, result.status)
        except BlockedError:
            # The site is refusing us outright; that is the crawl's problem to
            # report, not something to paper over as a robots decision.
            raise
        except FetchError as exc:
            log.warning("could not read robots.txt for %s: %s", root, exc)

        self._parsers[root] = parser
        return parser

    def allows(self, url: str, fetcher: Fetcher) -> bool:
        if not self.enabled:
            return True
        parser = self._parser_for(url, fetcher)
        if parser is None:
            if self.strict:
                log.error(
                    "could not read robots.txt for %s, so its crawl policy is unknown; "
                    "refusing. Set respect_robots: false only if you know the policy "
                    "permits what you are doing.",
                    url,
                )
                return False
            return True
        return parser.can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str, fetcher: Fetcher) -> float | None:
        """The host's declared Crawl-delay, if any."""
        parser = self._parser_for(url, fetcher) if self.enabled else None
        if parser is None:
            return None
        try:
            value = parser.crawl_delay(self.user_agent)
        except Exception:  # pragma: no cover - parser quirks
            return None
        return float(value) if value is not None else None
