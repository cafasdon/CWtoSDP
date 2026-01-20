"""
Configuration management for CWtoSDP integration.

Loads settings from environment variables and provides centralized configuration.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv


@dataclass
class ConnectWiseConfig:
    """ConnectWise API configuration."""
    client_id: str
    client_secret: str
    base_url: str = "https://openapi.service.euplatform.connectwise.com"
    token_endpoint: str = "/v1/token"
    
    @property
    def token_url(self) -> str:
        return f"{self.base_url}{self.token_endpoint}"


@dataclass
class ServiceDeskPlusConfig:
    """ServiceDesk Plus API configuration."""
    client_id: str
    client_secret: str
    refresh_token: str
    accounts_url: str = "https://accounts.zoho.eu"
    api_base_url: str = "https://sdpondemand.manageengine.eu/api/v3"
    scopes: str = "SDPOnDemand.assets.ALL,SDPOnDemand.cmdb.ALL,SDPOnDemand.requests.READ"
    
    @property
    def token_url(self) -> str:
        return f"{self.accounts_url}/oauth/v2/token"


@dataclass
class AppConfig:
    """Main application configuration."""
    # Sub-configurations
    connectwise: ConnectWiseConfig
    servicedesk: ServiceDeskPlusConfig
    
    # Output settings
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    
    # Safety settings
    dry_run: bool = True  # DEFAULT: ON - no write operations
    batch_size: int = 50  # Max items to process per batch
    require_confirmation: bool = True  # Prompt before writes
    
    # Retry settings
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    
    def __post_init__(self):
        """Ensure output directory exists."""
        self.output_dir.mkdir(parents=True, exist_ok=True)


def load_config(env_file: Optional[str] = None) -> AppConfig:
    """
    Load configuration from environment variables.
    
    Args:
        env_file: Optional path to .env file. Defaults to 'credentials.env'.
    
    Returns:
        AppConfig instance with all settings loaded.
    
    Raises:
        ValueError: If required environment variables are missing.
    """
    # Load environment file
    env_path = env_file or "credentials.env"
    load_dotenv(env_path)
    
    # Validate required ConnectWise credentials
    cw_client_id = os.getenv("CLIENT_ID") or os.getenv("CW_CLIENT_ID")
    cw_client_secret = os.getenv("CLIENT_SECRET") or os.getenv("CW_CLIENT_SECRET")
    
    if not cw_client_id or not cw_client_secret:
        raise ValueError(
            "Missing ConnectWise credentials. "
            "Set CLIENT_ID and CLIENT_SECRET in environment."
        )
    
    # Validate required ServiceDesk Plus credentials
    sdp_client_id = os.getenv("ZOHO_CLIENT_ID")
    sdp_client_secret = os.getenv("ZOHO_CLIENT_SECRET")
    sdp_refresh_token = os.getenv("ZOHO_REFRESH_TOKEN")
    
    if not all([sdp_client_id, sdp_client_secret, sdp_refresh_token]):
        raise ValueError(
            "Missing ServiceDesk Plus credentials. "
            "Set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, and ZOHO_REFRESH_TOKEN in environment."
        )
    
    # Build configuration objects
    cw_config = ConnectWiseConfig(
        client_id=cw_client_id,
        client_secret=cw_client_secret,
        base_url=os.getenv("CW_BASE_URL", "https://openapi.service.euplatform.connectwise.com"),
    )
    
    sdp_config = ServiceDeskPlusConfig(
        client_id=sdp_client_id,
        client_secret=sdp_client_secret,
        refresh_token=sdp_refresh_token,
        accounts_url=os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.eu"),
        api_base_url=os.getenv("SDP_API_BASE_URL", "https://sdpondemand.manageengine.eu/api/v3"),
        scopes=os.getenv("SCOPES", "SDPOnDemand.assets.ALL,SDPOnDemand.cmdb.ALL,SDPOnDemand.requests.READ"),
    )
    
    # Parse boolean/numeric settings from environment
    dry_run = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
    batch_size = int(os.getenv("BATCH_SIZE", "50"))
    require_confirmation = os.getenv("REQUIRE_CONFIRMATION", "true").lower() in ("true", "1", "yes")
    
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

