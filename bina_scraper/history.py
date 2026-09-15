"""Read an observation log back: timelines, price changes, summaries.

An observation log is only worth its size if you can ask it questions, and the
one it exists to answer is "what did this listing's price do". These are pure
functions over the parsed records so they are testable without a crawl.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

Record = dict[str, Any]


def load_observations(path: str | Path) -> list[Record]:
    """Parse a JSONL file, skipping unreadable lines rather than failing."""
    records: list[Record] = []
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                log.warning("%s:%s is not valid JSON; ignoring it", file_path, line_number)
                continue
            if isinstance(record, dict) and record.get("item_id") is not None:
                records.append(record)
    return records


def group_by_item(records: Iterable[Record]) -> dict[str, list[Record]]:
    """Group observations by item id, each list oldest first.

    Records with no ``scraped_at`` sort first; they are older data from before
    the field existed, or a hand-edited file.
    """
    grouped: dict[str, list[Record]] = {}
    for record in records:
        grouped.setdefault(str(record["item_id"]), []).append(record)
    for observations in grouped.values():
        observations.sort(key=lambda r: str(r.get("scraped_at") or ""))
    return grouped


@dataclass
class PriceChange:
    item_id: str
    old_price: float | None
    new_price: float | None
    currency: str | None
    observed_at: str | None
    previous_at: str | None

    @property
    def delta(self) -> float | None:
        if self.old_price is None or self.new_price is None:
            return None
        return self.new_price - self.old_price

    @property
    def pct(self) -> float | None:
        delta = self.delta
        if delta is None or not self.old_price:
            return None
        return delta / self.old_price * 100.0

    def describe(self) -> str:
        arrow = "→"
        if self.delta is None:
            change = ""
        elif self.pct is None:
            change = f"  ({self.delta:+,.0f})"
        else:
            change = f"  ({self.delta:+,.0f}, {self.pct:+.1f}%)"
        return (
            f"{self.item_id}  {self.old_price:,.0f} {arrow} {self.new_price:,.0f} "
            f"{self.currency or ''}{change}  on {self.observed_at}"
        )


def price_changes(records: Iterable[Record]) -> list[PriceChange]:
    """Every price move in the log, oldest first.

    A change is only reported between two observations that both carry a price,
    so a listing switching to "price on request" (which parses to null) does
    not register as a drop to zero.
    """
    changes: list[PriceChange] = []
    for item_id, observations in group_by_item(records).items():
        previous: Record | None = None
        for observation in observations:
            if previous is not None:
                old, new = previous.get("price"), observation.get("price")
                if old is not None and new is not None and old != new:
                    changes.append(
                        PriceChange(
                            item_id=item_id,
                            old_price=float(old),
                            new_price=float(new),
                            currency=observation.get("currency") or previous.get("currency"),
                            observed_at=observation.get("scraped_at"),
                            previous_at=previous.get("scraped_at"),
                        )
                    )
            previous = observation
    changes.sort(key=lambda c: str(c.observed_at or ""))
    return changes


@dataclass
class Summary:
    observations: int = 0
    items: int = 0
    first_seen: str | None = None
    last_seen: str | None = None
    items_with_multiple_observations: int = 0
    price_changes: int = 0
    currencies: dict[str, int] = field(default_factory=dict)

    def describe(self) -> str:
        lines = [
            f"observations:            {self.observations}",
            f"distinct listings:       {self.items}",
            f"window:                  {self.first_seen or '?'} .. {self.last_seen or '?'}",
            f"listings seen more once: {self.items_with_multiple_observations}",
            f"price changes:           {self.price_changes}",
        ]
        if self.currencies:
            breakdown = ", ".join(
                f"{code}={count}" for code, count in sorted(self.currencies.items())
            )
            lines.append(f"currencies:              {breakdown}")
        return "\n".join(lines)


def summarize(records: list[Record]) -> Summary:
    grouped = group_by_item(records)
    stamps = sorted(str(r["scraped_at"]) for r in records if r.get("scraped_at"))
    currencies: dict[str, int] = {}
    for record in records:
        code = record.get("currency")
        if code:
            currencies[str(code)] = currencies.get(str(code), 0) + 1
    return Summary(
        observations=len(records),
        items=len(grouped),
        first_seen=stamps[0] if stamps else None,
        last_seen=stamps[-1] if stamps else None,
        items_with_multiple_observations=sum(1 for obs in grouped.values() if len(obs) > 1),
        price_changes=len(price_changes(records)),
        currencies=currencies,
    )


def format_timeline(item_id: str, observations: list[Record]) -> str:
    """One listing's observations, oldest first, marking what moved."""
    if not observations:
        return f"{item_id}: no observations"

    lines = [f"{item_id}  ({len(observations)} observations)"]
    title = next((o.get("title") for o in reversed(observations) if o.get("title")), None)
    if title:
        lines.append(f"  {title}")
    previous: Record | None = None
    for observation in observations:
        price = observation.get("price")
        shown = f"{price:,.0f} {observation.get('currency') or ''}".strip() if price is not None else "—"
        marks: list[str] = []
        if previous is not None:
            if previous.get("price") != price:
                marks.append("price")
            if previous.get("content_hash") != observation.get("content_hash"):
                marks.append("content")
        note = f"   [{', '.join(marks)} changed]" if marks else ""
        lines.append(f"  {observation.get('scraped_at') or '?':<32} {shown:>16}{note}")
        previous = observation
    return "\n".join(lines)
