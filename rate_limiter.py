# rate_limiter.py
# Two limiters used by ai_core.py:
#
# 1. PerUserRateLimiter / per_user_rate_limiter
#    Per-user message rate gate: prevents a single user_id from flooding the
#    service with messages. Tracks a rolling 60-second window per user using
#    a deque of timestamps. Raises PerUserRateLimitExceeded when the limit
#    is exceeded. Called inside chat() and chat_stream() AFTER check_safety()
#    has confirmed the message is NOT crisis or severe — the safety invariant
#    in ai_core.py guarantees this function is never reached for crisis traffic.
#
# 2. sarvam_rate_limiter / SarvamRateLimiter
#    Account-level outgoing Sarvam API throttle. acquire() is awaited once
#    immediately before each HTTP POST to SARVAM_URL.  Uses asyncio.Semaphore
#    as a simple token bucket; tokens are replenished on a fixed 60-second
#    cycle in a background task that starts when the module is first imported.

import asyncio
import collections
import time
import logging

logger = logging.getLogger("youmatter.rate_limiter")


# ---------------------------------------------------------------------------
# Per-user message rate limiter
# ---------------------------------------------------------------------------

class PerUserRateLimitExceeded(Exception):
    """Raised by PerUserRateLimiter.check() when a user sends too many
    messages in the rolling window."""
    pass


class PerUserRateLimiter:
    """Rolling-window per-user rate limiter.

    Tracks a deque of timestamps per user_id.  On each check(), timestamps
    older than `window_seconds` are discarded, then the remaining count is
    compared to `max_messages`.  Thread-safe for asyncio (single-threaded
    event loop); no lock needed since all coroutines run on the same loop.

    Args:
        max_messages: Maximum number of messages allowed in the window.
        window_seconds: Length of the rolling window in seconds.
    """

    def __init__(self, max_messages: int = 10, window_seconds: int = 60):
        self._max = max_messages
        self._window = window_seconds
        # user_id -> collections.deque of float timestamps
        self._windows: dict = {}

    async def check(self, user_id: str) -> None:
        """Allow the message through, or raise PerUserRateLimitExceeded.

        Mutates the internal deque for user_id in place.  Discards expired
        timestamps before checking, so the window truly rolls.

        Raises:
            PerUserRateLimitExceeded: if the user has sent >= max_messages
                within the last window_seconds.
        """
        now = time.monotonic()
        cutoff = now - self._window

        if user_id not in self._windows:
            self._windows[user_id] = collections.deque()

        dq = self._windows[user_id]

        # Discard timestamps outside the rolling window
        while dq and dq[0] < cutoff:
            dq.popleft()

        if len(dq) >= self._max:
            logger.warning(
                "[RATE LIMIT] user_id=%r exceeded %d messages in %ds window",
                user_id, self._max, self._window
            )
            raise PerUserRateLimitExceeded(
                f"User {user_id!r} exceeded {self._max} messages "
                f"in {self._window} seconds"
            )

        dq.append(now)


# Singleton used by ai_core.py -- 10 messages per 60-second rolling window.
per_user_rate_limiter = PerUserRateLimiter(max_messages=10, window_seconds=60)


# ---------------------------------------------------------------------------
# Sarvam account-level outgoing API rate limiter
# ---------------------------------------------------------------------------

class SarvamRateLimiter:
    """Simple token-bucket throttle for outgoing Sarvam API calls.

    Maintains a semaphore with `capacity` tokens.  acquire() waits until a
    token is available, then consumes it.  A background asyncio task refills
    the semaphore back to capacity every `refill_seconds` seconds.

    This gives a fixed-window guarantee of at most `capacity` calls per
    `refill_seconds` second period, which matches Sarvam free-tier cap
    (40 requests per 60 seconds for sarvam-105b).

    The refill task is started lazily on the first acquire() call so it always
    runs on the event loop that is actually live when the app starts.
    """

    def __init__(self, capacity: int = 40, refill_seconds: int = 60):
        self._capacity = capacity
        self._refill_seconds = refill_seconds
        # Start with all tokens available
        self._sem = asyncio.Semaphore(capacity)
        self._refill_task = None

    def _ensure_refill_task(self):
        """Start the background refill task if it is not already running.
        Called lazily on first acquire() so the event loop is guaranteed live.
        """
        if self._refill_task is None or self._refill_task.done():
            self._refill_task = asyncio.ensure_future(self._refill_loop())

    async def _refill_loop(self):
        """Runs forever, refilling the semaphore to capacity every window."""
        while True:
            await asyncio.sleep(self._refill_seconds)
            # Release tokens up to capacity.  asyncio.Semaphore has no built-in
            # ceiling so we track how many to add manually via the internal counter.
            current = self._sem._value
            to_add = self._capacity - current
            for _ in range(to_add):
                self._sem.release()
            logger.debug(
                "[SARVAM LIMITER] refilled %d tokens (capacity=%d)",
                to_add, self._capacity
            )

    async def acquire(self, bypass: bool = False):
        """Consume one token, waiting if none are available.

        Called immediately before each HTTP POST to SARVAM_URL.

        Args:
            bypass: If True, return immediately without touching the semaphore
                or waiting for a token. Used to skip rate-limiting for
                crisis/severe traffic that must never be queued.
        """
        if bypass:
            return
        self._ensure_refill_task()
        await self._sem.acquire()


# Singleton used by ai_core.py -- 40 outgoing calls per 60-second window,
# matching Sarvam free-tier cap for sarvam-105b.
sarvam_rate_limiter = SarvamRateLimiter(capacity=40, refill_seconds=60)
