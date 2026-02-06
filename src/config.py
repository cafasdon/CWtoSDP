"""
Configuration Management Module for CWtoSDP Integration.

This module handles all configuration settings for the application, including:
- Loading credentials from environment variables or .env files
- Providing dataclass-based configuration objects for type safety
- Managing API endpoints for both ConnectWise and ServiceDesk Plus
- Configuring safety settings (dry run mode, batch limits, etc.)

The configuration uses a hierarchical structure:
- AppConfig (main config)
  ├── ConnectWiseConfig (CW API settings)
  └── ServiceDeskPlusConfig (SDP API settings)

Usage:
    from src.config import load_config
    config = load_config()  # Loads from credentials.env by default
    print(config.connectwise.client_id)
    print(config.servicedesk.api_base_url)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv  # Library to load .env files into environment variables


# =============================================================================
# CONNECTWISE CONFIGURATION
# =============================================================================

@dataclass
class ConnectWiseConfig:
    """
    Configuration dataclass for ConnectWise RMM API.

    ConnectWise uses OAuth2 client credentials flow for authentication.
    The base_url varies by data center (EU, US, AU).

    Attributes:
        client_id: OAuth2 client ID from ConnectWise Control admin panel
        client_secret: OAuth2 client secret (keep secure!)
        base_url: API base URL (varies by region/data center)
        token_endpoint: Path to the token endpoint for authentication
    """
    client_id: str          # Required: OAuth2 Client ID
    client_secret: str      # Required: OAuth2 Client Secret
    base_url: str = "https://openapi.service.euplatform.connectwise.com"  # EU data center default
    token_endpoint: str = "/v1/token"  # OAuth2 token endpoint path

    @property
    def token_url(self) -> str:
        """
        Construct the full token URL for OAuth2 authentication.

        Returns:
            Complete URL for requesting access tokens
            Example: "https://openapi.service.euplatform.connectwise.com/v1/token"
        """
        return f"{self.base_url}{self.token_endpoint}"


# =============================================================================
# SERVICEDESK PLUS CONFIGURATION
# =============================================================================

@dataclass
class ServiceDeskPlusConfig:
    """
    Configuration dataclass for ManageEngine ServiceDesk Plus API.

    SDP uses Zoho OAuth2 for authentication with refresh tokens.
    The accounts_url and api_base_url vary by data center (EU, US, IN, AU).

    Attributes:
        client_id: Zoho OAuth2 client ID from API console
        client_secret: Zoho OAuth2 client secret
        refresh_token: Long-lived refresh token (doesn't expire until revoked)
        accounts_url: Zoho accounts URL for OAuth (varies by region)
        api_base_url: SDP API base URL (varies by region)
        scopes: Comma-separated list of API scopes/permissions
    """
    client_id: str          # Required: Zoho OAuth2 Client ID
    client_secret: str      # Required: Zoho OAuth2 Client Secret
    refresh_token: str      # Required: Zoho OAuth2 Refresh Token (long-lived)
    accounts_url: str = "https://accounts.zoho.eu"  # EU Zoho accounts URL
    api_base_url: str = "https://sdpondemand.manageengine.eu/api/v3"  # EU SDP API
    # OAuth scopes required for this integration:
    # - assets.ALL: Full access to Assets module
    # - cmdb.ALL: Full access to CMDB (Configuration Management Database)
    # - requests.READ: Read-only access to service requests
    scopes: str = "SDPOnDemand.assets.ALL,SDPOnDemand.cmdb.ALL,SDPOnDemand.requests.READ"

    @property
    def token_url(self) -> str:
        """
        Construct the Zoho OAuth2 token URL.

        Returns:
            Complete URL for refreshing access tokens
            Example: "https://accounts.zoho.eu/oauth/v2/token"
        """
        return f"{self.accounts_url}/oauth/v2/token"


# =============================================================================
# MAIN APPLICATION CONFIGURATION
# =============================================================================

@dataclass
class AppConfig:
    """
    Main application configuration container.

    This is the top-level configuration object that contains all settings
    needed by the application. It combines both API configurations with
    application-specific settings like safety controls.

    Attributes:
        connectwise: ConnectWise API configuration
        servicedesk: ServiceDesk Plus API configuration
        output_dir: Directory for CSV exports and other output files
        dry_run: If True, no write operations are performed (SAFE mode)
        batch_size: Maximum items to process in a single batch
        require_confirmation: If True, prompts user before write operations
        max_retries: Maximum retry attempts for failed API calls
        retry_delay_seconds: Base delay between retry attempts
    """
    # Sub-configurations for each external system
    connectwise: ConnectWiseConfig      # CW API settings
    servicedesk: ServiceDeskPlusConfig  # SDP API settings

    # Output settings - where to save exported files
    output_dir: Path = field(default_factory=lambda: Path("./output"))

    # =========================================================================
    # SAFETY SETTINGS - These protect against accidental data modification
    # =========================================================================
    dry_run: bool = True           # DEFAULT: ON - prevents all write operations
    batch_size: int = 50           # Max items per batch (prevents overwhelming API)
    require_confirmation: bool = True  # Prompt before any destructive operations

    # Retry settings for handling transient API failures
    max_retries: int = 3                # Number of retry attempts
    retry_delay_seconds: float = 1.0    # Initial delay (may use exponential backoff)

    def __post_init__(self):
        """
        Post-initialization hook called after dataclass __init__.

        Ensures the output directory exists, creating it if necessary.
        This prevents FileNotFoundError when writing output files.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)


