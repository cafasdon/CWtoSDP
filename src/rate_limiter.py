"""
Adaptive Rate Limiter with Exponential Backoff.

Automatically adjusts request rate based on API responses:
- Speeds up when requests succeed
- Slows down when hitting rate limits (429) or errors
"""

import time
from typing import Optional

from .logger import get_logger

logger = get_logger("cwtosdp.rate_limiter")


class AdaptiveRateLimiter:
    """
    Adaptive rate limiter with exponential backoff.
    
    Starts with a base interval and adjusts based on success/failure:
    - On success: gradually decrease interval (speed up)
    - On rate limit (429): exponentially increase interval (slow down)
    - On other errors: moderately increase interval
    """
    
    def __init__(
        self,
        name: str = "API",
        base_interval: float = 0.5,      # Starting interval (seconds)
        min_interval: float = 0.2,        # Fastest allowed (seconds)
        max_interval: float = 120.0,      # Slowest allowed (seconds)
        backoff_factor: float = 2.0,      # Multiply interval on rate limit
        speedup_factor: float = 0.9,      # Multiply interval on success
        success_streak_to_speedup: int = 5  # Consecutive successes before speeding up
    ):
        self.name = name
        self.base_interval = base_interval
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.backoff_factor = backoff_factor
        self.speedup_factor = speedup_factor
        self.success_streak_to_speedup = success_streak_to_speedup
        
        self._current_interval = base_interval
        self._last_request_time: float = 0.0
        self._consecutive_successes: int = 0
        self._total_requests: int = 0
        self._total_rate_limits: int = 0
    
    @property
    def current_interval(self) -> float:
        return self._current_interval
    
    @property
    def stats(self) -> dict:
        return {
            "total_requests": self._total_requests,
            "rate_limits_hit": self._total_rate_limits,
            "current_interval": round(self._current_interval, 2),
            "requests_per_minute": round(60 / self._current_interval, 1) if self._current_interval > 0 else 0
        }
    
    def wait(self):
        """Wait before making the next request."""
        now = time.time()
        elapsed = now - self._last_request_time
        
        if elapsed < self._current_interval:
            wait_time = self._current_interval - elapsed
            if wait_time > 1.0:
                logger.debug(f"[{self.name}] Rate limiting: waiting {wait_time:.1f}s")
            time.sleep(wait_time)
        
        self._last_request_time = time.time()
        self._total_requests += 1
    
    def on_success(self):
        """Call after a successful request."""
        self._consecutive_successes += 1
        
        # Speed up after consistent success streak
        if self._consecutive_successes >= self.success_streak_to_speedup:
            new_interval = self._current_interval * self.speedup_factor
            if new_interval >= self.min_interval:
                self._current_interval = new_interval
                logger.debug(f"[{self.name}] Speeding up: interval now {self._current_interval:.2f}s")
            self._consecutive_successes = 0
    
    def on_rate_limit(self, retry_after: Optional[int] = None):
        """Call when hitting a rate limit (429)."""
        self._consecutive_successes = 0
        self._total_rate_limits += 1
        
        if retry_after:
            # Use server-provided wait time
            wait_time = retry_after
            self._current_interval = min(retry_after, self.max_interval)
        else:
            # Exponential backoff
            self._current_interval = min(
                self._current_interval * self.backoff_factor,
                self.max_interval
            )
            wait_time = self._current_interval
        
        logger.warning(f"[{self.name}] Rate limit hit! Backing off to {self._current_interval:.1f}s interval. Waiting {wait_time:.0f}s...")
        time.sleep(wait_time)
    
    def on_error(self):
        """Call on other errors (not rate limit)."""
        self._consecutive_successes = 0
        # Moderate backoff on errors
        self._current_interval = min(
            self._current_interval * 1.5,
            self.max_interval
        )
        logger.debug(f"[{self.name}] Error, slowing down: interval now {self._current_interval:.2f}s")
    
    def reset(self):
        """Reset to base interval."""
        self._current_interval = self.base_interval
        self._consecutive_successes = 0
        logger.info(f"[{self.name}] Rate limiter reset to {self.base_interval}s interval")

