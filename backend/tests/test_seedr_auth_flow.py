import asyncio
from hmac import compare_digest
import json
import logging

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

import main
from core.shared import SeedrError
from seedr import seedr_api, seedr_client, seedr_session


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload if payload is not None else {"id": 123}
        self.text = json.dumps(self.payload)
        self.content = self.text.encode("utf-8")
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self.payload


def test_pat_validation_sends_bearer_auth_without_logging_token(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="torrent-studio")
    requests = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers):
            requests.append((url, headers))
            return FakeResponse(200)

    monkeypatch.setattr(seedr_api, "_InstrumentedAsyncClient", lambda **kwargs: FakeClient())

    asyncio.run(seedr_api._validate_seedr_pat("unit-test-pat"))

    assert len(requests) == 1
    assert "unit-test-pat" not in caplog.text
    assert requests[0][1]["Authorization"] == "Bearer unit-test-pat"


@pytest.mark.parametrize(
    ("status_code", "payload", "expected_code"),
    [
        (401, {}, "SEEDR_PAT_REJECTED"),
        (403, {"error": "insufficient_scope"}, "SEEDR_PAT_INSUFFICIENT_SCOPE"),
        (429, {}, "SEEDR_RATE_LIMITED"),
        (404, {}, "SEEDR_ENDPOINT_NOT_FOUND"),
    ],
)
def test_pat_validation_reports_auth_and_endpoint_statuses(
    monkeypatch, status_code, payload, expected_code
):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers):
            return FakeResponse(status_code, payload)

    monkeypatch.setattr(seedr_api, "_InstrumentedAsyncClient", lambda **kwargs: FakeClient())

    with pytest.raises(SeedrError) as raised:
        asyncio.run(seedr_api._validate_seedr_pat("unit-test-pat"))

    assert raised.value.code == expected_code
    assert raised.value.status_code == status_code
    assert "unit-test-pat" not in raised.value.detail


def test_seedr_problem_distinguishes_insufficient_scope():
    code, status, message = seedr_client.seedr_problem(
        403, {"error": "insufficient_scope files.write"}, ""
    )

    assert code == "SEEDR_INSUFFICIENT_SCOPE"
    assert status == 403
    assert "required scope" in message


def test_seedr_task_add_uses_bearer_and_expected_request_body(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="torrent-studio")
    requests = []
    magnet = "magnet:?xt=urn:btih:" + "a" * 40 + "&dn=Example"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, headers, **kwargs):
            requests.append((method, url, headers, kwargs))
            return FakeResponse(200, {"id": 123})

    monkeypatch.setattr(seedr_client, "current_seedr_token", lambda: "unit-test-pat")
    monkeypatch.setattr(seedr_client, "_seedr_session_auth_mode", lambda _session: "pat")
    monkeypatch.setattr(seedr_client, "_InstrumentedAsyncClient", lambda **kwargs: FakeClient())

    result = asyncio.run(seedr_client.add_task(magnet, 17))

    assert result["id"] == 123
    method, url, headers, kwargs = requests[0]
    assert method == "POST"
    assert url.endswith("/tasks")
    assert headers["Authorization"] == "Bearer unit-test-pat"
    assert kwargs["json"] == {"torrent_magnet": magnet, "folder_id": 17}
    assert "unit-test-pat" not in caplog.text
    assert "token_fingerprint" not in caplog.text
    assert "token_length" not in caplog.text


def test_seedr_v2_request_uses_bearer_auth(monkeypatch):
    requests = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers):
            requests.append((url, headers))
            return FakeResponse(200, {"user": "example"})

    monkeypatch.setattr(seedr_api, "current_seedr_token", lambda: "unit-test-pat")
    monkeypatch.setattr(seedr_api, "seedr_v2_bearer_token", lambda: "unit-test-pat")
    monkeypatch.setattr(seedr_api, "_InstrumentedAsyncClient", lambda **kwargs: FakeClient())

    result = asyncio.run(seedr_api.seedr_v2_request("user"))

    assert result == {"user": "example"}
    assert requests[0][0].endswith("/user")
    assert requests[0][1]["Authorization"].startswith("Bearer ")
    assert requests[0][1]["Authorization"].endswith("unit-test-pat")


