"""
Sync Engine: CW -> SDP synchronization logic.

Handles:
1. Matching CW devices to existing SDP records
2. Determining create vs update actions
3. Building sync preview
4. Executing sync operations (with dry-run support)
"""
import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from .field_mapper import FieldMapper, DeviceClassifier

DB_PATH = Path("data/cwtosdp_compare.db")


class SyncAction(Enum):
    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"  # Already exists and matches
    ERROR = "error"


@dataclass
class SyncItem:
    """Represents a single sync operation."""
    cw_id: str
    cw_name: str
    cw_category: str
    sdp_ci_type: str
    action: SyncAction
    sdp_id: Optional[str] = None
    sdp_name: Optional[str] = None
    fields_to_sync: Dict[str, Any] = field(default_factory=dict)
    match_reason: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cw_id": self.cw_id,
            "cw_name": self.cw_name,
            "cw_category": self.cw_category,
            "sdp_ci_type": self.sdp_ci_type,
            "action": self.action.value,
            "sdp_id": self.sdp_id,
            "sdp_name": self.sdp_name,
            "fields_to_sync": self.fields_to_sync,
            "match_reason": self.match_reason,
        }


class SyncEngine:
    """Engine for syncing CW devices to SDP."""
    
    # CW category to SDP CI type mapping
    CI_TYPE_MAP = {
        "Laptop": "ci_windows_workstation",
        "Desktop": "ci_windows_workstation",
        "Virtual Server": "ci_virtual_machine",
        "Physical Server": "ci_windows_server",
        "Network Device": "ci_switch",  # Could be refined based on resourceType
    }
    
    def __init__(self, db_path: Path = DB_PATH):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        
    def close(self):
        self.conn.close()
    
    def build_sync_preview(self) -> List[SyncItem]:
        """Build a preview of all sync operations."""
        items = []
        cursor = self.conn.cursor()
        
        # Get all CW devices
        cursor.execute("SELECT endpointID, raw_json FROM cw_devices_full")
        
        for row in cursor.fetchall():
            cw_id = row["endpointID"]
            device = json.loads(row["raw_json"])
            
            mapper = FieldMapper(device)
            sdp_data = mapper.get_sdp_data()
            category = sdp_data.pop("_category")
            sdp_ci_type = self.CI_TYPE_MAP.get(category, "ci_windows_workstation")
            
            # Try to find matching SDP record
            match = self._find_sdp_match(device, sdp_ci_type)
            
            if match:
                sdp_id, sdp_name, match_reason = match
                item = SyncItem(
                    cw_id=cw_id,
                    cw_name=device.get("friendlyName", ""),
                    cw_category=category,
                    sdp_ci_type=sdp_ci_type,
                    action=SyncAction.UPDATE,
                    sdp_id=sdp_id,
                    sdp_name=sdp_name,
                    fields_to_sync=sdp_data,
                    match_reason=match_reason,
                )
            else:
                item = SyncItem(
                    cw_id=cw_id,
                    cw_name=device.get("friendlyName", ""),
                    cw_category=category,
                    sdp_ci_type=sdp_ci_type,
                    action=SyncAction.CREATE,
                    fields_to_sync=sdp_data,
                    match_reason="No match found",
                )
            
            items.append(item)
        
        return items
    
    def _find_sdp_match(self, cw_device: Dict, sdp_ci_type: str) -> Optional[Tuple[str, str, str]]:
        """Find matching SDP record for a CW device."""
        cursor = self.conn.cursor()
        cw_name = cw_device.get("friendlyName", "").upper()
        cw_serial = (cw_device.get("system", {}).get("serialNumber") or "").upper()
        
        # For now, only match against workstations (we only fetched those)
        # Match by hostname first
        cursor.execute(
            "SELECT sdp_id, name FROM sdp_workstations_full WHERE UPPER(name) = ?",
            (cw_name,)
        )
        row = cursor.fetchone()
        if row:
            return (str(row["sdp_id"]), row["name"], f"Hostname match: {row['name']}")
        
        # Match by serial (if not a VM serial)
        if cw_serial and "VMWARE" not in cw_serial:
            cursor.execute(
                "SELECT sdp_id, name FROM sdp_workstations_full WHERE UPPER(ci_attributes_txt_serial_number) = ?",
                (cw_serial,)
            )
            row = cursor.fetchone()
            if row:
                return (str(row["sdp_id"]), row["name"], f"Serial match: {cw_serial}")
        
        return None
    
    def get_summary(self, items: List[SyncItem]) -> Dict[str, Any]:
        """Get summary statistics for sync preview."""
        summary = {"total": len(items), "by_action": {}, "by_category": {}, "by_ci_type": {}}
        
        for item in items:
            # By action
            action = item.action.value
            summary["by_action"][action] = summary["by_action"].get(action, 0) + 1
            # By category
            summary["by_category"][item.cw_category] = summary["by_category"].get(item.cw_category, 0) + 1
            # By CI type
            summary["by_ci_type"][item.sdp_ci_type] = summary["by_ci_type"].get(item.sdp_ci_type, 0) + 1
        
        return summary

