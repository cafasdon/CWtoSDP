"""
================================================================================
Adaptive Rate Limiter with Exponential Backoff and Jitter
================================================================================

This module provides intelligent rate limiting for API requests that:
1. Automatically adjusts request rate based on API responses
2. Speeds up when requests succeed consistently (up to min_interval)
3. Slows down exponentially when hitting rate limits (429 errors)
4. Moderately backs off on other errors to prevent cascading failures
5. Uses jitter to prevent synchronized retry storms across threads

Why Adaptive Rate Limiting?
---------------------------
Both ConnectWise and ServiceDesk Plus APIs have rate limits that vary based on:
- Time of day
- Account tier
- Current API load

A fixed rate limit would either:
- Be too slow (wasting time when API is responsive)
- Be too fast (hitting rate limits and getting blocked)

The adaptive approach finds the optimal speed automatically by:
1. Starting at a conservative rate
2. Speeding up when requests succeed
3. Backing off immediately when limits are hit
4. Using boundary tracking to converge on the optimal rate

Thread Safety:
--------------
The wait() method uses a two-phase approach:
1. LOCK: Calculate required wait time and reserve a slot (update timestamp)
2. UNLOCK: Sleep outside the lock so other threads aren't blocked

This allows multiple threads to pipeline through the rate limiter
efficiently — each thread gets a scheduled slot, then sleeps independently.

Algorithm:
----------
1. WAIT: Reserve next time slot, sleep outside lock until slot arrives
2. ON SUCCESS: After N consecutive successes, speed up toward optimal
3. ON 429 (Rate Limit): Update interval (no sleep — wait() handles timing)
4. ON OTHER ERROR: Moderate backoff (1.5x)
5. RECOVERY: After sustained success, decay rate-limit boundaries so the
   limiter gradually re-probes faster speeds toward min_interval

Usage:
------
    limiter = AdaptiveRateLimiter(name="MyAPI", base_interval=1.0)

    # Before making request:
    limiter.wait()
    response = requests.get(url)

    # After response:
    if response.status_code == 200:
        limiter.on_success()
    elif response.status_code == 429:
        limiter.on_rate_limit()
    else:
        limiter.on_error()
"""

import time
import random
import threading
from typing import Optional

from .logger import get_logger

# Get logger for this module (child of main cwtosdp logger)
logger = get_logger("cwtosdp.rate_limiter")


