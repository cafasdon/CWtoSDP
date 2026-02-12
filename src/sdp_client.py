"""
================================================================================
ServiceDesk Plus Cloud API Client
================================================================================

This module provides a Python client for interacting with the ManageEngine
ServiceDesk Plus Cloud API. It handles:

1. Zoho OAuth2 Authentication (refresh token flow)
2. Automatic token refresh when tokens expire
3. Asset management operations
4. Retry logic for transient failures
5. Dry-run mode for safe testing

ServiceDesk Plus API Overview:
------------------------------
- Base URL: https://sdpondemand.manageengine.eu/api/v3 (EU)
- Auth: Zoho OAuth2 with refresh tokens
- Format: JSON with custom header (application/vnd.manageengine.sdp.v3+json)
- Rate Limits: Varies by endpoint

Main Endpoints Used:
-------------------
- GET /assets - List all assets
- POST /{asset_type} - Create a new asset
- DELETE /assets/{id} - Delete an asset
- GET /assets - List assets

Zoho OAuth2 Flow:
-----------------
Unlike ConnectWise, SDP uses Zoho's OAuth2 with refresh tokens:
1. Initial setup (manual): Get authorization code via browser
2. Exchange code for access_token + refresh_token (one-time)
3. Use refresh_token to get new access_tokens (this client handles)
4. Access tokens expire in 1 hour, refresh tokens don't expire

Usage Example:
--------------
    from src.sdp_client import SDPClient

    # Create client (loads config from credentials.env)
    client = SDPClient(dry_run=True)  # Safe mode

    # Get all assets
    assets = client.get_all_assets()
    print(f"Found {len(assets)} assets")

    # Create a new asset (only works if dry_run=False)
    client = SDPClient(dry_run=False)
    client.create_asset("asset_workstations", {"name": "NEW-PC-001"})
"""

import json
import time
import random
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests  # HTTP library for API calls

from .config import ServiceDeskPlusConfig  # Configuration dataclass
from .logger import get_logger              # Logging utilities
from .rate_limiter import AdaptiveRateLimiter  # Rate limiting for API calls

# Create a logger for this module
logger = get_logger("cwtosdp.sdp_client")


# =============================================================================
# CUSTOM EXCEPTION
# =============================================================================

class ServiceDeskPlusClientError(Exception):
    """
    Exception raised for ServiceDesk Plus API errors.

    This exception is raised when:
    - Token refresh fails (invalid credentials)
    - API returns an error response
    - Network errors after all retries exhausted
    - Write operation attempted in dry_run mode

    Example:
        >>> try:
        ...     assets = client.get_all_assets()
        ... except ServiceDeskPlusClientError as e:
        ...     print(f"API Error: {e}")
    """
    pass


# =============================================================================
# MAIN CLIENT CLASS
# =============================================================================

