import pytest
import requests

from bina_scraper.config import load_settings
from bina_scraper.fetchers import BlockedError, FetchError, build_fetcher
from bina_scraper.fetchers.http import HttpFetcher, looks_like_challenge


class FakeResponse:
    def __init__(self, status_code=200, text="<html>ok</html>", url="https://bina.az/x"):
        self.status_code = status_code
        self.text = text
        self.url = url


def _settings(**kwargs):
    defaults = dict(delay=0.0, jitter=0.0, backoff_factor=0.0, max_retries=2)
    defaults.update(kwargs)
    return load_settings(None, **defaults)


def test_detects_cloudflare_challenge(challenge_html):
    assert looks_like_challenge(challenge_html) is True
    assert looks_like_challenge("<html><body>Bakı, 3 otaq</body></html>") is False


def test_403_raises_blocked_with_actionable_advice(monkeypatch):
    fetcher = HttpFetcher(_settings())
    monkeypatch.setattr(fetcher.session, "get", lambda *a, **k: FakeResponse(403, "denied"))
    with pytest.raises(BlockedError) as excinfo:
        fetcher.get("https://bina.az/alqi-satqi")
    assert excinfo.value.status == 403
    assert "browser" in str(excinfo.value)


def test_challenge_body_with_200_still_raises_blocked(monkeypatch, challenge_html):
    fetcher = HttpFetcher(_settings())
    monkeypatch.setattr(fetcher.session, "get", lambda *a, **k: FakeResponse(200, challenge_html))
    with pytest.raises(BlockedError):
        fetcher.get("https://bina.az/alqi-satqi")


def test_retries_then_succeeds(monkeypatch):
    fetcher = HttpFetcher(_settings(max_retries=3))
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise requests.ConnectionError("reset by peer")
        return FakeResponse(200, "<html>fine</html>")

    monkeypatch.setattr(fetcher.session, "get", flaky)
    result = fetcher.get("https://bina.az/x")
    assert result.ok and len(calls) == 3


def test_gives_up_after_max_retries(monkeypatch):
    fetcher = HttpFetcher(_settings(max_retries=2))
    monkeypatch.setattr(
        fetcher.session, "get", lambda *a, **k: (_ for _ in ()).throw(requests.Timeout("slow"))
    )
    with pytest.raises(FetchError) as excinfo:
        fetcher.get("https://bina.az/x")
    assert "2 attempts" in str(excinfo.value)


def test_retries_5xx_but_returns_404(monkeypatch):
    fetcher = HttpFetcher(_settings(max_retries=2))
    statuses = [503, 200]
    monkeypatch.setattr(
        fetcher.session, "get", lambda *a, **k: FakeResponse(statuses.pop(0), "<html>x</html>")
    )
    assert fetcher.get("https://bina.az/x").status == 200

    fetcher2 = HttpFetcher(_settings())
    monkeypatch.setattr(fetcher2.session, "get", lambda *a, **k: FakeResponse(404, ""))
    result = fetcher2.get("https://bina.az/items/0")
    assert result.status == 404 and result.ok is False


def test_user_agent_carries_the_contact_email():
    fetcher = HttpFetcher(_settings(contact_email="me@example.com"))
    assert "me@example.com" in fetcher.session.headers["User-Agent"]
    fetcher.close()


def test_build_fetcher_selects_by_name():
    assert isinstance(build_fetcher(_settings(fetcher="http")), HttpFetcher)
