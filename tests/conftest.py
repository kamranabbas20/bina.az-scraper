from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def listing_html() -> str:
    return _read("listing_page.html")


@pytest.fixture
def item_html() -> str:
    return _read("item_page.html")


@pytest.fixture
def challenge_html() -> str:
    return _read("challenge_page.html")
