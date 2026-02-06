"""
================================================================================
Adaptive Rate Limiter with Exponential Backoff
================================================================================

This module provides intelligent rate limiting for API requests that:
1. Automatically adjusts request rate based on API responses
2. Speeds up when requests succeed consistently (up to min_interval)
3. Slows down exponentially when hitting rate limits (429 errors)
4. Moderately backs off on other errors to prevent cascading failures

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

Algorithm:
----------
1. WAIT: Before each request, wait for current_interval seconds
2. ON SUCCESS: After N consecutive successes, multiply interval by speedup_factor
3. ON 429 (Rate Limit): Multiply interval by backoff_factor (exponential backoff)
4. ON OTHER ERROR: Multiply interval by 1.5 (moderate backoff)

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
        success_streak_to_speedup: int = 5  # Need 5 successes to speed up
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
        """
        # Configuration
        self.name = name
        self.base_interval = base_interval
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.backoff_factor = backoff_factor
        self.speedup_factor = speedup_factor
        self.success_streak_to_speedup = success_streak_to_speedup

        # Thread safety
        self._lock = threading.RLock()

        # Internal state (prefixed with _ to indicate private)
        self._current_interval = base_interval      # Current delay between requests
        self._last_request_time: float = 0.0        # Timestamp of last request
        self._consecutive_successes: int = 0        # Success streak counter
        self._total_requests: int = 0               # Total requests made
        self._total_rate_limits: int = 0            # Total 429s received
        self._total_successes: int = 0              # Total successful requests

        # Optimal rate discovery - track the boundaries
        self._fastest_accepted: float = base_interval   # Fastest interval that worked
        self._slowest_rejected: float = 0.0             # Slowest interval that got rate limited
        self._optimal_interval: Optional[float] = None  # Calculated optimal rate

        # Performance tracking
        self._start_time: float = time.time()
        self._recent_intervals: list = []               # Last N intervals for averaging
    
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

        This method should be called BEFORE every API request. It:
        1. Calculates how long since the last request
        2. Sleeps if needed to maintain the rate limit
        3. Records the timestamp for the next calculation
        4. Increments the request counter

        Example:
            >>> limiter.wait()  # May sleep up to current_interval
            >>> response = api.get("/endpoint")
            >>> limiter.on_success()
        """
        with self._lock:
            # Get current time
            now = time.time()

            # Calculate how long since last request
            elapsed = now - self._last_request_time

            # If not enough time has passed, wait
            if elapsed < self._current_interval:
                wait_time = self._current_interval - elapsed
                # Only log if waiting more than 1 second (avoid log spam)
                if wait_time > 1.0:
                    logger.debug(f"[{self.name}] Rate limiting: waiting {wait_time:.1f}s")
                time.sleep(wait_time)

            # Record this request time for next calculation
            self._last_request_time = time.time()
            self._total_requests += 1

    def on_success(self):
        """
        Call this method AFTER a successful API request (200 OK).

        Tracks consecutive successes and speeds up the request rate
        after a streak of successful calls. This allows the limiter
        to find the optimal speed automatically.

        Also tracks the fastest interval that was accepted to help
        calculate the optimal rate.

        Example:
            >>> if response.status_code == 200:
            ...     limiter.on_success()
        """
        with self._lock:
            # Track success
            self._consecutive_successes += 1
            self._total_successes += 1

            # Track fastest accepted interval (this rate worked!)
            if self._current_interval < self._fastest_accepted:
                self._fastest_accepted = self._current_interval
                logger.debug(f"[{self.name}] New fastest accepted: {self._fastest_accepted:.3f}s")

            # Recalculate optimal interval if we have both boundaries
            self._calculate_optimal()

            # Check if we've had enough successes to speed up
            if self._consecutive_successes >= self.success_streak_to_speedup:
                # If we know the optimal, move toward it; otherwise use speedup_factor
                if self._optimal_interval and self._current_interval > self._optimal_interval:
                    # Move halfway toward optimal (binary search approach)
                    new_interval = (self._current_interval + self._optimal_interval) / 2
                else:
                    # Standard speedup
                    new_interval = self._current_interval * self.speedup_factor

                # Only apply if above minimum (don't go faster than allowed)
                if new_interval >= self.min_interval:
                    self._current_interval = new_interval
                    logger.debug(f"[{self.name}] Speeding up: interval now {self._current_interval:.3f}s "
                               f"({60/self._current_interval:.1f} req/min)")

                # Reset streak counter
                self._consecutive_successes = 0

    def on_rate_limit(self, retry_after: Optional[int] = None):
        """
        Call this method when receiving a 429 Too Many Requests response.

        Implements exponential backoff: each rate limit doubles the interval.
        If the server provides a Retry-After header, uses that value instead.

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
            # Reset success streak (we just failed)
            self._consecutive_successes = 0
            self._total_rate_limits += 1

            # Track the slowest rejected interval (this rate was too fast!)
            # We want to know the boundary where rate limiting kicks in
            if self._slowest_rejected == 0 or self._current_interval > self._slowest_rejected:
                self._slowest_rejected = self._current_interval
                logger.info(f"[{self.name}] Rate limit boundary found at {self._slowest_rejected:.3f}s")

            # Recalculate optimal interval
            self._calculate_optimal()

            if retry_after:
                # Server told us exactly how long to wait - use that
                wait_time = retry_after
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
                wait_time = self._current_interval

            # Log warning and wait
            logger.warning(f"[{self.name}] Rate limit hit #{self._total_rate_limits}! "
                          f"Interval: {self._current_interval:.2f}s ({60/self._current_interval:.1f} req/min). "
                          f"Waiting {wait_time:.1f}s...")
            time.sleep(wait_time)

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
            keep_optimal: If True, preserves learned optimal rate for next session.
                         If False, resets everything including learned boundaries.

        Example:
            >>> limiter.reset()  # Back to base_interval, keep learned rate
            >>> limiter.reset(keep_optimal=False)  # Full reset
        """
        # If we learned an optimal rate, start there instead of base
        if keep_optimal and self._optimal_interval:
            self._current_interval = self._optimal_interval
            logger.info(f"[{self.name}] Rate limiter reset to optimal {self._optimal_interval:.3f}s "
                       f"({60/self._optimal_interval:.1f} req/min)")
        else:
            self._current_interval = self.base_interval
            logger.info(f"[{self.name}] Rate limiter reset to base {self.base_interval}s interval")

        self._consecutive_successes = 0
        self._start_time = time.time()

        if not keep_optimal:
            # Full reset - forget learned boundaries
            self._fastest_accepted = self.base_interval
            self._slowest_rejected = 0.0
            self._optimal_interval = None
            self._total_requests = 0
            self._total_successes = 0
            self._total_rate_limits = 0

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

