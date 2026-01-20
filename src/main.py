"""
================================================================================
CWtoSDP - ConnectWise to ServiceDesk Plus Integration
================================================================================

Main entry point for the CWtoSDP integration tool. This module provides:

1. Command-line interface for all operations
2. Data fetching from ConnectWise and ServiceDesk Plus
3. CSV export functionality
4. GUI launcher for various interfaces

Command-Line Usage:
-------------------
    # Launch the Sync Manager GUI (recommended)
    python -m src.main --sync

    # Fetch data from ConnectWise
    python -m src.main --fetch-cw

    # Fetch data from ServiceDesk Plus
    python -m src.main --fetch-sdp

    # Fetch detailed data for comparison
    python -m src.main --compare

    # Export data to CSV
    python -m src.main --fetch-cw --export

    # Launch field mapping GUI
    python -m src.main --gui

    # Launch asset matcher GUI
    python -m src.main --match

Available Flags:
----------------
    --sync          Launch Sync Manager GUI (main interface)
    --fetch-cw      Fetch ConnectWise devices, sites, companies
    --fetch-sdp     Fetch ServiceDesk Plus workstations
    --compare       Fetch detailed data for field comparison
    --export        Export fetched data to CSV files
    --gui           Launch field mapping GUI
    --match         Launch asset matcher GUI
    --dry-run       Enable dry-run mode (default: True)
    --debug         Enable debug logging
    --env-file      Path to credentials file (default: credentials.env)

Data Flow:
----------
1. Credentials loaded from credentials.env
2. API clients authenticate with OAuth2
3. Data fetched and stored in SQLite database
4. GUI displays data for review and sync operations

Safety Features:
----------------
- DRY_RUN mode enabled by default (no write operations)
- All operations logged for audit trail
- Resumable fetch for large datasets
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

# Import internal modules
from .config import load_config, AppConfig
from .logger import setup_logger, get_logger
from .cw_client import ConnectWiseClient
from .sdp_client import ServiceDeskPlusClient
from .db import Database
from .db_compare import CompareDatabase


# =============================================================================
# DATA EXPORT FUNCTIONS
# =============================================================================

def export_to_csv(data: list, filename: str, output_dir: Path) -> Path:
    """
    Export data to CSV file using pandas.

    Flattens nested JSON structures and exports to CSV format
    for easy viewing in Excel or other tools.

    Args:
        data: List of dictionaries to export
        filename: Output filename (e.g., "cw_devices.csv")
        output_dir: Directory to save file

    Returns:
        Path to saved file

    Example:
        >>> export_to_csv(devices, "devices.csv", Path("output"))
        Path('output/devices.csv')
    """
    logger = get_logger("cwtosdp.main")
    # Use pandas to flatten nested JSON and export
    df = pd.json_normalize(data)
    filepath = output_dir / filename
    df.to_csv(filepath, index=False)
    logger.info(f"Exported {len(data)} records to {filepath}")
    return filepath


# =============================================================================
# DATA FETCHING FUNCTIONS
# =============================================================================

def fetch_connectwise_data(config: AppConfig) -> dict:
    """
    Fetch all data from ConnectWise RMM API.

    Fetches devices, sites, and companies from the ConnectWise API
    using OAuth2 authentication.

    Args:
        config: Application configuration with CW credentials

    Returns:
        Dictionary with:
        - devices: List of endpoint devices
        - sites: List of sites/locations
        - companies: List of companies/organizations

    Example:
        >>> config = load_config("credentials.env")
        >>> data = fetch_connectwise_data(config)
        >>> print(f"Found {len(data['devices'])} devices")
    """
    logger = get_logger("cwtosdp.main")
    logger.info("Starting ConnectWise data fetch...")

    # Create CW client with retry configuration
    cw_client = ConnectWiseClient(
        config=config.connectwise,
        max_retries=config.max_retries,
        retry_delay=config.retry_delay_seconds
    )

    # Fetch all data types
    data = {
        "devices": cw_client.get_devices(),      # Endpoint devices
        "sites": cw_client.get_sites(),          # Site/location info
        "companies": cw_client.get_companies(),  # Company/org info
    }

    logger.info(
        f"ConnectWise fetch complete: "
        f"{len(data['devices'])} devices, "
        f"{len(data['sites'])} sites, "
        f"{len(data['companies'])} companies"
    )

    return data


def fetch_sdp_data(config: AppConfig) -> dict:
    """
    Fetch data from ServiceDesk Plus CMDB (READ-ONLY).

    Fetches workstation CIs from the ServiceDesk Plus CMDB
    using Zoho OAuth2 authentication.

    Args:
        config: Application configuration with SDP credentials

    Returns:
        Dictionary with:
        - workstations: List of CMDB workstation CIs

    Note:
        This is a READ-ONLY operation. No data is modified in SDP.

    Example:
        >>> config = load_config("credentials.env")
        >>> data = fetch_sdp_data(config)
        >>> print(f"Found {len(data['workstations'])} workstations")
    """
    logger = get_logger("cwtosdp.main")
    logger.info("Starting ServiceDesk Plus data fetch...")

    # Create SDP client with retry and dry_run configuration
    sdp_client = ServiceDeskPlusClient(
        config=config.servicedesk,
        max_retries=config.max_retries,
        retry_delay=config.retry_delay_seconds,
        dry_run=config.dry_run  # Respects dry_run for safety
    )

    # Fetch workstations from CMDB
    data = {
        "workstations": sdp_client.get_all_cmdb_workstations(),
    }

    logger.info(f"ServiceDesk Plus fetch complete: {len(data['workstations'])} workstations")

    return data


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """
    Main entry point for the CWtoSDP application.

    Parses command-line arguments and executes the requested operation.
    Supports data fetching, export, comparison, and GUI launching.
    """
    # =========================================================================
    # ARGUMENT PARSING
    # =========================================================================

    parser = argparse.ArgumentParser(
        description="CWtoSDP - ConnectWise to ServiceDesk Plus Integration"
    )
    parser.add_argument(
        "--env-file",
        default="credentials.env",
        help="Path to environment file (default: credentials.env)"
    )
    parser.add_argument(
        "--fetch-cw",
        action="store_true",
        help="Fetch data from ConnectWise and store in local database"
    )
    parser.add_argument(
        "--fetch-sdp",
        action="store_true",
        help="Fetch data from ServiceDesk Plus and store in local database"
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export fetched data to CSV files"
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the field mapping GUI"
    )
    parser.add_argument(
        "--match",
        action="store_true",
        help="Launch the Asset Matcher GUI (find matches between CW and SDP)"
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Launch the Sync Manager GUI (preview and execute CW->SDP sync)"
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Fetch DETAILED data from both systems and store in comparison database"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Enable dry-run mode (no write operations, default: True)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    # Parse command-line arguments
    args = parser.parse_args()

    # =========================================================================
    # LOGGING SETUP
    # =========================================================================

    import logging
    # Use DEBUG level if --debug flag is set, otherwise INFO
    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logger(level=log_level)
    logger = get_logger("cwtosdp.main")

    # =========================================================================
    # CONFIGURATION LOADING
    # =========================================================================

    try:
        # Load configuration from environment file
        config = load_config(args.env_file)
        # Apply dry_run setting from command line
        config.dry_run = args.dry_run
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    # Log the dry_run status for visibility
    logger.info(f"DRY_RUN mode: {'ENABLED' if config.dry_run else 'DISABLED'}")

    # =========================================================================
    # DATABASE INITIALIZATION
    # =========================================================================

    # Initialize the main database for storing fetched data
    db = Database()

    # Variables to hold fetched data
    cw_data = None
    sdp_data = None

    # =========================================================================
    # CONNECTWISE DATA FETCH
    # =========================================================================

    if args.fetch_cw:
        # Fetch data from ConnectWise API
        cw_data = fetch_connectwise_data(config)
        # Store devices in SQLite database
        db.store_cw_devices(cw_data["devices"])
        # Analyze field structure for mapping
        db.analyze_fields("cw", cw_data["devices"])
        # Export to CSV if requested
        if args.export:
            export_to_csv(cw_data["devices"], "cw_devices.csv", config.output_dir)
            export_to_csv(cw_data["sites"], "cw_sites.csv", config.output_dir)
            export_to_csv(cw_data["companies"], "cw_companies.csv", config.output_dir)

    # =========================================================================
    # SERVICEDESK PLUS DATA FETCH
    # =========================================================================

    if args.fetch_sdp:
        # Fetch data from ServiceDesk Plus API
        sdp_data = fetch_sdp_data(config)
        # Store workstations in SQLite database
        db.store_sdp_workstations(sdp_data["workstations"])
        # Analyze field structure for mapping
        db.analyze_fields("sdp", sdp_data["workstations"])
        # Export to CSV if requested
        if args.export:
            export_to_csv(sdp_data["workstations"], "sdp_workstations.csv", config.output_dir)

    # =========================================================================
    # COMPARISON MODE - Detailed data fetch for field mapping
    # =========================================================================
    # This mode fetches DETAILED data from both systems for field comparison.
    # It uses resumable fetching - if interrupted, run again to continue.
    # Uses adaptive rate limiting to avoid API throttling.
    # =========================================================================

    if args.compare:
        logger.info("=== COMPARISON MODE: Resumable fetch with adaptive rate limiting ===")

        # Use the comparison database (separate from main database)
        compare_db = CompareDatabase()

        # Show current fetch status (for resumable fetching)
        fetch_stats = compare_db.get_fetch_stats()
        logger.info(f"Previously fetched: CW={fetch_stats.get('cw', 0)}, SDP={fetch_stats.get('sdp', 0)}")

        # Get IDs that have already been fetched (for skipping)
        cw_fetched_ids = compare_db.get_fetched_ids("cw")
        sdp_fetched_ids = compare_db.get_fetched_ids("sdp")

        # ---------------------------------------------------------------------
        # CONNECTWISE DETAILED FETCH
        # ---------------------------------------------------------------------
        # First get the device list, then fetch details for each device

        logger.info("Fetching ConnectWise device list...")
        cw_client = ConnectWiseClient(config.connectwise)
        devices = cw_client.get_devices()

        # Filter out devices that have already been fetched
        devices_to_fetch = [d for d in devices if d.get("endpointId") not in cw_fetched_ids]
        logger.info(f"Found {len(devices)} total devices, {len(devices_to_fetch)} new to fetch")

        # Fetch detailed data for each device
        cw_stored = 0
        for i, device in enumerate(devices_to_fetch):
            endpoint_id = device.get("endpointId")
            if endpoint_id:
                try:
                    # Get detailed endpoint information
                    details = cw_client.get_endpoint_details(endpoint_id)
                    # Store in database and mark as fetched
                    if compare_db.store_cw_device_single(details, endpoint_id):
                        cw_stored += 1

                    # Progress update every 10 devices
                    if (i + 1) % 10 == 0:
                        stats = cw_client.rate_limiter.stats
                        logger.info(f"  CW Progress: {i + 1}/{len(devices_to_fetch)} "
                                   f"(interval: {stats['current_interval']:.1f}s, "
                                   f"rate limits hit: {stats['rate_limits_hit']})")
                except Exception as e:
                    logger.warning(f"Failed to get details for {endpoint_id}: {e}")
                    # Continue with next device (don't fail entire batch)

        logger.info(f"Stored {cw_stored} new ConnectWise devices")

        # ---------------------------------------------------------------------
        # SERVICEDESK PLUS FETCH
        # ---------------------------------------------------------------------
        # SDP data comes in bulk, but we store individually for tracking

        logger.info("Fetching ServiceDesk Plus workstation data...")
        sdp_client = ServiceDeskPlusClient(config.servicedesk)
        workstations = sdp_client.get_all_cmdb_workstations()

        # Filter and store individually for resumable tracking
        sdp_stored = 0
        for ws in workstations:
            ws_id = str(ws.get("id", ""))
            if ws_id and ws_id not in sdp_fetched_ids:
                if compare_db.store_sdp_workstation_single(ws, ws_id):
                    sdp_stored += 1

        logger.info(f"Stored {sdp_stored} new SDP workstations")

        # ---------------------------------------------------------------------
        # SUMMARY AND COLUMN COMPARISON
        # ---------------------------------------------------------------------

        final_stats = compare_db.get_fetch_stats()
        logger.info("=" * 60)
        logger.info("FETCH COMPLETE:")
        logger.info(f"  ConnectWise devices: {final_stats.get('cw', 0)}")
        logger.info(f"  ServiceDesk Plus workstations: {final_stats.get('sdp', 0)}")

        # Show column comparison if data is available
        try:
            comparison = compare_db.get_column_comparison()
            logger.info(f"FIELD COMPARISON:")
            logger.info(f"  ConnectWise columns: {comparison['cw_count']}")
            logger.info(f"  ServiceDesk Plus columns: {comparison['sdp_count']}")
            logger.info(f"  Common column names: {len(comparison['common'])}")
            if comparison['common']:
                logger.info(f"  Common: {comparison['common'][:10]}...")
        except Exception as e:
            logger.debug(f"Column comparison not available yet: {e}")

        logger.info(f"")
        logger.info(f"Database: {compare_db.db_path}")
        logger.info("Run again to resume if interrupted. Use --gui to explore data.")

        # Clean up
        compare_db.close()
        db.close()
        logger.info("Done.")
        return

    # =========================================================================
    # GUI LAUNCHERS
    # =========================================================================

    # Launch Field Mapping GUI
    if args.gui:
        from .gui import launch_gui
        launch_gui()
        return

    # Launch Asset Matcher GUI
    if args.match:
        from .asset_matcher import launch_asset_matcher
        launch_asset_matcher()
        return

    # Launch Sync Manager GUI (main interface)
    if args.sync:
        from .sync_gui import launch_sync_gui
        launch_sync_gui()
        return

    # =========================================================================
    # NO ACTION SPECIFIED - Show help
    # =========================================================================

    if not args.fetch_cw and not args.fetch_sdp and not args.gui and not args.compare and not args.match and not args.sync:
        # Show database stats and help message
        stats = db.get_stats()
        logger.info(f"Database stats: {stats}")
        logger.warning("No action specified. Use --fetch-cw, --fetch-sdp, --compare, or --gui")
        parser.print_help()

    # Clean up
    db.close()
    logger.info("Done.")


# =============================================================================
# SCRIPT ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    main()

