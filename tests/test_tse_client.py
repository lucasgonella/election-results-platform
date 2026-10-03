import json

import pytest
import requests

from collector.src.tse_client import TseClient


class FakeResponse:
    def __init__(
        self,
        *,
        status_code,
        payload=None,
        headers=None,
        raw_content=None,
    ):
        self.status_code = status_code
        self.headers = headers or {}

        if raw_content is not None:
            self.content = raw_content
        elif payload is not None:
            self.content = json.dumps(
                payload
            ).encode("utf-8")
        else:
            self.content = b""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code}"
            )


def test_fetch_json_200(monkeypatch):
    client = TseClient()

    response = FakeResponse(
        status_code=200,
        payload={
            "ele": "21272",
            "idg": "123",
        },
        headers={
            "ETag": '"abc123"',
            "Last-Modified":
                "Sat, 03 Oct 2026 12:00:00 GMT",
        },
    )

    monkeypatch.setattr(
        client.session,
        "get",
        lambda *args, **kwargs: response,
    )

    result = client.fetch_json(
        "https://example.invalid/test.json"
    )

    assert result.status_code == 200
    assert result.etag == '"abc123"'
    assert result.payload["ele"] == "21272"
    assert result.sha256 is not None
    assert len(result.sha256) == 64


def test_fetch_json_304(monkeypatch):
    client = TseClient()

    captured = {}

    response = FakeResponse(
        status_code=304,
    )

    def fake_get(
        url,
        *,
        headers,
        timeout,
    ):
        captured["headers"] = headers
        return response

    monkeypatch.setattr(
        client.session,
        "get",
        fake_get,
    )

    result = client.fetch_json(
        "https://example.invalid/test.json",
        etag='"abc123"',
        last_modified=(
            "Sat, 03 Oct 2026 12:00:00 GMT"
        ),
    )

    assert result.status_code == 304
    assert result.payload is None
    assert result.sha256 is None

    assert (
        captured["headers"]["If-None-Match"]
        == '"abc123"'
    )

    assert (
        "If-Modified-Since"
        in captured["headers"]
    )


def test_invalid_json_is_rejected(monkeypatch):
    client = TseClient()

    response = FakeResponse(
        status_code=200,
        raw_content=b"this is not json",
    )

    monkeypatch.setattr(
        client.session,
        "get",
        lambda *args, **kwargs: response,
    )

    with pytest.raises(
        json.JSONDecodeError
    ):
        client.fetch_json(
            "https://example.invalid/test.json"
        )