class ServiceDeskPlusClient:
    """
    Client for interacting with ServiceDesk Plus Cloud API.

    This client handles all aspects of API communication including:
    - Zoho OAuth2 authentication using refresh tokens
    - Automatic token refresh when expired (proactive refresh 5 min before)
    - Retry logic for transient failures
    - Dry-run mode to prevent accidental writes

    IMPORTANT SAFETY FEATURE:
    By default, dry_run=True which blocks all write operations.
    Set dry_run=False explicitly to enable creating/updating/deleting CIs.

    Attributes:
        config: ServiceDeskPlusConfig with API credentials and URLs
        max_retries: Maximum retry attempts for failed requests
        retry_delay: Base delay between retries
        dry_run: If True, blocks all POST/PUT/DELETE requests (SAFE MODE)

    Example:
        >>> from src.config import load_config
        >>> config = load_config()
        >>> client = ServiceDeskPlusClient(config.servicedesk, dry_run=True)
        >>> assets = client.get_all_assets()
    """

    def __init__(
        self,
        config: ServiceDeskPlusConfig,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        dry_run: bool = True  # DEFAULT: SAFE MODE - no writes allowed
    ):
        """
        Initialize the ServiceDesk Plus client.

        Args:
            config: ServiceDeskPlusConfig object containing:
                    - client_id: Zoho OAuth2 client ID
                    - client_secret: Zoho OAuth2 client secret
                    - refresh_token: Zoho OAuth2 refresh token
                    - accounts_url: Zoho accounts URL for OAuth
                    - api_base_url: SDP API base URL
            max_retries: Maximum number of retry attempts. Default: 3
            retry_delay: Base delay in seconds between retries. Default: 1.0
            dry_run: If True, block all write operations. Default: True
                    This is a SAFETY FEATURE to prevent accidental changes.

        Warning:
            Setting dry_run=False enables write operations to production!
        """
        # Store configuration
        self.config = config
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.dry_run = dry_run  # SAFETY: Default True blocks writes

        # Token storage (populated on first request)
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None  # Track expiry for proactive refresh

        # Cancellation flag for long-running operations
        self._cancelled = False

        # Configure adaptive rate limiter for SDP API
        # SDP has different rate limits than CW - generally more lenient
        self.rate_limiter = AdaptiveRateLimiter(
            name="ServiceDeskPlus",
            base_interval=0.5,     # Start at 2 requests per second
            min_interval=0.2,      # Can speed up to ~5 req/sec if going well
            max_interval=60.0,     # Max 1 min between requests if throttled
            backoff_factor=2.0,    # Double interval when rate limited
            speedup_factor=0.9,    # Speed up by 10% after success streak
            success_streak_to_speedup=5  # Need 5 successes to speed up
        )
        
        # Thread lock for token management
        self._lock = threading.RLock()

    # =========================================================================
    # CANCELLATION SUPPORT
    # =========================================================================

    def cancel(self):
        """
        Cancel any ongoing long-running operations.

        Call this from another thread to stop pagination loops.
        """
        self._cancelled = True
        logger.info("SDP client cancellation requested")

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancelled

    def reset_cancel(self):
        """Reset the cancellation flag for a new operation."""
        self._cancelled = False

    # =========================================================================
    # PRIVATE HELPER METHODS
    # =========================================================================

    def _get_headers(self) -> Dict[str, str]:
        """
        Build HTTP headers for authenticated API requests.

        Automatically refreshes the access token if expired or not present.
        Uses Zoho-specific OAuth header format.

        Returns:
            Dictionary with Authorization and Accept headers

        Note:
            SDP uses "Zoho-oauthtoken" prefix instead of "Bearer"
        """
        # Check if we need to get/refresh token
        with self._lock:
            if not self._access_token or self._is_token_expired():
                self.refresh_access_token()

        return {
            # SDP uses Zoho-specific OAuth header format
            "Authorization": f"Zoho-oauthtoken {self._access_token}",
            # Request SDP v3 JSON format
            "Accept": "application/vnd.manageengine.sdp.v3+json"
        }

    def _is_token_expired(self) -> bool:
        """
        Check if the access token is expired or about to expire.

        Proactively refreshes 5 minutes before actual expiry to avoid
        request failures during long operations.

        Returns:
            True if token should be refreshed, False otherwise
        """
        # No expiry tracked = need to refresh
        if not self._token_expiry:
            return True

        # Refresh 5 minutes before actual expiry (buffer)
        return datetime.now() >= self._token_expiry - timedelta(minutes=5)

    # =========================================================================
    # AUTHENTICATION
    # =========================================================================

    def refresh_access_token(self) -> str:
        """
        Refresh the access token using the stored refresh token.

        Zoho OAuth2 Refresh Token Flow:
        1. Send POST request to Zoho token URL with refresh_token
        2. Zoho validates refresh_token (never expires unless revoked)
        3. Zoho returns new access_token (expires in ~1 hour)
        4. We store access_token and track its expiry

        Returns:
            The new access token string

        Raises:
            ServiceDeskPlusClientError: If token refresh fails due to:
                - Invalid/revoked refresh token
                - Network error
                - Zoho server error

        Note:
            Unlike ConnectWise client_credentials flow, this uses refresh_token
            grant type which requires an initial manual authorization step.
        """
        logger.info("Refreshing ServiceDesk Plus access token...")

        # Build OAuth2 token refresh request
        payload = {
            "refresh_token": self.config.refresh_token,  # Long-lived refresh token
            "grant_type": "refresh_token",                # OAuth2 grant type
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret
        }

        try:
            # POST to Zoho token endpoint (e.g., accounts.zoho.eu/oauth/v2/token)
            resp = requests.post(
                self.config.token_url,
                data=payload,  # Note: form-encoded, not JSON
                timeout=30
            )

            if resp.status_code == 200:
                # Success - extract token and expiry
                data = resp.json()
                self._access_token = data["access_token"]

                # Track expiry time (default 3600 seconds = 1 hour)
                expires_in = data.get("expires_in", 3600)
                self._token_expiry = datetime.now() + timedelta(seconds=expires_in)

                logger.info("Successfully refreshed access token")
                return self._access_token
            else:
                # Token refresh failed - likely invalid/revoked refresh token
                raise ServiceDeskPlusClientError(
                    f"Token refresh failed: {resp.status_code} - {resp.text}"
                )
        except requests.RequestException as e:
            # Network or connection error
            raise ServiceDeskPlusClientError(f"Token refresh request failed: {e}")

    # =========================================================================
    # CORE REQUEST METHOD
    # =========================================================================

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        **kwargs
    ) -> Any:
        """
        Make an authenticated API request with retry logic.

        This is the core method that all API calls go through. It handles:
        1. DRY RUN protection (blocks write operations when enabled)
        2. Adding authentication headers
        3. Retrying on transient failures
        4. Re-authenticating on token expiry

        Args:
            method: HTTP method ("GET", "POST", "PUT", "DELETE")
            endpoint: API path (e.g., "/assets")
            data: Optional dictionary for request body
            **kwargs: Additional arguments passed to requests.request()

        Returns:
            Parsed JSON response from the API

        Raises:
            ServiceDeskPlusClientError: If request fails after all retries

        SAFETY: POST/PUT/DELETE are blocked if dry_run=True
        """
        # =====================================================================
        # SAFETY CHECK: Block write operations in dry_run mode
        # =====================================================================
        if method.upper() in ("POST", "PUT", "DELETE") and self.dry_run:
            logger.warning(f"DRY_RUN: Blocked {method} request to {endpoint}")
            # Return a dummy response indicating dry run
            return {"dry_run": True, "message": "Write operation blocked in dry_run mode"}

        # Build full URL from base + endpoint
        url = f"{self.config.api_base_url}{endpoint}"

        # Retry loop - mirrors CW client pattern:
        # - while True with explicit max_retries check
        # - 401 (token refresh) and 429 (rate limit) do NOT count against attempts
        # - 5xx errors retry with exponential backoff
        # - 0 = infinite retries (useful for long pagination runs)
        attempt = 0
        while True:
            attempt += 1

            # Check for cancellation
            if self._cancelled:
                raise ServiceDeskPlusClientError("Operation cancelled by user")

            # Check max retries (0 = infinite)
            if self.max_retries > 0 and attempt > self.max_retries:
                raise ServiceDeskPlusClientError(
                    f"Request failed after {self.max_retries} attempts"
                )

            try:
                # Wait for rate limiter before making request
                self.rate_limiter.wait()

                # Check cancellation again after wait
                if self._cancelled:
                    raise ServiceDeskPlusClientError("Operation cancelled by user")

                # Build request kwargs with auth headers
                request_kwargs = {"headers": self._get_headers(), "timeout": 60, **kwargs}

                # SDP API uses input_data form field for POST/PUT data
                # The data parameter should be a raw dict; we JSON-serialize it here.
                # This is the SINGLE place where input_data wrapping happens.
                if data:
                    request_kwargs["data"] = {"input_data": json.dumps(data)}

                # Make the HTTP request
                resp = requests.request(method, url, **request_kwargs)

                # Handle response based on status code
                if 200 <= resp.status_code < 300:
                    # Success (200 OK, 201 Created, etc.) - inform rate limiter
                    self.rate_limiter.on_success()
                    return resp.json()

                elif resp.status_code == 401:
                    # Unauthorized - token probably expired
                    # Clear token and refresh, then retry
                    # Does NOT count against max_retries (decrement attempt)
                    logger.warning("Token expired, refreshing...")
                    with self._lock:
                        self._access_token = None
                        self.refresh_access_token()
                    attempt -= 1  # Don't count auth refresh as a retry
                    continue  # Retry with new token

                elif resp.status_code == 429:
                    # Rate limited - back off significantly
                    # Does NOT count against max_retries (decrement attempt)
                    retry_after = resp.headers.get("Retry-After")
                    wait_time = int(retry_after) if retry_after else None
                    self.rate_limiter.on_rate_limit(wait_time)
                    logger.info(f"Rate limited, backing off (attempt {attempt})...")
                    attempt -= 1  # Don't count rate limit as a retry
                    continue  # Retry after backoff

                elif resp.status_code >= 500:
                    # Server error (500, 502, 503, 504) - retry with backoff
                    self.rate_limiter.on_error()
                    logger.warning(
                        f"Server error {resp.status_code}, retrying..."
                    )
                    # Exponential backoff with ±20% jitter to prevent synchronized retries
                    wait_time = min(self.retry_delay * (2 ** (attempt - 1)), 60)
                    wait_time *= random.uniform(0.8, 1.2)
                    time.sleep(wait_time)
                    continue

                else:
                    # Client error (4xx except 401/429) - not retryable
                    self.rate_limiter.on_error()
                    raise ServiceDeskPlusClientError(
                        f"Request failed: {resp.status_code} - {resp.text}"
                    )

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
    # READ OPERATIONS (Safe for production - no data modification)
    # =========================================================================

    def get_assets_page(self, row_count: int = 100, start_index: int = 1) -> Dict[str, Any]:
        """
        Get one page of assets from ServiceDesk Plus.

        Args:
            row_count: Number of results per page (max 100)
            start_index: Starting index for pagination (1-based)

        Returns:
            API response dictionary containing:
            - "assets": List of asset dictionaries
            - "list_info": Pagination info (has_more_rows, total_count, etc.)
        """
        logger.info(f"Fetching assets (start: {start_index}, count: {row_count})...")
        # Assets API expects pagination via input_data query param containing JSON
        list_info = {
            "list_info": {
                "row_count": row_count,
                "start_index": start_index
            }
        }
        endpoint = "/assets"
        data = self._make_request(
            "GET", endpoint,
            params={"input_data": json.dumps(list_info)}
        )
        assets = data.get("assets", [])
        logger.info(f"Retrieved {len(assets)} assets")
        return data

    def get_asset_by_id(self, asset_id: str) -> Dict[str, Any]:
        """
        Get a single asset by its ID.

        Args:
            asset_id: The SDP asset ID

        Returns:
            Asset data dictionary
        """
        logger.info(f"Fetching asset by ID: {asset_id}")
        return self._make_request("GET", f"/assets/{asset_id}")

    def get_all_assets(
        self,
        max_items: int = None,
        progress_callback=None
    ) -> List[Dict[str, Any]]:
        """
        Fetch ALL assets with automatic pagination.

        Args:
            max_items: Optional maximum number of assets to fetch.
            progress_callback: Optional function called after each page.
                              Signature: callback(fetched_count, total_count, assets_page)

        Returns:
            List of all asset dictionaries
        """
        all_assets = []
        start_index = 1
        page_size = 100
        total_count = 0

        self.reset_cancel()

        while True:
            if self._cancelled:
                logger.info(f"SDP fetch cancelled after {len(all_assets)} assets")
                break

            data = self.get_assets_page(row_count=page_size, start_index=start_index)
            assets = data.get("assets", [])
            all_assets.extend(assets)

            list_info = data.get("list_info", {})
            has_more = list_info.get("has_more_rows", False)

            if total_count == 0:
                total_count = list_info.get("total_count", 0)

            if progress_callback:
                try:
                    progress_callback(len(all_assets), total_count, assets)
                except Exception as e:
                    logger.warning(f"Progress callback error: {e}")

            if max_items and len(all_assets) >= max_items:
                all_assets = all_assets[:max_items]
                break

            if not has_more or not assets:
                break

            start_index += page_size

        logger.info(f"Total assets retrieved: {len(all_assets)}")
        return all_assets

    # =========================================================================
    # ASSET WRITE OPERATIONS (CREATE / UPDATE / DELETE)
    # =========================================================================

    @staticmethod
    def _parse_extra_key_fields(error_message: str) -> list:
        """
        Parse an SDP error response to find fields rejected as EXTRA_KEY_FOUND_IN_JSON.

        Args:
            error_message: The full error string from ServiceDeskPlusClientError

        Returns:
            List of rejected field names, or empty list if not an EXTRA_KEY issue.
        """
        extra_fields = []
        try:
            json_start = error_message.find('{')
            if json_start == -1:
                return []

            error_json = json.loads(error_message[json_start:])
            messages = error_json.get("response_status", {}).get("messages", [])

            for msg in messages:
                if msg.get("message") == "EXTRA_KEY_FOUND_IN_JSON":
                    field = msg.get("field")
                    if field:
                        extra_fields.append(field)

        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return extra_fields

    def create_asset(self, asset_type_endpoint: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a new Asset in ServiceDesk Plus.

        SAFETY: This operation is BLOCKED if dry_run=True (default).

        Args:
            asset_type_endpoint: The product type API endpoint, e.g.:
                    - "asset_virtual_machines"
                    - "asset_workstations"
                    - "asset_servers"
            data: Dictionary of flat field values. Common fields:
                    - "name": Asset name (required)
                    - "serial_number": Serial number
                    - "ip_address": IP address
                    - "mac_address": MAC address
                    - "os": Operating system
                    - "manufacturer": Manufacturer

        Returns:
            Created asset data dictionary if successful
            {"dry_run": True, ...} if in dry_run mode
            None if creation failed
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would create {asset_type_endpoint}: {data.get('name', 'unknown')}")
            return {"dry_run": True, "would_create": data}

        # Build flat payload — Assets use flat structure, not nested ci_attributes
        asset_data = {}
        for key, value in data.items():
            if value is None or value == "":
                continue
            asset_data[key] = value

        # Wrap in the singular form key (e.g. asset_virtual_machine for asset_virtual_machines)
        singular_key = asset_type_endpoint.rstrip('s')
        payload = {singular_key: asset_data}

        endpoint = f"/{asset_type_endpoint}"
        device_name = data.get('name', 'unknown')

        # Retry loop: auto-strip fields rejected by SDP as EXTRA_KEY_FOUND_IN_JSON
        max_field_retries = 5
        for field_attempt in range(max_field_retries + 1):
            try:
                logger.debug(f"CREATE payload for {asset_type_endpoint}: {json.dumps(payload, indent=2)}")
                result = self._make_request("POST", endpoint, data=payload)
                logger.info(f"Created {asset_type_endpoint}: {device_name}")
                return result
            except ServiceDeskPlusClientError as e:
                error_str = str(e)
                extra_fields = self._parse_extra_key_fields(error_str)

                if extra_fields and field_attempt < max_field_retries:
                    for field in extra_fields:
                        if field in asset_data:
                            del asset_data[field]
                            logger.warning(
                                f"Field '{field}' not supported on {asset_type_endpoint}, "
                                f"removed and retrying ({device_name})"
                            )
                    continue

                logger.error(f"Failed to create {asset_type_endpoint} '{device_name}': {e}")
                return None

        logger.error(f"Failed to create {asset_type_endpoint} '{device_name}': too many rejected fields")
        return None

    def update_asset(self, asset_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Update an existing Asset in ServiceDesk Plus.

        Uses the generic /assets/{id} endpoint which works for all asset types.

        SAFETY: This operation is BLOCKED if dry_run=True (default).

        Args:
            asset_id: The SDP asset ID to update
            data: Dictionary of flat field values to update

        Returns:
            Updated asset data dictionary if successful
            {"dry_run": True, ...} if in dry_run mode
            None if update failed
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would update asset/{asset_id}: {data.get('name', 'unknown')}")
            return {"dry_run": True, "would_update": data, "asset_id": asset_id}

        # Build flat payload
        asset_data = {}
        for key, value in data.items():
            if value is None or value == "":
                continue
            asset_data[key] = value

        payload = {"asset": asset_data}
        endpoint = f"/assets/{asset_id}"
        device_name = data.get('name', 'unknown')

        # Retry loop for EXTRA_KEY_FOUND_IN_JSON
        max_field_retries = 5
        for field_attempt in range(max_field_retries + 1):
            try:
                logger.debug(f"UPDATE payload for asset/{asset_id}: {json.dumps(payload, indent=2)}")
                result = self._make_request("PUT", endpoint, data=payload)
                logger.info(f"Updated asset/{asset_id}: {device_name}")
                return result
            except ServiceDeskPlusClientError as e:
                error_str = str(e)

                if "404" in error_str:
                    logger.error(
                        f"Cannot update asset/{asset_id} '{device_name}': "
                        f"Asset not found in SDP"
                    )
                    return None

                extra_fields = self._parse_extra_key_fields(error_str)

                if extra_fields and field_attempt < max_field_retries:
                    for field in extra_fields:
                        if field in asset_data:
                            del asset_data[field]
                            logger.warning(
                                f"Field '{field}' not supported on assets, "
                                f"removed and retrying ({device_name})"
                            )
                    continue

                logger.error(f"Failed to update asset/{asset_id} '{device_name}': {e}")
                return None

        logger.error(f"Failed to update asset/{asset_id} '{device_name}': too many rejected fields")
        return None

    def delete_asset(self, asset_id: str) -> bool:
        """
        Delete an asset from ServiceDesk Plus.

        SAFETY: This operation is BLOCKED if dry_run=True (default).

        Args:
            asset_id: The SDP asset ID to delete

        Returns:
            True if deleted successfully, False if failed
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would delete asset/{asset_id}")
            return True

        try:
            self._make_request("DELETE", f"/assets/{asset_id}")
            logger.info(f"Deleted asset/{asset_id}")
            return True
        except ServiceDeskPlusClientError as e:
            logger.error(f"Failed to delete asset/{asset_id}: {e}")
            return False


# =============================================================================
# CONVENIENCE WRAPPER
# =============================================================================

class SDPClient(ServiceDeskPlusClient):
    """
    Simplified SDP client for sync operations.

    This is a convenience wrapper that automatically loads configuration
    from credentials.env file.

    Example:
        >>> from src.sdp_client import SDPClient
        >>>
        >>> # Read-only mode (safe)
        >>> client = SDPClient(dry_run=True)
        >>> assets = client.get_all_assets()
        >>>
        >>> # Write mode (creates/updates assets)
        >>> client = SDPClient(dry_run=False)
        >>> client.create_asset("asset_virtual_machines", {"name": "NEW-VM-001"})
    """

    def __init__(self, dry_run: bool = False):
        """
        Initialize SDPClient with auto-loaded configuration.

        Args:
            dry_run: If True, block write operations. Default: False
                    (Note: This differs from parent class default of True)
        """
        from .config import load_sdp_config
        config = load_sdp_config()
        super().__init__(config, dry_run=dry_run)

