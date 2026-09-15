import json

import pytest

from bina_scraper.cli import main
from bina_scraper.history import (
    format_timeline,
    group_by_item,
    load_observations,
    price_changes,
    summarize,
)

OBSERVATIONS = [
    {"item_id": "1", "scraped_at": "2025-01-01T00:00:00", "price": 185000.0, "currency": "AZN",
     "content_hash": "a", "title": "3 otaqlı yeni tikili"},
    {"item_id": "1", "scraped_at": "2025-02-01T00:00:00", "price": 185000.0, "currency": "AZN",
     "content_hash": "a", "title": "3 otaqlı yeni tikili"},
    {"item_id": "1", "scraped_at": "2025-03-01T00:00:00", "price": 175000.0, "currency": "AZN",
     "content_hash": "b", "title": "3 otaqlı yeni tikili"},
    {"item_id": "2", "scraped_at": "2025-01-01T00:00:00", "price": 1250000.0, "currency": "USD",
     "content_hash": "c"},
]


@pytest.fixture
def log_file(tmp_path):
    path = tmp_path / "listings.jsonl"
    path.write_text(
        "\n".join(json.dumps(o, ensure_ascii=False) for o in OBSERVATIONS) + "\n",
        encoding="utf-8",
    )
    return path


def test_load_skips_junk_lines(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text(
        '{"item_id": "1", "price": 1}\nbroken\n\n["not a dict"]\n{"no_id": true}\n',
        encoding="utf-8",
    )
    assert load_observations(path) == [{"item_id": "1", "price": 1}]


def test_group_by_item_sorts_oldest_first(log_file):
    grouped = group_by_item(load_observations(log_file))
    assert set(grouped) == {"1", "2"}
    assert [o["scraped_at"] for o in grouped["1"]] == [
        "2025-01-01T00:00:00",
        "2025-02-01T00:00:00",
        "2025-03-01T00:00:00",
    ]


def test_price_changes_reports_only_real_moves(log_file):
    changes = price_changes(load_observations(log_file))
    assert len(changes) == 1
    change = changes[0]
    assert change.item_id == "1"
    assert (change.old_price, change.new_price) == (185000.0, 175000.0)
    assert change.delta == -10000.0
    assert round(change.pct, 3) == -5.405
    assert change.previous_at == "2025-02-01T00:00:00"
    assert "-10,000" in change.describe()


def test_price_on_request_is_not_a_drop_to_zero():
    """A listing switching to "Razılaşma ilə" parses to null, not 0."""
    records = [
        {"item_id": "1", "scraped_at": "2025-01-01", "price": 100000.0},
        {"item_id": "1", "scraped_at": "2025-02-01", "price": None},
        {"item_id": "1", "scraped_at": "2025-03-01", "price": 100000.0},
    ]
    assert price_changes(records) == []


def test_a_price_returning_to_its_old_value_counts_twice():
    records = [
        {"item_id": "1", "scraped_at": "2025-01-01", "price": 100.0},
        {"item_id": "1", "scraped_at": "2025-02-01", "price": 90.0},
        {"item_id": "1", "scraped_at": "2025-03-01", "price": 100.0},
    ]
    changes = price_changes(records)
    assert [(c.old_price, c.new_price) for c in changes] == [(100.0, 90.0), (90.0, 100.0)]


def test_pct_is_none_when_the_old_price_was_zero():
    records = [
        {"item_id": "1", "scraped_at": "2025-01-01", "price": 0.0},
        {"item_id": "1", "scraped_at": "2025-02-01", "price": 50.0},
    ]
    change = price_changes(records)[0]
    assert change.delta == 50.0
    assert change.pct is None
    assert change.describe()  # must not raise on a zero base


def test_summary(log_file):
    summary = summarize(load_observations(log_file))
    assert summary.observations == 4
    assert summary.items == 2
    assert summary.first_seen == "2025-01-01T00:00:00"
    assert summary.last_seen == "2025-03-01T00:00:00"
    assert summary.items_with_multiple_observations == 1
    assert summary.price_changes == 1
    assert summary.currencies == {"AZN": 3, "USD": 1}
    assert "price changes:           1" in summary.describe()


def test_timeline_marks_what_changed(log_file):
    grouped = group_by_item(load_observations(log_file))
    text = format_timeline("1", grouped["1"])
    assert "3 observations" in text
    assert "3 otaqlı yeni tikili" in text
    # The middle observation is identical to the first, so it is unmarked.
    lines = [line for line in text.splitlines() if "2025-" in line]
    assert "changed" not in lines[0] and "changed" not in lines[1]
    assert "price, content changed" in lines[2]


def test_timeline_handles_a_missing_price(log_file):
    text = format_timeline("1", [{"item_id": "1", "scraped_at": "2025-01-01", "price": None}])
    assert "—" in text


def test_timeline_of_nothing():
    assert "no observations" in format_timeline("9", [])


def test_cli_history_summary(log_file, capsys):
    assert main(["history", str(log_file)]) == 0
    assert "distinct listings:       2" in capsys.readouterr().out


def test_cli_history_item_timeline(log_file, capsys):
    assert main(["history", str(log_file), "--item", "1"]) == 0
    assert "3 observations" in capsys.readouterr().out


def test_cli_history_price_changes_json(log_file, capsys):
    assert main(["history", str(log_file), "--price-changes", "--json"]) == 0
    changes = json.loads(capsys.readouterr().out)
    assert changes[0]["delta"] == -10000.0


def test_cli_history_unknown_item(log_file, capsys):
    assert main(["history", str(log_file), "--item", "999"]) == 1
    capsys.readouterr()


def test_cli_history_empty_file(tmp_path, capsys):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    assert main(["history", str(path)]) == 1
    capsys.readouterr()
