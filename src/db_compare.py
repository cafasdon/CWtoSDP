"""
Comparison Database for CWtoSDP.

Creates normalized tables with ALL fields from ConnectWise and ServiceDesk Plus
for direct 1:1 field comparison via SQL queries.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .logger import get_logger

logger = get_logger("cwtosdp.db_compare")

DEFAULT_DB_PATH = Path("./data/cwtosdp_compare.db")


class CompareDatabase:
    """
    Comparison database with full field extraction from both sources.

    Creates two main tables:
    - cw_devices_full: All ConnectWise endpoint fields flattened
    - sdp_workstations_full: All ServiceDesk Plus CI fields flattened
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        logger.info(f"Comparison database at {self.db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _init_fetch_tracker(self):
        """Initialize table to track which IDs have been fetched."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fetch_tracker (
                source TEXT NOT NULL,
                record_id TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (source, record_id)
            )
        """)
        conn.commit()

    def is_fetched(self, source: str, record_id: str) -> bool:
        """Check if a record has already been fetched."""
        self._init_fetch_tracker()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM fetch_tracker WHERE source = ? AND record_id = ?",
            (source, record_id)
        )
        return cursor.fetchone() is not None

    def mark_fetched(self, source: str, record_id: str):
        """Mark a record as fetched."""
        self._init_fetch_tracker()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO fetch_tracker (source, record_id, fetched_at) VALUES (?, ?, ?)",
            (source, record_id, datetime.now().isoformat())
        )
        conn.commit()

    def get_fetched_ids(self, source: str) -> set:
        """Get all fetched IDs for a source."""
        self._init_fetch_tracker()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT record_id FROM fetch_tracker WHERE source = ?", (source,))
        return {row[0] for row in cursor.fetchall()}

    def get_fetch_stats(self) -> Dict[str, int]:
        """Get count of fetched records per source."""
        self._init_fetch_tracker()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT source, COUNT(*) FROM fetch_tracker GROUP BY source")
        return {row[0]: row[1] for row in cursor.fetchall()}

    def clear_fetch_tracker(self, source: Optional[str] = None):
        """Clear fetch tracker (all or for a specific source)."""
        self._init_fetch_tracker()
        conn = self._get_connection()
        cursor = conn.cursor()
        if source:
            cursor.execute("DELETE FROM fetch_tracker WHERE source = ?", (source,))
        else:
            cursor.execute("DELETE FROM fetch_tracker")
        conn.commit()

    def _flatten_dict(self, d: Dict, prefix: str = "") -> Dict[str, Any]:
        """Flatten a nested dictionary into dot-notation keys."""
        items = {}
        for key, value in d.items():
            new_key = f"{prefix}_{key}" if prefix else key
            # Sanitize key for SQLite column name
            new_key = new_key.replace(".", "_").replace("-", "_").replace(" ", "_")

            if isinstance(value, dict):
                items.update(self._flatten_dict(value, new_key))
            elif isinstance(value, list):
                # Store lists as JSON strings
                items[new_key] = json.dumps(value) if value else None
            else:
                items[new_key] = value
        return items

    def _create_table_from_data(self, table_name: str, records: List[Dict]) -> set:
        """
        Dynamically create a table based on all fields found in records.
        Returns set of all column names.
        """
        # Collect all unique keys from all records
        all_keys = set()
        for record in records:
            flattened = self._flatten_dict(record)
            all_keys.update(flattened.keys())

        conn = self._get_connection()
        cursor = conn.cursor()

        # Drop existing table
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")

        # Create table with all columns as TEXT (flexible for comparison)
        columns = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
        for key in sorted(all_keys):
            safe_key = key.replace("'", "").replace('"', "")
            columns.append(f'"{safe_key}" TEXT')
        columns.append("raw_json TEXT")
        columns.append("fetched_at TEXT")

        create_sql = f"CREATE TABLE {table_name} ({', '.join(columns)})"
        cursor.execute(create_sql)
        conn.commit()

        logger.info(f"Created table {table_name} with {len(all_keys)} columns")
        return all_keys

    def store_cw_devices_full(self, devices: List[Dict[str, Any]]) -> int:
        """
        Store ConnectWise devices with ALL fields as columns.

        Args:
            devices: List of DETAILED device dictionaries (from get_endpoint_details).

        Returns:
            Number of devices stored.
        """
        if not devices:
            return 0

        # Create table dynamically based on data
        all_keys = self._create_table_from_data("cw_devices_full", devices)

        conn = self._get_connection()
        cursor = conn.cursor()
        fetched_at = datetime.now().isoformat()
        stored = 0

        for device in devices:
            try:
                flattened = self._flatten_dict(device)

                # Build INSERT statement
                cols = list(flattened.keys()) + ["raw_json", "fetched_at"]
                placeholders = ["?"] * len(cols)
                values = list(flattened.values()) + [json.dumps(device), fetched_at]

                # Convert non-string values to strings
                values = [str(v) if v is not None and not isinstance(v, str) else v for v in values]

                col_str = '", "'.join(cols)
                sql = f'INSERT INTO cw_devices_full ("{col_str}") VALUES ({", ".join(placeholders)})'
                cursor.execute(sql, values)
                stored += 1
            except Exception as e:
                logger.warning(f"Failed to store CW device: {e}")

        conn.commit()
        logger.info(f"Stored {stored} ConnectWise devices with {len(all_keys)} fields each")
        return stored

    def store_cw_device_single(self, device: Dict[str, Any], endpoint_id: str) -> bool:
        """
        Store a single ConnectWise device and mark it as fetched.
        Uses INSERT OR REPLACE to handle existing records.

        Args:
            device: Device data dictionary.
            endpoint_id: The unique endpoint ID.

        Returns:
            True if stored successfully, False otherwise.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Ensure table exists with at least basic columns
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cw_devices_full (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpointID TEXT UNIQUE,
                raw_json TEXT,
                fetched_at TEXT
            )
        """)

        try:
            flattened = self._flatten_dict(device)
            fetched_at = datetime.now().isoformat()

            # Add missing columns dynamically
            for key in flattened.keys():
                try:
                    cursor.execute(f'ALTER TABLE cw_devices_full ADD COLUMN "{key}" TEXT')
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # Build UPSERT statement
            cols = list(flattened.keys()) + ["raw_json", "fetched_at"]
            placeholders = ["?"] * len(cols)
            values = list(flattened.values()) + [json.dumps(device), fetched_at]
            values = [str(v) if v is not None and not isinstance(v, str) else v for v in values]

            col_str = '", "'.join(cols)
            sql = f'INSERT OR REPLACE INTO cw_devices_full ("{col_str}") VALUES ({", ".join(placeholders)})'
            cursor.execute(sql, values)
            conn.commit()

            # Mark as fetched
            self.mark_fetched("cw", endpoint_id)
            return True
        except Exception as e:
            logger.warning(f"Failed to store CW device {endpoint_id}: {e}")
            return False

    def store_sdp_workstation_single(self, workstation: Dict[str, Any], ws_id: str) -> bool:
        """
        Store a single SDP workstation and mark it as fetched.

        Args:
            workstation: Workstation data dictionary.
            ws_id: The unique workstation ID.

        Returns:
            True if stored successfully, False otherwise.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Ensure table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sdp_workstations_full (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sdp_id TEXT UNIQUE,
                raw_json TEXT,
                fetched_at TEXT
            )
        """)

        try:
            flattened = self._flatten_dict(workstation)
            fetched_at = datetime.now().isoformat()

            # Add missing columns dynamically
            for key in flattened.keys():
                try:
                    cursor.execute(f'ALTER TABLE sdp_workstations_full ADD COLUMN "{key}" TEXT')
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # Build UPSERT statement
            cols = list(flattened.keys()) + ["raw_json", "fetched_at"]
            placeholders = ["?"] * len(cols)
            values = list(flattened.values()) + [json.dumps(workstation), fetched_at]
            values = [str(v) if v is not None and not isinstance(v, str) else v for v in values]

            col_str = '", "'.join(cols)
            sql = f'INSERT OR REPLACE INTO sdp_workstations_full ("{col_str}") VALUES ({", ".join(placeholders)})'
            cursor.execute(sql, values)
            conn.commit()

            # Mark as fetched
            self.mark_fetched("sdp", ws_id)
            return True
        except Exception as e:
            logger.warning(f"Failed to store SDP workstation {ws_id}: {e}")
            return False

    def store_sdp_workstations_full(self, workstations: List[Dict[str, Any]]) -> int:
        """
        Store ServiceDesk Plus workstations with ALL fields as columns.

        Args:
            workstations: List of workstation dictionaries from SDP API.

        Returns:
            Number of workstations stored.
        """
        if not workstations:
            return 0

        # Create table dynamically based on data
        all_keys = self._create_table_from_data("sdp_workstations_full", workstations)

        conn = self._get_connection()
        cursor = conn.cursor()
        fetched_at = datetime.now().isoformat()
        stored = 0

        for ws in workstations:
            try:
                flattened = self._flatten_dict(ws)

                # Build INSERT statement
                cols = list(flattened.keys()) + ["raw_json", "fetched_at"]
                placeholders = ["?"] * len(cols)
                values = list(flattened.values()) + [json.dumps(ws), fetched_at]

                # Convert non-string values to strings
                values = [str(v) if v is not None and not isinstance(v, str) else v for v in values]

                col_str = '", "'.join(cols)
                sql = f'INSERT INTO sdp_workstations_full ("{col_str}") VALUES ({", ".join(placeholders)})'
                cursor.execute(sql, values)
                stored += 1
            except Exception as e:
                logger.warning(f"Failed to store SDP workstation: {e}")

        conn.commit()
        logger.info(f"Stored {stored} SDP workstations with {len(all_keys)} fields each")
        return stored

    def get_cw_columns(self) -> List[str]:
        """Get all column names from CW table."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(cw_devices_full)")
        return [row[1] for row in cursor.fetchall()]

    def get_sdp_columns(self) -> List[str]:
        """Get all column names from SDP table."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(sdp_workstations_full)")
        return [row[1] for row in cursor.fetchall()]

    def get_column_comparison(self) -> Dict[str, Any]:
        """
        Compare columns between CW and SDP tables.

        Returns dictionary with:
        - cw_only: Columns only in ConnectWise
        - sdp_only: Columns only in ServiceDesk Plus
        - common: Columns in both (potential matches)
        """
        cw_cols = set(self.get_cw_columns())
        sdp_cols = set(self.get_sdp_columns())

        # Remove internal columns
        internal = {"id", "raw_json", "fetched_at"}
        cw_cols -= internal
        sdp_cols -= internal

        return {
            "cw_only": sorted(cw_cols - sdp_cols),
            "sdp_only": sorted(sdp_cols - cw_cols),
            "common": sorted(cw_cols & sdp_cols),
            "cw_count": len(cw_cols),
            "sdp_count": len(sdp_cols)
        }

    def get_sample_values(self, table: str, column: str, limit: int = 5) -> List[str]:
        """Get sample values from a column."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(f'SELECT DISTINCT "{column}" FROM {table} WHERE "{column}" IS NOT NULL LIMIT ?', (limit,))
        return [row[0] for row in cursor.fetchall()]

    def query(self, sql: str) -> List[Dict]:
        """Execute a custom SQL query."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(sql)
        return [dict(row) for row in cursor.fetchall()]
