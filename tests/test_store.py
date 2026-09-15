import json

import pytest

from bina_scraper.store import JsonlStore


def test_writes_one_json_object_per_line(tmp_path):
    path = tmp_path / "out.jsonl"
    with JsonlStore(path) as store:
        assert store.write({"item_id": "1", "price": 100}) is True
        assert store.write({"item_id": "2", "price": 200}) is True
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(line)["item_id"] for line in lines] == ["1", "2"]


def test_dedupes_within_a_run_in_every_mode(tmp_path):
    """One listing seen twice in one crawl is one row, whatever the mode."""
    for mode in ("unique", "observations", "changes"):
        path = tmp_path / f"{mode}.jsonl"
        with JsonlStore(path, mode=mode) as store:
            assert store.write({"item_id": "1", "content_hash": "a"}) is True
            assert store.write({"item_id": "1", "content_hash": "a"}) is False
        assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_unique_mode_skips_ids_already_on_disk(tmp_path):
    path = tmp_path / "out.jsonl"
    with JsonlStore(path, mode="unique") as store:
        store.write({"item_id": "1"})
    with JsonlStore(path, mode="unique") as store:
        assert store.has("1")
        assert store.should_fetch("1") is False
        assert store.write({"item_id": "1"}) is False
        assert store.write({"item_id": "2"}) is True
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_no_resume_rewrites(tmp_path):
    path = tmp_path / "out.jsonl"
    with JsonlStore(path, mode="unique") as store:
        store.write({"item_id": "1"})
    with JsonlStore(path, mode="unique", resume=False) as store:
        assert store.has("1") is False
        assert store.write({"item_id": "1"}) is True


def test_corrupt_line_does_not_break_resume(tmp_path):
    path = tmp_path / "out.jsonl"
    path.write_text('{"item_id": "1"}\nnot json at all\n{"item_id": "2"}\n', encoding="utf-8")
    store = JsonlStore(path)
    assert store.seen == {"1", "2"}


# --- observation-log modes -------------------------------------------------


def test_default_mode_is_an_observation_log(tmp_path):
    assert JsonlStore(tmp_path / "out.jsonl").mode == "observations"


def test_unknown_mode_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown store mode"):
        JsonlStore(tmp_path / "out.jsonl", mode="append-everything")


def test_observations_mode_keeps_one_row_per_crawl(tmp_path):
    """The same listing at two prices must leave two rows, not one."""
    path = tmp_path / "out.jsonl"
    with JsonlStore(path) as store:
        assert store.write({"item_id": "1", "scraped_at": "2025-01-01", "price": 100}) is True
    with JsonlStore(path) as store:
        assert store.should_fetch("1") is True  # must re-check to learn the price
        assert store.write({"item_id": "1", "scraped_at": "2025-02-01", "price": 120}) is True

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]
    assert [r["price"] for r in rows] == [100, 120]
    assert [r["scraped_at"] for r in rows] == ["2025-01-01", "2025-02-01"]


def test_observations_mode_records_an_unchanged_listing_again(tmp_path):
    """"Still live and unchanged on this date" is information worth keeping."""
    path = tmp_path / "out.jsonl"
    with JsonlStore(path) as store:
        store.write({"item_id": "1", "scraped_at": "2025-01-01", "content_hash": "same"})
    with JsonlStore(path) as store:
        assert store.write({"item_id": "1", "scraped_at": "2025-02-01", "content_hash": "same"}) is True
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_changes_mode_writes_only_when_the_fingerprint_moves(tmp_path):
    path = tmp_path / "out.jsonl"
    with JsonlStore(path, mode="changes") as store:
        assert store.write({"item_id": "1", "scraped_at": "2025-01-01", "content_hash": "a"}) is True
    with JsonlStore(path, mode="changes") as store:
        # Unchanged: still fetched, but not written again.
        assert store.should_fetch("1") is True
        assert store.write({"item_id": "1", "scraped_at": "2025-02-01", "content_hash": "a"}) is False
    with JsonlStore(path, mode="changes") as store:
        assert store.write({"item_id": "1", "scraped_at": "2025-03-01", "content_hash": "b"}) is True

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]
    assert [r["content_hash"] for r in rows] == ["a", "b"]


def test_changes_mode_compares_against_the_latest_row(tmp_path):
    """A price that returns to an earlier value is still a change."""
    path = tmp_path / "out.jsonl"
    path.write_text(
        '{"item_id": "1", "content_hash": "a"}\n{"item_id": "1", "content_hash": "b"}\n',
        encoding="utf-8",
    )
    with JsonlStore(path, mode="changes") as store:
        assert store.last_hash["1"] == "b"
        assert store.write({"item_id": "1", "content_hash": "a"}) is True


def test_changes_mode_writes_a_record_with_no_hash(tmp_path):
    """No fingerprint means we cannot prove it is unchanged, so keep it."""
    path = tmp_path / "out.jsonl"
    with JsonlStore(path, mode="changes") as store:
        assert store.write({"item_id": "1"}) is True
    with JsonlStore(path, mode="changes") as store:
        assert store.write({"item_id": "1"}) is True


def test_non_ascii_is_stored_unescaped(tmp_path):
    path = tmp_path / "out.jsonl"
    with JsonlStore(path) as store:
        store.write({"item_id": "1", "city": "Bakı", "district": "Nərimanov"})
    assert "Bakı" in path.read_text(encoding="utf-8")


def test_write_before_open_is_an_error(tmp_path):
    with pytest.raises(RuntimeError):
        JsonlStore(tmp_path / "out.jsonl").write({"item_id": "1"})


def test_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "deeper" / "out.jsonl"
    with JsonlStore(path) as store:
        store.write({"item_id": "1"})
    assert path.exists()
