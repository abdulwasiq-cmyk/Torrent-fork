import base64

import httpx
from fastapi.testclient import TestClient

import main
from integrations import torrserver


HASH = "0123456789abcdef0123456789abcdef01234567"
USERNAME = "server-only-test-user"
PASSWORD = "server-only-test-password"


def _client():
    client = TestClient(main.app)
    session = client.get("/api/seedr/session")
    client.headers["X-Torrent-Studio-CSRF"] = session.json()["csrfToken"]
    return client


class _JsonResponse:
    status_code = 200
    is_error = False

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def _torrent_payload(action):
    if action == "add":
        return {
            "hash": HASH,
            "title": "Sample Movie",
            "file_stats": [
                {"id": 0, "path": "Sample.Movie/movie.mkv", "length": 1200},
                {"id": 1, "path": "Sample.Movie/subtitles.srt", "length": 100},
            ],
        }
    return {
        "hash": HASH,
        "title": "Sample Movie",
        "stat_string": "Ready",
        "file_stats": [{"id": 0, "path": "Sample.Movie/movie.mkv", "length": 1200}],
    }


def test_torrserver_add_info_and_remove_use_documented_payloads_without_auth(monkeypatch):
    client = _client()
    calls = []

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, url, *, json, auth):
            calls.append({"url": url, "json": json, "auth": auth})
            return _JsonResponse(_torrent_payload(json["action"]))

    monkeypatch.setattr(torrserver, "TORRSERVER_ENABLED", True)
    monkeypatch.setattr(torrserver, "TORRSERVER_URL", "http://torrserver:8090")
    monkeypatch.setattr(torrserver, "TORRSERVER_USERNAME", "")
    monkeypatch.setattr(torrserver, "TORRSERVER_PASSWORD", "")
    monkeypatch.setattr(torrserver.httpx, "AsyncClient", FakeAsyncClient)

    added = client.post(
        "/api/torrserver/add",
        json={"magnet": f"magnet:?xt=urn:btih:{HASH}"},
    )
    assert added.status_code == 200
    assert added.json()["files"][0]["streamUrl"] == f"/api/torrserver/stream/{HASH}/0"
    assert "key=" not in added.json()["files"][0]["streamUrl"]
    assert calls[0]["json"] == {
        "action": "add",
        "link": f"magnet:?xt=urn:btih:{HASH}",
        "save_to_db": False,
    }
    assert calls[0]["auth"] is None

    info = client.get(f"/api/torrserver/torrents/{HASH}")
    assert info.status_code == 200
    assert info.json()["status"] == "Ready"
    assert calls[1]["json"] == {"action": "get", "hash": HASH}
    assert calls[1]["auth"] is None

    removed = client.delete(f"/api/torrserver/torrents/{HASH}")
    assert removed.status_code == 200
    assert removed.json() == {"removed": True}
    assert calls[2]["json"] == {"action": "rem", "hash": HASH}
    assert calls[2]["auth"] is None


