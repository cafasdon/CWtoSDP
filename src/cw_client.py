"""
================================================================================
ConnectWise RMM API Client
================================================================================

This module provides a Python client for interacting with the ConnectWise RMM
(Remote Monitoring & Management) API. It handles:

1. OAuth2 Authentication (client credentials flow)
2. Automatic token refresh when tokens expire
3. Rate limiting with adaptive backoff
4. Retry logic for transient failures
5. Pagination for large result sets

ConnectWise API Overview:
-------------------------
- Base URL: https://openapi.service.euplatform.connectwise.com (EU)
- Auth: OAuth2 client_credentials grant
- Format: JSON
- Rate Limits: Varies by endpoint (this client handles automatically)

Main Endpoints Used:
-------------------
- GET /api/platform/v1/device/endpoints - List all device endpoints
- GET /api/platform/v1/device/endpoints/{id} - Get endpoint details
- GET /api/platform/v1/company/sites - List sites
- GET /api/platform/v1/company/companies - List companies

Usage Example:
--------------
    from src.config import load_config
    from src.cw_client import ConnectWiseClient

    config = load_config()
    client = ConnectWiseClient(config.connectwise)

    # Get all devices
    devices = client.get_devices()
    print(f"Found {len(devices)} devices")

    # Get details for a specific device
    details = client.get_endpoint_details(devices[0]["endpointId"])
"""

import time
import random
import threading
from typing import Any, Dict, List, Optional

import requests  # HTTP library for making API calls

from .config import ConnectWiseConfig  # Configuration dataclass
from .logger import get_logger          # Logging utilities
from .rate_limiter import AdaptiveRateLimiter  # Rate limiting

# Create a logger for this module
logger = get_logger("cwtosdp.cw_client")


# =============================================================================
# CUSTOM EXCEPTION
# =============================================================================

class ConnectWiseClientError(Exception):
    """
    Exception raised for ConnectWise API errors.

    This exception is raised when:
    - Authentication fails (invalid credentials)
    - API returns an error response
    - Network errors after all retries exhausted
    - Unexpected response format from API

    Example:
        >>> try:
        ...     devices = client.get_devices()
        ... except ConnectWiseClientError as e:
        ...     print(f"API Error: {e}")
    """
    pass


# =============================================================================
# MAIN CLIENT CLASS
# =============================================================================

