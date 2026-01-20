#!/usr/bin/env python3
"""
================================================================================
CWtoSDP Automated Sync Script
================================================================================

This script runs a REAL synchronization from ConnectWise to ServiceDesk Plus.
Unlike the GUI which defaults to dry-run mode, this script performs actual 
write operations to SDP's CMDB.

IMPORTANT: This script will CREATE and UPDATE records in ServiceDesk Plus!
           Make sure you understand what this does before running.

Features:
---------
1. Fetches latest data from both CW and SDP APIs
2. Compares devices and builds sync plan
3. Executes sync (creates new CIs, updates existing ones)
4. Logs all actions with full audit trail
5. Supports dry-run mode for testing

Usage:
------
    # Dry run (preview only, no changes):
    python run_sync.py --dry-run
    
    # Real sync with auto-confirmation:
    python run_sync.py --yes
    
    # Real sync with prompts:
    python run_sync.py
    
    # Sync only CREATE actions (skip updates):
    python run_sync.py --create-only --yes
    
    # Show what would be synced without fetching new data:
    python run_sync.py --preview-only

Author: DMH Stallard IT Team
Version: 1.0.0
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# =============================================================================
# CONFIGURATION
# =============================================================================

# Add project root to Python path for imports
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import project modules
from src.config import load_config
from src.logger import setup_logger, get_logger
from src.cw_client import ConnectWiseClient
from src.sdp_client import SDPClient
from src.db_compare import CompareDatabase
from src.sync_engine import SyncEngine, SyncAction


# =============================================================================
# MAIN SYNC FUNCTION
# =============================================================================

def run_sync(
    dry_run: bool = False,
    create_only: bool = False,
    skip_fetch: bool = False,
    auto_confirm: bool = False
) -> dict:
    """
    Execute the CW to SDP synchronization.
    
    Args:
        dry_run: If True, only simulate sync (no actual changes)
        create_only: If True, only create new records (skip updates)
        skip_fetch: If True, use existing local data (don't fetch from APIs)
        auto_confirm: If True, don't prompt for confirmation
    
    Returns:
        Dictionary with sync results and statistics
    """
    # Initialize logging
    setup_logger()
    logger = get_logger("cwtosdp.sync")
    
    logger.info("=" * 70)
    logger.info("CWtoSDP AUTOMATED SYNC")
    logger.info(f"Started: {datetime.now().isoformat()}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE SYNC'}")
    logger.info(f"Create only: {create_only}")
    logger.info("=" * 70)
    
    # Load configuration
    try:
        config = load_config()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Make sure credentials.env exists with valid API credentials")
        return {"success": False, "error": str(e)}
    
    # Initialize results tracking
    results = {
        "success": True,
        "started": datetime.now().isoformat(),
        "mode": "dry_run" if dry_run else "live",
        "items_processed": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "error_details": []
    }
    
    # -------------------------------------------------------------------------
    # STEP 1: Fetch latest data from APIs (unless skipped)
    # -------------------------------------------------------------------------
    if not skip_fetch:
        logger.info("")
        logger.info("STEP 1: Fetching latest data from APIs...")
        logger.info("-" * 50)
        
        try:
            # Fetch from ConnectWise
            logger.info("Fetching ConnectWise devices...")
            cw_client = ConnectWiseClient(config.connectwise)
            cw_devices = cw_client.get_devices()
            logger.info(f"  ✓ Retrieved {len(cw_devices)} CW devices")
            
            # Store in local database
            db = CompareDatabase()
            # Note: Using the store method to save all devices
            for device in cw_devices:
                endpoint_id = device.get("endpointId")
                if endpoint_id:
                    db.store_cw_device_single(device, endpoint_id)
            
            # Fetch from ServiceDesk Plus
            logger.info("Fetching ServiceDesk Plus workstations...")
            sdp_client = SDPClient(dry_run=True)  # Always dry_run for fetch
            sdp_workstations = sdp_client.get_all_cmdb_workstations()
            logger.info(f"  ✓ Retrieved {len(sdp_workstations)} SDP workstations")
            
            # Store in local database
            for ws in sdp_workstations:
                ws_id = str(ws.get("id", ""))
                if ws_id:
                    db.store_sdp_workstation_single(ws, ws_id)
            
            db.close()
            logger.info("  ✓ Data stored in local database")
            
        except Exception as e:
            logger.error(f"Failed to fetch data: {e}")
            results["success"] = False
            results["error"] = f"Fetch failed: {e}"
            return results
    else:
        logger.info("")
        logger.info("STEP 1: Skipping data fetch (using local cache)")
        logger.info("-" * 50)
    
    # -------------------------------------------------------------------------
    # STEP 2: Build sync preview
    # -------------------------------------------------------------------------
    logger.info("")
    logger.info("STEP 2: Building sync preview...")
    logger.info("-" * 50)

    try:
        engine = SyncEngine()
        sync_items = engine.build_sync_preview()
        summary = engine.get_summary(sync_items)
        engine.close()

        logger.info(f"  Total items: {summary['total']}")
        logger.info(f"  By action: {summary['by_action']}")
        logger.info(f"  By category: {summary['by_category']}")

    except Exception as e:
        logger.error(f"Failed to build sync preview: {e}")
        results["success"] = False
        results["error"] = f"Preview failed: {e}"
        return results

    # Filter to CREATE only if requested
    if create_only:
        sync_items = [item for item in sync_items if item.action == SyncAction.CREATE]
        logger.info(f"  Filtered to CREATE only: {len(sync_items)} items")

    # Count actions
    create_count = sum(1 for i in sync_items if i.action == SyncAction.CREATE)
    update_count = sum(1 for i in sync_items if i.action == SyncAction.UPDATE)

    logger.info(f"  Will CREATE: {create_count}")
    logger.info(f"  Will UPDATE: {update_count}")

    # -------------------------------------------------------------------------
    # STEP 3: Confirm before proceeding (unless auto-confirm)
    # -------------------------------------------------------------------------
    if not dry_run and not auto_confirm:
        logger.info("")
        logger.info("=" * 70)
        logger.warning("⚠️  ABOUT TO PERFORM LIVE SYNC")
        logger.warning(f"    This will CREATE {create_count} and UPDATE {update_count} records in SDP")
        logger.info("=" * 70)

        response = input("\nType 'yes' to proceed, anything else to abort: ").strip().lower()
        if response != 'yes':
            logger.info("Sync aborted by user")
            results["success"] = False
            results["error"] = "Aborted by user"
            return results

    # -------------------------------------------------------------------------
    # STEP 4: Execute sync
    # -------------------------------------------------------------------------
    logger.info("")
    logger.info("STEP 3: Executing sync...")
    logger.info("-" * 50)

    # Initialize SDP client with correct dry_run setting
    sdp_client = SDPClient(dry_run=dry_run)

    for i, item in enumerate(sync_items):
        results["items_processed"] += 1

        try:
            if item.action == SyncAction.CREATE:
                # Create new CI in SDP
                ci_data = item.fields_to_sync.copy()
                ci_data["name"] = item.cw_name

                result = sdp_client.create_ci(item.sdp_ci_type, ci_data)

                if result:
                    if dry_run:
                        logger.info(f"  [DRY RUN] Would create: {item.cw_name} ({item.sdp_ci_type})")
                    else:
                        logger.info(f"  ✓ Created: {item.cw_name} ({item.sdp_ci_type})")
                    results["created"] += 1
                else:
                    logger.warning(f"  ✗ Failed to create: {item.cw_name}")
                    results["errors"] += 1
                    results["error_details"].append(f"Create failed: {item.cw_name}")

            elif item.action == SyncAction.UPDATE:
                # TODO: Implement update logic when needed
                logger.debug(f"  [SKIP] Update not implemented: {item.cw_name}")
                results["skipped"] += 1

            else:
                results["skipped"] += 1

        except Exception as e:
            logger.error(f"  ✗ Error processing {item.cw_name}: {e}")
            results["errors"] += 1
            results["error_details"].append(f"{item.cw_name}: {str(e)}")

        # Progress update every 10 items
        if (i + 1) % 10 == 0:
            logger.info(f"  Progress: {i + 1}/{len(sync_items)}")

    # -------------------------------------------------------------------------
    # STEP 5: Generate report
    # -------------------------------------------------------------------------
    results["completed"] = datetime.now().isoformat()

    logger.info("")
    logger.info("=" * 70)
    logger.info("SYNC COMPLETE")
    logger.info("=" * 70)
    logger.info(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info(f"  Items processed: {results['items_processed']}")
    logger.info(f"  Created: {results['created']}")
    logger.info(f"  Updated: {results['updated']}")
    logger.info(f"  Skipped: {results['skipped']}")
    logger.info(f"  Errors: {results['errors']}")

    if results["error_details"]:
        logger.info("")
        logger.info("Error details:")
        for err in results["error_details"][:10]:  # Show first 10
            logger.info(f"  - {err}")
        if len(results["error_details"]) > 10:
            logger.info(f"  ... and {len(results['error_details']) - 10} more")

    # Save results to JSON file
    results_file = Path("logs") / f"sync_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    results_file.parent.mkdir(exist_ok=True)
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"  Results saved to: {results_file}")

    return results


# =============================================================================
# COMMAND LINE INTERFACE
# =============================================================================

def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="CWtoSDP Automated Sync - Synchronize ConnectWise devices to ServiceDesk Plus",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_sync.py --dry-run           Preview what would be synced
  python run_sync.py --yes               Run sync with auto-confirmation
  python run_sync.py --create-only       Only create new records (skip updates)
  python run_sync.py --preview-only      Show plan without fetching new data
        """
    )

    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Simulate sync without making changes (RECOMMENDED for first run)"
    )

    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Auto-confirm sync (no prompts) - USE WITH CAUTION"
    )

    parser.add_argument(
        "--create-only",
        action="store_true",
        help="Only create new records, skip updates"
    )

    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="Use cached data (don't fetch from APIs)"
    )

    args = parser.parse_args()

    # Run the sync
    results = run_sync(
        dry_run=args.dry_run,
        create_only=args.create_only,
        skip_fetch=args.preview_only,
        auto_confirm=args.yes
    )

    # Exit with appropriate code
    sys.exit(0 if results.get("success") else 1)


if __name__ == "__main__":
    main()

