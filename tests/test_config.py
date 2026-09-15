import pytest

from bina_scraper.config import Settings, load_settings


def test_defaults_are_conservative():
    settings = Settings()
    assert settings.max_pages == 1
    assert settings.delay >= 1
    assert settings.respect_robots is True
    assert settings.fetcher == "http"


def test_yaml_file_is_applied(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(
        "deal_type: rent\nmax_pages: 5\ndelay: 3.5\nquery_params:\n  where: baku\n",
        encoding="utf-8",
    )
    settings = load_settings(path)
    assert settings.search_url_path() == "/kiraye"
    assert settings.max_pages == 5
    assert settings.delay == 3.5
    assert settings.query_params == {"where": "baku"}


def test_overrides_beat_the_file(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("max_pages: 5\n", encoding="utf-8")
    assert load_settings(path, max_pages=2).max_pages == 2


def test_unknown_keys_are_rejected(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("max_page: 5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown config keys: max_page"):
        load_settings(path)


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "nope.yml")


def test_string_values_are_coerced(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("max_pages: '4'\ndelay: '0.5'\nfetch_details: 'false'\n", encoding="utf-8")
    settings = load_settings(path)
    assert settings.max_pages == 4
    assert settings.delay == 0.5
    assert settings.fetch_details is False


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"deal_type": "barter"}, "unknown deal_type"),
        ({"fetcher": "curl"}, "unknown fetcher"),
        ({"max_pages": 0}, "max_pages"),
        ({"delay": -1}, "delay"),
    ],
)
def test_validation_rejects_bad_values(kwargs, message):
    with pytest.raises(ValueError, match=message):
        load_settings(None, **kwargs)


def test_example_config_is_valid():
    """config.example.yml must stay in step with Settings."""
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "config.example.yml"
    settings = load_settings(example)
    assert settings.deal_type == "sale"
    assert settings.respect_robots is True
