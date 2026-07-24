"""The real SigV4 + forwarded-token transport. The signing is exercised offline
(injected static credentials + a fake httpx client) so the request shape and
response mapping are pinned without AWS or the network."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from botocore.credentials import Credentials

from ideation.adapter import CoreHttpError, CoreNotFoundError
from ideation.transport import FORWARDED_USER_HEADER, CoreTransport


class FakeHttpx:
    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status = status
        self.body = {} if body is None else body
        self.calls: list[dict[str, Any]] = []

    async def request(self, method, url, headers, content):  # noqa: ANN001
        self.calls.append({"method": method, "url": url, "headers": headers, "content": content})
        return httpx.Response(self.status, content=json.dumps(self.body).encode())


def _transport(fake: FakeHttpx) -> CoreTransport:
    return CoreTransport(
        founder_token="founder-jwt",
        base_url="https://core.example/prod",
        region="eu-west-1",
        credentials=Credentials("AKIA", "secret"),
        client=fake,
    )


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_signs_forwards_the_token_and_returns_json():
    fake = FakeHttpx(200, {"id": "sess-1"})
    out = _run(
        _transport(fake).request(
            "PATCH",
            "/api/v1/internal/owner-data/ideation_sessions/sess-1",
            json={"turn_count": 3},
        )
    )
    assert out == {"id": "sess-1"}
    call = fake.calls[0]
    assert call["method"] == "PATCH"
    assert (
        call["url"]
        == "https://core.example/prod/api/v1/internal/owner-data/ideation_sessions/sess-1"
    )
    # SigV4 signed (Authorization) AND the founder token forwarded for Core to re-verify
    assert call["headers"]["Authorization"].startswith("AWS4-HMAC-SHA256")
    assert call["headers"][FORWARDED_USER_HEADER] == "founder-jwt"
    assert json.loads(call["content"]) == {"turn_count": 3}


def test_query_params_are_appended():
    fake = FakeHttpx(200, [])
    _run(
        _transport(fake).request(
            "GET",
            "/api/v1/internal/owner-data/ideation_reports",
            params={"session_id": "s1"},
        )
    )
    assert fake.calls[0]["url"].endswith("/ideation_reports?session_id=s1")


def test_404_maps_to_core_not_found():
    with pytest.raises(CoreNotFoundError):
        _run(_transport(FakeHttpx(404)).request("GET", "/api/v1/internal/owner-data/x/missing"))


def test_other_errors_map_to_core_http_error():
    with pytest.raises(CoreHttpError):
        _run(_transport(FakeHttpx(500)).request("POST", "/api/v1/internal/agent-runs", json={}))