def test_seedr_add_requires_csrf_before_calling_provider(monkeypatch):
    seedr_session._seedr_sessions.clear()
    async def accept_test_pat(_token):
        return None

    monkeypatch.setattr(seedr_api, "_validate_seedr_pat", accept_test_pat)
    client = TestClient(main.app)
    csrf = client.get("/api/seedr/session").json()["csrfToken"]
    client.headers["X-Torrent-Studio-CSRF"] = csrf
    response = client.post(
        "/api/seedr/connect/pat",
        json={"pat": "unit-test-pat"},
    )
    assert response.status_code == 200

    client.headers.pop("X-Torrent-Studio-CSRF")
    response = client.post(
        "/api/seedr/add",
        json={"magnet": "magnet:?xt=urn:btih:" + "b" * 40},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "SEEDR_CSRF_INVALID"
    seedr_session._seedr_sessions.clear()


def test_seedr_add_forwards_magnet_after_csrf_validation(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="torrent-studio")
    seedr_session._seedr_sessions.clear()
    async def accept_test_pat(_token):
        return None

    monkeypatch.setattr(seedr_api, "_validate_seedr_pat", accept_test_pat)
    client = TestClient(main.app)
    csrf = client.get("/api/seedr/session").json()["csrfToken"]
    client.headers["X-Torrent-Studio-CSRF"] = csrf
    client.post("/api/seedr/connect/pat", json={"pat": "unit-test-pat"})
    assert "unit-test-pat" not in caplog.text
    assert "token_length" not in caplog.text
    assert "token_fingerprint" not in caplog.text
    requests = []

    async def no_active_tasks(_replace_task_id=""):
        return []

    async def fake_add_task(magnet, folder_id):
        requests.append((magnet, folder_id))
        return {"id": 123, "torrent_name": "Example"}

    monkeypatch.setattr(seedr_api, "_cancel_active_seedr_tasks_for_replacement", no_active_tasks)
    monkeypatch.setattr(seedr_api, "add_task", fake_add_task)
    monkeypatch.setattr(seedr_api, "schedule_seedr_cleanup", lambda *args: None)
    magnet = "magnet:?xt=urn:btih:" + "c" * 40 + "&dn=Example"

    response = client.post("/api/seedr/add", json={"magnet": magnet})

    assert response.status_code == 200
    assert requests == [(magnet, 0)]
    seedr_session._seedr_sessions.clear()


def test_token_diagnostic_does_not_return_credential_metadata(monkeypatch):
    async def successful_request(_path):
        return {"id": 123}

    monkeypatch.setattr(seedr_api, "current_seedr_token", lambda: "private-test-token")
    monkeypatch.setattr(seedr_api, "seedr_request", successful_request)

    result = asyncio.run(seedr_api.seedr_token_diagnostic())

    assert result == {
        "configured": True,
        "code": "SEEDR_TOKEN_PRESENT",
        "checks": {"user": {"ok": True, "status": 200}},
    }
    assert "private-test-token" not in json.dumps(result)
    assert "tokenLength" not in result
    assert "tokenFingerprint" not in result


def test_seedr_video_stream_uses_provider_playback_url_without_exposing_session_token(monkeypatch):
    async def resolve_stream_id(_file_id, _name):
        return "123"

    async def resolve_presentation_url(_file_id, audio_index=None):
        return "https://cdn.seedr.cc/presentation/123.m3u8"

    async def is_not_hls(_url):
        return False

    monkeypatch.setattr(seedr_api, "current_seedr_token", lambda: "private-test-value")
    monkeypatch.setattr(seedr_api, "resolve_seedr_stream_id", resolve_stream_id)
    monkeypatch.setattr(seedr_api, "seedr_v2_video_url", resolve_presentation_url)
    monkeypatch.setattr(seedr_api, "_presentation_is_hls", is_not_hls)

    result = asyncio.run(seedr_api.seedr_file_stream("123", "video", "Example"))

    assert result["url"] == "/api/seedr/media/video/123"
    assert result["externalUrl"] == "https://cdn.seedr.cc/presentation/123.m3u8"
    assert "private-test-value" not in json.dumps(result)


def test_seedr_video_stream_omits_credential_bearing_external_url(monkeypatch):
    async def resolve_stream_id(_file_id, _name):
        return "123"

    async def resolve_presentation_url(_file_id, audio_index=None):
        return "https://cdn.seedr.cc/presentation/123.m3u8?access_token=secret-value"

    async def is_not_hls(_url):
        return False

    monkeypatch.setattr(seedr_api, "current_seedr_token", lambda: "private-test-value")
    monkeypatch.setattr(seedr_api, "resolve_seedr_stream_id", resolve_stream_id)
    monkeypatch.setattr(seedr_api, "seedr_v2_video_url", resolve_presentation_url)
    monkeypatch.setattr(seedr_api, "_presentation_is_hls", is_not_hls)

    result = asyncio.run(seedr_api.seedr_file_stream("123", "video", "Example"))

    assert result["url"] == "/api/seedr/media/video/123"
    assert "externalUrl" not in result
    assert "secret-value" not in json.dumps(result)
    assert "private-test-value" not in json.dumps(result)


def test_seedr_audio_stream_url_is_encoded_and_does_not_expose_session_token(monkeypatch):
    async def resolve_stream_id(_file_id, _name):
        return "folder/file 123"

    monkeypatch.setattr(seedr_api, "current_seedr_token", lambda: "private-test-value")
    monkeypatch.setattr(seedr_api, "resolve_seedr_stream_id", resolve_stream_id)

    result = asyncio.run(seedr_api.seedr_file_stream("123", "audio", "Example"))

    assert result["url"] == "/api/seedr/media/audio/folder%2Ffile%20123"
    assert result["protocol"] == "mp3"
    assert "externalUrl" not in result
    assert "private-test-value" not in json.dumps(result)


def test_seedr_hls_fallback_video_url_does_not_expose_session_token(monkeypatch):
    async def resolve_stream_id(_file_id, _name):
        return "folder/video 123"

    async def no_presentation(_file_id, audio_index=None):
        return ""

    async def fetch_manifest(_file_id):
        return "#EXTM3U", "https://cdn.seedr.cc/video.m3u8"

    monkeypatch.setattr(seedr_api, "current_seedr_token", lambda: "private-test-value")
    monkeypatch.setattr(seedr_api, "resolve_seedr_stream_id", resolve_stream_id)
    monkeypatch.setattr(seedr_api, "seedr_v2_video_url", no_presentation)
    monkeypatch.setattr(seedr_api, "_fetch_seedr_hls_manifest", fetch_manifest)

    result = asyncio.run(seedr_api.seedr_file_stream("123", "video", "Example"))

    assert result["url"] == "/api/seedr/hls/folder%2Fvideo%20123"
    assert "externalUrl" not in result
    assert "private-test-value" not in json.dumps(result)


def test_seedr_download_links_redirect_to_seedr_directly(monkeypatch):
    async def get_file_url(_file_id):
        return {"url": "https://www.seedr.cc/file-download?signature=file", "name": "movie.mkv"}

    async def get_folder_url(_folder_id):
        return "https://www.seedr.cc/folder-download?signature=folder"

    monkeypatch.setattr(seedr_api, "download_url", get_file_url)
    monkeypatch.setattr(seedr_api, "seedr_folder_download_url", get_folder_url)

    file_link = asyncio.run(seedr_api.seedr_file_download_url("123"))
    folder_link = asyncio.run(seedr_api.seedr_folder_download_url_api("456"))
    file_redirect = asyncio.run(seedr_api.seedr_file_download("123"))
    folder_redirect = asyncio.run(seedr_api.seedr_folder_download("456"))

    assert file_link["url"] == "https://www.seedr.cc/file-download?signature=file"
    assert folder_link["url"] == "https://www.seedr.cc/folder-download?signature=folder"
    assert file_redirect.status_code == 307
    assert file_redirect.headers["location"] == file_link["url"]
    assert folder_redirect.status_code == 307
    assert folder_redirect.headers["location"] == folder_link["url"]


def test_seedr_progress_request_follows_valid_redirect_with_bearer(monkeypatch, caplog):
    requests = []
    client_options = []
    synthetic_token = "synthetic-seedr-review-token"

    class RedirectClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, headers, **kwargs):
            requests.append((method, url, headers))
            if len(requests) == 1:
                response = FakeResponse(302, {})
                response.headers["location"] = "/api/v0.1/p/tasks/123/progress/result"
                return response
            return FakeResponse(200, {"ok": True})

    def make_client(**kwargs):
        client_options.append(kwargs)
        return RedirectClient()

    monkeypatch.setattr(seedr_client, "current_seedr_token", lambda: synthetic_token)
    monkeypatch.setattr(seedr_client, "_seedr_session_auth_mode", lambda _session: "pat")
    monkeypatch.setattr(seedr_client, "_InstrumentedAsyncClient", make_client)

    result = asyncio.run(
        seedr_client.seedr_request(
            "/api/v0.1/p/tasks/123/progress/poll",
            base_url="https://www.seedr.cc",
            allowed_redirect_hosts=frozenset({"www.seedr.cc"}),
        )
    )

    assert result == {"ok": True}
    assert len(requests) == 2
    assert requests[0][0] == requests[1][0] == "GET"
    assert compare_digest(
        requests[0][2]["Authorization"],
        f"Bearer {synthetic_token}",
    )
    assert compare_digest(
        requests[1][2]["Authorization"],
        f"Bearer {synthetic_token}",
    )
    assert synthetic_token not in caplog.text
    assert client_options[0]["follow_redirects"] is False