class ConnectWiseClient:
    """
    Client for interacting with the ConnectWise RMM API.

    This client handles all aspects of API communication including:
    - OAuth2 authentication using client credentials
    - Automatic token refresh when expired
    - Adaptive rate limiting to avoid 429 errors
    - Retry logic with exponential backoff
    - Response parsing and error handling

    Attributes:
        config: ConnectWiseConfig with API credentials and URLs
        max_retries: Maximum retry attempts for failed requests
        retry_delay: Base delay between retries (increases with attempts)
        rate_limiter: AdaptiveRateLimiter instance for request throttling

    Example:
        >>> from src.config import load_config
        >>> config = load_config()
        >>> client = ConnectWiseClient(config.connectwise)
        >>> devices = client.get_devices()
    """

    def __init__(self, config: ConnectWiseConfig, max_retries: int = 0, retry_delay: float = 1.0):
        """
        Initialize the ConnectWise client.

        Args:
            config: ConnectWiseConfig object containing:
                    - client_id: OAuth2 client ID
                    - client_secret: OAuth2 client secret
                    - base_url: API base URL
            max_retries: Maximum number of retry attempts for failed requests.
                        0 = infinite retries with exponential backoff (default)
                        >0 = limit to that many attempts
            retry_delay: Base delay in seconds between retries.
                        Actual delay increases exponentially. Default: 1.0

        Note:
            Authentication happens lazily on first API call, not during init.
        """
        # Store configuration
        self.config = config
        self.max_retries = max_retries  # 0 = infinite
        self.retry_delay = retry_delay

        # Access token storage (populated on first request)
        self._access_token: Optional[str] = None

        # Cancellation flag - set to True to abort ongoing operations
        self._cancelled = False

        # Configure adaptive rate limiter for ConnectWise API
        # These settings are tuned based on observed CW API behavior
        self.rate_limiter = AdaptiveRateLimiter(
            name="ConnectWise",
            base_interval=1.0,     # Start at 1 request per second (conservative)
            min_interval=0.3,      # Can speed up to ~3 req/sec if going well
            max_interval=120.0,    # Max 2 min between requests if heavily throttled
            backoff_factor=2.0,    # Double interval when rate limited
            speedup_factor=0.85,   # Speed up by 15% after success streak
            success_streak_to_speedup=3  # Need 3 successes to speed up
        )
        
        # Thread lock for authentication
        self._lock = threading.RLock()

    def cancel(self):
        """Cancel any ongoing operations. Thread-safe."""
        self._cancelled = True
        logger.info("ConnectWise client: cancellation requested")

    def reset_cancel(self):
        """Reset cancellation flag for new operations."""
        self._cancelled = False

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancelled

    # =========================================================================
    # PRIVATE HELPER METHODS
    # =========================================================================

    def _get_headers(self) -> Dict[str, str]:
        """
        Build HTTP headers for authenticated API requests.

        If no access token exists, triggers authentication first.

        Returns:
            Dictionary with Authorization and Accept headers
        """
        # Lazy authentication - only authenticate when needed
        with self._lock:
            if not self._access_token:
                self.authenticate()

        return {
            "Authorization": f"Bearer {self._access_token}",  # OAuth2 Bearer token
            "Accept": "application/json"  # Request JSON response
        }

    # =========================================================================
    # AUTHENTICATION
    # =========================================================================

    def authenticate(self) -> str:
        """
        Authenticate with ConnectWise using OAuth2 client credentials flow.

        This method requests a new access token from the ConnectWise OAuth
        server using the client_id and client_secret from configuration.

        OAuth2 Client Credentials Flow:
        1. Send POST request to token URL with credentials
        2. Server validates credentials
        3. Server returns access_token (and optionally refresh_token)
        4. Use access_token in Authorization header for API calls

        Returns:
            The new access token string

        Raises:
            ConnectWiseClientError: If authentication fails due to:
                - Invalid credentials
                - Network error
                - Server error

        Note:
            Access tokens typically expire after 1 hour. The client
            automatically re-authenticates on 401 responses.
        """
        logger.info("Authenticating with ConnectWise...")

        # Build OAuth2 token request payload
        payload = {
            "grant_type": "client_credentials",  # OAuth2 grant type
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret
        }
        headers = {"Content-Type": "application/json"}

        try:
            # POST to token endpoint
            resp = requests.post(
                self.config.token_url,  # e.g., https://...connectwise.com/v1/token
                json=payload,
                headers=headers,
                timeout=30  # 30 second timeout for auth
            )

            if resp.status_code == 200:
                # Success - extract and store token
                self._access_token = resp.json()["access_token"]
                logger.info("Successfully authenticated with ConnectWise")
                return self._access_token
            else:
                # Authentication failed - raise with details
                raise ConnectWiseClientError(
                    f"Authentication failed: {resp.status_code} - {resp.text}"
                )
        except requests.RequestException as e:
            # Network or connection error
            raise ConnectWiseClientError(f"Authentication request failed: {e}")

    # =========================================================================
    # CORE REQUEST METHOD
    # =========================================================================

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Any:
        """
        Make an authenticated API request with retry logic and rate limiting.

        This is the core method that all API calls go through. It handles:
        1. Rate limiting (via AdaptiveRateLimiter)
        2. Adding authentication headers
        3. Retrying on transient failures with exponential backoff
        4. Re-authenticating on token expiry
        5. Backing off on rate limits
        6. Cancellation support

        Args:
            method: HTTP method ("GET", "POST", "PUT", "DELETE")
            endpoint: API path (e.g., "/api/platform/v1/device/endpoints")
            **kwargs: Additional arguments passed to requests.request()

        Returns:
            Parsed JSON response from the API

        Raises:
            ConnectWiseClientError: If request fails or is cancelled

        Example:
            >>> data = self._make_request("GET", "/api/platform/v1/device/endpoints")
        """
        # Build full URL from base + endpoint
        url = f"{self.config.base_url}{endpoint}"

        # Retry loop - infinite if max_retries=0, otherwise limited
        attempt = 0
        while True:
            attempt += 1

            # Check for cancellation
            if self._cancelled:
                raise ConnectWiseClientError("Request cancelled by user")

            # Check max retries (0 = infinite)
            if self.max_retries > 0 and attempt > self.max_retries:
                raise ConnectWiseClientError(f"Request failed after {self.max_retries} attempts")

            try:
                # Wait according to rate limiter (may sleep)
                self.rate_limiter.wait()

                # Check cancellation again after wait
                if self._cancelled:
                    raise ConnectWiseClientError("Request cancelled by user")

                # Make the HTTP request
                resp = requests.request(
                    method,
                    url,
                    headers=self._get_headers(),  # Adds auth header
                    timeout=60,  # 60 second timeout for data requests
                    **kwargs
                )

                # Handle response based on status code
                if resp.status_code == 200:
                    # Success - inform rate limiter and return data
                    self.rate_limiter.on_success()
                    return resp.json()

                elif resp.status_code == 401:
                    # Unauthorized - token probably expired
                    # Clear token and re-authenticate, then retry
                    # Does NOT count against max_retries (decrement attempt)
                    logger.warning("Token expired, re-authenticating...")
                    with self._lock:
                        # Double-check inside lock to ensure another thread didn't just refresh it
                        self._access_token = None
                        self.authenticate()
                    attempt -= 1  # Don't count auth refresh as a retry
                    continue  # Retry with new token

                elif resp.status_code == 429:
                    # Rate limited - back off and retry
                    retry_after = resp.headers.get("Retry-After")
                    wait_time = int(retry_after) if retry_after else None
                    self.rate_limiter.on_rate_limit(wait_time)
                    logger.info(f"Rate limited, backing off (attempt {attempt})...")
                    continue  # Retry after backoff

                else:
                    # Other error - inform rate limiter and retry with backoff
                    self.rate_limiter.on_error()
                    logger.warning(f"Request failed with {resp.status_code}, retrying...")
                    # Exponential backoff with ±20% jitter to prevent synchronized retries
                    wait_time = min(self.retry_delay * (2 ** (attempt - 1)), 60)
                    wait_time *= random.uniform(0.8, 1.2)
                    time.sleep(wait_time)
                    continue

            except requests.RequestException as e:
                # Network/connection error - back off and retry
                self.rate_limiter.on_error()
                logger.warning(f"Request attempt {attempt} failed: {e}")

                # Exponential backoff with ±20% jitter to prevent synchronized retries
                wait_time = min(self.retry_delay * (2 ** (attempt - 1)), 60)
                wait_time *= random.uniform(0.8, 1.2)
                logger.info(f"Waiting {wait_time:.1f}s before retry...")
                time.sleep(wait_time)

    # =========================================================================
    # PUBLIC API METHODS - These are the main methods users call
    # =========================================================================

    def get_devices(self) -> List[Dict[str, Any]]:
        """
        Get all device endpoints from ConnectWise.
        Handles pagination automatically to retrieve all devices.
        """
        logger.info("Fetching devices from ConnectWise (with pagination)...")
        
        all_devices = []
        page = 1
        page_size = 1000  # Maximize page size to reduce requests
        
        while True:
            # Check cancellation
            if self._cancelled:
                logger.info("ConnectWise fetch cancelled")
                break
                
            logger.debug(f"Fetching device page {page}...")
            
            # Make API call with pagination params
            params = {"page": page, "pageSize": page_size}
            data = self._make_request("GET", "/api/platform/v1/device/endpoints", params=params)
            
            if not isinstance(data, list):
                # Older API versions returned {"endpoints": [...]}
                # Newer versions typically return a list directly for this endpoint type
                # but we handle both just in case
                if isinstance(data, dict) and "endpoints" in data:
                    page_items = data["endpoints"]
                else:
                    logger.warning("Unexpected response format (not list), stopping fetch")
                    break
            else:
                page_items = data
                
            if not page_items:
                break
                
            all_devices.extend(page_items)
            logger.info(f"Page {page}: Retrieved {len(page_items)} devices")
            
            # If we got fewer items than page_size, we're done
            if len(page_items) < page_size:
                break
                
            page += 1
            
        logger.info(f"Total devices retrieved: {len(all_devices)}")
        return all_devices

    def get_sites(self) -> List[Dict[str, Any]]:
        """
        Get all sites from ConnectWise.
        Handles pagination automatically.
        """
        logger.info("Fetching sites from ConnectWise (with pagination)...")
        
        all_sites = []
        page = 1
        page_size = 1000
        
        while True:
            if self._cancelled:
                break
                
            params = {"page": page, "pageSize": page_size}
            data = self._make_request("GET", "/api/platform/v1/company/sites", params=params)
            
            # Sites endpoint usually returns list directly
            page_items = data if isinstance(data, list) else data.get("sites", [])
            
            if not page_items:
                break
                
            all_sites.extend(page_items)
            logger.info(f"Page {page}: Retrieved {len(page_items)} sites")
            
            if len(page_items) < page_size:
                break
                
            page += 1
            
        logger.info(f"Total sites retrieved: {len(all_sites)}")
        return all_sites

    def get_companies(self) -> List[Dict[str, Any]]:
        """
        Get all companies (clients) from ConnectWise.
        Handles pagination automatically.
        """
        logger.info("Fetching companies from ConnectWise (with pagination)...")
        
        all_companies = []
        page = 1
        page_size = 1000
        
        while True:
            if self._cancelled:
                break
                
            params = {"page": page, "pageSize": page_size}
            data = self._make_request("GET", "/api/platform/v1/company/companies", params=params)
            
            # Companies endpoint usually returns list directly
            page_items = data if isinstance(data, list) else data.get("companies", [])
            
            if not page_items:
                break
                
            all_companies.extend(page_items)
            logger.info(f"Page {page}: Retrieved {len(page_items)} companies")
            
            if len(page_items) < page_size:
                break
                
            page += 1
            
        logger.info(f"Total companies retrieved: {len(all_companies)}")
        return all_companies

    def get_endpoint_details(self, endpoint_id: str) -> Dict[str, Any]:
        """
        Get detailed information for a specific endpoint.

        This returns more detailed information than the list endpoint,
        including full hardware inventory, installed software, etc.

        Args:
            endpoint_id: The unique endpoint ID (from get_devices())

        Returns:
            Complete endpoint details dictionary

        Example:
            >>> devices = client.get_devices()
            >>> details = client.get_endpoint_details(devices[0]["endpointId"])
            >>> print(details["system"]["serialNumber"])
        """
        logger.debug(f"Fetching details for endpoint: {endpoint_id}")
        return self._make_request("GET", f"/api/platform/v1/device/endpoints/{endpoint_id}")

    def get_endpoint_system_state(self, endpoint_id: str) -> Dict[str, Any]:
        """
        Get system state information for a specific endpoint.

        Returns current system state including:
        - CPU usage
        - Memory usage
        - Disk usage
        - Running processes
        - Services status

        Args:
            endpoint_id: The unique endpoint ID

        Returns:
            System state information dictionary

        Note:
            This requires the endpoint to be online and responding.
            May return stale data if device is offline.
        """
        logger.debug(f"Fetching system state for endpoint: {endpoint_id}")
        return self._make_request(
            "GET",
            f"/api/platform/v1/device/endpoints/{endpoint_id}/system-state-info"
        )

