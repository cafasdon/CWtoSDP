"""
================================================================================
Comparison Database for CWtoSDP
================================================================================

This module provides a SQLite database for storing and comparing device data
from ConnectWise RMM and ServiceDesk Plus. It handles:

1. Dynamic table creation based on API response fields
2. Flattening nested JSON into flat columns
3. Tracking which records have been fetched
4. Providing comparison utilities

Database Schema:
----------------
The database contains these main tables:

1. cw_devices_full - ConnectWise devices with ALL fields as columns
   - endpointID: Unique CW identifier
   - friendlyName: Computer name
   - system_serialNumber: Serial number
   - os_product: Operating system
   - raw_json: Original JSON for reference
   - fetched_at: Timestamp of fetch
   - ... (many more dynamically created columns)

2. sdp_workstations_full - SDP workstations with ALL fields as columns
   - sdp_id: Unique SDP identifier
   - name: CI name
   - ci_attributes_txt_serial_number: Serial number
   - raw_json: Original JSON for reference
   - fetched_at: Timestamp of fetch
   - ... (many more dynamically created columns)

3. fetch_tracker - Tracks which records have been fetched
   - source: "cw" or "sdp"
   - record_id: The unique ID
   - fetched_at: Timestamp

Dynamic Column Creation:
------------------------
Unlike traditional databases with fixed schemas, this database creates
columns dynamically based on the data received from APIs. This allows
storing ALL fields without knowing them in advance.

Nested JSON is flattened using underscore notation:
- device.system.serialNumber → system_serialNumber
- device.os.product → os_product

Usage Example:
--------------
    from src.db_compare import CompareDatabase

    db = CompareDatabase()

    # Store CW devices
    db.store_cw_devices_full(cw_devices)

    # Store SDP workstations
    db.store_sdp_workstations_full(sdp_workstations)

    # Compare columns
    comparison = db.get_column_comparison()
    print(f"CW-only columns: {comparison['cw_only']}")

    # Custom query
    results = db.query("SELECT name, system_serialNumber FROM cw_devices_full")

    db.close()
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .logger import get_logger

# Create a logger for this module
logger = get_logger("cwtosdp.db_compare")

# Default database path (relative to project root)
DEFAULT_DB_PATH = Path("./data/cwtosdp_compare.db")


# =============================================================================
# MAIN DATABASE CLASS
# =============================================================================

class CompareDatabase:
    """
    SQLite database for storing and comparing CW and SDP device data.

    This class provides methods for:
    - Storing device data with dynamic column creation
    - Tracking which records have been fetched
    - Comparing columns between CW and SDP tables
    - Running custom SQL queries

    The database uses dynamic schema - columns are created based on the
    fields present in the API responses. This allows storing ALL fields
    without knowing them in advance.

    Attributes:
        db_path: Path to the SQLite database file
        _conn: SQLite connection (lazy-initialized)

    Example:
        >>> db = CompareDatabase()
        >>> db.store_cw_devices_full(devices)
        >>> columns = db.get_cw_columns()
        >>> db.close()
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the comparison database.

        Args:
            db_path: Path to SQLite database file.
                    Defaults to ./data/cwtosdp_compare.db

        Note:
            Creates the data/ directory if it doesn't exist.
            Connection is lazy-initialized on first use.
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Lazy connection - initialized on first use
        self._conn: Optional[sqlite3.Connection] = None
        logger.info(f"Comparison database at {self.db_path}")

    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================

    def _get_connection(self) -> sqlite3.Connection:
        """
        Get or create the SQLite connection.

        Uses lazy initialization - connection is only created when first needed.
        Uses Row factory for dict-like access to query results.

        Returns:
            SQLite connection object
        """
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            # Row factory allows accessing columns by name
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        """
        Close the database connection.

        Should be called when done with the database to release resources.
        """
        if self._conn:
            self._conn.close()
            self._conn = None

    # =========================================================================
    # FETCH TRACKING
    # =========================================================================
    # These methods track which records have been fetched from APIs.
    # This allows resuming interrupted fetches without re-fetching everything.

    def _init_fetch_tracker(self):
        """
        Initialize the fetch_tracker table if it doesn't exist.

        The fetch_tracker table stores:
        - source: "cw" or "sdp"
        - record_id: The unique ID of the record
        - fetched_at: ISO timestamp of when it was fetched
        """
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
        """
        Check if a record has already been fetched.

        Args:
            source: "cw" or "sdp"
            record_id: The unique ID to check

        Returns:
            True if already fetched, False otherwise
        """
        self._init_fetch_tracker()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM fetch_tracker WHERE source = ? AND record_id = ?",
            (source, record_id)
        )
        return cursor.fetchone() is not None

    def mark_fetched(self, source: str, record_id: str):
        """
        Mark a record as fetched.

        Args:
            source: "cw" or "sdp"
            record_id: The unique ID to mark
        """
        self._init_fetch_tracker()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO fetch_tracker (source, record_id, fetched_at) VALUES (?, ?, ?)",
            (source, record_id, datetime.now().isoformat())
        )
        conn.commit()

    def get_fetched_ids(self, source: str) -> set:
        """
        Get all fetched IDs for a source.

        Args:
            source: "cw" or "sdp"

        Returns:
            Set of record IDs that have been fetched
        """
        self._init_fetch_tracker()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT record_id FROM fetch_tracker WHERE source = ?", (source,))
        return {row[0] for row in cursor.fetchall()}

    def get_fetch_stats(self) -> Dict[str, int]:
        """
        Get count of fetched records per source.

        Returns:
            Dictionary like {"cw": 204, "sdp": 150}
        """
        self._init_fetch_tracker()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT source, COUNT(*) FROM fetch_tracker GROUP BY source")
        return {row[0]: row[1] for row in cursor.fetchall()}

    def clear_fetch_tracker(self, source: Optional[str] = None):
        """
        Clear fetch tracker (all or for a specific source).

        Args:
            source: If provided, only clear that source.
                   If None, clear all sources.
        """
        self._init_fetch_tracker()
        conn = self._get_connection()
        cursor = conn.cursor()
        if source:
            cursor.execute("DELETE FROM fetch_tracker WHERE source = ?", (source,))
        else:
            cursor.execute("DELETE FROM fetch_tracker")
        conn.commit()

    def get_incomplete_cw_endpoints(self, all_endpoint_ids: List[str]) -> List[str]:
        """
        Get list of endpoint IDs that need detailed fetch.

        An endpoint needs fetch if:
        1. It doesn't exist in the database at all
        2. It exists but has only basic data (missing detailed fields like friendlyName)

        This enables incremental fetch - only fetch what's missing or incomplete.

        Args:
            all_endpoint_ids: List of all endpoint IDs from API

        Returns:
            List of endpoint IDs that need to be fetched
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Check if table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cw_devices_full'"
        )
        if not cursor.fetchone():
            # Table doesn't exist - need to fetch all
            logger.info(f"No CW data table found - need to fetch all {len(all_endpoint_ids)} endpoints")
            return list(all_endpoint_ids)

        # Check which columns exist (to see if we have detailed data)
        cursor.execute("PRAGMA table_info(cw_devices_full)")
        columns = {row[1] for row in cursor.fetchall()}

        # Key field that indicates detailed data (only present in get_endpoint_details response)
        has_detailed_schema = "friendlyName" in columns

        if not has_detailed_schema:
            # Table exists but has only basic schema - need to refetch all
            logger.info(f"CW table has only basic schema - need to fetch all {len(all_endpoint_ids)} endpoints")
            return list(all_endpoint_ids)

        # Get endpoints that are either missing or have NULL friendlyName (incomplete)
        # We use friendlyName as the indicator of complete data
        incomplete = []

        for endpoint_id in all_endpoint_ids:
            cursor.execute(
                'SELECT friendlyName FROM cw_devices_full WHERE endpointId = ?',
                (endpoint_id,)
            )
            row = cursor.fetchone()

            if row is None:
                # Endpoint not in database
                incomplete.append(endpoint_id)
            elif row[0] is None or row[0] == "":
                # Endpoint has incomplete data (no friendlyName)
                incomplete.append(endpoint_id)

        complete_count = len(all_endpoint_ids) - len(incomplete)
        logger.info(f"CW incremental check: {complete_count} complete, {len(incomplete)} need fetch")
        return incomplete

    def get_incomplete_sdp_workstations(self, all_ws_ids: List[str]) -> List[str]:
        """
        Get list of SDP workstation IDs that need fetch.

        A workstation needs fetch if:
        1. It doesn't exist in the database at all
        2. It exists but has only basic data (missing detailed fields like name)

        This enables incremental fetch - only fetch what's missing or incomplete.

        Args:
            all_ws_ids: List of all workstation IDs from API

        Returns:
            List of workstation IDs that need to be fetched
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Check if table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sdp_workstations_full'"
        )
        if not cursor.fetchone():
            # Table doesn't exist - need to fetch all
            logger.info(f"No SDP data table found - need to fetch all {len(all_ws_ids)} workstations")
            return list(all_ws_ids)

        # Check which columns exist (to see if we have detailed data)
        cursor.execute("PRAGMA table_info(sdp_workstations_full)")
        columns = {row[1] for row in cursor.fetchall()}

        # Key field that indicates detailed data
        has_detailed_schema = "name" in columns

        if not has_detailed_schema:
            # Table exists but has only basic schema - need to refetch all
            logger.info(f"SDP table has only basic schema - need to fetch all {len(all_ws_ids)} workstations")
            return list(all_ws_ids)

        # Get workstations that are either missing or have NULL name (incomplete)
        incomplete = []

        for ws_id in all_ws_ids:
            cursor.execute(
                'SELECT name FROM sdp_workstations_full WHERE id = ? OR sdp_id = ?',
                (ws_id, ws_id)
            )
            row = cursor.fetchone()

            if row is None:
                # Workstation not in database
                incomplete.append(ws_id)
            elif row[0] is None or row[0] == "":
                # Workstation has incomplete data (no name)
                incomplete.append(ws_id)

        complete_count = len(all_ws_ids) - len(incomplete)
        logger.info(f"SDP incremental check: {complete_count} complete, {len(incomplete)} need fetch")
        return incomplete

    def get_sdp_workstation_count(self) -> int:
        """
        Get count of SDP workstations with complete data.

        Returns:
            Number of workstations with complete detailed data
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Check if table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sdp_workstations_full'"
        )
        if not cursor.fetchone():
            return 0

        # Count workstations with non-null name
        cursor.execute(
            "SELECT COUNT(*) FROM sdp_workstations_full WHERE name IS NOT NULL AND name != ''"
        )
        return cursor.fetchone()[0]

    def get_cw_endpoint_count(self) -> int:
        """
        Get count of CW endpoints with complete data.

        Returns:
            Number of endpoints with complete detailed data
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Check if table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cw_devices_full'"
        )
        if not cursor.fetchone():
            return 0

        # Check if friendlyName column exists
        cursor.execute("PRAGMA table_info(cw_devices_full)")
        columns = {row[1] for row in cursor.fetchall()}

        if "friendlyName" not in columns:
            return 0  # No detailed data

        # Count endpoints with non-null friendlyName
        cursor.execute(
            "SELECT COUNT(*) FROM cw_devices_full WHERE friendlyName IS NOT NULL AND friendlyName != ''"
        )
        return cursor.fetchone()[0]

    # =========================================================================
    # DATA TRANSFORMATION HELPERS
    # =========================================================================

    def _flatten_dict(self, d: Dict, prefix: str = "") -> Dict[str, Any]:
        """
        Flatten a nested dictionary into underscore-separated keys.

        Converts nested structures like:
            {"system": {"serialNumber": "ABC123"}}
        Into flat structures like:
            {"system_serialNumber": "ABC123"}

        Lists are converted to JSON strings.

        Args:
            d: Dictionary to flatten
            prefix: Prefix for keys (used in recursion)

        Returns:
            Flattened dictionary with sanitized keys
        """
        items = {}
        for key, value in d.items():
            # Build new key with prefix
            new_key = f"{prefix}_{key}" if prefix else key
            # Sanitize key for SQLite column name (no dots, dashes, spaces)
            new_key = new_key.replace(".", "_").replace("-", "_").replace(" ", "_")

            if isinstance(value, dict):
                # Recursively flatten nested dicts
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

        Scans all records to find all unique field names, then creates
        a table with columns for each field. All columns are TEXT type
        for flexibility.

        Args:
            table_name: Name of the table to create
            records: List of dictionaries to analyze

        Returns:
            Set of all column names created
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
        # Use row_id instead of id to avoid conflicts with data that has an 'id' field
        columns = ["row_id INTEGER PRIMARY KEY AUTOINCREMENT"]
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
        # Note: endpointId column is the unique key from the API
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cw_devices_full (
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpointId TEXT UNIQUE,
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
