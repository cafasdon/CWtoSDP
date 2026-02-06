"""
================================================================================
Sync Engine: ConnectWise → ServiceDesk Plus Synchronization
================================================================================

This module contains the core synchronization logic for syncing devices from
ConnectWise RMM to ServiceDesk Plus CMDB. It handles:

1. Loading device data from the local SQLite database
2. Matching CW devices to existing SDP records (by hostname or serial)
3. Determining the appropriate action (CREATE or UPDATE)
4. Building a sync preview for user review
5. Providing summary statistics

Sync Workflow:
--------------
1. Fetch data from both APIs and store in SQLite (done by GUI/scripts)
2. SyncEngine reads from SQLite and builds a sync plan
3. User reviews the plan in the GUI
4. User selects items to sync and clicks "Execute Sync"
5. SDP client creates/updates CIs based on the plan

Matching Logic:
---------------
The engine tries to match CW devices to existing SDP records using:
1. Hostname match (case-insensitive) - Primary matching method
2. Serial number match (if not a VM) - Secondary matching method

If a match is found → UPDATE action
If no match found → CREATE action

CI Type Mapping:
----------------
CW Category → SDP CI Type:
- Laptop → ci_windows_workstation
- Desktop → ci_windows_workstation
- Virtual Server → ci_virtual_machine
- Physical Server → ci_windows_server
- Network Device → ci_switch

Usage Example:
--------------
    from src.sync_engine import SyncEngine

    # Build sync preview
    engine = SyncEngine()
    items = engine.build_sync_preview()

    # Get summary
    summary = engine.get_summary(items)
    print(f"Total: {summary['total']}")
    print(f"Creates: {summary['by_action'].get('create', 0)}")
    print(f"Updates: {summary['by_action'].get('update', 0)}")

    # Close when done
    engine.close()
"""

import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from .field_mapper import FieldMapper, DeviceClassifier

# Default path to the main database
# This database contains fresh data from CW and SDP APIs
from .db import DEFAULT_DB_PATH
DB_PATH = DEFAULT_DB_PATH


# =============================================================================
# ENUMS AND DATA CLASSES
# =============================================================================

class SyncAction(Enum):
    """
    Enumeration of possible sync actions for a device.

    Values:
        CREATE: Device doesn't exist in SDP, needs to be created
        UPDATE: Device exists in SDP, needs to be updated with CW data
        SKIP: Device exists and matches, no action needed
        ERROR: An error occurred during processing
    """
    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"    # Already exists and matches
    ERROR = "error"  # Processing error