def test_torrserver_stream_uses_documented_get_query_and_forwards_ranges(monkeypatch):
    client = _client()
    calls = []

    class FakeUpstream:
        status_code = 206
        headers = {
            "accept-ranges": "bytes",
            "cache-control": "no-cache",
            "content-length": "4",
            "content-range": "bytes 0-3/10",
            "content-type": "video/mp4",
            "etag": '"stream-etag"',
        }

        async def aiter_raw(self):
            yield b"data"

        async def aclose(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        def build_request(self, method, url, *, params, headers):
            calls.append({
                "method": method,
                "url": url,
                "params": params,
                "headers": headers,
            })
            return object()

        async def send(self, _request, *, stream, auth):
            assert stream is True
            calls[-1]["auth"] = auth
            return FakeUpstream()

        async def aclose(self):
            return None

    monkeypatch.setattr(torrserver, "TORRSERVER_ENABLED", True)
    monkeypatch.setattr(torrserver, "TORRSERVER_URL", "http://torrserver:8090")
    monkeypatch.setattr(torrserver, "TORRSERVER_USERNAME", "")
    monkeypatch.setattr(torrserver, "TORRSERVER_PASSWORD", "")
    monkeypatch.setattr(torrserver.httpx, "AsyncClient", FakeAsyncClient)

    response = client.get(
        f"/api/torrserver/stream/{HASH}/0",
        headers={"Range": "bytes=0-3", "If-Range": '"stream-etag"'},
    )
    assert response.status_code == 206
    assert response.content == b"data"
    assert response.headers["content-range"] == "bytes 0-3/10"
    assert response.headers["etag"] == '"stream-etag"'
    assert response.headers["cache-control"] == "no-cache"
    assert f"{USERNAME}:{PASSWORD}" not in response.text
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "http://torrserver:8090/stream"
    assert calls[0]["headers"] == {
        "range": "bytes=0-3",
        "if-range": '"stream-etag"',
    }
    assert calls[0]["params"] == {
        "link": HASH,
        "index": "0",
        "play": "",
    }
    assert calls[0]["auth"] is None


def test_torrserver_uses_optional_http_basic_auth_for_api_and_stream(monkeypatch):
    observed_api_auth = []
    observed_stream_auth = []

    class FakeApiClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, _url, *, json, auth):
            observed_api_auth.append(auth)
            return _JsonResponse(_torrent_payload(json["action"]))

    class FakeUpstream:
        status_code = 200
        headers = {"content-type": "video/mp4"}

        async def aiter_raw(self):
            yield b"data"

        async def aclose(self):
            return None

    class FakeStreamClient:
        def __init__(self, **_kwargs):
            pass

        def build_request(self, method, _url, *, params, headers):
            return object()

        async def send(self, _request, *, stream, auth):
            observed_stream_auth.append(auth)
            return FakeUpstream()

        async def aclose(self):
            return None

    monkeypatch.setattr(torrserver, "TORRSERVER_ENABLED", True)
    monkeypatch.setattr(torrserver, "TORRSERVER_URL", "http://torrserver:8090")
    monkeypatch.setattr(torrserver, "TORRSERVER_USERNAME", USERNAME)
    monkeypatch.setattr(torrserver, "TORRSERVER_PASSWORD", PASSWORD)
    monkeypatch.setattr(torrserver.httpx, "AsyncClient", FakeApiClient)
    assert _client().post(
        "/api/torrserver/add",
        json={"magnet": f"magnet:?xt=urn:btih:{HASH}"},
    ).status_code == 200

    monkeypatch.setattr(torrserver.httpx, "AsyncClient", FakeStreamClient)
    response = _client().get(f"/api/torrserver/stream/{HASH}/0")
    assert response.status_code == 200
    expected_auth = "Basic " + base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    request = httpx.Request("GET", "http://torrserver:8090/stream")
    assert next(observed_api_auth[0].auth_flow(request)).headers["Authorization"] == expected_auth
    assert next(observed_stream_auth[0].auth_flow(request)).headers["Authorization"] == expected_auth


def test_torrserver_is_hidden_when_feature_flag_is_off(monkeypatch):
    monkeypatch.setattr(torrserver, "TORRSERVER_ENABLED", False)
    response = _client().get("/api/torrserver/status")
    assert response.status_code == 200
    assert response.json() == {"enabled": False}


def test_torrserver_configuration_error_is_visible_without_credentials(monkeypatch):
    monkeypatch.setattr(torrserver, "TORRSERVER_ENABLED", True)
    monkeypatch.setattr(torrserver, "TORRSERVER_URL", "")
    response = _client().get("/api/torrserver/status")
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert "TORRSERVER_URL" in response.json()["error"]


def test_torrserver_rejects_partial_basic_auth_configuration(monkeypatch):
    monkeypatch.setattr(torrserver, "TORRSERVER_ENABLED", True)
    monkeypatch.setattr(torrserver, "TORRSERVER_URL", "http://torrserver:8090")
    monkeypatch.setattr(torrserver, "TORRSERVER_USERNAME", USERNAME)
    monkeypatch.setattr(torrserver, "TORRSERVER_PASSWORD", "")
    response = _client().get("/api/torrserver/status")
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert "both TORRSERVER_USERNAME and TORRSERVER_PASSWORD" in response.json()["error"]