# =============================================================================
# CONFIGURATION LOADING FUNCTIONS
# =============================================================================

def load_config(env_file: Optional[str] = None) -> AppConfig:
    """
    Load complete application configuration from environment variables.

    This is the main configuration loading function. It reads credentials
    from a .env file (defaults to 'credentials.env'), validates that all
    required values are present, and returns a fully configured AppConfig.

    The function follows this process:
    1. Load environment variables from .env file
    2. Validate ConnectWise credentials exist
    3. Validate ServiceDesk Plus credentials exist
    4. Build configuration objects for each system
    5. Parse optional settings (dry_run, batch_size, etc.)
    6. Return complete AppConfig

    Args:
        env_file: Optional path to .env file. If not provided, defaults to
                  'credentials.env' in the current working directory.

    Returns:
        AppConfig: Fully configured application configuration object

    Raises:
        ValueError: If any required environment variables are missing.
                   The error message specifies which variables are needed.

    Example:
        >>> config = load_config()
        >>> print(config.connectwise.client_id)
        >>> print(config.dry_run)  # True by default
    """
    # Load environment file - this reads key=value pairs and sets them
    # as environment variables that os.getenv() can access
    env_path = env_file or "credentials.env"
    load_dotenv(env_path)

    # =========================================================================
    # VALIDATE CONNECTWISE CREDENTIALS
    # =========================================================================
    # Support both CLIENT_ID and CW_CLIENT_ID naming conventions
    cw_client_id = os.getenv("CLIENT_ID") or os.getenv("CW_CLIENT_ID")
    cw_client_secret = os.getenv("CLIENT_SECRET") or os.getenv("CW_CLIENT_SECRET")

    # Fail fast if credentials are missing - better to error early than
    # fail later during an API call
    if not cw_client_id or not cw_client_secret:
        raise ValueError(
            "Missing ConnectWise credentials. "
            "Set CLIENT_ID and CLIENT_SECRET in environment."
        )

    # =========================================================================
    # VALIDATE SERVICEDESK PLUS CREDENTIALS
    # =========================================================================
    sdp_client_id = os.getenv("ZOHO_CLIENT_ID")
    sdp_client_secret = os.getenv("ZOHO_CLIENT_SECRET")
    sdp_refresh_token = os.getenv("ZOHO_REFRESH_TOKEN")

    # all() returns True only if all values are truthy (not None/empty)
    if not all([sdp_client_id, sdp_client_secret, sdp_refresh_token]):
        raise ValueError(
            "Missing ServiceDesk Plus credentials. "
            "Set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, and ZOHO_REFRESH_TOKEN in environment."
        )

    # =========================================================================
    # BUILD CONFIGURATION OBJECTS
    # =========================================================================

    # Create ConnectWise configuration with optional URL override
    cw_config = ConnectWiseConfig(
        client_id=cw_client_id,
        client_secret=cw_client_secret,
        # Allow overriding base URL for different data centers
        base_url=os.getenv("CW_BASE_URL", "https://openapi.service.euplatform.connectwise.com"),
    )

    # Create ServiceDesk Plus configuration with optional URL overrides
    sdp_config = ServiceDeskPlusConfig(
        client_id=sdp_client_id,
        client_secret=sdp_client_secret,
        refresh_token=sdp_refresh_token,
        # These URLs vary by data center (EU, US, IN, AU)
        accounts_url=os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.eu"),
        api_base_url=os.getenv("SDP_API_BASE_URL", "https://sdpondemand.manageengine.eu/api/v3"),
        scopes=os.getenv("SCOPES", "SDPOnDemand.assets.ALL,SDPOnDemand.cmdb.ALL,SDPOnDemand.requests.READ"),
    )

    # =========================================================================
    # PARSE OPTIONAL SETTINGS
    # =========================================================================

    # Parse boolean from string - accepts "true", "1", or "yes" (case-insensitive)
    dry_run = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
    batch_size = int(os.getenv("BATCH_SIZE", "50"))
    require_confirmation = os.getenv("REQUIRE_CONFIRMATION", "true").lower() in ("true", "1", "yes")

    # Build and return the complete configuration
    return AppConfig(
        connectwise=cw_config,
        servicedesk=sdp_config,
        output_dir=Path(os.getenv("OUTPUT_DIR", "./output")),
        dry_run=dry_run,
        batch_size=batch_size,
        require_confirmation=require_confirmation,
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        retry_delay_seconds=float(os.getenv("RETRY_DELAY_SECONDS", "1.0")),
    )


