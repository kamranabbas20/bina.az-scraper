"""Small helpers over BeautifulSoup for selector candidate lists."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from bs4 import BeautifulSoup, Tag

from .normalize import clean_text


def make_soup(html: str) -> BeautifulSoup:
    """Parse with lxml, falling back to the stdlib parser if it is missing."""
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # pragma: no cover - only when lxml is absent
        return BeautifulSoup(html, "html.parser")


def select_first(node: Tag | BeautifulSoup, candidates: Sequence[str]) -> Tag | None:
    """Return the first element matched by any candidate selector."""
    for selector in candidates:
        found = node.select_one(selector)
        if found is not None:
            return found
    return None


def select_all(node: Tag | BeautifulSoup, candidates: Sequence[str]) -> list[Tag]:
    """Return matches from the first candidate selector that matches anything."""
    for selector in candidates:
        found = node.select(selector)
        if found:
            return found
    return []


def text_of(node: Tag | BeautifulSoup | None, candidates: Sequence[str] | None = None) -> str | None:
    """Text of ``node``, or of the first element in it matching ``candidates``."""
    if node is None:
        return None
    target = node if candidates is None else select_first(node, candidates)
    if target is None:
        return None
    return clean_text(target.get_text(" ", strip=True))


def attr_of(
    node: Tag | BeautifulSoup | None,
    candidates: Sequence[str],
    attrs: Iterable[str],
) -> str | None:
    """First present attribute among ``attrs`` on the first matching element."""
    if node is None:
        return None
    target = select_first(node, candidates)
    if target is None:
        return None
    for attr in attrs:
        value = target.get(attr)
        if isinstance(value, list):
            value = value[0] if value else None
        if value:
            return clean_text(str(value))
    return None
