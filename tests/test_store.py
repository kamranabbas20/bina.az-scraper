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


def test_dedupes_within_a_run(tmp_path):
    path = tmp_path / "out.jsonl"
    with JsonlStore(path) as store:
        store.write({"item_id": "1"})
        assert store.write({"item_id": "1"}) is False
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_resume_skips_ids_already_on_disk(tmp_path):
    path = tmp_path / "out.jsonl"
    with JsonlStore(path) as store:
        store.write({"item_id": "1"})
    with JsonlStore(path) as store:
        assert store.has("1")
        assert store.write({"item_id": "1"}) is False
        assert store.write({"item_id": "2"}) is True
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_no_resume_rewrites(tmp_path):
    path = tmp_path / "out.jsonl"
    with JsonlStore(path) as store:
        store.write({"item_id": "1"})
    with JsonlStore(path, resume=False) as store:
        assert store.has("1") is False
        assert store.write({"item_id": "1"}) is True


def test_corrupt_line_does_not_break_resume(tmp_path):
    path = tmp_path / "out.jsonl"
    path.write_text('{"item_id": "1"}\nnot json at all\n{"item_id": "2"}\n', encoding="utf-8")
    store = JsonlStore(path)
    assert store.seen == {"1", "2"}


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