class AdaptiveRateLimiter:
    """
    Adaptive rate limiter with exponential backoff for API requests.
    Thread-safe implementation using RLock.

    This class tracks request timing and automatically adjusts the delay
    between requests based on success/failure patterns. It prevents
    overwhelming APIs while maximizing throughput when conditions allow.
    """

    def __init__(
        self,
        name: str = "API",
        base_interval: float = 0.5,       # Starting interval in seconds
        min_interval: float = 0.2,        # Fastest allowed (5 req/sec)
        max_interval: float = 120.0,      # Slowest allowed (1 req per 2 min)
        backoff_factor: float = 2.0,      # 2x slower on rate limit
        speedup_factor: float = 0.9,      # 10% faster after success streak
        success_streak_to_speedup: int = 3,  # Need 3 successes to speed up
        recovery_threshold: int = 10      # Successes before decaying boundaries
    ):
        """
        Initialize the adaptive rate limiter.

        Args:
            name: Identifier for this limiter (used in log messages)
            base_interval: Initial delay between requests in seconds
            min_interval: Minimum delay (won't go faster than this)
            max_interval: Maximum delay (won't go slower than this)
            backoff_factor: How much to slow down on rate limit (2.0 = double)
            speedup_factor: How much to speed up on success (0.9 = 10% faster)
            success_streak_to_speedup: Consecutive successes needed to speed up
            recovery_threshold: Consecutive successes after last rate limit before
                               boundaries start decaying (allows re-probing faster speeds)
        """
        # Configuration
        self.name = name
        self.base_interval = base_interval
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.backoff_factor = backoff_factor
        self.speedup_factor = speedup_factor
        self.success_streak_to_speedup = success_streak_to_speedup
        self.recovery_threshold = recovery_threshold

        # Thread safety — used for short critical sections only.
        # wait() releases the lock BEFORE sleeping so other threads
        # can reserve their own time slots concurrently.
        self._lock = threading.RLock()

        # Internal state (prefixed with _ to indicate private)
        self._current_interval = base_interval      # Current delay between requests
        self._next_allowed_time: float = 0.0        # Earliest time next request may fire
        self._consecutive_successes: int = 0        # Success streak counter
        self._total_requests: int = 0               # Total requests made
        self._total_rate_limits: int = 0            # Total 429s received
        self._total_successes: int = 0              # Total successful requests
        self._successes_since_rate_limit: int = 0   # Successes since last 429 (for recovery)

        # Optimal rate discovery - track the boundaries
        # fastest_accepted: smallest interval that got a 200 (fastest safe speed)
        # slowest_rejected: largest interval that still got a 429 (slowest unsafe speed)
        # When fastest_accepted > slowest_rejected, the boundary is bracketed
        self._fastest_accepted: float = base_interval   # Fastest interval that worked
        self._slowest_rejected: float = 0.0             # Slowest interval that got rate limited
        self._optimal_interval: Optional[float] = None  # Calculated optimal rate

        # Performance tracking
        self._start_time: float = time.time()
    
    # =========================================================================
    # PROPERTIES - Read-only access to internal state
    # =========================================================================

    @property
    def current_interval(self) -> float:
        """
        Get the current interval between requests.

        Returns:
            Current delay in seconds between API requests
        """
        return self._current_interval

    @property
    def stats(self) -> dict:
        """
        Get statistics about rate limiter performance.

        Useful for monitoring and debugging API interactions.

        Returns:
            Dictionary with performance metrics and optimal rate info
        """
        with self._lock:
            elapsed = time.time() - self._start_time
            actual_rate = self._total_requests / elapsed if elapsed > 0 else 0
            success_rate = (self._total_successes / self._total_requests * 100) if self._total_requests > 0 else 0

            return {
                "total_requests": self._total_requests,
                "total_successes": self._total_successes,
                "rate_limits_hit": self._total_rate_limits,
                "success_rate_pct": round(success_rate, 1),
                "current_interval": round(self._current_interval, 3),
                "requests_per_minute": round(60 / self._current_interval, 1) if self._current_interval > 0 else 0,
                "actual_rpm": round(actual_rate * 60, 1),
                "fastest_accepted": round(self._fastest_accepted, 3),
                "slowest_rejected": round(self._slowest_rejected, 3) if self._slowest_rejected > 0 else None,
                "optimal_interval": round(self._optimal_interval, 3) if self._optimal_interval else None,
                "elapsed_seconds": round(elapsed, 1),
            }

    # =========================================================================
    # CORE METHODS - Called before/after each API request
    # =========================================================================

    def wait(self):
        """
        Wait before making the next request.

        This method should be called BEFORE every API request. It uses a
        two-phase approach for thread safety without blocking:

        Phase 1 (under lock): Reserve the next available time slot by
            advancing _next_allowed_time. This is instant — no sleeping.
        Phase 2 (lock released): Sleep until the reserved slot arrives.

        This allows multiple threads to pipeline through the rate limiter:
        - Thread A reserves slot at t=1.0, releases lock, sleeps until 1.0
        - Thread B reserves slot at t=2.0, releases lock, sleeps until 2.0
        - Both threads sleep concurrently without blocking each other.

        Example:
            >>> limiter.wait()  # May sleep up to current_interval
            >>> response = api.get("/endpoint")
            >>> limiter.on_success()
        """
        # Phase 1: Reserve a time slot (fast, under lock)
        with self._lock:
            now = time.time()

            # Ensure next_allowed_time is at least 'now'
            if self._next_allowed_time < now:
                self._next_allowed_time = now

            # This thread's reserved slot
            my_slot = self._next_allowed_time

            # Advance the slot for the next thread by current_interval
            self._next_allowed_time += self._current_interval
            self._total_requests += 1

        # Phase 2: Sleep until our reserved slot (lock is released)
        sleep_time = my_slot - time.time()
        if sleep_time > 0:
            # Add ±10% jitter to prevent synchronized bursts
            jitter = sleep_time * random.uniform(-0.1, 0.1)
            sleep_time = max(0, sleep_time + jitter)
            if sleep_time > 1.0:
                logger.debug(f"[{self.name}] Rate limiting: waiting {sleep_time:.1f}s")
            time.sleep(sleep_time)

    def on_success(self):
        """
        Call this method AFTER a successful API request (200 OK).

        Tracks consecutive successes and speeds up the request rate
        after a streak of successful calls:

        1. If an optimal interval is known and current > optimal:
           Binary search — jumps 75% toward optimal for fast convergence.

        2. Otherwise, uses dynamic speedup based on distance from target:
           - >10x min_interval: halve the interval (aggressive recovery)
           - >3x min_interval: reduce by 30% (moderate recovery)
           - ≤3x min_interval: reduce by 10% (gentle fine-tuning)

           This means recovery from max_interval (120s) to min_interval
           (0.3s) takes ~39 requests instead of ~156 with a fixed 10%.

        After sustained success (recovery_threshold consecutive successes
        since the last rate limit), gradually decays the rate-limit
        boundaries so the limiter can re-probe faster speeds and
        eventually reach min_interval.

        Example:
            >>> if response.status_code == 200:
            ...     limiter.on_success()
        """
        with self._lock:
            # Track success
            self._consecutive_successes += 1
            self._total_successes += 1
            self._successes_since_rate_limit += 1

            # Track fastest accepted interval (this rate worked!)
            if self._current_interval < self._fastest_accepted:
                self._fastest_accepted = self._current_interval
                logger.debug(f"[{self.name}] New fastest accepted: {self._fastest_accepted:.3f}s")

            # Decay boundaries after sustained success (no rate limits for a while)
            # This allows the limiter to gradually forget old rate-limit boundaries
            # and re-probe faster speeds, eventually reaching min_interval.
            if (self._slowest_rejected > 0
                    and self._successes_since_rate_limit >= self.recovery_threshold):
                self._slowest_rejected *= self.speedup_factor  # Decay by same factor
                if self._slowest_rejected < self.min_interval:
                    # Boundary has decayed below minimum — clear it entirely
                    self._slowest_rejected = 0.0
                    self._optimal_interval = None
                    logger.info(f"[{self.name}] Rate-limit boundary fully decayed — "
                               f"re-probing toward min interval ({self.min_interval:.3f}s)")
                else:
                    logger.debug(f"[{self.name}] Decaying rate-limit boundary: "
                                f"slowest_rejected now {self._slowest_rejected:.3f}s")

            # Recalculate optimal interval if we have both boundaries
            self._calculate_optimal()

            # Check if we've had enough successes to speed up
            if self._consecutive_successes >= self.success_streak_to_speedup:
                if self._optimal_interval and self._current_interval > self._optimal_interval:
                    # Aggressive binary search: jump 75% toward optimal
                    # (was 50% — the old midpoint approach recovered too slowly)
                    new_interval = self._current_interval * 0.25 + self._optimal_interval * 0.75
                else:
                    # Dynamic speedup based on how far above min_interval we are.
                    # When the interval is very high (e.g. after hitting max_interval),
                    # a fixed 10% reduction is far too slow — recovery from 120s to 0.3s
                    # would take ~156 requests (~4 hours). Instead, use aggressive halving
                    # when far away and gentle 10% when close to the target.
                    ratio = self._current_interval / self.min_interval
                    if ratio > 10:
                        # Very far from target — aggressive recovery (halve the interval)
                        effective_speedup = 0.5
                    elif ratio > 3:
                        # Moderately far — moderate recovery (30% reduction)
                        effective_speedup = 0.7
                    else:
                        # Close to target — gentle recovery (10% reduction)
                        effective_speedup = self.speedup_factor

                    new_interval = self._current_interval * effective_speedup

                # Only apply if above minimum (don't go faster than allowed)
                if new_interval >= self.min_interval:
                    old_interval = self._current_interval
                    self._current_interval = new_interval
                    # Use INFO level for aggressive recovery so it's visible in logs
                    if old_interval / self.min_interval > 3:
                        logger.info(f"[{self.name}] Recovery speedup: {old_interval:.2f}s → "
                                   f"{self._current_interval:.2f}s ({60/self._current_interval:.1f} req/min)")
                    else:
                        logger.debug(f"[{self.name}] Speeding up: interval now {self._current_interval:.3f}s "
                                    f"({60/self._current_interval:.1f} req/min)")

                # Reset streak counter
                self._consecutive_successes = 0

    def on_rate_limit(self, retry_after: Optional[int] = None):
        """
        Call this method when receiving a 429 Too Many Requests response.

        Updates the interval and pushes _next_allowed_time into the future
        so the next wait() call will respect the cooldown. Does NOT sleep
        here — sleeping is handled by wait() on the next iteration, which
        eliminates the old double-sleep problem.

        Also tracks the slowest interval that was rejected to help
        calculate the optimal rate (the sweet spot between accepted and rejected).

        Args:
            retry_after: Optional server-provided wait time in seconds
                        (from Retry-After HTTP header)

        Example:
            >>> if response.status_code == 429:
            ...     retry = response.headers.get("Retry-After")
            ...     limiter.on_rate_limit(int(retry) if retry else None)
        """
        with self._lock:
            # Reset success streak and recovery counter (we just failed)
            self._consecutive_successes = 0
            self._successes_since_rate_limit = 0
            self._total_rate_limits += 1

            # Track the slowest rejected interval (this rate was too fast!)
            # We want to know the boundary where rate limiting kicks in
            if self._slowest_rejected == 0 or self._current_interval > self._slowest_rejected:
                self._slowest_rejected = self._current_interval
                logger.info(f"[{self.name}] Rate limit boundary found at {self._slowest_rejected:.3f}s")

            # Recalculate optimal interval
            self._calculate_optimal()

            if retry_after:
                # Server told us exactly how long to wait
                cooldown = retry_after
                self._current_interval = min(retry_after, self.max_interval)
            else:
                # If we know the optimal, jump to it with a safety margin
                if self._optimal_interval:
                    # Use optimal + 10% safety margin
                    self._current_interval = min(self._optimal_interval * 1.1, self.max_interval)
                else:
                    # No optimal known - use exponential backoff
                    self._current_interval = min(
                        self._current_interval * self.backoff_factor,
                        self.max_interval
                    )
                cooldown = self._current_interval

            # Push _next_allowed_time into the future so the next wait()
            # call will enforce the cooldown. No sleeping here.
            now = time.time()
            self._next_allowed_time = max(self._next_allowed_time, now + cooldown)

            logger.warning(f"[{self.name}] Rate limit hit #{self._total_rate_limits}! "
                          f"Interval: {self._current_interval:.2f}s ({60/self._current_interval:.1f} req/min). "
                          f"Cooldown {cooldown:.1f}s before next request.")

    def on_error(self):
        """
        Call this method on non-rate-limit errors (5xx, network errors, etc).

        Applies a moderate backoff (1.5x) since errors might indicate
        server stress or temporary issues. Less aggressive than rate
        limit backoff since we want to retry reasonably soon.

        Example:
            >>> if response.status_code >= 500:
            ...     limiter.on_error()
        """
        with self._lock:
            # Reset success streak
            self._consecutive_successes = 0

            # Moderate backoff - 1.5x slower, not as aggressive as rate limit
            self._current_interval = min(
                self._current_interval * 1.5,  # 50% slower
                self.max_interval
            )
            logger.debug(f"[{self.name}] Error, slowing down: interval now {self._current_interval:.2f}s")

    def _calculate_optimal(self):
        """
        Calculate the optimal interval based on accepted/rejected boundaries.

        The optimal rate is the midpoint between:
        - fastest_accepted: The fastest interval that worked
        - slowest_rejected: The slowest interval that got rate limited

        This gives us a safe operating point with some margin.
        """
        if self._slowest_rejected > 0 and self._fastest_accepted > self._slowest_rejected:
            # We have both boundaries - optimal is midpoint with safety margin
            # Add 15% buffer above the midpoint for safety
            midpoint = (self._fastest_accepted + self._slowest_rejected) / 2
            self._optimal_interval = midpoint * 1.15
            logger.info(f"[{self.name}] Optimal rate calculated: {self._optimal_interval:.3f}s "
                       f"({60/self._optimal_interval:.1f} req/min) "
                       f"[accepted: {self._fastest_accepted:.3f}s, rejected: {self._slowest_rejected:.3f}s]")

    def reset(self, keep_optimal: bool = True):
        """
        Reset the rate limiter to its initial state.

        Useful when starting a new batch of requests or after a long
        pause where the API may have recovered.

        Args:
            keep_optimal: If True, preserves learned optimal rate and boundaries
                         for the next session, but resets counters so stats
                         (actual_rpm, etc.) are accurate for the new batch.
                         If False, resets everything including learned boundaries.

        Example:
            >>> limiter.reset()  # Back to optimal, keep learned rate
            >>> limiter.reset(keep_optimal=False)  # Full reset
        """
        with self._lock:
            # If we learned an optimal rate, start there instead of base
            if keep_optimal and self._optimal_interval:
                self._current_interval = self._optimal_interval
                logger.info(f"[{self.name}] Rate limiter reset to optimal {self._optimal_interval:.3f}s "
                           f"({60/self._optimal_interval:.1f} req/min)")
            else:
                self._current_interval = self.base_interval
                logger.info(f"[{self.name}] Rate limiter reset to base {self.base_interval}s interval")

            # Always reset timing and streak state
            self._consecutive_successes = 0
            self._successes_since_rate_limit = 0
            self._next_allowed_time = 0.0
            self._start_time = time.time()

            # Always reset counters so stats reflect the new batch
            self._total_requests = 0
            self._total_successes = 0
            self._total_rate_limits = 0

            if not keep_optimal:
                # Full reset - also forget learned boundaries
                self._fastest_accepted = self.base_interval
                self._slowest_rejected = 0.0
                self._optimal_interval = None

    def get_status_line(self) -> str:
        """
        Get a human-readable status line for display in UI.

        Returns:
            String like "45 req/min (optimal: 50 req/min, 2 rate limits)"
        """
        rpm = 60 / self._current_interval if self._current_interval > 0 else 0
        optimal_rpm = 60 / self._optimal_interval if self._optimal_interval else None

        if optimal_rpm:
            return (f"{rpm:.0f} req/min (optimal: {optimal_rpm:.0f} req/min, "
                   f"{self._total_rate_limits} rate limits)")
        else:
            return f"{rpm:.0f} req/min ({self._total_rate_limits} rate limits)"