@pytest.mark.parametrize(
    "location",
    [
        "http://www.seedr.cc/poll",
        "https://attacker.example/poll",
        "https://localhost/poll",
        "https://127.0.0.1/poll",
        "https://10.0.0.1/poll",
        "https://www.seedr.cc:444/poll",
        "https://user@www.seedr.cc/poll",
        "//attacker.example/poll",
    ],
)
def test_seedr_progress_request_rejects_unsafe_redirects_before_forwarding_bearer(
    monkeypatch, location
):
    requests = []
    synthetic_token = "synthetic-seedr-review-token"

    class RedirectClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, headers, **kwargs):
            requests.append((method, url, headers))
            response = FakeResponse(302, {})
            response.headers["location"] = location
            return response

    monkeypatch.setattr(seedr_client, "current_seedr_token", lambda: synthetic_token)
    monkeypatch.setattr(seedr_client, "_seedr_session_auth_mode", lambda _session: "pat")
    monkeypatch.setattr(
        seedr_client,
        "_InstrumentedAsyncClient",
        lambda **kwargs: RedirectClient(),
    )

    with pytest.raises(SeedrError) as raised:
        asyncio.run(
            seedr_client.seedr_request(
                "/api/v0.1/p/tasks/123/progress/poll",
                base_url="https://www.seedr.cc",
                allowed_redirect_hosts=frozenset({"www.seedr.cc"}),
            )
        )

    assert raised.value.code == "SEEDR_PROGRESS_REDIRECT_INVALID"
    assert len(requests) == 1
    assert compare_digest(
        requests[0][2]["Authorization"],
        f"Bearer {synthetic_token}",
    )


