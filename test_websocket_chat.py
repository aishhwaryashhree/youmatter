"""
test_websocket_chat.py
-----------------------
CI-safe replacement for the old manual test_ws.py.

Uses FastAPI's built-in WebSocket test support (TestClient.websocket_connect)
in-process — no live server, no real Sarvam API calls.

What it asserts:
  1. A WebSocket message produces at least one {"type": "token"} event.
  2. The event stream ends with exactly one {"type": "safety_result"} event.
  3. The safety_result payload contains all expected keys.
  4. A crisis-keyword message still gets a safety_result with safety_level
     in ["crisis", "severe"] (crisis pipeline fires correctly over WS).
  5. A blocked request (harmful keyword) returns blocked=True in safety_result.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import json

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXPECTED_SAFETY_RESULT_KEYS = {
    "type", "safety_level", "blocked", "alert_sent",
    "show_consent_prompt", "helplines",
}


def _sse_classify(topics="NONE", score=1, in_domain="yes"):
    content = f"TOPICS: {topics}\nSCORE: {score}\nIN_DOMAIN: {in_domain}"
    return MagicMock(
        json=lambda: {
            "choices": [{"message": {"content": content, "reasoning_content": None}}]
        }
    )


# chat_stream uses http_client.stream() for SSE, not .post() for the reply.
# We mock the async context manager that stream() returns.
def _make_stream_mock(reply_text="I'm right here with you."):
    """
    Build an async context manager mock that yields SSE lines matching
    the Sarvam streaming format, so chat_stream() can iterate over them.
    """
    lines = [
        f'data: {json.dumps({"choices": [{"delta": {"content": chunk}}]})}'
        for chunk in reply_text.split()  # one token per word
    ]
    lines.append("data: [DONE]")

    async def _aiter_lines():
        for line in lines:
            yield line

    mock_response = MagicMock()
    mock_response.aiter_lines = _aiter_lines

    class _AsyncCM:
        async def __aenter__(self): return mock_response
        async def __aexit__(self, *_): pass

    return _AsyncCM()


# ---------------------------------------------------------------------------
# App + client fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def ws_client():
    """
    TestClient with mocked Sarvam calls (classify via .post, reply via .stream).
    """
    with patch("ai_core.sarvam_rate_limiter") as mock_srl:
        mock_srl.acquire = AsyncMock(return_value=None)

        from main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            mock_http = MagicMock()

            # aclose must be AsyncMock because lifespan does `await http_client.aclose()`.
            mock_http.aclose = AsyncMock(return_value=None)

            # .post() is used for classify_topic_and_score
            mock_http.post = AsyncMock(return_value=_sse_classify())

            # .stream() is used for the SSE reply in chat_stream
            mock_http.stream = MagicMock(return_value=_make_stream_mock())

            app.state.http_client = mock_http
            yield client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_ws_produces_token_events(ws_client):
    """
    A normal message over WebSocket must produce at least one token event
    before the safety_result event.
    """
    with ws_client.websocket_connect("/ws/chat/ws-test-user") as ws:
        ws.send_json({"message": "hi how are you", "consent": None})

        events = []
        for _ in range(50):   # safety cap — never spin forever
            try:
                raw = ws.receive_json()
                events.append(raw)
                if raw.get("type") == "safety_result":
                    break
            except Exception:
                break

    token_events = [e for e in events if e.get("type") == "token"]
    safety_events = [e for e in events if e.get("type") == "safety_result"]

    assert len(token_events) >= 1, \
        f"Expected at least one token event, got events: {events}"
    assert len(safety_events) == 1, \
        f"Expected exactly one safety_result event, got: {safety_events}"


def test_ws_safety_result_has_required_keys(ws_client):
    """
    The safety_result event must contain all expected payload keys.
    """
    with ws_client.websocket_connect("/ws/chat/ws-key-test") as ws:
        ws.send_json({"message": "feeling a bit down today", "consent": None})

        safety_result = None
        for _ in range(50):
            try:
                raw = ws.receive_json()
                if raw.get("type") == "safety_result":
                    safety_result = raw
                    break
            except Exception:
                break

    assert safety_result is not None, "Never received a safety_result event"
    missing = EXPECTED_SAFETY_RESULT_KEYS - set(safety_result.keys())
    assert not missing, \
        f"safety_result is missing keys: {missing}. Got: {set(safety_result.keys())}"


def test_ws_safety_level_is_valid(ws_client):
    """
    The safety_level in safety_result must be one of the four known values.
    """
    valid_levels = {"safe", "distress", "crisis", "severe"}

    with ws_client.websocket_connect("/ws/chat/ws-level-test") as ws:
        ws.send_json({"message": "just checking in", "consent": None})

        safety_result = None
        for _ in range(50):
            try:
                raw = ws.receive_json()
                if raw.get("type") == "safety_result":
                    safety_result = raw
                    break
            except Exception:
                break

    assert safety_result is not None
    assert safety_result["safety_level"] in valid_levels, \
        f"Unexpected safety_level: {safety_result['safety_level']!r}"


def test_ws_crisis_message_produces_crisis_level(ws_client):
    """
    A message containing a clear crisis keyword must produce safety_level
    in ['crisis', 'severe'] — the keyword layer fires before anything else.
    """
    # "want to die" is in CRISIS_KEYWORDS in safety.py
    crisis_msg = "i want to die i can't take it anymore"

    with ws_client.websocket_connect("/ws/chat/ws-crisis-test") as ws:
        ws.send_json({"message": crisis_msg, "consent": None})

        safety_result = None
        for _ in range(50):
            try:
                raw = ws.receive_json()
                if raw.get("type") == "safety_result":
                    safety_result = raw
                    break
            except Exception:
                break

    assert safety_result is not None, "Never received safety_result for crisis message"
    assert safety_result["safety_level"] in ("crisis", "severe"), (
        f"Crisis message should produce crisis/severe, "
        f"got {safety_result['safety_level']!r}"
    )


def test_ws_blocked_request_returns_blocked_true(ws_client):
    """
    A message matching the BLOCKED_REQUESTS keyword list must produce
    a safety_result with blocked=True.
    """
    # "how to tie a noose" is in BLOCKED_REQUESTS in safety.py
    blocked_msg = "how to tie a noose"

    with ws_client.websocket_connect("/ws/chat/ws-blocked-test") as ws:
        ws.send_json({"message": blocked_msg, "consent": None})

        safety_result = None
        for _ in range(50):
            try:
                raw = ws.receive_json()
                if raw.get("type") == "safety_result":
                    safety_result = raw
                    break
            except Exception:
                break

    assert safety_result is not None
    assert safety_result.get("blocked") is True, \
        f"Expected blocked=True for harmful request, got: {safety_result}"