def load_sdp_config() -> ServiceDeskPlusConfig:
    """
    Load only the ServiceDesk Plus configuration.

    This is a convenience function for when you only need to interact
    with ServiceDesk Plus and don't need the full AppConfig. Useful for
    the SDPClient and other SDP-specific operations.

    Returns:
        ServiceDeskPlusConfig: Configuration for SDP API access

    Raises:
        ValueError: If required ZOHO_* environment variables are missing

    Example:
        >>> sdp_config = load_sdp_config()
        >>> client = ServiceDeskPlusClient(sdp_config)
    """
    # Load environment variables from credentials.env file
    load_dotenv("credentials.env")

    # Get required credentials
    sdp_client_id = os.getenv("ZOHO_CLIENT_ID")
    sdp_client_secret = os.getenv("ZOHO_CLIENT_SECRET")
    sdp_refresh_token = os.getenv("ZOHO_REFRESH_TOKEN")

    # Validate all required values are present
    if not all([sdp_client_id, sdp_client_secret, sdp_refresh_token]):
        raise ValueError(
            "Missing ServiceDesk Plus credentials. "
            "Set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, and ZOHO_REFRESH_TOKEN."
        )

    # Build and return SDP-specific configuration
    return ServiceDeskPlusConfig(
        client_id=sdp_client_id,
        client_secret=sdp_client_secret,
        refresh_token=sdp_refresh_token,
        accounts_url=os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.eu"),
        api_base_url=os.getenv("SDP_API_BASE_URL", "https://sdpondemand.manageengine.eu/api/v3"),
        scopes=os.getenv("SCOPES", "SDPOnDemand.assets.ALL,SDPOnDemand.cmdb.ALL,SDPOnDemand.requests.READ"),
    )

