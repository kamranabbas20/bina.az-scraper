"""Append-only JSON Lines output in three modes: unique, observations, changes."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import TracebackType
from typing import Any, Iterator, Literal

log = logging.getLogger(__name__)

Mode = Literal["unique", "observations", "changes"]

MODES: tuple[str, ...] = ("unique", "observations", "changes")


class JsonlStore:
    """One JSON object per line, flushed per record.

    The mode decides what counts as a duplicate, which is the difference
    between a catalogue of listings and a history of them:

    ``unique``
        One row per listing, ever. A listing already in the file is skipped,
        so its first-seen price is what you keep. Cheapest, and loses history.

    ``observations``
        One row per listing per crawl, keyed on ``(item_id, scraped_at)``. Every
        crawl appends what it saw, so a listing's price over time is a query
        away — and so is "this listing was still live on that date", which
        matters for time-on-market and spotting a delisting.

    ``changes``
        One row per listing per *change*. A listing whose fingerprint matches
        its last recorded row is not written again. Same history for anything
        that actually moved, far smaller files, but an unchanged listing leaves
        no trace of having been checked.

    ``resume`` decides whether existing file state is read at all; mode decides
    what that state is used for. In ``observations`` mode nothing is skipped on
    the strength of it, so it only affects the dedupe of a re-seen listing
    inside one run.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        mode: str = "observations",
        resume: bool = True,
        id_field: str = "item_id",
        hash_field: str = "content_hash",
    ):
        if mode not in MODES:
            raise ValueError(f"unknown store mode {mode!r}; expected one of {list(MODES)}")
        self.path = Path(path)
        self.mode = mode
        self.id_field = id_field
        self.hash_field = hash_field
        # Ids already in the file (unique mode) and the last fingerprint recorded
        # per id (changes mode).
        self.seen: set[str] = set()
        self.last_hash: dict[str, str] = {}
        # Ids written during this run, so one listing appearing on two pages of
        # the same crawl is one observation, not two.
        self.written_this_run: set[str] = set()
        self._handle = None

        if resume and self.path.exists():
            for item_id, content_hash in self._existing_records():
                self.seen.add(item_id)
                if content_hash:
                    self.last_hash[item_id] = content_hash
            if self.seen:
                log.info(
                    "%s already holds %s distinct listings (mode=%s)",
                    self.path,
                    len(self.seen),
                    self.mode,
                )

    def _existing_records(self) -> Iterator[tuple[str, str | None]]:
        """Yield (item_id, content_hash) per line, in file order.

        Later lines win for a given id, which is what makes the last recorded
        fingerprint the one ``changes`` mode compares against.
        """
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("%s:%s is not valid JSON; ignoring it", self.path, line_number)
                    continue
                if not isinstance(record, dict):
                    continue
                value = record.get(self.id_field)
                if value is None:
                    continue
                content_hash = record.get(self.hash_field)
                yield str(value), str(content_hash) if content_hash else None

    def open(self) -> "JsonlStore":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")
        return self

    def __enter__(self) -> "JsonlStore":
        return self.open()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def has(self, item_id: str) -> bool:
        """True if this id is already in the file (regardless of mode)."""
        return str(item_id) in self.seen

    def should_fetch(self, item_id: str) -> bool:
        """Whether this listing is worth fetching now.

        Only ``unique`` mode can answer this from the id alone. The history
        modes have to fetch before they can tell whether anything changed, so
        the only thing they skip is a listing already recorded in this run.
        """
        key = str(item_id)
        if key in self.written_this_run:
            return False
        if self.mode == "unique":
            return key not in self.seen
        return True

    def write(self, record: dict[str, Any]) -> bool:
        """Append one record. False means it was a duplicate under this mode."""
        if self._handle is None:
            raise RuntimeError("JsonlStore.open() must be called before write()")

        item_id = record.get(self.id_field)
        key = str(item_id) if item_id is not None else None
        content_hash = record.get(self.hash_field)

        if key is not None:
            if key in self.written_this_run:
                return False
            if self.mode == "unique" and key in self.seen:
                return False
            if self.mode == "changes" and content_hash and self.last_hash.get(key) == content_hash:
                return False

        self._handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self._handle.flush()
        if key is not None:
            self.seen.add(key)
            self.written_this_run.add(key)
            if content_hash:
                self.last_hash[key] = str(content_hash)
        return True

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
