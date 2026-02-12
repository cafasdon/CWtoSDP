"""
SQLite Database Storage for CWtoSDP.

Provides local storage for ConnectWise and ServiceDesk Plus data
to enable offline analysis and field mapping.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .logger import get_logger

logger = get_logger("cwtosdp.db")

# Default database path
DEFAULT_DB_PATH = Path("./data/cwtosdp.db")


class Database:
    """
    SQLite database for storing CW and SDP data locally.

    Stores raw JSON data along with extracted key fields for querying.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file. Defaults to ./data/cwtosdp.db
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_database(self):
        """Initialize database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # ConnectWise devices table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cw_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint_id TEXT UNIQUE NOT NULL,
                name TEXT,
                site_name TEXT,
                company_name TEXT,
                os_type TEXT,
                last_seen TEXT,
                raw_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
        """)

        # ServiceDesk Plus assets table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sdp_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT UNIQUE NOT NULL,
                name TEXT,
                serial_number TEXT,
                ip_address TEXT,
                mac_address TEXT,
                os TEXT,
                manufacturer TEXT,
                model TEXT,
                raw_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
        """)

        # Migrate from old sdp_workstations table if it exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sdp_workstations'")
        if cursor.fetchone():
            logger.info("Migrating sdp_workstations → sdp_assets")
            cursor.execute("DROP TABLE IF EXISTS sdp_workstations")
            conn.commit()

        # Field metadata table (for mapping)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS field_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                field_path TEXT NOT NULL,
                field_type TEXT,
                sample_value TEXT,
                occurrence_count INTEGER DEFAULT 0,
                UNIQUE(source, field_path)
            )
        """)

        # Field mappings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS field_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cw_field TEXT NOT NULL,
                sdp_field TEXT NOT NULL,
                transform_type TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(cw_field, sdp_field)
            )
        """)

        # Sync history table (for stats)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sync_type TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                records_processed INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running'
            )
        """)

        # Sync log table (for revert functionality)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sync_time TEXT NOT NULL,
                items_json TEXT NOT NULL,
                reverted INTEGER DEFAULT 0
            )
        """)

        conn.commit()
        logger.info(f"Database initialized at {self.db_path}")

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # =========================================================================
    # ConnectWise Device Operations
    # =========================================================================

    def store_cw_devices(self, devices: List[Dict[str, Any]]) -> int:
        """
        Store ConnectWise devices in database.
        
        Args:
            devices: List of device dictionaries from CW API.
            
        Returns:
            Number of devices stored.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        fetched_at = datetime.now().isoformat()
        
        counts = {"new": 0, "updated": 0, "total": 0}

        for device in devices:
            try:
                endpoint_id = device.get("endpointId", "")
                if not endpoint_id:
                    continue

                # Check if exists (to distinguish insert vs update)
                cursor.execute("SELECT 1 FROM cw_devices WHERE endpoint_id = ?", (endpoint_id,))
                exists = cursor.fetchone() is not None
                
                if exists:
                    counts["updated"] += 1
                else:
                    counts["new"] += 1

                cursor.execute("""
                    INSERT OR REPLACE INTO cw_devices
                    (endpoint_id, name, site_name, company_name, os_type, last_seen, raw_json, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    endpoint_id,
                    device.get("friendlyName", device.get("endpointName", device.get("name", ""))),
                    device.get("siteName", ""),
                    device.get("companyName", ""),
                    device.get("osType", ""),
                    device.get("lastSeen", ""),
                    json.dumps(device),
                    fetched_at
                ))
                counts["total"] += 1
            except Exception as e:
                logger.warning(f"Failed to store device: {e}")

        conn.commit()
        logger.info(f"Stored {counts['total']} CW devices (New: {counts['new']}, Updated: {counts['updated']})")
        return counts['total']

    def get_cw_devices(self) -> List[Dict[str, Any]]:
        """Get all stored ConnectWise devices."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM cw_devices ORDER BY name")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_cw_device_raw(self, endpoint_id: str) -> Optional[Dict[str, Any]]:
        """Get raw JSON data for a specific CW device."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT raw_json FROM cw_devices WHERE endpoint_id = ?", (endpoint_id,))
        row = cursor.fetchone()
        return json.loads(row["raw_json"]) if row else None

    def get_cw_device_ids(self) -> set:
        """Get set of all stored CW endpoint IDs."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT endpoint_id FROM cw_devices")
        return {row[0] for row in cursor.fetchall()}

    def get_cw_device_count(self) -> int:
        """Get count of stored CW devices."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cw_devices")
        return cursor.fetchone()[0]

    # =========================================================================
    # ServiceDesk Plus Asset Operations
    # =========================================================================

    def store_sdp_assets(self, assets: List[Dict[str, Any]]) -> int:
        """
        Store ServiceDesk Plus assets in database.

        Assets have a flat structure with fields at the top level:
        - name, serial_number, ip_address, mac_address, os, etc.

        Args:
            assets: List of asset dictionaries from SDP Assets API.

        Returns:
            Number of assets stored.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        fetched_at = datetime.now().isoformat()

        counts = {"new": 0, "updated": 0, "total": 0}

        for asset in assets:
            try:
                asset_id = str(asset.get("id", ""))
                if not asset_id:
                    continue

                # Extract product info (manufacturer/model are in product ref)
                product = asset.get("product", {})
                manufacturer = ""
                model = ""
                if isinstance(product, dict):
                    manufacturer = product.get("manufacturer", "") or ""
                    model = product.get("name", "") or ""

                # Extract OS from nested operating_system object
                # Assets API returns: {"operating_system": {"os": "windows 11 ..."}}
                os_info = asset.get("operating_system", {})
                os_value = ""
                if isinstance(os_info, dict):
                    os_value = os_info.get("os", "") or ""

                # Fallback: manufacturer from computer_system if product lacks it
                if not manufacturer:
                    cs_info = asset.get("computer_system", {})
                    if isinstance(cs_info, dict):
                        manufacturer = cs_info.get("system_manufacturer", "") or ""

                # Check if exists (to distinguish insert vs update)
                cursor.execute("SELECT 1 FROM sdp_assets WHERE asset_id = ?", (asset_id,))
                exists = cursor.fetchone() is not None

                if exists:
                    counts["updated"] += 1
                else:
                    counts["new"] += 1

                cursor.execute("""
                    INSERT OR REPLACE INTO sdp_assets
                    (asset_id, name, serial_number, ip_address, mac_address, os, manufacturer, model, raw_json, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    asset_id,
                    asset.get("name", "") or "",
                    asset.get("serial_number", "") or "",
                    asset.get("ip_address", "") or "",
                    asset.get("mac_address", "") or "",
                    os_value,
                    manufacturer,
                    model,
                    json.dumps(asset),
                    fetched_at
                ))
                counts["total"] += 1
            except Exception as e:
                logger.warning(f"Failed to store asset: {e}")

        conn.commit()
        logger.info(f"Stored {counts['total']} SDP assets (New: {counts['new']}, Updated: {counts['updated']})")
        return counts['total']

    def get_sdp_assets(self) -> List[Dict[str, Any]]:
        """Get all stored ServiceDesk Plus assets."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sdp_assets ORDER BY name")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_sdp_asset_raw(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """Get raw JSON data for a specific SDP asset."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT raw_json FROM sdp_assets WHERE asset_id = ?", (asset_id,))
        row = cursor.fetchone()
        return json.loads(row["raw_json"]) if row else None

    def get_sdp_asset_ids(self) -> set:
        """Get set of all stored SDP asset IDs (as strings)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT asset_id FROM sdp_assets")
        return {str(row[0]) for row in cursor.fetchall()}

    # =========================================================================
    # Field Metadata Operations
    # =========================================================================

    def analyze_fields(self, source: str, data: List[Dict[str, Any]]) -> Dict[str, Dict]:
        """
        Analyze and store field metadata from data.

        Args:
            source: Data source ('cw' or 'sdp').
            data: List of dictionaries to analyze.

        Returns:
            Dictionary of field paths to metadata.
        """
        field_stats = {}

        def extract_fields(obj: Any, prefix: str = ""):
            """Recursively extract field paths and values."""
            if isinstance(obj, dict):
                for key, value in obj.items():
                    path = f"{prefix}.{key}" if prefix else key
                    extract_fields(value, path)
            elif isinstance(obj, list) and obj:
                # Sample first item of list
                extract_fields(obj[0], f"{prefix}[]")
            else:
                if prefix not in field_stats:
                    field_stats[prefix] = {
                        "type": type(obj).__name__,
                        "sample": str(obj)[:100] if obj else None,
                        "count": 0
                    }
                field_stats[prefix]["count"] += 1

        for item in data:
            extract_fields(item)

        # Store in database
        conn = self._get_connection()
        cursor = conn.cursor()

        for path, stats in field_stats.items():
            cursor.execute("""
                INSERT OR REPLACE INTO field_metadata
                (source, field_path, field_type, sample_value, occurrence_count)
                VALUES (?, ?, ?, ?, ?)
            """, (source, path, stats["type"], stats["sample"], stats["count"]))

        conn.commit()
        logger.info(f"Analyzed {len(field_stats)} fields from {source}")
        return field_stats

    def get_field_metadata(self, source: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get stored field metadata, optionally filtered by source."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if source:
            cursor.execute(
                "SELECT * FROM field_metadata WHERE source = ? ORDER BY field_path",
                (source,)
            )
        else:
            cursor.execute("SELECT * FROM field_metadata ORDER BY source, field_path")

        return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # Field Mapping Operations
    # =========================================================================

    def save_field_mapping(self, cw_field: str, sdp_field: str, transform: str = None):
        """Save a field mapping between CW and SDP."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO field_mappings
            (cw_field, sdp_field, transform_type, created_at)
            VALUES (?, ?, ?, ?)
        """, (cw_field, sdp_field, transform, datetime.now().isoformat()))
        conn.commit()

    def get_field_mappings(self) -> List[Dict[str, Any]]:
        """Get all saved field mappings."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM field_mappings ORDER BY cw_field")
        return [dict(row) for row in cursor.fetchall()]

    def delete_field_mapping(self, mapping_id: int):
        """Delete a field mapping by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM field_mappings WHERE id = ?", (mapping_id,))
        conn.commit()

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> Dict[str, int]:
        """Get database statistics."""
        conn = self._get_connection()
        cursor = conn.cursor()

        stats = {}
        for table in ["cw_devices", "sdp_assets", "field_metadata", "field_mappings"]:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cursor.fetchone()[0]

        return stats
