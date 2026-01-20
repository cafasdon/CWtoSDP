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
        help="Fetch data from ConnectWise"
    )
    parser.add_argument(
        "--fetch-sdp",
        action="store_true",
        help="Fetch data from ServiceDesk Plus"
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export fetched data to CSV files"
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
    
    # Fetch data
    cw_data = None
    sdp_data = None
    
    if args.fetch_cw:
        cw_data = fetch_connectwise_data(config)
        if args.export:
            export_to_csv(cw_data["devices"], "cw_devices.csv", config.output_dir)
            export_to_csv(cw_data["sites"], "cw_sites.csv", config.output_dir)
            export_to_csv(cw_data["companies"], "cw_companies.csv", config.output_dir)
    
    if args.fetch_sdp:
        sdp_data = fetch_sdp_data(config)
        if args.export:
            export_to_csv(sdp_data["workstations"], "sdp_workstations.csv", config.output_dir)
    
    if not args.fetch_cw and not args.fetch_sdp:
        logger.warning("No action specified. Use --fetch-cw or --fetch-sdp")
        parser.print_help()
    
    logger.info("Done.")


if __name__ == "__main__":
    main()

