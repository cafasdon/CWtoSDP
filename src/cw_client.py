"""
ConnectWise API Client.

Handles authentication and API calls to ConnectWise platform.
"""

import time
from typing import Any, Dict, List, Optional

import requests

from .config import ConnectWiseConfig
from .logger import get_logger

logger = get_logger("cwtosdp.cw_client")


class ConnectWiseClientError(Exception):
    """Exception raised for ConnectWise API errors."""
    pass


class ConnectWiseClient:
    """
    Client for interacting with ConnectWise API.

    Handles OAuth2 authentication and provides methods for
    retrieving devices, sites, and companies.
    """

    def __init__(self, config: ConnectWiseConfig, max_retries: int = 3, retry_delay: float = 1.0):
        """
        Initialize ConnectWise client.

        Args:
            config: ConnectWise configuration object.
            max_retries: Maximum number of retry attempts for failed requests.
            retry_delay: Delay in seconds between retries.
        """
        self.config = config
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._access_token: Optional[str] = None

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for authenticated API requests."""
        if not self._access_token:
            self.authenticate()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json"
        }

    def authenticate(self) -> str:
        """
        Authenticate with ConnectWise and obtain access token.

        Returns:
            Access token string.

        Raises:
            ConnectWiseClientError: If authentication fails.
        """
        logger.info("Authenticating with ConnectWise...")

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret
        }
        headers = {"Content-Type": "application/json"}

        try:
            resp = requests.post(
                self.config.token_url,
                json=payload,
                headers=headers,
                timeout=30
            )

            if resp.status_code == 200:
                self._access_token = resp.json()["access_token"]
                logger.info("Successfully authenticated with ConnectWise")
                return self._access_token
            else:
                raise ConnectWiseClientError(
                    f"Authentication failed: {resp.status_code} - {resp.text}"
                )
        except requests.RequestException as e:
            raise ConnectWiseClientError(f"Authentication request failed: {e}")

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Any:
        """
        Make an authenticated API request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.).
            endpoint: API endpoint path.
            **kwargs: Additional arguments for requests.

        Returns:
            Parsed JSON response.

        Raises:
            ConnectWiseClientError: If request fails after retries.
        """
        url = f"{self.config.base_url}{endpoint}"

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.request(
                    method,
                    url,
                    headers=self._get_headers(),
                    timeout=60,
                    **kwargs
                )

                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 401:
                    # Token expired, re-authenticate
                    logger.warning("Token expired, re-authenticating...")
                    self._access_token = None
                    self.authenticate()
                    continue
                else:
                    raise ConnectWiseClientError(
                        f"Request failed: {resp.status_code} - {resp.text}"
                    )
            except requests.RequestException as e:
                logger.warning(f"Request attempt {attempt} failed: {e}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * attempt)  # Exponential backoff
                else:
                    raise ConnectWiseClientError(f"Request failed after {self.max_retries} attempts: {e}")

        raise ConnectWiseClientError("Request failed: max retries exceeded")

    def get_devices(self) -> List[Dict[str, Any]]:
        """
        Get all device endpoints.

        Returns:
            List of device dictionaries.
        """
        logger.info("Fetching devices from ConnectWise...")
        data = self._make_request("GET", "/api/platform/v1/device/endpoints")

        if isinstance(data, dict) and "endpoints" in data:
            devices = data["endpoints"]
            logger.info(f"Retrieved {len(devices)} devices")
            return devices

        raise ConnectWiseClientError("Unexpected response format: 'endpoints' key missing")

    def get_sites(self) -> List[Dict[str, Any]]:
        """Get all sites."""
        logger.info("Fetching sites from ConnectWise...")
        data = self._make_request("GET", "/api/platform/v1/company/sites")
        sites = data if isinstance(data, list) else data.get("sites", [])
        logger.info(f"Retrieved {len(sites)} sites")
        return sites

    def get_companies(self) -> List[Dict[str, Any]]:
        """Get all companies."""
        logger.info("Fetching companies from ConnectWise...")
        data = self._make_request("GET", "/api/platform/v1/company/companies")
        companies = data if isinstance(data, list) else data.get("companies", [])
        logger.info(f"Retrieved {len(companies)} companies")
        return companies

    def get_endpoint_details(self, endpoint_id: str) -> Dict[str, Any]:
        """
        Get detailed information for a specific endpoint.

        Args:
            endpoint_id: The endpoint ID to fetch details for.

        Returns:
            Endpoint details dictionary.
        """
        logger.debug(f"Fetching details for endpoint: {endpoint_id}")
        return self._make_request("GET", f"/api/platform/v1/device/endpoints/{endpoint_id}")

    def get_endpoint_system_state(self, endpoint_id: str) -> Dict[str, Any]:
        """
        Get system state information for a specific endpoint.

        Args:
            endpoint_id: The endpoint ID to fetch state for.

        Returns:
            System state information dictionary.
        """
        logger.debug(f"Fetching system state for endpoint: {endpoint_id}")
        return self._make_request(
            "GET",
            f"/api/platform/v1/device/endpoints/{endpoint_id}/system-state-info"
        )

