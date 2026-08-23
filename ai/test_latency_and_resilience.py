"""
test_latency_and_resilience.py
------------------------------
Unit and regression tests for response latency, max_tokens configuration,
automatic retry on timeout, timing instrumentation, and streaming in ai_core.py.
"""

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from ai_core import (
    _get_ai_reply,
    chat_stream,
    MAX_COMPANION_TOKENS,
    PRIMARY_TIMEOUT,
    RETRY_TIMEOUT,
    FALLBACK_CRISIS_MESSAGE,
)


def _make_sarvam_reply(content: str, finish_reason: str = "stop"):
    return MagicMock(
        json=lambda: {
            "choices": [{
                "finish_reason": finish_reason,
                "message": {
                    "content": content,
                    "reasoning_content": None,
                }
            }]
        }
    )


@pytest.mark.asyncio
async def test_get_ai_reply_uses_max_companion_tokens(caplog):
    """Verify _get_ai_reply sends max_tokens=250 and logs timing instrumentation."""
    mock_client = MagicMock()
    mock_post = AsyncMock(return_value=_make_sarvam_reply("I hear you completely. Take your time."))
    mock_client.post = mock_post

    messages = [{"role": "user", "content": "I feel so overwhelmed today."}]

    with caplog.at_level(logging.INFO):
        reply = await _get_ai_reply(mock_client, messages)

    assert reply == "I hear you completely. Take your time."
    assert mock_post.call_count == 1

    called_args, called_kwargs = mock_post.call_args
    sent_payload = called_kwargs.get("json", {})
    assert sent_payload.get("max_tokens") == MAX_COMPANION_TOKENS
    assert sent_payload.get("max_tokens") == 250
    assert called_kwargs.get("timeout") == PRIMARY_TIMEOUT
    assert called_kwargs.get("timeout") == 15.0

    # Verify timing log was recorded
    assert any("[TIMING] _get_ai_reply" in record.message for record in caplog.records)
    assert any("Sarvam network=" in record.message for record in caplog.records)
    assert any("pre/post processing=" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_get_ai_reply_single_retry_on_read_timeout(caplog):
    """
    On httpx.ReadTimeout / TimeoutException during primary attempt:
    - Log [RETRY] attempt
    - Retry once with RETRY_TIMEOUT (12s)
    - Return successful reply if retry succeeds
    """
    mock_client = MagicMock()
    mock_post = AsyncMock(side_effect=[
        httpx.ReadTimeout("Connection timed out reading from Sarvam"),
        _make_sarvam_reply("I'm here for you now.")
    ])
    mock_client.post = mock_post

    messages = [{"role": "user", "content": "I need help."}]

    with caplog.at_level(logging.INFO):
        reply = await _get_ai_reply(mock_client, messages)

    assert reply == "I'm here for you now."
    assert mock_post.call_count == 2

    # Check first call timeout vs second call timeout
    first_call_kwargs = mock_post.call_args_list[0].kwargs
    second_call_kwargs = mock_post.call_args_list[1].kwargs
    assert first_call_kwargs.get("timeout") == PRIMARY_TIMEOUT
    assert second_call_kwargs.get("timeout") == RETRY_TIMEOUT
    assert second_call_kwargs.get("timeout") == 12.0

    # Verify retry warning was logged
    assert any("[RETRY] Sarvam timeout" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_get_ai_reply_fallback_on_double_timeout(caplog):
    """
    When both primary and retry attempts time out:
    - Fallback safely to static crisis resource message
    """
    mock_client = MagicMock()
    mock_post = AsyncMock(side_effect=[
        httpx.ReadTimeout("Timeout 1"),
        httpx.ReadTimeout("Timeout 2")
    ])
    mock_client.post = mock_post

    messages = [{"role": "user", "content": "Please talk to me."}]

    with caplog.at_level(logging.INFO):
        reply = await _get_ai_reply(mock_client, messages)

    assert reply == FALLBACK_CRISIS_MESSAGE
    assert "9152987821" in reply
    assert mock_post.call_count == 2


@pytest.mark.asyncio
async def test_crisis_long_reply_not_truncated():
    """
    Simulate a realistic ~170 token crisis response and verify _get_ai_reply
    returns the entire content intact.
    """
    long_crisis_text = (
        "I can hear how much pain you're in right now, and I want you to know you don't have to carry this completely alone. "
        "Your life and your presence matter more than words can express, even when everything feels unbearable and dark. "
        "Please take a deep breath with me. Are you in a safe place right now? "
        "If you are in immediate danger or having thoughts of hurting yourself, please reach out to someone who can support you immediately: "
        "iCall at 9152987821 or Vandrevala Foundation at 1860-2662-345. They are free, confidential, and available 24/7. "
        "I am right here with you. Can you tell me what's feeling the heaviest right now?"
    )
    # Ensure it is ~170 tokens
    estimated_tokens = len(long_crisis_text.split()) * 1.3
    assert estimated_tokens > 130

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=_make_sarvam_reply(long_crisis_text))

    messages = [{"role": "user", "content": "I can't do this anymore, I want to end it all."}]
    reply = await _get_ai_reply(mock_client, messages, bypass_rate_limit=True)

    assert reply == long_crisis_text
    assert "9152987821" in reply
    assert reply.endswith("heaviest right now?")


@pytest.mark.asyncio
async def test_chat_stream_retry_on_initial_timeout(caplog):
    """
    When streaming encounters a timeout before any tokens are yielded:
    - Retries once with RETRY_TIMEOUT (12s)
    - Yields streamed tokens successfully
    """
    mock_client = MagicMock()

    class _MockStreamCM:
        def __init__(self, should_fail=False):
            self.should_fail = should_fail

        async def __aenter__(self):
            if self.should_fail:
                raise httpx.ReadTimeout("Stream timeout before first byte")

            lines = [
                f'data: {json.dumps({"choices": [{"delta": {"content": "I am "}}]})}',
                f'data: {json.dumps({"choices": [{"delta": {"content": "listening."}}]})}',
                "data: [DONE]"
            ]

            async def _aiter():
                for line in lines:
                    yield line

            resp = MagicMock()
            resp.aiter_lines = _aiter
            return resp

        async def __aexit__(self, *args):
            pass

    stream_attempts = []

    def _stream_side_effect(*args, **kwargs):
        timeout = kwargs.get("timeout")
        stream_attempts.append(timeout)
        if len(stream_attempts) == 1:
            return _MockStreamCM(should_fail=True)
        return _MockStreamCM(should_fail=False)

    mock_client.stream = MagicMock(side_effect=_stream_side_effect)

    with patch("ai_core.classify_topic_and_score", AsyncMock(return_value={"topics": [], "score": 1, "in_domain": True})):
        events = []
        with caplog.at_level(logging.INFO):
            async for event in chat_stream("test-user", "hello", mock_client):
                events.append(event)

    tokens = [e["content"] for e in events if e["type"] == "token"]
    assert "".join(tokens) == "I am listening."
    assert stream_attempts == [PRIMARY_TIMEOUT, RETRY_TIMEOUT]
    assert any("[RETRY] Sarvam stream timeout" in r.message for r in caplog.records)