def test_seedr_progress_request_rejects_too_many_redirects(monkeypatch):
    class RedirectClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, headers, **kwargs):
            response = FakeResponse(302, {})
            response.headers["location"] = "/next"
            return response

    monkeypatch.setattr(seedr_client, "current_seedr_token", lambda: "synthetic-token")
    monkeypatch.setattr(seedr_client, "_seedr_session_auth_mode", lambda _session: "pat")
    monkeypatch.setattr(
        seedr_client,
        "_InstrumentedAsyncClient",
        lambda **kwargs: RedirectClient(),
    )

    with pytest.raises(SeedrError) as raised:
        asyncio.run(
            seedr_client.seedr_request(
                "/poll",
                base_url="https://www.seedr.cc",
                allowed_redirect_hosts=frozenset({"www.seedr.cc"}),
            )
        )

    assert raised.value.code == "SEEDR_PROGRESS_REDIRECT_INVALID"


def test_seedr_progress_request_revalidates_each_redirect_hop(monkeypatch):
    requests = []

    class RedirectClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, headers, **kwargs):
            requests.append((method, url))
            response = FakeResponse(302, {})
            response.headers["location"] = (
                "/same-origin-next" if len(requests) == 1 else "https://attacker.example/poll"
            )
            return response

    monkeypatch.setattr(seedr_client, "current_seedr_token", lambda: "synthetic-token")
    monkeypatch.setattr(seedr_client, "_seedr_session_auth_mode", lambda _session: "pat")
    monkeypatch.setattr(
        seedr_client,
        "_InstrumentedAsyncClient",
        lambda **kwargs: RedirectClient(),
    )

    with pytest.raises(SeedrError) as raised:
        asyncio.run(
            seedr_client.seedr_request(
                "/poll",
                base_url="https://www.seedr.cc",
                allowed_redirect_hosts=frozenset({"www.seedr.cc"}),
            )
        )

    assert raised.value.code == "SEEDR_PROGRESS_REDIRECT_INVALID"
    assert len(requests) == 2


