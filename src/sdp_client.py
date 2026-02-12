"""
================================================================================
ServiceDesk Plus Cloud API Client
================================================================================

This module provides a Python client for interacting with the ManageEngine
ServiceDesk Plus Cloud API. It handles:

1. Zoho OAuth2 Authentication (refresh token flow)
2. Automatic token refresh when tokens expire
3. CMDB (Configuration Management Database) operations
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
- GET /cmdb/ci_workstation - List CMDB workstations
- POST /cmdb/{ci_type} - Create a new CI
- DELETE /cmdb/{ci_type}/{id} - Delete a CI
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

    # Get all workstations
    workstations = client.get_all_cmdb_workstations()
    print(f"Found {len(workstations)} workstations")

    # Create a new CI (only works if dry_run=False)
    client = SDPClient(dry_run=False)
    client.create_ci("ci_windows_workstation", {"name": "NEW-PC-001"})
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
        ...     workstations = client.get_all_cmdb_workstations()
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
        >>> workstations = client.get_all_cmdb_workstations()
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
            endpoint: API path (e.g., "/cmdb/ci_workstation")
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

    def get_assets(self, row_count: int = 100, start_index: int = 1) -> Dict[str, Any]:
        """
        Get assets from ServiceDesk Plus.

        Assets are the general asset management items in SDP, separate from
        CMDB Configuration Items. This is typically used for IT asset tracking.

        Args:
            row_count: Number of results per page (max 100)
            start_index: Starting index for pagination (1-based)

        Returns:
            API response dictionary containing:
            - "assets": List of asset dictionaries
            - "list_info": Pagination info (has_more_rows, total_count, etc.)
        """
        logger.info(f"Fetching assets (start: {start_index}, count: {row_count})...")
        endpoint = f"/assets?list_info.row_count={row_count}&list_info.start_index={start_index}"
        data = self._make_request("GET", endpoint)
        assets = data.get("assets", [])
        logger.info(f"Retrieved {len(assets)} assets")
        return data

    def get_cmdb_workstations(
        self, row_count: int = 100, start_index: int = 1
    ) -> Dict[str, Any]:
        """
        Get CMDB workstations from ServiceDesk Plus (single page).

        CMDB workstations are Configuration Items of type "ci_workstation".
        This is the main CI type we sync ConnectWise devices to.

        Args:
            row_count: Number of results per page (max 100)
            start_index: Starting index for pagination (1-based)

        Returns:
            API response dictionary containing:
            - "ci_workstation": List of workstation CI dictionaries
            - "list_info": Pagination info (has_more_rows, total_count, etc.)

        Note:
            For fetching ALL workstations, use get_all_cmdb_workstations() instead.
        """
        logger.info(f"Fetching CMDB workstations (start: {start_index}, count: {row_count})...")

        # CMDB API uses input_data parameter for list_info (different from assets API)
        list_info = {"list_info": {"row_count": row_count, "start_index": start_index}}
        endpoint = f"/cmdb/ci_workstation?input_data={json.dumps(list_info)}"

        data = self._make_request("GET", endpoint)
        workstations = data.get("ci_workstation", [])
        logger.info(f"Retrieved {len(workstations)} workstations")
        return data

    def get_cmdb_workstation_by_id(self, workstation_id: str) -> Dict[str, Any]:
        """
        Get a specific CMDB workstation by its ID.

        Args:
            workstation_id: The unique CI ID (from list response)

        Returns:
            Complete workstation CI details dictionary
        """
        logger.debug(f"Fetching workstation: {workstation_id}")
        return self._make_request("GET", f"/cmdb/ci_workstation/{workstation_id}")

    def get_requests(self, row_count: int = 100, start_index: int = 1) -> Dict[str, Any]:
        """
        Get service requests from ServiceDesk Plus.

        Service requests are help desk tickets. This is READ-ONLY and
        used for reference/reporting purposes.

        Args:
            row_count: Number of results per page (max 100)
            start_index: Starting index for pagination (1-based)

        Returns:
            API response with requests and list_info
        """
        logger.info(f"Fetching requests (start: {start_index}, count: {row_count})...")
        endpoint = f"/requests?list_info.row_count={row_count}&list_info.start_index={start_index}"
        data = self._make_request("GET", endpoint)
        requests_list = data.get("requests", [])
        logger.info(f"Retrieved {len(requests_list)} requests")
        return data

    def get_all_cmdb_workstations(
        self,
        max_items: Optional[int] = None,
        progress_callback: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        Get ALL CMDB workstations with automatic pagination.

        This method handles pagination automatically, fetching all pages
        until no more results are available. Supports cancellation and
        progress callbacks for UI integration.

        Args:
            max_items: Optional limit on total items to fetch.
                      If None, fetches all available workstations.
            progress_callback: Optional callback function called after each page.
                              Signature: callback(fetched_count, total_count, workstations_page)
                              If total_count is unknown, it will be 0.

        Returns:
            List of all workstation CI dictionaries

        Example:
            >>> workstations = client.get_all_cmdb_workstations()
            >>> print(f"Total: {len(workstations)}")
            >>>
            >>> # With progress callback
            >>> def on_progress(fetched, total, page):
            ...     print(f"Fetched {fetched} of {total}")
            >>> workstations = client.get_all_cmdb_workstations(progress_callback=on_progress)
        """
        all_workstations = []
        start_index = 1
        page_size = 100  # Max allowed by API
        total_count = 0  # Will be updated from first response

        # Reset cancellation flag at start
        self.reset_cancel()

        # Pagination loop
        while True:
            # Check for cancellation
            if self._cancelled:
                logger.info(f"SDP fetch cancelled after {len(all_workstations)} workstations")
                break

            # Fetch one page
            data = self.get_cmdb_workstations(row_count=page_size, start_index=start_index)
            workstations = data.get("ci_workstation", [])
            all_workstations.extend(workstations)

            # Check pagination info
            list_info = data.get("list_info", {})
            has_more = list_info.get("has_more_rows", False)

            # Get total count from first response (if available)
            if total_count == 0:
                total_count = list_info.get("total_count", 0)

            # Call progress callback if provided
            if progress_callback:
                try:
                    progress_callback(len(all_workstations), total_count, workstations)
                except Exception as e:
                    logger.warning(f"Progress callback error: {e}")

            # Check if we've hit the max_items limit
            if max_items and len(all_workstations) >= max_items:
                all_workstations = all_workstations[:max_items]
                break

            # Check if there are more pages
            if not has_more or not workstations:
                break

            # Move to next page
            start_index += page_size

        logger.info(f"Total workstations retrieved: {len(all_workstations)}")
        return all_workstations

    # =========================================================================
    # WRITE OPERATIONS (Blocked in dry_run mode for safety)
    # =========================================================================

    @staticmethod
    def _parse_extra_key_fields(error_message: str) -> list:
        """
        Parse an SDP error response to find fields rejected as EXTRA_KEY_FOUND_IN_JSON.

        When a CI type doesn't support a particular attribute (e.g. ci_virtual_machine
        doesn't have txt_os), SDP returns a 400 with a JSON body listing the offending
        field names. This method extracts those field names so they can be stripped
        from the payload and the request retried.

        Args:
            error_message: The full error string from ServiceDeskPlusClientError

        Returns:
            List of rejected field names (e.g. ['ci_attributes_txt_os']),
            or empty list if the error is not an EXTRA_KEY issue.
        """
        extra_fields = []
        try:
            # Error format: "Request failed: 400 - {json}"
            # Find the JSON portion after the status code
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
            pass  # Not a parseable EXTRA_KEY error — let caller handle it

        return extra_fields

    def create_ci(self, ci_type: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a new CI (Configuration Item) in CMDB.

        This is the main method for syncing devices from ConnectWise to SDP.
        Creates a new CI of the specified type with the provided field values.

        SAFETY: This operation is BLOCKED if dry_run=True (default).

        Args:
            ci_type: The CI type to create. Valid types include:
                    - "ci_windows_workstation" - Windows laptops/desktops
                    - "ci_virtual_machine" - Virtual servers
                    - "ci_windows_server" - Physical Windows servers
                    - "ci_switch" - Network devices
            data: Dictionary of field values to set. Common fields:
                    - "name": CI name (required)
                    - "ci_attributes_serial_number": Serial number
                    - "ci_attributes_ip_address": IP address
                    - etc.

        Returns:
            Created CI data dictionary if successful
            {"dry_run": True, ...} if in dry_run mode
            None if creation failed

        Example:
            >>> client = ServiceDeskPlusClient(config, dry_run=False)
            >>> result = client.create_ci("ci_windows_workstation", {
            ...     "name": "LAPTOP-001",
            ...     "ci_attributes_serial_number": "ABC123"
            ... })
        """
        # SAFETY: Block in dry_run mode
        if self.dry_run:
            logger.info(f"[DRY RUN] Would create {ci_type}: {data.get('name', 'unknown')}")
            return {"dry_run": True, "would_create": data}

        # Build the request payload
        # SDP expects nested structure: {"ci_type": {"name": "...", "ci_attributes": {...}}}
        ci_data = {ci_type: {}}

        # Map fields to proper structure
        for key, value in data.items():
            # Skip empty values
            if value is None or value == "":
                continue

            if key == "name":
                # Name goes at top level
                ci_data[ci_type]["name"] = value
            elif key.startswith("ci_attributes_"):
                # Attributes go under ci_attributes object
                if "ci_attributes" not in ci_data[ci_type]:
                    ci_data[ci_type]["ci_attributes"] = {}
                # Keep full field name as SDP expects it
                ci_data[ci_type]["ci_attributes"][key] = value

        # Build endpoint - pass raw dict, _make_request handles JSON serialization
        endpoint = f"/cmdb/{ci_type}"
        device_name = data.get('name', 'unknown')

        # Retry loop: auto-strip fields rejected by SDP as EXTRA_KEY_FOUND_IN_JSON
        # Different CI types accept different attributes — this handles mismatches
        # dynamically without maintaining a manual exclusion list.
        max_field_retries = 5  # Safety cap (one retry per rejected field)
        for field_attempt in range(max_field_retries + 1):
            try:
                logger.debug(f"CREATE payload for {ci_type}: {json.dumps(ci_data, indent=2)}")
                result = self._make_request("POST", endpoint, data=ci_data)
                logger.info(f"Created {ci_type}: {device_name}")
                return result
            except ServiceDeskPlusClientError as e:
                error_str = str(e)
                extra_fields = self._parse_extra_key_fields(error_str)

                if extra_fields and field_attempt < max_field_retries:
                    # Remove rejected fields and retry
                    attrs = ci_data.get(ci_type, {}).get("ci_attributes", {})
                    for field in extra_fields:
                        if field in attrs:
                            del attrs[field]
                            logger.warning(
                                f"Field '{field}' not supported on {ci_type}, "
                                f"removed and retrying ({device_name})"
                            )
                    continue  # Retry without the rejected field(s)

                # Non-retryable error or max retries exhausted
                logger.error(f"Failed to create {ci_type} '{device_name}': {e}")
                return None

        logger.error(f"Failed to create {ci_type} '{device_name}': too many rejected fields")
        return None

    def update_ci(self, ci_type: str, ci_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Update an existing CI (Configuration Item) in CMDB.

        This method updates an existing CI with new field values from ConnectWise.
        Only non-empty fields are updated; existing values are preserved for
        fields not included in the update.

        SAFETY: This operation is BLOCKED if dry_run=True (default).

        Args:
            ci_type: The CI type to update. Valid types include:
                    - "ci_windows_workstation" - Windows laptops/desktops
                    - "ci_virtual_machine" - Virtual servers
                    - "ci_windows_server" - Physical Windows servers
                    - "ci_switch" - Network devices
            ci_id: The unique CI ID in SDP to update
            data: Dictionary of field values to update. Common fields:
                    - "name": CI name
                    - "ci_attributes_serial_number": Serial number
                    - "ci_attributes_ip_address": IP address
                    - etc.

        Returns:
            Updated CI data dictionary if successful
            {"dry_run": True, ...} if in dry_run mode
            None if update failed

        Example:
            >>> client = ServiceDeskPlusClient(config, dry_run=False)
            >>> result = client.update_ci("ci_windows_workstation", "123456", {
            ...     "ci_attributes_ip_address": "192.168.1.100"
            ... })
        """
        # SAFETY: Block in dry_run mode
        if self.dry_run:
            logger.info(f"[DRY RUN] Would update {ci_type}/{ci_id}: {data.get('name', 'unknown')}")
            return {"dry_run": True, "would_update": data, "ci_id": ci_id}

        # Build the request payload (same structure as create)
        # SDP expects nested structure: {"ci_type": {"name": "...", "ci_attributes": {...}}}
        ci_data = {ci_type: {}}

        # Map fields to proper structure
        for key, value in data.items():
            # Skip empty values
            if value is None or value == "":
                continue

            if key == "name":
                # Name goes at top level
                ci_data[ci_type]["name"] = value
            elif key.startswith("ci_attributes_"):
                # Attributes go under ci_attributes object
                if "ci_attributes" not in ci_data[ci_type]:
                    ci_data[ci_type]["ci_attributes"] = {}
                # Keep full field name as SDP expects it
                ci_data[ci_type]["ci_attributes"][key] = value

        # Build endpoint - pass raw dict, _make_request handles JSON serialization
        endpoint = f"/cmdb/{ci_type}/{ci_id}"
        device_name = data.get('name', 'unknown')

        # Retry loop: auto-strip fields rejected by SDP as EXTRA_KEY_FOUND_IN_JSON
        max_field_retries = 5
        for field_attempt in range(max_field_retries + 1):
            try:
                logger.debug(f"UPDATE payload for {ci_type}/{ci_id}: {json.dumps(ci_data, indent=2)}")
                result = self._make_request("PUT", endpoint, data=ci_data)
                logger.info(f"Updated {ci_type}/{ci_id}: {device_name}")
                return result
            except ServiceDeskPlusClientError as e:
                error_str = str(e)

                # Check for 404 — endpoint doesn't exist for this CI type
                if "404" in error_str and "Invalid URL" in error_str:
                    logger.error(
                        f"Cannot update {ci_type}/{ci_id} '{device_name}': "
                        f"SDP API does not support updating this CI type via REST"
                    )
                    return None

                extra_fields = self._parse_extra_key_fields(error_str)

                if extra_fields and field_attempt < max_field_retries:
                    attrs = ci_data.get(ci_type, {}).get("ci_attributes", {})
                    for field in extra_fields:
                        if field in attrs:
                            del attrs[field]
                            logger.warning(
                                f"Field '{field}' not supported on {ci_type}, "
                                f"removed and retrying ({device_name})"
                            )
                    continue

                logger.error(f"Failed to update {ci_type}/{ci_id} '{device_name}': {e}")
                return None

        logger.error(f"Failed to update {ci_type}/{ci_id} '{device_name}': too many rejected fields")
        return None

    def delete_ci(self, ci_type: str, ci_id: str) -> bool:
        """
        Delete a CI (Configuration Item) from CMDB.

        SAFETY: This operation is BLOCKED if dry_run=True (default).

        Args:
            ci_type: The CI type (e.g., "ci_windows_workstation")
            ci_id: The unique CI ID to delete

        Returns:
            True if deleted successfully
            True if in dry_run mode (simulated success)
            False if deletion failed

        Warning:
            This permanently deletes the CI from CMDB!
        """
        # SAFETY: Block in dry_run mode
        if self.dry_run:
            logger.info(f"[DRY RUN] Would delete {ci_type}/{ci_id}")
            return True  # Simulate success

        endpoint = f"/cmdb/{ci_type}/{ci_id}"

        try:
            self._make_request("DELETE", endpoint)
            logger.info(f"Deleted {ci_type}/{ci_id}")
            return True
        except ServiceDeskPlusClientError as e:
            logger.error(f"Failed to delete {ci_type}/{ci_id}: {e}")
            return False


# =============================================================================
# CONVENIENCE WRAPPER
# =============================================================================

class SDPClient(ServiceDeskPlusClient):
    """
    Simplified SDP client for sync operations.

    This is a convenience wrapper that automatically loads configuration
    from credentials.env file. Use this for quick scripts and automation.

    Example:
        >>> from src.sdp_client import SDPClient
        >>>
        >>> # Read-only mode (safe)
        >>> client = SDPClient(dry_run=True)
        >>> workstations = client.get_all_cmdb_workstations()
        >>>
        >>> # Write mode (creates/updates CIs)
        >>> client = SDPClient(dry_run=False)
        >>> client.create_ci("ci_windows_workstation", {"name": "NEW-PC"})
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

