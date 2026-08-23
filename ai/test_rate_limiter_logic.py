"""
test_rate_limiter_logic.py
--------------------------
CI-safe replacement for the old manual test_bypass.py.

What it tests:
  1. The per-user rate limiter correctly blocks the 11th+ message for a user
     within the rolling window.
  2. Crisis-flagged messages bypass the per-user rate limiter entirely — even
     if the user has already hit the limit — and the crisis pipeline still
     classifies the message correctly.
  3. The Sarvam rate limiter bypass flag works: crisis calls never queue behind
     casual calls even when the global semaphore bucket is drained.

All Sarvam HTTP calls are mocked with unittest.mock so CI never touches the
real api.sarvam.ai endpoint. Memory calls are also stubbed out (the memory
module already short-circuits when BACKEND_DISABLED=True, so no extra patch
needed for memory reads; save_message is patched to be a no-op).
"""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import httpx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sarvam_classify_response(topics="NONE", score=1, in_domain="yes"):
    """Build a minimal fake Sarvam JSON response for classify_topic_and_score."""
    content = f"TOPICS: {topics}\nSCORE: {score}\nIN_DOMAIN: {in_domain}"
    return MagicMock(
        json=lambda: {
            "choices": [{
                "message": {
                    "content": content,
                    "reasoning_content": None,
                }
            }]
        }
    )


def _make_sarvam_reply_response(text="I hear you. Tell me more."):
    """Build a minimal fake Sarvam JSON response for _get_ai_reply."""
    return MagicMock(
        json=lambda: {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": text,
                    "reasoning_content": None,
                }
            }]
        }
    )


# ---------------------------------------------------------------------------
# Test 1: per-user rate limiter blocks the 11th request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_per_user_rate_limiter_blocks_after_limit():
    """
    After 10 successful messages, the 11th should return the rate-limit reply
    (safety_level=safe, specific reply text) without making a Sarvam call.
    """
    from ai_core import chat

    # patch http_client.post to return controlled fake responses
    mock_post = AsyncMock(side_effect=[
        # 10 classify calls + 10 reply calls for the first 10 messages
        *[_make_sarvam_classify_response() for _ in range(10)],
        *[_make_sarvam_reply_response() for _ in range(10)],
    ])

    mock_client = MagicMock()
    mock_client.post = mock_post

    user_id = "rl-test-user"

    # Send 10 messages — all should pass through
    for i in range(10):
        result = await chat(user_id, f"message {i}", mock_client)
        assert result["safety_level"] in ("safe", "distress", "crisis", "severe"), \
            f"Unexpected safety_level on message {i}: {result}"

    # 11th message should be rate-limited
    result_11 = await chat(user_id, "message 11", mock_client)
    assert result_11["safety_level"] == "safe"
    assert "lot of messages" in result_11["reply"] or "moment" in result_11["reply"], \
        f"Expected rate-limit reply text, got: {result_11['reply']!r}"


# ---------------------------------------------------------------------------
# Test 2: crisis messages bypass the per-user rate limiter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_crisis_bypasses_per_user_rate_limiter():
    """
    Even after a user has hit the per-user rate limit, a message containing
    a clear crisis keyword must NOT be blocked by the rate limiter — it must
    fall through to the full crisis pipeline.
    """
    from ai_core import chat
    from rate_limiter import per_user_rate_limiter
    import time

    user_id = "crisis-bypass-user"

    # Manually saturate the rate limiter for this user (inject 10 timestamps)
    import collections
    now = time.monotonic()
    per_user_rate_limiter._windows[user_id] = collections.deque([now] * 10)

    # "want to die" is in CRISIS_KEYWORDS in safety.py — keyword layer should
    # catch it before the rate limiter check.
    crisis_message = "i want to die i can't take it anymore"

    # The classify call will return a crisis-level score; reply returns warmth
    mock_post = AsyncMock(side_effect=[
        _make_sarvam_classify_response(topics="crisis", score=8, in_domain="yes"),
        _make_sarvam_reply_response("I'm here with you. Please don't go."),
    ])
    mock_client = MagicMock()
    mock_client.post = mock_post

    result = await chat(user_id, crisis_message, mock_client)

    # Must NOT be rate-limited — safety_level must be crisis or severe
    assert result["safety_level"] in ("crisis", "severe"), (
        f"Crisis message was incorrectly rate-limited or misclassified. "
        f"Got safety_level={result['safety_level']!r}, reply={result['reply']!r}"
    )
    assert result["blocked"] is False


# ---------------------------------------------------------------------------
# Test 3: Sarvam rate limiter bypass=True lets crisis calls skip the queue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sarvam_rate_limiter_bypass_for_crisis():
    """
    When the global Sarvam semaphore is fully drained (0 tokens), a crisis
    call with bypass=True must acquire immediately without waiting.
    """
    from rate_limiter import SarvamRateLimiter

    # Create a limiter with 0 capacity — acquire without bypass would hang
    limiter = SarvamRateLimiter(capacity=0, refill_seconds=9999)
    # Manually drain the semaphore to ensure no tokens
    limiter._sem = asyncio.Semaphore(0)

    # bypass=True should return immediately without touching the semaphore
    completed = False
    async def _try_acquire():
        nonlocal completed
        await limiter.acquire(bypass=True)
        completed = True

    await asyncio.wait_for(_try_acquire(), timeout=1.0)
    assert completed, "bypass=True did not return immediately on a drained semaphore"


# ---------------------------------------------------------------------------
# Test 4: domain filter redirects off-topic messages, not crisis ones
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_domain_filter_blocks_offtopic_but_not_crisis():
    """
    When IN_DOMAIN=no and no safety signal, the pipeline must return the warm
    redirect (not call _get_ai_reply). When IN_DOMAIN=no BUT ai_score >= 4,
    the domain filter must be bypassed and the crisis pipeline runs normally.
    """
    from ai_core import chat
    import ai_core

    # --- Part A: off-topic, no safety signal → should be redirected ---
    mock_post_offtopic = AsyncMock(return_value=_make_sarvam_classify_response(
        topics="NONE", score=1, in_domain="no"
    ))
    mock_client = MagicMock()
    mock_client.post = mock_post_offtopic

    result = await chat("domain-test-user", "what is 2+2", mock_client)
    assert result["safety_level"] == "safe"
    assert result["blocked"] is False
    # Should NOT have called _get_ai_reply — reply should be one of the redirect pool
    assert any(phrase in result["reply"] for phrase in [
        "love", "dear", "care", "check in", "feeling", "doing", "listen"
    ]), f"Expected a warm redirect, got: {result['reply']!r}"

    # --- Part B: "off-topic" surface but ai_score=5 → crisis pipeline runs ---
    mock_post_distress = AsyncMock(side_effect=[
        _make_sarvam_classify_response(topics="NONE", score=5, in_domain="no"),
        _make_sarvam_reply_response("You matter so much. Tell me what's going on."),
    ])
    mock_client2 = MagicMock()
    mock_client2.post = mock_post_distress

    result2 = await chat("domain-test-user-2",
                         "just calculate something for me, feeling really hopeless",
                         mock_client2)
    assert result2["safety_level"] in ("distress", "crisis", "severe"), (
        f"Expected distress/crisis to bypass domain filter, "
        f"got safety_level={result2['safety_level']!r}"
    )