def test_seedr_progress_request_reports_timeout_without_logging_token(monkeypatch, caplog):
    synthetic_token = "synthetic-seedr-review-token"

    class TimeoutClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, headers, **kwargs):
            raise seedr_client.httpx.ReadTimeout("request timed out")

    monkeypatch.setattr(seedr_client, "current_seedr_token", lambda: synthetic_token)
    monkeypatch.setattr(seedr_client, "_seedr_session_auth_mode", lambda _session: "pat")
    monkeypatch.setattr(
        seedr_client,
        "_InstrumentedAsyncClient",
        lambda **kwargs: TimeoutClient(),
    )

    with pytest.raises(SeedrError) as raised:
        asyncio.run(
            seedr_client.seedr_request(
                "/poll",
                base_url="https://www.seedr.cc",
                allowed_redirect_hosts=frozenset({"www.seedr.cc"}),
            )
        )

    assert raised.value.code == "SEEDR_NETWORK_ERROR"
    assert synthetic_token not in caplog.text


@pytest.mark.parametrize(
    ("token", "expected_code"),
    [
        ("", "SEEDR_TOKEN_MISSING"),
        ("synthetic invalid token", "SEEDR_TOKEN_INVALID"),
    ],
)
def test_seedr_request_rejects_missing_or_invalid_token_before_http(
    monkeypatch, token, expected_code
):
    class UnexpectedClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, *args, **kwargs):
            raise AssertionError("Invalid credentials must not reach the HTTP client.")

    monkeypatch.setattr(seedr_client, "current_seedr_token", lambda: token)
    monkeypatch.setattr(
        seedr_client,
        "_InstrumentedAsyncClient",
        lambda **kwargs: UnexpectedClient(),
    )

    with pytest.raises(SeedrError) as raised:
        asyncio.run(seedr_client.seedr_request("/user"))

    assert raised.value.code == expected_code


def install_progress_response(monkeypatch, task_response, *, polling_url=None, poll_error=None):
    requests = []
    poll_path = "api/v0.1/p/tasks/123/progress/poll?ticket=opaque"
    if polling_url is None:
        polling_url = f"https://www.seedr.cc/{poll_path}"

    async def fake_seedr_request(path, *args, **kwargs):
        requests.append((path, kwargs))
        if path == "/tasks/123/progress":
            return polling_url
        if path == poll_path:
            assert kwargs["base_url"] == "https://www.seedr.cc"
            if poll_error:
                raise poll_error
            return {"pollAccepted": True}
        if path == "/tasks/123":
            return task_response
        raise AssertionError(f"Unexpected Seedr request path: {path}")

    monkeypatch.setattr(seedr_api, "seedr_request", fake_seedr_request)
    return requests