@dataclass
class SyncItem:
    """
    Represents a single sync operation for one device.

    This dataclass holds all information needed to sync a CW device to SDP,
    including the source data, target CI type, action to take, and any
    matching SDP record information.

    Attributes:
        cw_id: ConnectWise endpoint ID (unique identifier)
        cw_name: ConnectWise friendly name (computer name)
        cw_category: Classified category (Laptop, Server, etc.)
        sdp_ci_type: Target SDP CI type (ci_windows_workstation, etc.)
        action: The sync action to perform (CREATE, UPDATE, etc.)
        sdp_id: Matching SDP CI ID (if UPDATE action)
        sdp_name: Matching SDP CI name (if UPDATE action)
        fields_to_sync: Dictionary of SDP field values to set (from CW)
        sdp_existing_fields: Dictionary of current SDP field values (for UPDATE comparison)
        match_reason: Human-readable explanation of why matched/not matched
    """
    cw_id: str                                    # CW endpoint ID
    cw_name: str                                  # CW computer name
    cw_category: str                              # Classified category
    sdp_ci_type: str                              # Target SDP CI type
    action: SyncAction                            # CREATE, UPDATE, etc.
    sdp_id: Optional[str] = None                  # Matching SDP ID (if any)
    sdp_name: Optional[str] = None                # Matching SDP name (if any)
    fields_to_sync: Dict[str, Any] = field(default_factory=dict)  # New values from CW
    sdp_existing_fields: Dict[str, Any] = field(default_factory=dict)  # Current SDP values
    match_reason: str = ""                        # Why matched/not matched

    def get_field_changes(self) -> Dict[str, str]:
        """
        Compare fields_to_sync with sdp_existing_fields to determine changes.

        Returns a dictionary mapping field names to change types:
        - "new": Field doesn't exist in SDP, will be added
        - "changed": Field exists in SDP but has different value
        - "unchanged": Field exists in SDP with same value
        """
        changes = {}
        for field_name, new_value in self.fields_to_sync.items():
            if not new_value:  # Skip empty values
                continue
            existing_value = self.sdp_existing_fields.get(field_name)
            if existing_value is None or existing_value == "":
                changes[field_name] = "new"
            elif str(existing_value).strip().upper() != str(new_value).strip().upper():
                changes[field_name] = "changed"
            else:
                changes[field_name] = "unchanged"
        return changes

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert SyncItem to a dictionary for JSON serialization.

        Returns:
            Dictionary representation of this sync item
        """
        return {
            "cw_id": self.cw_id,
            "cw_name": self.cw_name,
            "cw_category": self.cw_category,
            "sdp_ci_type": self.sdp_ci_type,
            "action": self.action.value,  # Convert enum to string
            "sdp_id": self.sdp_id,
            "sdp_name": self.sdp_name,
            "fields_to_sync": self.fields_to_sync,
            "sdp_existing_fields": self.sdp_existing_fields,
            "match_reason": self.match_reason,
        }


# =============================================================================
# SYNC ENGINE
# =============================================================================

class SyncEngine:
    """
    Engine for syncing ConnectWise devices to ServiceDesk Plus CMDB.

    This class reads device data from the local SQLite database (populated
    by the GUI or scripts), matches CW devices to existing SDP records,
    and builds a sync plan.

    The engine does NOT execute sync operations directly - it only builds
    the plan. Execution is handled by the GUI or automation scripts using
    the SDP client.

    Attributes:
        conn: SQLite database connection
        CI_TYPE_MAP: Mapping from CW categories to SDP CI types

    Example:
        >>> engine = SyncEngine()
        >>> items = engine.build_sync_preview()
        >>> for item in items:
        ...     print(f"{item.cw_name}: {item.action.value}")
        >>> engine.close()
    """

    # =========================================================================
    # CI TYPE MAPPING
    # =========================================================================

    # Maps DeviceClassifier categories to SDP CI types
    # This determines which CMDB table a device goes into
    CI_TYPE_MAP = {
        "Laptop": "ci_windows_workstation",       # Portable computers
        "Desktop": "ci_windows_workstation",      # Fixed workstations
        "Virtual Server": "ci_virtual_machine",   # VMs (VMware, Hyper-V, etc.)
        "Physical Server": "ci_windows_server",   # Bare metal servers
        "Network Device": "ci_switch",            # Routers, switches, etc.
    }

    # =========================================================================
    # INITIALIZATION
    # =========================================================================

    def __init__(self, db_path: Path = DB_PATH):
        """
        Initialize the sync engine with a database connection.

        Args:
            db_path: Path to the SQLite database file.
                    Defaults to data/cwtosdp.db
        """
        # Connect to SQLite database
        self.conn = sqlite3.connect(db_path)
        # Use Row factory for dict-like access to columns
        self.conn.row_factory = sqlite3.Row

    def close(self):
        """Close the database connection."""
        self.conn.close()

    # =========================================================================
    # SYNC PREVIEW
    # =========================================================================

    def build_sync_preview(self) -> List[SyncItem]:
        """
        Build a preview of all sync operations.
        
        Optimized implementation:
        1. Pre-loads all SDP workstations into memory lookup maps (O(1) access)
        2. Iterates CW devices and matches against maps
        3. Eliminates N+1 DB query problem
        """
        items = []
        cursor = self.conn.cursor()

        # =====================================================================
        # PRE-LOAD SDP DATA FOR LOOKUP (Performance Optimization)
        # =====================================================================
        sdp_lookup_name = {}
        sdp_lookup_serial = {}
        
        try:
            # Use main DB table 'sdp_workstations'
            cursor.execute("SELECT * FROM sdp_workstations")
            sdp_rows = cursor.fetchall()
            
            for row in sdp_rows:
                # Build Hostname Lookup
                if row["name"]:
                    sdp_lookup_name[row["name"].upper()] = row
                    
                # Build Serial Lookup (skip empty or VM serials)
                serial = row["serial_number"]
                if serial and "VMWARE" not in serial.upper() and "VIRTUAL" not in serial.upper():
                    sdp_lookup_serial[serial.upper()] = row
                    
        except sqlite3.OperationalError:
            # Table might not exist if SDP fetch hasn't run yet
            pass

        # =====================================================================
        # PROCESS CONNECTWISE DEVICES
        # =====================================================================
        
        # Get all CW devices from the main DB table 'cw_devices'
        cursor.execute("SELECT endpoint_id, raw_json FROM cw_devices")
        
        for row in cursor.fetchall():
            # Extract device data
            cw_id = row["endpoint_id"]
            device = json.loads(row["raw_json"])

            # Use FieldMapper to classify and map fields
            mapper = FieldMapper(device)
            sdp_data = mapper.get_sdp_data()

            # Extract category
            category = sdp_data.pop("_category")

            # Determine target SDP CI type
            sdp_ci_type = self.CI_TYPE_MAP.get(category, "ci_windows_workstation")

            # Try to find matching SDP record using in-memory lookups
            match = self._find_sdp_match_optimized(device, sdp_lookup_name, sdp_lookup_serial)

            if match:
                # Match found → UPDATE action
                sdp_id, sdp_name, match_reason, existing_fields = match
                item = SyncItem(
                    cw_id=cw_id,
                    cw_name=device.get("friendlyName", ""),
                    cw_category=category,
                    sdp_ci_type=sdp_ci_type,
                    action=SyncAction.UPDATE,
                    sdp_id=sdp_id,
                    sdp_name=sdp_name,
                    fields_to_sync=sdp_data,
                    sdp_existing_fields=existing_fields,
                    match_reason=match_reason,
                )
            else:
                # No match → CREATE action
                item = SyncItem(
                    cw_id=cw_id,
                    cw_name=device.get("friendlyName", ""),
                    cw_category=category,
                    sdp_ci_type=sdp_ci_type,
                    action=SyncAction.CREATE,
                    fields_to_sync=sdp_data,
                    sdp_existing_fields={},
                    match_reason="No match found",
                )

            items.append(item)

        return items

    # =========================================================================
    # MATCHING LOGIC
    # =========================================================================

    def _find_sdp_match_optimized(
        self, 
        cw_device: Dict, 
        lookup_name: Dict[str, Any], 
        lookup_serial: Dict[str, Any]
    ) -> Optional[Tuple[str, str, str, Dict[str, Any]]]:
        """
        Find a matching SDP record using in-memory lookups.
        
        Args:
            cw_device: CW device dictionary
            lookup_name: Dictionary mapping UPPER(hostname) -> row
            lookup_serial: Dictionary mapping UPPER(serial) -> row
            
        Returns:
            Tuple match data or None
        """
        # Extract matching fields from CW device
        cw_name = cw_device.get("friendlyName", "").upper()
        cw_serial = (cw_device.get("system", {}).get("serialNumber") or "").upper()
        
        # 1. Hostname Match
        if cw_name in lookup_name:
            row = lookup_name[cw_name]
            existing_fields = self._extract_sdp_fields(row)
            return (str(row["ci_id"]), row["name"], f"Hostname match: {row['name']}", existing_fields)
            
        # 2. Serial Match (if not VM)
        if cw_serial and "VMWARE" not in cw_serial and "VIRTUAL" not in cw_serial:
            if cw_serial in lookup_serial:
                row = lookup_serial[cw_serial]
                existing_fields = self._extract_sdp_fields(row)
                return (str(row["ci_id"]), row["name"], f"Serial match: {cw_serial}", existing_fields)
                
        return None

    def _extract_sdp_fields(self, row) -> Dict[str, Any]:
        """
        Extract relevant fields from an SDP database row for comparison.
        Samples keys safely to avoid KeyErrors if columns are missing.
        """
        def get_val(key):
            # Check if key exists in row (sqlite3.Row supports searching keys)
            if key in row.keys():
                return row[key]
            return None
            
        return {
            "name": get_val("name"),
            "ci_attributes_txt_serial_number": get_val("serial_number"),
            "ci_attributes_txt_os": get_val("os"),
            "ci_attributes_txt_manufacturer": get_val("manufacturer"),
            "ci_attributes_txt_ip_address": get_val("ip_address"),
            "ci_attributes_txt_mac_address": None, # Not strictly in standard table, would need json parse if crucial
        }

    # =========================================================================
    # SUMMARY STATISTICS
    # =========================================================================

    def get_summary(self, items: List[SyncItem]) -> Dict[str, Any]:
        """
        Get summary statistics for a sync preview.

        Provides counts grouped by:
        - Action (create, update, skip, error)
        - Category (Laptop, Server, etc.)
        - CI Type (ci_windows_workstation, etc.)

        Args:
            items: List of SyncItem objects from build_sync_preview()

        Returns:
            Dictionary with summary statistics:
            {
                "total": 204,
                "by_action": {"create": 172, "update": 32},
                "by_category": {"Laptop": 150, "Virtual Server": 54},
                "by_ci_type": {"ci_windows_workstation": 150, ...}
            }
        """
        summary = {
            "total": len(items),
            "by_action": {},
            "by_category": {},
            "by_ci_type": {}
        }

        for item in items:
            # Count by action
            action = item.action.value
            summary["by_action"][action] = summary["by_action"].get(action, 0) + 1

            # Count by category
            summary["by_category"][item.cw_category] = summary["by_category"].get(item.cw_category, 0) + 1

            # Count by CI type
            summary["by_ci_type"][item.sdp_ci_type] = summary["by_ci_type"].get(item.sdp_ci_type, 0) + 1

        return summary

