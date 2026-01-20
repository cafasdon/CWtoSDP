"""
CWtoSDP - ConnectWise to ServiceDesk Plus Integration

Main entry point for the integration tool.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

from .config import load_config, AppConfig
from .logger import setup_logger, get_logger
from .cw_client import ConnectWiseClient
from .sdp_client import ServiceDeskPlusClient
from .db import Database
from .db_compare import CompareDatabase


def export_to_csv(data: list, filename: str, output_dir: Path) -> Path:
    """
    Export data to CSV file.
    
    Args:
        data: List of dictionaries to export.
        filename: Output filename.
        output_dir: Directory to save file.
    
    Returns:
        Path to saved file.
    """
    logger = get_logger("cwtosdp.main")
    df = pd.json_normalize(data)
    filepath = output_dir / filename
    df.to_csv(filepath, index=False)
    logger.info(f"Exported {len(data)} records to {filepath}")
    return filepath


def fetch_connectwise_data(config: AppConfig) -> dict:
    """
    Fetch all data from ConnectWise.
    
    Args:
        config: Application configuration.
    
    Returns:
        Dictionary with devices, sites, and companies data.
    """
    logger = get_logger("cwtosdp.main")
    logger.info("Starting ConnectWise data fetch...")
    
    cw_client = ConnectWiseClient(
        config=config.connectwise,
        max_retries=config.max_retries,
        retry_delay=config.retry_delay_seconds
    )
    
    data = {
        "devices": cw_client.get_devices(),
        "sites": cw_client.get_sites(),
        "companies": cw_client.get_companies(),
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
    Fetch data from ServiceDesk Plus (READ-ONLY).
    
    Args:
        config: Application configuration.
    
    Returns:
        Dictionary with CMDB workstations data.
    """
    logger = get_logger("cwtosdp.main")
    logger.info("Starting ServiceDesk Plus data fetch...")
    
    sdp_client = ServiceDeskPlusClient(
        config=config.servicedesk,
        max_retries=config.max_retries,
        retry_delay=config.retry_delay_seconds,
        dry_run=config.dry_run
    )
    
    data = {
        "workstations": sdp_client.get_all_cmdb_workstations(),
    }
    
    logger.info(f"ServiceDesk Plus fetch complete: {len(data['workstations'])} workstations")
    
    return data


def main():
    """Main entry point."""
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

    args = parser.parse_args()

    # Setup logging
    import logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logger(level=log_level)
    logger = get_logger("cwtosdp.main")

    # Load configuration
    try:
        config = load_config(args.env_file)
        config.dry_run = args.dry_run
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    logger.info(f"DRY_RUN mode: {'ENABLED' if config.dry_run else 'DISABLED'}")

    # Initialize database
    db = Database()

    # Fetch data
    cw_data = None
    sdp_data = None

    if args.fetch_cw:
        cw_data = fetch_connectwise_data(config)
        # Store in database
        db.store_cw_devices(cw_data["devices"])
        # Analyze field structure
        db.analyze_fields("cw", cw_data["devices"])
        if args.export:
            export_to_csv(cw_data["devices"], "cw_devices.csv", config.output_dir)
            export_to_csv(cw_data["sites"], "cw_sites.csv", config.output_dir)
            export_to_csv(cw_data["companies"], "cw_companies.csv", config.output_dir)

    if args.fetch_sdp:
        sdp_data = fetch_sdp_data(config)
        # Store in database
        db.store_sdp_workstations(sdp_data["workstations"])
        # Analyze field structure
        db.analyze_fields("sdp", sdp_data["workstations"])
        if args.export:
            export_to_csv(sdp_data["workstations"], "sdp_workstations.csv", config.output_dir)

    # Comparison mode - fetch detailed data for 1:1 field mapping
    if args.compare:
        logger.info("=== COMPARISON MODE: Resumable fetch with adaptive rate limiting ===")
        compare_db = CompareDatabase()

        # Show current fetch status
        fetch_stats = compare_db.get_fetch_stats()
        logger.info(f"Previously fetched: CW={fetch_stats.get('cw', 0)}, SDP={fetch_stats.get('sdp', 0)}")

        # Get already fetched IDs
        cw_fetched_ids = compare_db.get_fetched_ids("cw")
        sdp_fetched_ids = compare_db.get_fetched_ids("sdp")

        # Fetch CW detailed device data
        logger.info("Fetching ConnectWise device list...")
        cw_client = ConnectWiseClient(config.connectwise)
        devices = cw_client.get_devices()

        # Filter out already-fetched devices
        devices_to_fetch = [d for d in devices if d.get("endpointId") not in cw_fetched_ids]
        logger.info(f"Found {len(devices)} total devices, {len(devices_to_fetch)} new to fetch")

        cw_stored = 0
        for i, device in enumerate(devices_to_fetch):
            endpoint_id = device.get("endpointId")
            if endpoint_id:
                try:
                    details = cw_client.get_endpoint_details(endpoint_id)
                    if compare_db.store_cw_device_single(details, endpoint_id):
                        cw_stored += 1

                    # Progress update
                    if (i + 1) % 10 == 0:
                        stats = cw_client.rate_limiter.stats
                        logger.info(f"  CW Progress: {i + 1}/{len(devices_to_fetch)} "
                                   f"(interval: {stats['current_interval']:.1f}s, "
                                   f"rate limits hit: {stats['rate_limits_hit']})")
                except Exception as e:
                    logger.warning(f"Failed to get details for {endpoint_id}: {e}")
                    # Continue with next device

        logger.info(f"Stored {cw_stored} new ConnectWise devices")

        # Fetch SDP workstation data (these come in bulk, store individually for tracking)
        logger.info("Fetching ServiceDesk Plus workstation data...")
        sdp_client = ServiceDeskPlusClient(config.servicedesk)
        workstations = sdp_client.get_all_cmdb_workstations()

        # Filter and store individually
        sdp_stored = 0
        for ws in workstations:
            ws_id = str(ws.get("id", ""))
            if ws_id and ws_id not in sdp_fetched_ids:
                if compare_db.store_sdp_workstation_single(ws, ws_id):
                    sdp_stored += 1

        logger.info(f"Stored {sdp_stored} new SDP workstations")

        # Show final stats and column comparison
        final_stats = compare_db.get_fetch_stats()
        logger.info("=" * 60)
        logger.info("FETCH COMPLETE:")
        logger.info(f"  ConnectWise devices: {final_stats.get('cw', 0)}")
        logger.info(f"  ServiceDesk Plus workstations: {final_stats.get('sdp', 0)}")

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
        compare_db.close()
        db.close()
        logger.info("Done.")
        return

    # Launch GUI if requested
    if args.gui:
        from .gui import launch_gui
        launch_gui()
        return

    # Launch Asset Matcher GUI if requested
    if args.match:
        from .asset_matcher import launch_asset_matcher
        launch_asset_matcher()
        return

    # Launch Sync Manager GUI if requested
    if args.sync:
        from .sync_gui import launch_sync_gui
        launch_sync_gui()
        return

    if not args.fetch_cw and not args.fetch_sdp and not args.gui and not args.compare and not args.match and not args.sync:
        # Show stats and help
        stats = db.get_stats()
        logger.info(f"Database stats: {stats}")
        logger.warning("No action specified. Use --fetch-cw, --fetch-sdp, --compare, or --gui")
        parser.print_help()

    db.close()
    logger.info("Done.")


if __name__ == "__main__":
    main()

