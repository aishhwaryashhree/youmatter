"""
conftest.py -- shared pytest fixtures and configuration.

- asyncio_mode: auto so every async def test_ is handled automatically.
- reset_rate_limiter: clears per_user_rate_limiter state between tests
  so request counts never bleed across test functions.
"""
import pytest

pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear the per-user rate limiter windows before and after each test."""
    from rate_limiter import per_user_rate_limiter
    per_user_rate_limiter._windows.clear()
    yield
    per_user_rate_limiter._windows.clear()
