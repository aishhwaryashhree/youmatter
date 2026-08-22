"""
test_api_rate_limit.py
----------------------
CI-safe replacement for the old manual test_rate_limit.py.

Tests the HTTP API rate-limiting behavior via FastAPI's in-process
TestClient (httpx.ASGITransport) — no live server, no real Sarvam calls.

What it asserts:
  1. The first 10 requests for a given user_id succeed (200 OK, non-rate-limited reply).
  2. The 11th+ request for the same user_id within the window returns 200 with
     the rate-limit response text.
  3. A completely different user_id is never affected by another user's rate limit.
  4. The /health endpoint is always reachable (sanity check for CI).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# App fixture — patch everything that touches the network before importing app
# ---------------------------------------------------------------------------

def _classify_response(topics="NONE", score=1, in_domain="yes"):
    content = f"TOPICS: {topics}\nSCORE: {score}\nIN_DOMAIN: {in_domain}"
    return MagicMock(
        json=lambda: {
            "choices": [{"message": {"content": content, "reasoning_content": None}}]
        }
    )


def _reply_response(text="I'm here for you."):
    return MagicMock(
        json=lambda: {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": text, "reasoning_content": None},
            }]
        }
    )


@pytest.fixture()
def app_client():
    """
    Return a synchronous TestClient wrapping the FastAPI app.

    The app's lifespan creates a real httpx.AsyncClient; we patch it out at
    the module level so every Sarvam call goes to our mock instead of the
    network.
    """
    # Provide an essentially infinite stream of alternating classify/reply mocks
    def _infinite_post(*args, **kwargs):
        url = args[0] if args else kwargs.get("url", "")
        # classify call — short max_tokens, produces the 3-line structured output
        return _classify_response()

    # We patch ai_core's http_client.post calls via a module-level AsyncMock
    with patch("ai_core.sarvam_rate_limiter") as mock_srl:
        mock_srl.acquire = AsyncMock(return_value=None)

        from main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            # Inject a mock http_client into app state after lifespan runs.
            # aclose must be AsyncMock because lifespan does `await http_client.aclose()`.
            mock_http = MagicMock()
            mock_http.aclose = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(side_effect=lambda *a, **kw: (
                _classify_response() if kw.get("json", {}).get("max_tokens", 500) <= 80
                else _reply_response()
            ))
            app.state.http_client = mock_http
            yield client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health_endpoint(app_client):
    """Health endpoint must always return 200."""
    r = app_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "YouMatter AI is running"


def test_first_ten_requests_not_rate_limited(app_client):
    """
    First 10 POST /chat/{user_id} calls for a user must succeed without
    being rate-limited. Each must return 200 with a normal (non-rate-limit) reply.
    """
    user_id = "rl-api-test-user"
    for i in range(10):
        r = app_client.post(
            f"/chat/{user_id}",
            json={"user_id": user_id, "message": f"hello {i}"},
        )
        assert r.status_code == 200, f"Request {i} failed: {r.text}"
        body = r.json()
        reply = body.get("reply", "")
        assert "lot of messages" not in reply, (
            f"Request {i} was unexpectedly rate-limited. Reply: {reply!r}"
        )


def test_eleventh_request_is_rate_limited(app_client):
    """
    After 10 requests, the 11th must return the rate-limit reply text.
    """
    user_id = "rl-api-test-user-11"
    for i in range(10):
        app_client.post(
            f"/chat/{user_id}",
            json={"user_id": user_id, "message": f"msg {i}"},
        )

    r = app_client.post(
        f"/chat/{user_id}",
        json={"user_id": user_id, "message": "msg 11"},
    )
    assert r.status_code == 200
    reply = r.json().get("reply", "")
    assert "lot of messages" in reply or "moment" in reply, (
        f"Expected rate-limit reply for 11th request, got: {reply!r}"
    )


def test_different_user_not_rate_limited(app_client):
    """
    Rate limiting one user must never affect a completely different user_id.
    """
    user_a = "rl-user-a"
    user_b = "rl-user-b"

    # Saturate user_a
    for i in range(11):
        app_client.post(
            f"/chat/{user_a}",
            json={"user_id": user_a, "message": f"msg {i}"},
        )

    # user_b's first message must not be rate-limited
    r = app_client.post(
        f"/chat/{user_b}",
        json={"user_id": user_b, "message": "hello"},
    )
    assert r.status_code == 200
    reply = r.json().get("reply", "")
    assert "lot of messages" not in reply, (
        f"user_b was incorrectly rate-limited by user_a's traffic. Reply: {reply!r}"
    )