def test_seedr_task_progress_polls_documented_url_then_reads_task_state(monkeypatch):
    requests = install_progress_response(
        monkeypatch,
        {"task": {"id": "123", "state": "downloading", "progress": 35, "torrent_name": "Example"}},
    )

    result = asyncio.run(seedr_api.seedr_task_progress("123"))

    assert [path for path, _kwargs in requests] == [
        "/tasks/123/progress",
        "api/v0.1/p/tasks/123/progress/poll?ticket=opaque",
        "/tasks/123",
    ]
    assert requests[1][1]["allowed_redirect_hosts"] == frozenset({"www.seedr.cc"})
    assert result["status"] == "downloading"
    assert result["progress"] == 35
    assert "ticket=opaque" not in json.dumps(result)


def test_seedr_task_progress_keeps_missing_progress_unknown(monkeypatch):
    install_progress_response(
        monkeypatch,
        {"task": {"id": "123", "state": "downloading"}},
    )

    result = asyncio.run(seedr_api.seedr_task_progress("123"))

    assert result["status"] == "downloading"
    assert result["progress"] is None


def test_seedr_task_progress_marks_completed_task(monkeypatch):
    install_progress_response(
        monkeypatch,
        {"task": {"id": "123", "state": "completed", "progress": 98}},
    )
    async def no_task_contents(_tid):
        return []

    monkeypatch.setattr(seedr_api, "task_contents", no_task_contents)

    result = asyncio.run(seedr_api.seedr_task_progress("123"))

    assert result["status"] == "completed"
    assert result["progress"] == 100


def test_seedr_task_progress_marks_failed_task(monkeypatch):
    install_progress_response(
        monkeypatch,
        {"task": {"id": "123", "state": "failed", "progress": 24}},
    )

    result = asyncio.run(seedr_api.seedr_task_progress("123"))

    assert result["status"] == "failed"
    assert result["progress"] == 24


@pytest.mark.parametrize(
    "polling_url",
    [
        "",
        "https://attacker.example/poll",
        "http://www.seedr.cc/api/v0.1/p/poll",
        "https://user@www.seedr.cc/api/v0.1/p/poll",
        {"poll_url": "https://www.seedr.cc/api/v0.1/p/poll"},
    ],
)
def test_seedr_task_progress_rejects_invalid_polling_urls(monkeypatch, polling_url):
    install_progress_response(monkeypatch, {}, polling_url=polling_url)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(seedr_api.seedr_task_progress("123"))

    assert raised.value.status_code == 502


def test_seedr_task_progress_surfaces_polling_failure(monkeypatch):
    install_progress_response(
        monkeypatch,
        {"task": {"id": "123", "state": "downloading", "progress": 1}},
        poll_error=HTTPException(504, "Seedr progress polling timed out."),
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(seedr_api.seedr_task_progress("123"))

    assert raised.value.status_code == 504


@pytest.mark.parametrize("task_response", [None, {}, {"task": {}}])
def test_seedr_task_progress_rejects_unexpected_task_response(monkeypatch, task_response):
    install_progress_response(monkeypatch, task_response)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(seedr_api.seedr_task_progress("123"))

    assert raised.value.status_code == 502


def test_seedr_add_classifies_insufficient_scope_response(monkeypatch):
    class ForbiddenClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, headers, **kwargs):
            return FakeResponse(
                403,
                {
                    "error": "insufficient_scope",
                    "error_description": "files.write",
                },
            )

    monkeypatch.setattr(seedr_client, "current_seedr_token", lambda: "unit-test-pat")
    monkeypatch.setattr(seedr_client, "_seedr_session_auth_mode", lambda _session: "pat")
    monkeypatch.setattr(seedr_client, "_InstrumentedAsyncClient", lambda **kwargs: ForbiddenClient())

    with pytest.raises(SeedrError) as raised:
        asyncio.run(
            seedr_client.add_task(
                "magnet:?xt=urn:btih:" + "d" * 40,
                0,
            )
        )

    assert raised.value.code == "SEEDR_INSUFFICIENT_SCOPE"
    assert raised.value.status_code == 403
    assert "tasks.write" in raised.value.detail
    assert "files.write" in raised.value.detail
    assert "enable both" not in raised.value.detail.lower()
    assert "unit-test-pat" not in raised.value.detail
