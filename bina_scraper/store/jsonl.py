"""Append-only JSON Lines output with id-based dedupe and resume."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import TracebackType
from typing import Any, Iterator

log = logging.getLogger(__name__)


class JsonlStore:
    """One JSON object per line, flushed per record.

    On open, ids already present in the file are loaded so a re-run skips what
    it already has; a crash therefore costs the current record, not the run.
    """

    def __init__(self, path: str | Path, *, resume: bool = True, id_field: str = "item_id"):
        self.path = Path(path)
        self.id_field = id_field
        self.seen: set[str] = set()
        self._handle = None
        if resume and self.path.exists():
            self.seen = set(self._existing_ids())
            if self.seen:
                log.info("resuming: %s already holds %s records", self.path, len(self.seen))

    def _existing_ids(self) -> Iterator[str]:
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
                value = record.get(self.id_field)
                if value is not None:
                    yield str(value)

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
        return str(item_id) in self.seen

    def write(self, record: dict[str, Any]) -> bool:
        """Append one record. Returns False if its id was already written."""
        if self._handle is None:
            raise RuntimeError("JsonlStore.open() must be called before write()")
        item_id = record.get(self.id_field)
        key = str(item_id) if item_id is not None else None
        if key is not None and key in self.seen:
            return False
        self._handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self._handle.flush()
        if key is not None:
            self.seen.add(key)
        return True

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
