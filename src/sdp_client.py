"""
ServiceDesk Plus Cloud API Client.

Handles Zoho OAuth2 authentication and API calls to ServiceDesk Plus.
Currently implements READ-ONLY operations for safety.
"""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from .config import ServiceDeskPlusConfig
from .logger import get_logger

logger = get_logger("cwtosdp.sdp_client")


class ServiceDeskPlusClientError(Exception):
    """Exception raised for ServiceDesk Plus API errors."""
    pass


class ServiceDeskPlusClient:
    """
    Client for interacting with ServiceDesk Plus Cloud API.

    Uses Zoho OAuth2 for authentication. Currently implements
    READ-ONLY operations for safety in production environments.
    """

    def __init__(
        self,
        config: ServiceDeskPlusConfig,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        dry_run: bool = True
    ):
        """
        Initialize ServiceDesk Plus client.

        Args:
            config: ServiceDesk Plus configuration object.
            max_retries: Maximum number of retry attempts for failed requests.
            retry_delay: Delay in seconds between retries.
            dry_run: If True, write operations are disabled (default: True).
        """
        self.config = config
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.dry_run = dry_run
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for authenticated API requests."""
        if not self._access_token or self._is_token_expired():
            self.refresh_access_token()
        return {
            "Authorization": f"Zoho-oauthtoken {self._access_token}",
            "Accept": "application/vnd.manageengine.sdp.v3+json"
        }

    def _is_token_expired(self) -> bool:
        """Check if the access token is expired or about to expire."""
        if not self._token_expiry:
            return True
        # Refresh 5 minutes before expiry
        return datetime.now() >= self._token_expiry - timedelta(minutes=5)

    def refresh_access_token(self) -> str:
        """
        Refresh the access token using the refresh token.

        Returns:
            New access token string.

        Raises:
            ServiceDeskPlusClientError: If token refresh fails.
        """
        logger.info("Refreshing ServiceDesk Plus access token...")

        payload = {
            "refresh_token": self.config.refresh_token,
            "grant_type": "refresh_token",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret
        }

        try:
            resp = requests.post(
                self.config.token_url,
                data=payload,
                timeout=30
            )

            if resp.status_code == 200:
                data = resp.json()
                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", 3600)
                self._token_expiry = datetime.now() + timedelta(seconds=expires_in)
                logger.info("Successfully refreshed access token")
                return self._access_token
            else:
                raise ServiceDeskPlusClientError(
                    f"Token refresh failed: {resp.status_code} - {resp.text}"
                )
        except requests.RequestException as e:
            raise ServiceDeskPlusClientError(f"Token refresh request failed: {e}")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        **kwargs
    ) -> Any:
        """
        Make an authenticated API request with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            endpoint: API endpoint path (without base URL).
            data: Optional request body data.
            **kwargs: Additional arguments for requests.

        Returns:
            Parsed JSON response.

        Raises:
            ServiceDeskPlusClientError: If request fails after retries.
        """
        # Block write operations in dry_run mode
        if method.upper() in ("POST", "PUT", "DELETE") and self.dry_run:
            logger.warning(f"DRY_RUN: Blocked {method} request to {endpoint}")
            return {"dry_run": True, "message": "Write operation blocked in dry_run mode"}

        url = f"{self.config.api_base_url}{endpoint}"

        for attempt in range(1, self.max_retries + 1):
            try:
                request_kwargs = {"headers": self._get_headers(), "timeout": 60, **kwargs}

                if data:
                    request_kwargs["data"] = {"input_data": str(data)}

                resp = requests.request(method, url, **request_kwargs)

                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 401:
                    logger.warning("Token expired, refreshing...")
                    self._access_token = None
                    self.refresh_access_token()
                    continue
                else:
                    raise ServiceDeskPlusClientError(
                        f"Request failed: {resp.status_code} - {resp.text}"
                    )
            except requests.RequestException as e:
                logger.warning(f"Request attempt {attempt} failed: {e}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * attempt)
                else:
                    raise ServiceDeskPlusClientError(
                        f"Request failed after {self.max_retries} attempts: {e}"
                    )

        raise ServiceDeskPlusClientError("Request failed: max retries exceeded")

    # =========================================================================
    # READ OPERATIONS (Safe for production)
    # =========================================================================

    def get_assets(self, row_count: int = 100, start_index: int = 1) -> Dict[str, Any]:
        """
        Get assets from ServiceDesk Plus.

        Args:
            row_count: Number of results per page (max 100).
            start_index: Starting index for pagination.

        Returns:
            API response with assets and list_info.
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
        Get CMDB workstations from ServiceDesk Plus.

        Args:
            row_count: Number of results per page (max 100).
            start_index: Starting index for pagination.

        Returns:
            API response with workstations and list_info.
        """
        logger.info(f"Fetching CMDB workstations (start: {start_index}, count: {row_count})...")
        endpoint = f"/cmdb/ci_workstation?list_info.row_count={row_count}&list_info.start_index={start_index}"
        data = self._make_request("GET", endpoint)
        workstations = data.get("ci_workstation", [])
        logger.info(f"Retrieved {len(workstations)} workstations")
        return data

    def get_cmdb_workstation_by_id(self, workstation_id: str) -> Dict[str, Any]:
        """
        Get a specific CMDB workstation by ID.

        Args:
            workstation_id: The workstation CI ID.

        Returns:
            Workstation details.
        """
        logger.debug(f"Fetching workstation: {workstation_id}")
        return self._make_request("GET", f"/cmdb/ci_workstation/{workstation_id}")

    def get_requests(self, row_count: int = 100, start_index: int = 1) -> Dict[str, Any]:
        """
        Get service requests from ServiceDesk Plus (READ-ONLY scope).

        Args:
            row_count: Number of results per page (max 100).
            start_index: Starting index for pagination.

        Returns:
            API response with requests and list_info.
        """
        logger.info(f"Fetching requests (start: {start_index}, count: {row_count})...")
        endpoint = f"/requests?list_info.row_count={row_count}&list_info.start_index={start_index}"
        data = self._make_request("GET", endpoint)
        requests_list = data.get("requests", [])
        logger.info(f"Retrieved {len(requests_list)} requests")
        return data

    def get_all_cmdb_workstations(self, max_items: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get all CMDB workstations with automatic pagination.

        Args:
            max_items: Optional limit on total items to fetch.

        Returns:
            List of all workstation dictionaries.
        """
        all_workstations = []
        start_index = 1
        page_size = 100

        while True:
            data = self.get_cmdb_workstations(row_count=page_size, start_index=start_index)
            workstations = data.get("ci_workstation", [])
            all_workstations.extend(workstations)

            list_info = data.get("list_info", {})
            has_more = list_info.get("has_more_rows", False)

            if max_items and len(all_workstations) >= max_items:
                all_workstations = all_workstations[:max_items]
                break

            if not has_more or not workstations:
                break

            start_index += page_size

        logger.info(f"Total workstations retrieved: {len(all_workstations)}")
        return all_workstations

