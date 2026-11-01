import pytest
from fastapi import HTTPException

from core import rate_limit
from integrations import nexstream


class FakeRequest:
    def __init__(self, forwarded="", host="10.0.0.1"):
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}
        self.client = type("Client", (), {"host": host})()


def test_rate_limit_blocks_after_the_limit_per_client(monkeypatch):
    monkeypatch.setattr(rate_limit, "_DISABLED", False)
    limiter = rate_limit.RateLimit("test", 3, window=60)
    limiter.limit = 3
    for _ in range(3):
        limiter(FakeRequest("1.1.1.1"))
    with pytest.raises(HTTPException) as caught:
        limiter(FakeRequest("1.1.1.1"))
    assert caught.value.status_code == 429
    assert int(caught.value.headers["Retry-After"]) >= 1
    limiter(FakeRequest("2.2.2.2"))  # other clients are unaffected


def test_rate_limit_window_expires(monkeypatch):
    monkeypatch.setattr(rate_limit, "_DISABLED", False)
    clock = {"now": 100.0}
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: clock["now"])
    limiter = rate_limit.RateLimit("test", 1, window=10)
    limiter.limit = 1
    limiter(FakeRequest())
    with pytest.raises(HTTPException):
        limiter(FakeRequest())
    clock["now"] += 11
    limiter(FakeRequest())


def test_client_ip_uses_first_forwarded_address_then_socket():
    assert rate_limit.client_ip(FakeRequest("9.9.9.9, 10.1.1.1")) == "9.9.9.9"
    assert rate_limit.client_ip(FakeRequest(host="4.4.4.4")) == "4.4.4.4"


def test_live_episode_cache_is_bounded_and_keeps_bundled_shows(monkeypatch):
    monkeypatch.setattr(nexstream, "_MAX_LIVE_EPISODE_SHOWS", 2)
    shows = {
        "bundled": {"tmdbId": 1},
        "old": {"cachedAt": 10.0},
        "mid": {"cachedAt": 20.0},
        "new": {"cachedAt": 30.0},
    }
    nexstream._prune_live_episode_shows(shows)
    assert set(shows) == {"bundled", "mid", "new"}
