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

        # ServiceDesk Plus workstations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sdp_workstations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ci_id TEXT UNIQUE NOT NULL,
                name TEXT,
                serial_number TEXT,
                ip_address TEXT,
                os TEXT,
                manufacturer TEXT,
                model TEXT,
                raw_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
        """)

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

        # Sync history table
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
        stored = 0

        for device in devices:
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO cw_devices
                    (endpoint_id, name, site_name, company_name, os_type, last_seen, raw_json, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    device.get("endpointId", ""),
                    device.get("endpointName", device.get("name", "")),
                    device.get("siteName", ""),
                    device.get("companyName", ""),
                    device.get("osType", ""),
                    device.get("lastSeen", ""),
                    json.dumps(device),
                    fetched_at
                ))
                stored += 1
            except Exception as e:
                logger.warning(f"Failed to store device: {e}")

        conn.commit()
        logger.info(f"Stored {stored} ConnectWise devices")
        return stored

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

    # =========================================================================
    # ServiceDesk Plus Workstation Operations
    # =========================================================================

    def store_sdp_workstations(self, workstations: List[Dict[str, Any]]) -> int:
        """
        Store ServiceDesk Plus workstations in database.

        Args:
            workstations: List of workstation dictionaries from SDP API.

        Returns:
            Number of workstations stored.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        fetched_at = datetime.now().isoformat()
        stored = 0

        for ws in workstations:
            try:
                # Extract CI attributes
                ci_attrs = ws.get("ci_attributes", {})
                model_info = ci_attrs.get("ref_model", {})

                cursor.execute("""
                    INSERT OR REPLACE INTO sdp_workstations
                    (ci_id, name, serial_number, ip_address, os, manufacturer, model, raw_json, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(ws.get("id", "")),
                    ws.get("name", ""),
                    ci_attrs.get("txt_serial_number", ""),
                    ci_attrs.get("txt_ip_address", ""),
                    ci_attrs.get("txt_os", ""),
                    model_info.get("manufacturer", "") if isinstance(model_info, dict) else "",
                    model_info.get("name", "") if isinstance(model_info, dict) else "",
                    json.dumps(ws),
                    fetched_at
                ))
                stored += 1
            except Exception as e:
                logger.warning(f"Failed to store workstation: {e}")

        conn.commit()
        logger.info(f"Stored {stored} ServiceDesk Plus workstations")
        return stored

    def get_sdp_workstations(self) -> List[Dict[str, Any]]:
        """Get all stored ServiceDesk Plus workstations."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sdp_workstations ORDER BY name")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_sdp_workstation_raw(self, ci_id: str) -> Optional[Dict[str, Any]]:
        """Get raw JSON data for a specific SDP workstation."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT raw_json FROM sdp_workstations WHERE ci_id = ?", (ci_id,))
        row = cursor.fetchone()
        return json.loads(row["raw_json"]) if row else None

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
        for table in ["cw_devices", "sdp_workstations", "field_metadata", "field_mappings"]:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cursor.fetchone()[0]

        return stats
