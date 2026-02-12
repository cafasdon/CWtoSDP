"""
================================================================================
Sync GUI for CWtoSDP - Main User Interface
================================================================================

This module provides the main graphical user interface for the CWtoSDP
integration tool. It allows users to:

1. Preview sync operations (what will be created/updated)
2. View field mappings between ConnectWise and ServiceDesk Plus
3. See category breakdown of devices
4. Execute sync operations with safety controls
5. View sync results and revert changes if needed

GUI Layout:
-----------
+------------------------------------------------------------------+
|  Summary Cards (Total, Creates, Updates)  |  Sync Controls       |
+------------------------------------------------------------------+
|  Notebook Tabs:                                                   |
|  +------------------------------------------------------------+  |
|  | Sync Preview | By Category | Field Mapping | Results       |  |
|  +------------------------------------------------------------+  |
|  |                                                             |  |
|  |  Main content area with treeviews and data                 |  |
|  |                                                             |  |
|  +------------------------------------------------------------+  |
+------------------------------------------------------------------+

Key Features:
-------------
- Checkbox selection for individual items to sync
- Dry run mode (default) prevents accidental changes
- Real-time progress updates during sync
- Results tab shows what was created/updated
- Revert functionality to undo changes
- Settings dialog for credential configuration

Threading:
----------
Sync operations run in background threads to keep the GUI responsive.
Progress updates are sent to the main thread via root.after().

Usage:
------
    from src.sync_gui import launch_sync_gui
    launch_sync_gui()

Or via command line:
    python -m src.main --sync
"""

import json
import sqlite3
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Dict, List, Optional

from .db import DEFAULT_DB_PATH
from .logger import get_logger
from .field_mapper import DeviceClassifier
from .sync_engine import SyncEngine, SyncAction, SyncItem

# Create logger for this module
logger = get_logger("cwtosdp.sync_gui")


# =============================================================================
# HELPER WIDGETS
# =============================================================================

class ScrollableTreeview(ttk.Frame):
    """
    A Treeview widget with both horizontal and vertical scrollbars.

    This custom widget wraps a ttk.Treeview in a canvas with scrollbars
    to allow horizontal scrolling of wide tables. Standard Treeview
    only supports vertical scrolling.

    Attributes:
        tree: The underlying ttk.Treeview widget
        canvas: Canvas for horizontal scrolling
        h_scroll: Horizontal scrollbar
        v_scroll: Vertical scrollbar

    Example:
        >>> columns = ["name", "type", "action"]
        >>> headings = ["Name", "Type", "Action"]
        >>> widths = [200, 100, 100]
        >>> tree = ScrollableTreeview(parent, columns, headings, widths)
        >>> tree.tree.insert("", "end", values=("Device1", "Laptop", "CREATE"))
    """

    def __init__(self, parent, columns, headings, widths=None, **kwargs):
        """
        Initialize the scrollable treeview.

        Args:
            parent: Parent widget
            columns: List of column identifiers
            headings: List of column header text
            widths: Optional list of column widths (default: 120)
            **kwargs: Additional arguments passed to Treeview
        """
        super().__init__(parent)

        # Create canvas for horizontal scrolling
        self.canvas = tk.Canvas(self, highlightthickness=0)
        # Horizontal scrollbar at bottom
        self.h_scroll = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.canvas.xview)
        # Vertical scrollbar at right
        self.v_scroll = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)

        # Create inner frame to hold the treeview
        self.inner_frame = ttk.Frame(self.canvas)

        # Create the actual treeview widget
        self.tree = ttk.Treeview(self.inner_frame, columns=columns, show="headings", **kwargs)

        # Configure each column with heading and width
        for i, col in enumerate(columns):
            heading = headings[i] if i < len(headings) else col
            width = widths[i] if widths and i < len(widths) else 120
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=width, minwidth=width)

        # Vertical scrollbar for the treeview itself
        tree_scroll = ttk.Scrollbar(self.inner_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        # Pack treeview and its scrollbar
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Create window in canvas to hold the inner frame
        self.canvas.create_window((0, 0), window=self.inner_frame, anchor="nw")

        # Configure canvas horizontal scrolling
        self.canvas.configure(xscrollcommand=self.h_scroll.set)
        # Update scroll region when frame size changes
        self.inner_frame.bind("<Configure>", self._on_frame_configure)

        # Pack all components
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Configure row colors for different actions
        self.tree.tag_configure("create", background="#d4edda")  # Light green for CREATE
        self.tree.tag_configure("update", background="#cce5ff")  # Light blue for UPDATE

    def _on_frame_configure(self, event):
        """Update canvas scroll region when frame size changes."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))


# =============================================================================
# MAIN GUI CLASS
# =============================================================================

class SyncGUI:
    """
    Main Sync Manager GUI application.

    This class creates and manages the main window for the CWtoSDP
    synchronization tool. It provides:

    - Sync preview showing all devices and their sync status
    - Category breakdown of devices
    - Field mapping reference
    - Sync execution with dry run mode
    - Results viewing and revert functionality
    - Settings dialog for credential configuration

    Attributes:
        root: The main Tk window
        engine: SyncEngine instance for building sync plans
        items: List of SyncItem objects from the sync preview
        summary: Dictionary with sync statistics
        sync_in_progress: Flag to prevent concurrent syncs
        notebook: Tabbed interface container
        preview_tree: Treeview showing sync preview
        category_tree: Treeview showing category breakdown
        mapping_tree: Treeview showing field mappings

    Example:
        >>> gui = SyncGUI()
        >>> gui.run()  # Starts the main event loop
    """

    def __init__(self):
        """
        Initialize the Sync Manager GUI.

        Creates the main window, initializes the sync engine,
        and loads data from the database.
        """
        # Create main window
        self.root = tk.Tk()
        self.root.title("CWtoSDP - Sync Manager")
        self.root.geometry("1600x900")  # Default size
        self.root.minsize(1400, 800)    # Minimum size

        # Initialize sync engine (reads from SQLite database)
        self.engine = SyncEngine()

        # Data storage
        self.items: List[SyncItem] = []  # Sync items from preview
        self.summary: Dict = {}           # Summary statistics
        self.sync_in_progress = False     # Prevent concurrent syncs

        # Build the GUI layout
        self._create_layout()
        # Load data from database
        self._load_data()

    # =========================================================================
    # LAYOUT CREATION
    # =========================================================================

    def _create_layout(self):
        """
        Create the main GUI layout.

        Layout structure:
        - Top: Summary section with stats and controls
        - Middle: Notebook with tabs for different views
        """
        # Main container with padding
        main = ttk.Frame(self.root, padding="10")
        main.pack(fill=tk.BOTH, expand=True)

        # Top section: Summary cards and sync controls
        self._create_summary_section(main)

        # Middle section: Tabbed notebook
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        # Tab 1: Sync Preview - shows all devices with sync status
        self.preview_frame = ttk.Frame(self.notebook, padding="5")
        self.notebook.add(self.preview_frame, text="Sync Preview")
        self._create_preview_tab()

        # Tab 2: By Category - shows device counts by category
        self.category_frame = ttk.Frame(self.notebook, padding="5")
        self.notebook.add(self.category_frame, text="By Category")
        self._create_category_tab()

        # Tab 3: Diff View - side-by-side comparison of CW vs SDP data
        self.diff_frame = ttk.Frame(self.notebook, padding="5")
        self.notebook.add(self.diff_frame, text="Diff View")
        self._create_diff_tab()

        # Tab 4: Full DB Comparison - shows ALL records from both systems
        self.fulldb_frame = ttk.Frame(self.notebook, padding="5")
        self.notebook.add(self.fulldb_frame, text="Full DB")
        self._create_fulldb_tab()

        # Tab 5: Field Mapping - shows CW to SDP field mappings
        self.mapping_frame = ttk.Frame(self.notebook, padding="5")
        self.notebook.add(self.mapping_frame, text="Field Mapping")
        self._create_mapping_tab()

    def _create_summary_section(self, parent):
        """
        Create the summary section at the top of the window.

        Contains:
        - Title label
        - Sync controls (dry run checkbox, sync button, revert button)
        - Data refresh buttons
        - Settings button

        Args:
            parent: Parent widget to add the section to
        """
        summary_frame = ttk.Frame(parent)
        summary_frame.pack(fill=tk.X, pady=(0, 10))

        # Title on the left
        ttk.Label(summary_frame, text="CW → SDP Sync Manager",
                  font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)

        # Controls on the right
        controls_frame = ttk.Frame(summary_frame)
        controls_frame.pack(side=tk.RIGHT)

        # -----------------------------------------------------------------
        # Row 1: Sync controls
        # -----------------------------------------------------------------
        sync_row = ttk.Frame(controls_frame)
        sync_row.pack(fill=tk.X, pady=2)

        # Dry run checkbox - unchecked by default (dry run mode)
        # When checked, enables real sync operations
        self.real_sync_var = tk.BooleanVar(value=False)
        self.real_sync_check = ttk.Checkbutton(
            sync_row, text="Enable Real Sync", variable=self.real_sync_var,
            command=self._on_real_sync_toggle
        )
        self.real_sync_check.pack(side=tk.LEFT, padx=5)

        # Sync button - text changes based on dry run mode
        self.sync_btn = ttk.Button(sync_row, text="🔍 Preview Sync (Dry Run)",
                                   command=self._execute_sync)
        self.sync_btn.pack(side=tk.LEFT, padx=5)

        # Revert button - enabled after a successful sync
        self.revert_btn = ttk.Button(sync_row, text="↩️ Revert Last Sync",
                                     command=self._revert_sync, state=tk.DISABLED)
        self.revert_btn.pack(side=tk.LEFT, padx=5)

        # -----------------------------------------------------------------
        # Row 2: Data refresh controls
        # -----------------------------------------------------------------
        refresh_row = ttk.Frame(controls_frame)
        refresh_row.pack(fill=tk.X, pady=2)

        # Refresh buttons for fetching fresh data from APIs
        ttk.Button(refresh_row, text="🔄 Refresh CW Data",
                   command=self._refresh_cw_data).pack(side=tk.LEFT, padx=5)
        ttk.Button(refresh_row, text="🔄 Refresh SDP Data",
                   command=self._refresh_sdp_data).pack(side=tk.LEFT, padx=5)
        # Check for orphaned entries in database
        ttk.Button(refresh_row, text="🔍 Check Orphans",
                   command=self._check_orphans).pack(side=tk.LEFT, padx=5)
        # Open settings dialog for credential configuration
        ttk.Button(refresh_row, text="⚙️ Settings",
                   command=self._open_settings).pack(side=tk.LEFT, padx=5)
        # Open help/automation guide
        ttk.Button(refresh_row, text="❓ Help",
                   command=self._open_help).pack(side=tk.LEFT, padx=5)

        # Stats labels will be added after data loads
        self.stats_frame = ttk.Frame(summary_frame)
        self.stats_frame.pack(side=tk.RIGHT, padx=20)

    def _on_real_sync_toggle(self):
        """Update sync button text and ensure it's enabled (called after sync too)."""
        if self.real_sync_var.get():
            self.sync_btn.config(text="⚠️ Execute Real Sync", state=tk.NORMAL)
        else:
            self.sync_btn.config(text="🔍 Preview Sync (Dry Run)", state=tk.NORMAL)

    def _create_preview_tab(self):
        """Create the sync preview tab with ALL fields visible and selection support."""
        # Filter and selection controls frame
        filter_frame = ttk.Frame(self.preview_frame)
        filter_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(filter_frame, text="Filter by Action:").pack(side=tk.LEFT)
        self.action_filter = ttk.Combobox(filter_frame, values=["All", "CREATE", "UPDATE"],
                                           state="readonly", width=15)
        self.action_filter.set("All")
        self.action_filter.pack(side=tk.LEFT, padx=5)
        self.action_filter.bind("<<ComboboxSelected>>", self._apply_filter)

        ttk.Label(filter_frame, text="Category:").pack(side=tk.LEFT, padx=(20, 0))
        self.category_filter = ttk.Combobox(filter_frame, state="readonly", width=20)
        self.category_filter.pack(side=tk.LEFT, padx=5)
        self.category_filter.bind("<<ComboboxSelected>>", self._apply_filter)

        # Selection controls - grouped in a labeled frame for clarity
        ttk.Separator(filter_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)
        ttk.Label(filter_frame, text="Selection:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(filter_frame, text="✓ All", command=self._select_all, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(filter_frame, text="✗ None", command=self._select_none, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(filter_frame, text="✓ Filtered", command=self._select_filtered).pack(side=tk.LEFT, padx=2)
        ttk.Button(filter_frame, text="✗ Filtered", command=self._deselect_filtered).pack(side=tk.LEFT, padx=2)
        ttk.Button(filter_frame, text="✓ CREATE", command=self._select_create_only).pack(side=tk.LEFT, padx=2)

        # Selection count label
        self.selection_label = ttk.Label(filter_frame, text="Selected: 0", font=("Segoe UI", 9, "bold"))
        self.selection_label.pack(side=tk.LEFT, padx=10)

        # Info label
        ttk.Label(filter_frame, text="(Scroll right to see all SDP fields →)",
                  foreground="gray").pack(side=tk.RIGHT)

        # Tree container with scrollbars
        tree_container = ttk.Frame(self.preview_frame)
        tree_container.pack(fill=tk.BOTH, expand=True)

        # Define ALL columns including checkbox and SDP fields
        columns = ("selected", "cw_name", "category", "action", "sdp_ci_type", "match_reason",
                   "name", "serial_number", "os", "manufacturer", "ip_address", "mac_address")
        headings = ("✓", "CW Device", "Category", "Action", "SDP CI Type", "Match Reason",
                    "→ SDP Name", "→ Serial #", "→ OS", "→ Manufacturer", "→ IP Address", "→ MAC Address")
        widths = (30, 200, 110, 70, 160, 200, 200, 150, 200, 150, 120, 180)

        # Create treeview with both scrollbars
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings", height=25)

        for i, col in enumerate(columns):
            self.tree.heading(col, text=headings[i])
            self.tree.column(col, width=widths[i], minwidth=widths[i])

        # Scrollbars
        v_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.tree.yview)
        h_scroll = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        # Grid layout for scrollbars
        self.tree.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        # Bind selection events:
        # - Single click on checkbox column (first column) toggles selection
        # - Single click anywhere on row also toggles (more intuitive)
        # - Space key toggles currently highlighted items
        # - Double-click still works for compatibility
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._toggle_selected_items)

        # Configure tags for colors
        # CREATE items: Green tones (new items to be added)
        self.tree.tag_configure("create", background="#d4edda")  # Light green - not selected
        self.tree.tag_configure("selected_create", background="#28a745", foreground="white")  # Dark green - selected

        # UPDATE items: Blue/cyan tones (existing items to be modified)
        self.tree.tag_configure("update", background="#cce5ff")  # Light blue - not selected
        self.tree.tag_configure("selected_update", background="#007bff", foreground="white")  # Dark blue - selected

        # Track selected items by their unique ID (cw_id)
        self.selected_items = set()

        # Track currently visible (filtered) items
        self.filtered_item_ids = set()

    def _create_category_tab(self):
        """Create category breakdown tab as proper GUI."""
        # Split into two panes
        paned = ttk.PanedWindow(self.category_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Left: Category summary tree
        left_frame = ttk.LabelFrame(paned, text="Categories", padding=5)
        paned.add(left_frame, weight=1)

        cat_columns = ("category", "total", "create", "update", "sdp_type")
        self.cat_tree = ttk.Treeview(left_frame, columns=cat_columns, show="headings", height=10)

        self.cat_tree.heading("category", text="Category")
        self.cat_tree.heading("total", text="Total")
        self.cat_tree.heading("create", text="Create")
        self.cat_tree.heading("update", text="Update")
        self.cat_tree.heading("sdp_type", text="SDP CI Type")

        self.cat_tree.column("category", width=120)
        self.cat_tree.column("total", width=60, anchor="center")
        self.cat_tree.column("create", width=60, anchor="center")
        self.cat_tree.column("update", width=60, anchor="center")
        self.cat_tree.column("sdp_type", width=180)

        cat_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.cat_tree.yview)
        self.cat_tree.configure(yscrollcommand=cat_scroll.set)

        self.cat_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cat_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Bind selection to show devices in that category
        self.cat_tree.bind("<<TreeviewSelect>>", self._on_category_select)

        # Right: Devices in selected category
        right_frame = ttk.LabelFrame(paned, text="Devices in Category", padding=5)
        paned.add(right_frame, weight=2)

        dev_columns = ("name", "action", "match_reason")
        self.cat_device_tree = ttk.Treeview(right_frame, columns=dev_columns, show="headings", height=15)

        self.cat_device_tree.heading("name", text="Device Name")
        self.cat_device_tree.heading("action", text="Action")
        self.cat_device_tree.heading("match_reason", text="Match/Notes")

        self.cat_device_tree.column("name", width=250)
        self.cat_device_tree.column("action", width=80)
        self.cat_device_tree.column("match_reason", width=300)

        dev_scroll = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.cat_device_tree.yview)
        self.cat_device_tree.configure(yscrollcommand=dev_scroll.set)

        self.cat_device_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        dev_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Tags for coloring (consistent with main tree)
        self.cat_device_tree.tag_configure("create", background="#d4edda")  # Light green
        self.cat_device_tree.tag_configure("update", background="#cce5ff")  # Light blue

    def _create_diff_tab(self):
        """
        Create the Diff View tab with side-by-side comparison.

        Layout:
        - Top: Device list with action filter
        - Bottom: Side-by-side comparison panel (CW left, SDP right)
        """
        # Main paned window - top for device list, bottom for diff detail
        paned = ttk.PanedWindow(self.diff_frame, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # =====================================================================
        # TOP: Device list with filters
        # =====================================================================
        top_frame = ttk.Frame(paned)
        paned.add(top_frame, weight=1)

        # Filter row
        filter_frame = ttk.Frame(top_frame)
        filter_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(filter_frame, text="Filter:").pack(side=tk.LEFT)
        self.diff_action_filter = ttk.Combobox(
            filter_frame, values=["All", "UPDATE Only", "CREATE Only"],
            state="readonly", width=15
        )
        self.diff_action_filter.set("All")
        self.diff_action_filter.pack(side=tk.LEFT, padx=5)
        self.diff_action_filter.bind("<<ComboboxSelected>>", self._apply_diff_filter)

        ttk.Label(filter_frame, text="(Select a device to see field comparison below)",
                  foreground="gray").pack(side=tk.RIGHT)

        # Device list tree
        device_frame = ttk.Frame(top_frame)
        device_frame.pack(fill=tk.BOTH, expand=True)

        diff_columns = ("action", "cw_name", "sdp_name", "match_reason", "changes")
        diff_headings = ("Action", "CW Device Name", "SDP CI Name", "Match Reason", "Changes")
        diff_widths = (80, 250, 250, 200, 300)

        self.diff_device_tree = ttk.Treeview(
            device_frame, columns=diff_columns, show="headings", height=10
        )
        for i, col in enumerate(diff_columns):
            self.diff_device_tree.heading(col, text=diff_headings[i])
            self.diff_device_tree.column(col, width=diff_widths[i], minwidth=diff_widths[i])

        # Scrollbars
        diff_v_scroll = ttk.Scrollbar(device_frame, orient=tk.VERTICAL,
                                       command=self.diff_device_tree.yview)
        self.diff_device_tree.configure(yscrollcommand=diff_v_scroll.set)

        self.diff_device_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        diff_v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Color tags
        self.diff_device_tree.tag_configure("create", background="#d4edda")
        self.diff_device_tree.tag_configure("update", background="#cce5ff")

        # Bind selection event
        self.diff_device_tree.bind("<<TreeviewSelect>>", self._on_diff_device_select)

        # =====================================================================
        # BOTTOM: Side-by-side comparison panel
        # =====================================================================
        bottom_frame = ttk.LabelFrame(paned, text="Field Comparison", padding=5)
        paned.add(bottom_frame, weight=2)

        # Two-column layout for side-by-side
        compare_frame = ttk.Frame(bottom_frame)
        compare_frame.pack(fill=tk.BOTH, expand=True)

        # Left side: ConnectWise data
        cw_frame = ttk.LabelFrame(compare_frame, text="ConnectWise (Source)", padding=5)
        cw_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        cw_columns = ("field", "value")
        self.diff_cw_tree = ttk.Treeview(cw_frame, columns=cw_columns, show="headings", height=12)
        self.diff_cw_tree.heading("field", text="Field")
        self.diff_cw_tree.heading("value", text="Value")
        self.diff_cw_tree.column("field", width=150)
        self.diff_cw_tree.column("value", width=250)

        cw_scroll = ttk.Scrollbar(cw_frame, orient=tk.VERTICAL, command=self.diff_cw_tree.yview)
        self.diff_cw_tree.configure(yscrollcommand=cw_scroll.set)
        self.diff_cw_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cw_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Right side: ServiceDesk Plus data
        sdp_frame = ttk.LabelFrame(compare_frame, text="ServiceDesk Plus (Target)", padding=5)
        sdp_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        self.diff_sdp_tree = ttk.Treeview(sdp_frame, columns=cw_columns, show="headings", height=12)
        self.diff_sdp_tree.heading("field", text="Field")
        self.diff_sdp_tree.heading("value", text="Value")
        self.diff_sdp_tree.column("field", width=150)
        self.diff_sdp_tree.column("value", width=250)

        sdp_scroll = ttk.Scrollbar(sdp_frame, orient=tk.VERTICAL, command=self.diff_sdp_tree.yview)
        self.diff_sdp_tree.configure(yscrollcommand=sdp_scroll.set)
        self.diff_sdp_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sdp_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Configure tags for highlighting differences
        for tree in [self.diff_cw_tree, self.diff_sdp_tree]:
            tree.tag_configure("new", background="#c3e6cb", foreground="#155724")      # Green - new field
            tree.tag_configure("changed", background="#fff3cd", foreground="#856404")  # Yellow - changed
            tree.tag_configure("unchanged", background="white")                         # White - same
            tree.tag_configure("missing", background="#f8d7da", foreground="#721c24")  # Red - missing

        # Legend
        legend_frame = ttk.Frame(bottom_frame)
        legend_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(legend_frame, text="Legend:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(legend_frame, text="  ● New", foreground="#155724",
                  background="#c3e6cb").pack(side=tk.LEFT, padx=5)
        ttk.Label(legend_frame, text="  ● Changed", foreground="#856404",
                  background="#fff3cd").pack(side=tk.LEFT, padx=5)
        ttk.Label(legend_frame, text="  ● Missing", foreground="#721c24",
                  background="#f8d7da").pack(side=tk.LEFT, padx=5)
        ttk.Label(legend_frame, text="  ● Unchanged", background="white").pack(side=tk.LEFT, padx=5)

    def _populate_diff_tab(self):
        """Populate the diff view device list."""
        self.diff_device_tree.delete(*self.diff_device_tree.get_children())

        for item in self.items:
            # Count changes for this item
            if item.action == SyncAction.UPDATE:
                changes = item.get_field_changes()
                new_count = sum(1 for v in changes.values() if v == "new")
                changed_count = sum(1 for v in changes.values() if v == "changed")
                change_summary = f"{new_count} new, {changed_count} changed"
            else:
                change_summary = "All fields (new record)"

            tag = item.action.value.lower()
            self.diff_device_tree.insert("", tk.END, iid=item.cw_id, values=(
                item.action.value.upper(),
                item.cw_name or "(no name)",
                item.sdp_name or "(new)",
                item.match_reason or "-",
                change_summary
            ), tags=(tag,))

    def _apply_diff_filter(self, event=None):
        """Apply filter to diff view device list."""
        filter_val = self.diff_action_filter.get()
        self.diff_device_tree.delete(*self.diff_device_tree.get_children())

        for item in self.items:
            # Apply filter
            if filter_val == "UPDATE Only" and item.action != SyncAction.UPDATE:
                continue
            if filter_val == "CREATE Only" and item.action != SyncAction.CREATE:
                continue

            # Count changes
            if item.action == SyncAction.UPDATE:
                changes = item.get_field_changes()
                new_count = sum(1 for v in changes.values() if v == "new")
                changed_count = sum(1 for v in changes.values() if v == "changed")
                change_summary = f"{new_count} new, {changed_count} changed"
            else:
                change_summary = "All fields (new record)"

            tag = item.action.value.lower()
            self.diff_device_tree.insert("", tk.END, iid=item.cw_id, values=(
                item.action.value.upper(),
                item.cw_name or "(no name)",
                item.sdp_name or "(new)",
                item.match_reason or "-",
                change_summary
            ), tags=(tag,))

    def _on_diff_device_select(self, event=None):
        """Handle device selection in diff view - show side-by-side comparison."""
        selection = self.diff_device_tree.selection()
        if not selection:
            return

        cw_id = selection[0]

        # Find the corresponding SyncItem
        item = next((i for i in self.items if i.cw_id == cw_id), None)
        if not item:
            return

        # Clear both trees
        self.diff_cw_tree.delete(*self.diff_cw_tree.get_children())
        self.diff_sdp_tree.delete(*self.diff_sdp_tree.get_children())

        # Get field changes for UPDATE items
        if item.action == SyncAction.UPDATE:
            changes = item.get_field_changes()
        else:
            changes = {k: "new" for k in item.fields_to_sync.keys()}

        # Field display names
        field_names = {
            "name": "Device Name",
            "ci_attributes_txt_serial_number": "Serial Number",
            "ci_attributes_txt_os": "Operating System",
            "ci_attributes_txt_manufacturer": "Manufacturer",
            "ci_attributes_txt_ip_address": "IP Address",
            "ci_attributes_txt_mac_address": "MAC Address",
        }

        # Populate both trees with aligned fields
        for field_key, display_name in field_names.items():
            cw_value = item.fields_to_sync.get(field_key, "")
            sdp_value = item.sdp_existing_fields.get(field_key, "") if item.sdp_existing_fields else ""

            # Determine tag based on change status
            change_status = changes.get(field_key, "unchanged")
            if change_status == "new":
                cw_tag = "new"
                sdp_tag = "missing"
            elif change_status == "changed":
                cw_tag = "changed"
                sdp_tag = "changed"
            else:
                cw_tag = "unchanged"
                sdp_tag = "unchanged"

            # Insert into CW tree
            self.diff_cw_tree.insert("", tk.END, values=(
                display_name,
                cw_value or "(empty)"
            ), tags=(cw_tag,))

            # Insert into SDP tree
            self.diff_sdp_tree.insert("", tk.END, values=(
                display_name,
                sdp_value or "(empty)"
            ), tags=(sdp_tag,))


    def _create_fulldb_tab(self):
        """
        Create the Full DB Comparison tab showing ALL records from both systems.

        This tab shows:
        - All CW devices (209) with their match status
        - All SDP workstations (690) including unmatched ones
        - Filter to show: All, CW Only, SDP Only, Matched, Unmatched
        """
        # Main paned window - left for CW, right for SDP
        paned = ttk.PanedWindow(self.fulldb_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # =====================================================================
        # LEFT: ConnectWise Devices
        # =====================================================================
        cw_frame = ttk.LabelFrame(paned, text="ConnectWise Devices", padding=5)
        paned.add(cw_frame, weight=1)

        # CW filter row
        cw_filter_frame = ttk.Frame(cw_frame)
        cw_filter_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(cw_filter_frame, text="Filter:").pack(side=tk.LEFT)
        self.fulldb_cw_filter = ttk.Combobox(
            cw_filter_frame, values=["All", "Matched", "Unmatched"],
            state="readonly", width=12
        )
        self.fulldb_cw_filter.set("All")
        self.fulldb_cw_filter.pack(side=tk.LEFT, padx=5)
        self.fulldb_cw_filter.bind("<<ComboboxSelected>>", self._apply_fulldb_cw_filter)

        self.fulldb_cw_count_label = ttk.Label(cw_filter_frame, text="0 devices")
        self.fulldb_cw_count_label.pack(side=tk.RIGHT)

        # CW tree
        cw_tree_frame = ttk.Frame(cw_frame)
        cw_tree_frame.pack(fill=tk.BOTH, expand=True)

        cw_columns = ("status", "name", "category", "serial", "matched_to")
        cw_headings = ("Status", "Device Name", "Category", "Serial #", "Matched SDP Record")
        cw_widths = (80, 180, 100, 120, 200)

        self.fulldb_cw_tree = ttk.Treeview(
            cw_tree_frame, columns=cw_columns, show="headings", height=20
        )
        for i, col in enumerate(cw_columns):
            self.fulldb_cw_tree.heading(col, text=cw_headings[i])
            self.fulldb_cw_tree.column(col, width=cw_widths[i], minwidth=cw_widths[i])

        cw_v_scroll = ttk.Scrollbar(cw_tree_frame, orient=tk.VERTICAL,
                                     command=self.fulldb_cw_tree.yview)
        cw_h_scroll = ttk.Scrollbar(cw_tree_frame, orient=tk.HORIZONTAL,
                                     command=self.fulldb_cw_tree.xview)
        self.fulldb_cw_tree.configure(yscrollcommand=cw_v_scroll.set,
                                       xscrollcommand=cw_h_scroll.set)

        self.fulldb_cw_tree.grid(row=0, column=0, sticky="nsew")
        cw_v_scroll.grid(row=0, column=1, sticky="ns")
        cw_h_scroll.grid(row=1, column=0, sticky="ew")
        cw_tree_frame.grid_rowconfigure(0, weight=1)
        cw_tree_frame.grid_columnconfigure(0, weight=1)

        # CW tree tags
        self.fulldb_cw_tree.tag_configure("matched", background="#d4edda")  # Green
        self.fulldb_cw_tree.tag_configure("unmatched", background="#fff3cd")  # Yellow

        # =====================================================================
        # RIGHT: ServiceDesk Plus Workstations
        # =====================================================================
        sdp_frame = ttk.LabelFrame(paned, text="ServiceDesk Plus Workstations", padding=5)
        paned.add(sdp_frame, weight=1)

        # SDP filter row
        sdp_filter_frame = ttk.Frame(sdp_frame)
        sdp_filter_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(sdp_filter_frame, text="Filter:").pack(side=tk.LEFT)
        self.fulldb_sdp_filter = ttk.Combobox(
            sdp_filter_frame, values=["All", "Matched", "Unmatched"],
            state="readonly", width=12
        )
        self.fulldb_sdp_filter.set("All")
        self.fulldb_sdp_filter.pack(side=tk.LEFT, padx=5)
        self.fulldb_sdp_filter.bind("<<ComboboxSelected>>", self._apply_fulldb_sdp_filter)

        self.fulldb_sdp_count_label = ttk.Label(sdp_filter_frame, text="0 workstations")
        self.fulldb_sdp_count_label.pack(side=tk.RIGHT)

        # SDP tree
        sdp_tree_frame = ttk.Frame(sdp_frame)
        sdp_tree_frame.pack(fill=tk.BOTH, expand=True)

        sdp_columns = ("status", "name", "serial", "ip", "matched_to")
        sdp_headings = ("Status", "Workstation Name", "Serial #", "IP Address", "Matched CW Device")
        sdp_widths = (80, 180, 120, 120, 200)

        self.fulldb_sdp_tree = ttk.Treeview(
            sdp_tree_frame, columns=sdp_columns, show="headings", height=20
        )
        for i, col in enumerate(sdp_columns):
            self.fulldb_sdp_tree.heading(col, text=sdp_headings[i])
            self.fulldb_sdp_tree.column(col, width=sdp_widths[i], minwidth=sdp_widths[i])

        sdp_v_scroll = ttk.Scrollbar(sdp_tree_frame, orient=tk.VERTICAL,
                                      command=self.fulldb_sdp_tree.yview)
        sdp_h_scroll = ttk.Scrollbar(sdp_tree_frame, orient=tk.HORIZONTAL,
                                      command=self.fulldb_sdp_tree.xview)
        self.fulldb_sdp_tree.configure(yscrollcommand=sdp_v_scroll.set,
                                        xscrollcommand=sdp_h_scroll.set)

        self.fulldb_sdp_tree.grid(row=0, column=0, sticky="nsew")
        sdp_v_scroll.grid(row=0, column=1, sticky="ns")
        sdp_h_scroll.grid(row=1, column=0, sticky="ew")
        sdp_tree_frame.grid_rowconfigure(0, weight=1)
        sdp_tree_frame.grid_columnconfigure(0, weight=1)

        # SDP tree tags
        self.fulldb_sdp_tree.tag_configure("matched", background="#d4edda")  # Green
        self.fulldb_sdp_tree.tag_configure("unmatched", background="#f8d7da")  # Red/pink

        # =====================================================================
        # BOTTOM: Legend
        # =====================================================================
        legend_frame = ttk.Frame(self.fulldb_frame)
        legend_frame.pack(fill=tk.X, pady=(5, 0))

        ttk.Label(legend_frame, text="Legend:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(legend_frame, text="  ● Matched", foreground="#155724",
                  background="#d4edda").pack(side=tk.LEFT, padx=5)
        ttk.Label(legend_frame, text="  ● CW Unmatched (will CREATE)", foreground="#856404",
                  background="#fff3cd").pack(side=tk.LEFT, padx=5)
        ttk.Label(legend_frame, text="  ● SDP Unmatched (no CW source)", foreground="#721c24",
                  background="#f8d7da").pack(side=tk.LEFT, padx=5)

        # Store data for filtering
        self._fulldb_cw_data = []
        self._fulldb_sdp_data = []

    def _populate_fulldb_tab(self):
        """
        Populate the Full DB Comparison tab with all records from both systems.
        
        Queries the database directly to get ALL records, not just sync items.
        """
        # Clear existing data
        self.fulldb_cw_tree.delete(*self.fulldb_cw_tree.get_children())
        self.fulldb_sdp_tree.delete(*self.fulldb_sdp_tree.get_children())
        self._fulldb_cw_data = []
        self._fulldb_sdp_data = []

        conn = None
        try:
            conn = sqlite3.connect(str(DEFAULT_DB_PATH))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Build a set of matched SDP IDs from sync items
            matched_sdp_ids = set()
            matched_cw_ids = set()
            cw_to_sdp_map = {}  # cw_id -> sdp_name
            sdp_to_cw_map = {}  # sdp_id -> cw_name
            
            for item in self.items:
                if item.action == SyncAction.UPDATE and item.sdp_id:
                    matched_sdp_ids.add(str(item.sdp_id))
                    matched_cw_ids.add(item.cw_id)
                    cw_to_sdp_map[item.cw_id] = item.sdp_name or item.sdp_id
                    sdp_to_cw_map[str(item.sdp_id)] = item.cw_name

            # =====================================================================
            # Load ALL CW devices
            # =====================================================================
            try:
                cursor.execute("SELECT endpoint_id, raw_json FROM cw_devices")
                for row in cursor.fetchall():
                    cw_id = row["endpoint_id"]
                    try:
                        device = json.loads(row["raw_json"])
                        name = device.get("friendlyName", device.get("name", "(no name)"))
                        serial = device.get("system", {}).get("serialNumber", "")
                        category = self._classify_device_category(device)
                        
                        is_matched = cw_id in matched_cw_ids
                        matched_to = cw_to_sdp_map.get(cw_id, "") if is_matched else ""
                        status = "MATCHED" if is_matched else "UNMATCHED"
                        
                        self._fulldb_cw_data.append({
                            "id": cw_id,
                            "status": status,
                            "name": name,
                            "category": category,
                            "serial": serial,
                            "matched_to": matched_to,
                            "is_matched": is_matched
                        })
                    except Exception as e:
                        logger.warning(f"Error parsing CW device {cw_id}: {e}")
            except sqlite3.OperationalError:
                logger.warning("CW devices table not found")

            # =====================================================================
            # Load ALL SDP assets
            # =====================================================================
            try:
                # First check which columns exist (using sdp_assets)
                cursor.execute("PRAGMA table_info(sdp_assets)")
                available_cols = {row[1] for row in cursor.fetchall()}
                
                # Build dynamic SELECT based on available columns
                select_cols = ["asset_id", "name"]
                if "serial_number" in available_cols:
                    select_cols.append("serial_number")
                if "ip_address" in available_cols:
                    select_cols.append("ip_address")
                    
                cursor.execute(f"SELECT {', '.join(select_cols)} FROM sdp_assets")
                for row in cursor.fetchall():
                    sdp_id = str(row["asset_id"]) if row["asset_id"] else ""
                    name = row["name"] or "(no name)"
                    # Safely get optional columns
                    serial = row["serial_number"] if "serial_number" in available_cols else ""
                    ip = row["ip_address"] if "ip_address" in available_cols else ""
                    
                    is_matched = sdp_id in matched_sdp_ids
                    matched_to = sdp_to_cw_map.get(sdp_id, "") if is_matched else ""
                    status = "MATCHED" if is_matched else "UNMATCHED"
                    
                    self._fulldb_sdp_data.append({
                        "id": sdp_id,
                        "status": status,
                        "name": name,
                        "serial": serial or "",
                        "ip": ip or "",
                        "matched_to": matched_to,
                        "is_matched": is_matched
                    })
            except sqlite3.OperationalError as e:
                logger.warning(f"SDP workstations table not found or error: {e}")

            # Populate trees
            self._apply_fulldb_cw_filter()
            self._apply_fulldb_sdp_filter()

        except Exception as e:
            logger.error(f"Error populating Full DB tab: {e}")
        finally:
            if conn:
                conn.close()

    def _classify_device_category(self, device: dict) -> str:
        """Classify a CW device into a category using DeviceClassifier for consistency."""
        return DeviceClassifier.classify(device)

    def _apply_fulldb_cw_filter(self, event=None):
        """Apply filter to CW devices in Full DB tab."""
        self.fulldb_cw_tree.delete(*self.fulldb_cw_tree.get_children())
        filter_val = self.fulldb_cw_filter.get()

        count = 0
        for idx, item in enumerate(self._fulldb_cw_data):
            # Apply filter
            if filter_val == "Matched" and not item["is_matched"]:
                continue
            if filter_val == "Unmatched" and item["is_matched"]:
                continue

            tag = "matched" if item["is_matched"] else "unmatched"
            # Use unique index-based ID to avoid duplicates
            self.fulldb_cw_tree.insert("", tk.END, iid=f"cw_row_{idx}", values=(
                item["status"],
                item["name"],
                item["category"],
                item["serial"],
                item["matched_to"]
            ), tags=(tag,))
            count += 1

        self.fulldb_cw_count_label.config(text=f"{count} devices")

    def _apply_fulldb_sdp_filter(self, event=None):
        """Apply filter to SDP workstations in Full DB tab."""
        self.fulldb_sdp_tree.delete(*self.fulldb_sdp_tree.get_children())
        filter_val = self.fulldb_sdp_filter.get()

        count = 0
        for idx, item in enumerate(self._fulldb_sdp_data):
            # Apply filter
            if filter_val == "Matched" and not item["is_matched"]:
                continue
            if filter_val == "Unmatched" and item["is_matched"]:
                continue

            tag = "matched" if item["is_matched"] else "unmatched"
            # Use unique index-based ID to avoid duplicates
            self.fulldb_sdp_tree.insert("", tk.END, iid=f"sdp_row_{idx}", values=(
                item["status"],
                item["name"],
                item["serial"],
                item["ip"],
                item["matched_to"]
            ), tags=(tag,))
            count += 1

        self.fulldb_sdp_count_label.config(text=f"{count} workstations")


    def _create_mapping_tab(self):
        """Create field mapping reference tab as proper GUI."""
        # Split into field mapping and category mapping
        paned = ttk.PanedWindow(self.mapping_frame, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Top: Field Mapping
        field_frame = ttk.LabelFrame(paned, text="Field Mapping: CW → SDP", padding=5)
        paned.add(field_frame, weight=1)

        field_columns = ("sdp_field", "cw_source", "transformation", "notes")
        field_tree = ttk.Treeview(field_frame, columns=field_columns, show="headings", height=8)

        field_tree.heading("sdp_field", text="SDP Field")
        field_tree.heading("cw_source", text="CW Source")
        field_tree.heading("transformation", text="Transformation")
        field_tree.heading("notes", text="Notes")

        field_tree.column("sdp_field", width=180)
        field_tree.column("cw_source", width=200)
        field_tree.column("transformation", width=200)
        field_tree.column("notes", width=300)

        # Insert field mappings
        field_mappings = [
            ("name", "friendlyName", "Direct copy", "Asset name in SDP"),
            ("serial_number", "system.serialNumber", "Skip VMware UUIDs", "Physical device serials only"),
            ("os", "os.product", "Direct copy", "Operating system name"),
            ("manufacturer", "bios.manufacturer", "Normalize case", "LENOVO → Lenovo, HP → HP Inc"),
            ("ip_address", "networks[].ipv4", "First valid IP", "Excludes 0.0.0.0"),
            ("mac_address", "networks[].macAddress", "Comma-join", "All MAC addresses"),
            ("processor", "processor.product", "Direct copy", "CPU model"),
        ]
        for mapping in field_mappings:
            field_tree.insert("", tk.END, values=mapping)

        field_tree.pack(fill=tk.BOTH, expand=True)

        # Bottom: Category/CI Type Mapping
        ci_frame = ttk.LabelFrame(paned, text="Category Mapping: CW → SDP CI Type", padding=5)
        paned.add(ci_frame, weight=1)

        ci_columns = ("cw_category", "sdp_ci_type", "description", "count")
        self.ci_tree = ttk.Treeview(ci_frame, columns=ci_columns, show="headings", height=6)

        self.ci_tree.heading("cw_category", text="CW Category")
        self.ci_tree.heading("sdp_ci_type", text="SDP CI Type")
        self.ci_tree.heading("description", text="Description")
        self.ci_tree.heading("count", text="Count")

        self.ci_tree.column("cw_category", width=150)
        self.ci_tree.column("sdp_ci_type", width=200)
        self.ci_tree.column("description", width=300)
        self.ci_tree.column("count", width=80, anchor="center")

        # Will be populated with counts after data loads
        self.ci_tree.pack(fill=tk.BOTH, expand=True)

    def _check_data_availability(self) -> dict:
        """
        Check which data sources are available in the database.

        Returns:
            Dictionary with 'cw_available', 'sdp_available', 'cw_count', 'sdp_count'
        """
        result = {'cw_available': False, 'sdp_available': False, 'cw_count': 0, 'sdp_count': 0}
        conn = None
        try:
            conn = sqlite3.connect(str(DEFAULT_DB_PATH))
            cursor = conn.cursor()

            # Check CW table
            try:
                cursor.execute("SELECT COUNT(*) FROM cw_devices")
                result['cw_count'] = cursor.fetchone()[0]
                result['cw_available'] = result['cw_count'] > 0
            except sqlite3.OperationalError:
                pass

            # Check SDP table
            try:
                cursor.execute("SELECT COUNT(*) FROM sdp_assets")
                result['sdp_count'] = cursor.fetchone()[0]
                result['sdp_available'] = result['sdp_count'] > 0
            except sqlite3.OperationalError:
                pass
        except Exception as e:
            logger.warning(f"Error checking data availability: {e}")
        finally:
            if conn:
                conn.close()

        return result

    def _load_data(self):
        """
        Load sync preview data.

        Handles three scenarios:
        1. No data: Shows empty state with instructions
        2. Partial data (CW only or SDP only): Shows available data without matching
        3. Both available: Runs full sync preview with matching logic
        """
        # Check what data is available
        availability = self._check_data_availability()
        cw_available = availability['cw_available']
        sdp_available = availability['sdp_available']

        if not cw_available and not sdp_available:
            # No data at all - show empty state
            logger.info("No data tables found - please refresh CW and SDP data")
            self.items = []
            self.summary = {"total": 0, "by_action": {}, "by_category": {}, "by_ci_type": {}}
            self._update_stats_with_availability(availability)
            self._populate_tree()
            self._populate_category_tab()
            self._populate_diff_tab()
            self._populate_fulldb_tab()
            self._update_filters()
            return

        if cw_available and sdp_available:
            # Both available - run full sync preview with matching
            try:
                self.items = self.engine.build_sync_preview()
                self.summary = self.engine.get_summary(self.items)
                self._update_stats_with_availability(availability)
                self._populate_tree()
                self._populate_category_tab()
                self._populate_diff_tab()
                self._populate_fulldb_tab()
                self._update_filters()
                return
            except Exception as e:
                logger.error(f"Failed to build sync preview: {e}")
                messagebox.showerror("Error", f"Failed to build sync preview: {e}")
                self.items = []
                self.summary = {"total": 0, "by_action": {}, "by_category": {}, "by_ci_type": {}}
                self._update_stats_with_availability(availability)
                self._populate_tree()
                self._populate_category_tab()
                self._populate_diff_tab()
                self._populate_fulldb_tab()
                self._update_filters()
                return

        # Partial data - show what we have without matching
        try:
            self.items = self._build_partial_preview(cw_available, sdp_available)
            self.summary = self.engine.get_summary(self.items) if self.items else {
                "total": 0, "by_action": {}, "by_category": {}, "by_ci_type": {}
            }
            self._update_stats_with_availability(availability)
            self._populate_tree()
            self._populate_category_tab()
            self._populate_diff_tab()
            self._populate_fulldb_tab()
            self._update_filters()
        except Exception as e:
            logger.error(f"Failed to load partial data: {e}")
            self.items = []
            self.summary = {"total": 0, "by_action": {}, "by_category": {}, "by_ci_type": {}}
            self._update_stats_with_availability(availability)
            self._populate_tree()
            self._populate_category_tab()
            self._populate_diff_tab()
            self._populate_fulldb_tab()
            self._update_filters()

    def _build_partial_preview(self, cw_available: bool, sdp_available: bool) -> list:
        """
        Build a preview with only partial data (CW only or SDP only).

        When only CW data is available, shows all devices as pending (no matching possible).
        When only SDP data is available, shows info message (nothing to sync from).
        """
        from .field_mapper import FieldMapper

        items = []

        if cw_available and not sdp_available:
            # CW data only - show devices as CREATE (pending SDP data for matching)
            conn = None
            try:
                conn = sqlite3.connect(str(DEFAULT_DB_PATH))
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("SELECT endpoint_id, raw_json FROM cw_devices")
                for row in cursor.fetchall():
                    try:
                        cw_id = row["endpoint_id"]
                        device = json.loads(row["raw_json"])

                        # Use FieldMapper to classify and map fields
                        mapper = FieldMapper(device)
                        sdp_data = mapper.get_sdp_data()
                        category = sdp_data.pop("_category")

                        # Determine target SDP Asset type endpoint
                        sdp_ci_type = self.engine.ASSET_TYPE_MAP.get(category, "asset_workstations")

                        # All items are CREATE since we can't match without SDP data
                        item = SyncItem(
                            cw_id=cw_id,
                            cw_name=device.get("friendlyName", ""),
                            cw_category=category,
                            sdp_ci_type=sdp_ci_type,
                            action=SyncAction.CREATE,
                            fields_to_sync=sdp_data,
                            sdp_existing_fields={},
                            match_reason="Pending SDP data for matching",
                        )
                        items.append(item)
                    except Exception as e:
                        logger.warning(f"Error processing CW device: {e}")

                logger.info(f"Loaded {len(items)} CW devices (SDP data pending for matching)")
            finally:
                if conn:
                    conn.close()

        elif sdp_available and not cw_available:
            # SDP data only - nothing to show (sync is CW → SDP)
            logger.info("SDP data available but no CW data - refresh CW to see sync preview")

        return items

    def _update_stats_with_availability(self, availability: dict):
        """Update summary statistics with data availability info."""
        for widget in self.stats_frame.winfo_children():
            widget.destroy()

        total = self.summary.get("total", 0)
        creates = self.summary.get("by_action", {}).get("create", 0)
        updates = self.summary.get("by_action", {}).get("update", 0)

        cw_count = availability.get('cw_count', 0)
        sdp_count = availability.get('sdp_count', 0)
        cw_available = availability.get('cw_available', False)
        sdp_available = availability.get('sdp_available', False)

        # Show data source status
        cw_status = f"CW: {cw_count}" if cw_available else "CW: ⚠ No data"
        sdp_status = f"SDP: {sdp_count}" if sdp_available else "SDP: ⚠ No data"

        stats = [
            (cw_status, "#0066cc" if cw_available else "#dc3545"),
            (sdp_status, "#0066cc" if sdp_available else "#dc3545"),
            ("|", "#999"),
            (f"Total: {total}", "#333"),
            (f"Create: {creates}", "#28a745"),
            (f"Update: {updates}", "#007bff"),
        ]

        for text, color in stats:
            lbl = ttk.Label(self.stats_frame, text=text, font=("Segoe UI", 11, "bold"), foreground=color)
            lbl.pack(side=tk.LEFT, padx=8)

    def _update_filters(self):
        """Update filter dropdowns."""
        categories = ["All"] + sorted(self.summary.get("by_category", {}).keys())
        self.category_filter["values"] = categories
        self.category_filter.set("All")

    def _populate_tree(self, items=None):
        """
        Populate the tree view with ALL fields and selection checkbox.

        For UPDATE items, field values are annotated to show what's changing:
        - ★ prefix = NEW field (doesn't exist in SDP)
        - ↻ prefix = CHANGED field (different from SDP)
        - (no prefix) = UNCHANGED field (same as SDP)
        """
        self.tree.delete(*self.tree.get_children())

        items = items or self.items
        for item in items:
            is_selected = item.cw_id in self.selected_items
            check_mark = "☑" if is_selected else "☐"

            # Determine tag based on action and selection
            if is_selected:
                tag = f"selected_{item.action.value}"
            else:
                tag = item.action.value

            fields = item.fields_to_sync

            # For UPDATE items, get field change status and annotate values
            if item.action == SyncAction.UPDATE:
                changes = item.get_field_changes()
                display_fields = self._format_fields_with_changes(fields, changes, item.sdp_existing_fields)
            else:
                # CREATE items - all fields are new (show with ★)
                display_fields = {k: f"★ {v}" if v else "" for k, v in fields.items()}

            # Use cw_id as unique identifier (cw_name may have duplicates)
            # Show placeholder for missing fields
            no_data = "(no data)"
            self.tree.insert("", tk.END, iid=item.cw_id, values=(
                check_mark,
                item.cw_name or no_data,
                item.cw_category,
                item.action.value.upper(),
                item.sdp_ci_type,
                item.match_reason or "-",
                # SDP fields with change indicators - show placeholder if empty
                display_fields.get("name") or no_data,
                display_fields.get("ci_attributes_txt_serial_number") or no_data,
                display_fields.get("ci_attributes_txt_os") or no_data,
                display_fields.get("ci_attributes_txt_manufacturer") or no_data,
                display_fields.get("ci_attributes_txt_ip_address") or no_data,
                display_fields.get("ci_attributes_txt_mac_address") or no_data,
            ), tags=(tag,))

        self._update_selection_label()

    def _format_fields_with_changes(self, fields: dict, changes: dict, existing: dict = None) -> dict:
        """
        Format field values with change indicators for UPDATE items.

        Args:
            fields: Dictionary of field names to new values (from CW)
            changes: Dictionary of field names to change types (new/changed/unchanged)
            existing: Dictionary of current SDP values (for showing old→new)

        Returns:
            Dictionary with formatted display values:
            - ★ value = NEW (field will be added to SDP)
            - old → new = CHANGED (shows both old and new value)
            - value = UNCHANGED (same value, no change)
        """
        existing = existing or {}
        display = {}
        for field_name, value in fields.items():
            if not value:
                display[field_name] = ""
                continue

            change_type = changes.get(field_name, "unchanged")
            if change_type == "new":
                display[field_name] = f"★ {value}"  # Star = new field (was empty)
            elif change_type == "changed":
                old_val = existing.get(field_name, "")
                # Truncate long values for display
                old_display = str(old_val)[:20] + "..." if len(str(old_val)) > 20 else str(old_val)
                new_display = str(value)[:20] + "..." if len(str(value)) > 20 else str(value)
                display[field_name] = f"{old_display} → {new_display}"  # Show old→new
            else:
                display[field_name] = str(value)  # No indicator = unchanged

        return display

    def _populate_category_tab(self):
        """Populate category breakdown as proper GUI."""
        # Clear existing
        self.cat_tree.delete(*self.cat_tree.get_children())

        asset_type_map = {
            "Laptop": "asset_workstations",
            "Desktop": "asset_workstations",
            "Virtual Server": "asset_virtual_machines",
            "Physical Server": "asset_servers",
            "Network Device": "asset_switches",
        }

        for category in sorted(self.summary.get("by_category", {}).keys()):
            count = self.summary["by_category"][category]
            cat_items = [i for i in self.items if i.cw_category == category]
            creates = len([i for i in cat_items if i.action == SyncAction.CREATE])
            updates = len([i for i in cat_items if i.action == SyncAction.UPDATE])
            sdp_type = asset_type_map.get(category, "asset_workstations")

            self.cat_tree.insert("", tk.END, values=(
                category, count, creates, updates, sdp_type
            ), iid=category)

        # Also populate the CI type mapping tree
        self._populate_ci_mapping()

    def _populate_ci_mapping(self):
        """Populate CI type mapping in Field Mapping tab."""
        self.ci_tree.delete(*self.ci_tree.get_children())

        ci_mappings = [
            ("Laptop", "asset_workstations", "ThinkPads, ProBooks, etc.", 0),
            ("Desktop", "asset_workstations", "Physical workstations", 0),
            ("Virtual Server", "asset_virtual_machines", "VMware VMs", 0),
            ("Physical Server", "asset_servers", "Physical servers", 0),
            ("Network Device", "asset_switches", "Switches, routers, firewalls", 0),
        ]

        for cat, ci_type, desc, _ in ci_mappings:
            count = self.summary.get("by_category", {}).get(cat, 0)
            self.ci_tree.insert("", tk.END, values=(cat, ci_type, desc, count))

    def _on_category_select(self, event):
        """Handle category selection - show devices in that category."""
        selection = self.cat_tree.selection()
        if not selection:
            return

        category = selection[0]  # iid is the category name
        self.cat_device_tree.delete(*self.cat_device_tree.get_children())

        cat_items = [i for i in self.items if i.cw_category == category]
        for item in cat_items:
            tag = item.action.value
            self.cat_device_tree.insert("", tk.END, values=(
                item.cw_name,
                item.action.value.upper(),
                item.match_reason or "-"
            ), tags=(tag,))

    def _apply_filter(self, event=None):
        """Apply filters to the tree view."""
        action_filter = self.action_filter.get()
        category_filter = self.category_filter.get()

        filtered = self.items

        if action_filter != "All":
            filtered = [i for i in filtered if i.action.value.upper() == action_filter]

        if category_filter != "All":
            filtered = [i for i in filtered if i.cw_category == category_filter]

        self._populate_tree(filtered)

        # Track which items are currently visible (for filtered selection)
        self.filtered_item_ids = set(self.tree.get_children())

    # =========================================================================
    # SELECTION HANDLING
    # =========================================================================

    def _on_tree_click(self, event):
        """
        Handle single-click on treeview row.

        Clicking anywhere on a row toggles its selection checkbox.
        This is more intuitive than requiring double-click or
        clicking exactly on the checkbox column.

        Args:
            event: Mouse click event with x, y coordinates
        """
        # Identify which row was clicked
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return  # Clicked on empty area

        # Identify which column was clicked (for future column-specific behavior)
        column = self.tree.identify_column(event.x)

        # Toggle selection for this item
        if item_id in self.selected_items:
            self.selected_items.discard(item_id)
        else:
            self.selected_items.add(item_id)

        # Update the display
        self._refresh_item_display(item_id)
        self._update_selection_label()

        # Select the row in the treeview for visual feedback
        self.tree.selection_set(item_id)

    def _toggle_selected_items(self, event):
        """
        Toggle selection for all currently highlighted items.

        Triggered by pressing the Space key. Useful for toggling
        multiple items that have been shift-selected.

        Args:
            event: Keyboard event
        """
        selection = self.tree.selection()
        for item_id in selection:
            if item_id in self.selected_items:
                self.selected_items.discard(item_id)
            else:
                self.selected_items.add(item_id)
            self._refresh_item_display(item_id)
        self._update_selection_label()

    def _refresh_item_display(self, item_id):
        """
        Refresh a single item's display in the tree.

        Updates the checkbox character and row color based on
        whether the item is selected or not. Also maintains
        field change indicators for UPDATE items.

        Args:
            item_id: The CW endpoint ID (used as tree item ID)
        """
        item = next((i for i in self.items if i.cw_id == item_id), None)
        if not item:
            return

        is_selected = item_id in self.selected_items
        check_mark = "☑" if is_selected else "☐"
        tag = f"selected_{item.action.value}" if is_selected else item.action.value

        fields = item.fields_to_sync

        # Format fields with change indicators (same logic as _populate_tree)
        if item.action == SyncAction.UPDATE:
            changes = item.get_field_changes()
            display_fields = self._format_fields_with_changes(fields, changes, item.sdp_existing_fields)
        else:
            display_fields = {k: f"★ {v}" if v else "" for k, v in fields.items()}

        # Show placeholder for missing fields (consistent with _populate_tree)
        no_data = "(no data)"
        self.tree.item(item_id, values=(
            check_mark,
            item.cw_name or no_data,
            item.cw_category,
            item.action.value.upper(),
            item.sdp_ci_type,
            item.match_reason or "-",
            display_fields.get("name") or no_data,
            display_fields.get("ci_attributes_txt_serial_number") or no_data,
            display_fields.get("ci_attributes_txt_os") or no_data,
            display_fields.get("ci_attributes_txt_manufacturer") or no_data,
            display_fields.get("ci_attributes_txt_ip_address") or no_data,
            display_fields.get("ci_attributes_txt_mac_address") or no_data,
        ), tags=(tag,))

    def _select_all(self):
        """Select ALL items (not just visible/filtered)."""
        for item in self.items:
            self.selected_items.add(item.cw_id)
        self._apply_filter()  # Refresh display
        self._update_selection_label()

    def _select_none(self):
        """Deselect ALL items."""
        self.selected_items.clear()
        self._apply_filter()  # Refresh display
        self._update_selection_label()

    def _select_filtered(self):
        """Select only the currently visible (filtered) items."""
        for item_id in self.filtered_item_ids:
            self.selected_items.add(item_id)
            self._refresh_item_display(item_id)
        self._update_selection_label()

    def _deselect_filtered(self):
        """Deselect only the currently visible (filtered) items."""
        for item_id in self.filtered_item_ids:
            self.selected_items.discard(item_id)
            self._refresh_item_display(item_id)
        self._update_selection_label()

    def _select_create_only(self):
        """Select only CREATE items (items that don't exist in SDP yet)."""
        self.selected_items.clear()
        for item in self.items:
            if item.action == SyncAction.CREATE:
                self.selected_items.add(item.cw_id)
        self._apply_filter()  # Refresh display
        self._update_selection_label()

    def _update_selection_label(self):
        """Update the selection count label."""
        count = len(self.selected_items)
        create_count = len([i for i in self.items if i.cw_id in self.selected_items and i.action == SyncAction.CREATE])
        self.selection_label.config(text=f"Selected: {count} ({create_count} CREATE)")

    def _execute_sync(self):
        """
        Execute sync: CREATE new items and UPDATE existing items.

        Dry run by default for safety. Uses selection if any items are selected,
        otherwise syncs all CREATE and UPDATE items.
        """
        if self.sync_in_progress:
            messagebox.showwarning("Sync in Progress", "A sync operation is already running.")
            return

        is_dry_run = not self.real_sync_var.get()

        # Get items to sync - use selection if any, otherwise all CREATE and UPDATE items
        if self.selected_items:
            # Selected CREATE and UPDATE items
            sync_items = [i for i in self.items
                         if i.cw_id in self.selected_items and
                         i.action in (SyncAction.CREATE, SyncAction.UPDATE)]
            selection_mode = "SELECTED"
        else:
            # All CREATE and UPDATE items
            sync_items = [i for i in self.items
                         if i.action in (SyncAction.CREATE, SyncAction.UPDATE)]
            selection_mode = "ALL"

        if not sync_items:
            if self.selected_items:
                messagebox.showinfo("Nothing to Sync",
                    "No CREATE or UPDATE items in your selection.")
            else:
                messagebox.showinfo("Nothing to Sync",
                    "No items need syncing. All CW devices are already up-to-date in SDP.")
            return

        # Count by action type
        create_items = [i for i in sync_items if i.action == SyncAction.CREATE]
        update_items = [i for i in sync_items if i.action == SyncAction.UPDATE]

        # Build confirmation message
        mode_text = "DRY RUN (preview only)" if is_dry_run else "REAL SYNC"
        msg = f"Mode: {mode_text}\n"
        msg += f"Selection: {selection_mode} ({len(sync_items)} items)\n\n"

        if create_items:
            msg += f"📝 CREATE: {len(create_items)} new assets\n"
        if update_items:
            msg += f"🔄 UPDATE: {len(update_items)} existing assets\n"

        msg += "\nBy Category:\n"
        for cat in sorted(set(i.cw_category for i in sync_items)):
            cat_items = [i for i in sync_items if i.cw_category == cat]
            creates = len([i for i in cat_items if i.action == SyncAction.CREATE])
            updates = len([i for i in cat_items if i.action == SyncAction.UPDATE])
            msg += f"  • {cat}: {creates} create, {updates} update\n"

        if not is_dry_run:
            msg += "\n⚠️ WARNING: This will make REAL changes to SDP!\n"

        msg += "\nProceed?"

        if not messagebox.askyesno("Confirm Sync", msg):
            return

        # Start sync in background thread
        self.sync_in_progress = True
        self.sync_btn.config(state=tk.DISABLED, text="⏳ Syncing...")

        # Create progress window
        self._create_progress_window(len(sync_items), is_dry_run)

        # Run sync in thread
        thread = threading.Thread(target=self._run_sync_thread, args=(sync_items, is_dry_run))
        thread.daemon = True
        thread.start()

    def _create_progress_window(self, total: int, is_dry_run: bool):
        """Create progress window for sync."""
        self.progress_win = tk.Toplevel(self.root)
        title = "Sync Preview (Dry Run)" if is_dry_run else "Sync Progress"
        self.progress_win.title(title)
        self.progress_win.geometry("600x400")
        self.progress_win.transient(self.root)
        # Prevent crash if user closes window during sync — treat as no-op
        self.progress_win.protocol("WM_DELETE_WINDOW", lambda: None)

        header = "Preview: What would be created..." if is_dry_run else "Creating assets in SDP..."
        ttk.Label(self.progress_win, text=header,
                  font=("Segoe UI", 12, "bold")).pack(pady=10)

        self.progress_bar = ttk.Progressbar(self.progress_win, length=500, mode="determinate",
                                             maximum=total)
        self.progress_bar.pack(pady=10)

        self.progress_label = ttk.Label(self.progress_win, text=f"0 / {total}")
        self.progress_label.pack()

        # Log area
        self.progress_log = tk.Text(self.progress_win, height=15, width=70, state=tk.DISABLED)
        self.progress_log.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

    def _run_sync_thread(self, items: List[SyncItem], is_dry_run: bool):
        """
        Run sync in background thread.

        Handles both CREATE (new items) and UPDATE (existing items) operations.
        Tracks created IDs for revert capability.
        """
        from .sdp_client import SDPClient

        created_ids = []  # Track created items for revert
        sync_results = []  # Track all results for results tab
        start_time = datetime.now()

        try:
            sdp = SDPClient(dry_run=is_dry_run)
        except Exception as e:
            self.root.after(0, lambda: self._sync_error(f"Failed to connect to SDP: {e}"))
            return

        success_count = 0
        error_count = 0

        for i, item in enumerate(items):
            result_entry = {
                "name": item.cw_name,
                "category": item.cw_category,
                "ci_type": item.sdp_ci_type,
                "action": item.action.value.upper(),
                "status": "pending",
                "message": "",
                "sdp_id": item.sdp_id  # Pre-fill for UPDATE items
            }

            try:
                if item.action == SyncAction.CREATE:
                    # =========================================================
                    # CREATE: New asset in SDP
                    # =========================================================
                    result = sdp.create_asset(item.sdp_ci_type, item.fields_to_sync)
                    if result:
                        success_count += 1
                        if is_dry_run:
                            log_msg = f"[DRY] Would create: {item.cw_name} → {item.sdp_ci_type}"
                            result_entry["status"] = "would_create"
                            result_entry["message"] = "Would be created (dry run)"
                        else:
                            log_msg = f"✓ Created: {item.cw_name}"
                            result_entry["status"] = "created"
                            result_entry["message"] = "Created successfully"
                            # Track for revert
                            sdp_id = result.get("asset", result.get(item.sdp_ci_type.rstrip('s'), {})).get("id")
                            if sdp_id:
                                result_entry["sdp_id"] = sdp_id
                                created_ids.append({
                                    "sdp_id": sdp_id,
                                    "asset_type": item.sdp_ci_type,
                                    "name": item.cw_name,
                                    "action": "create"
                                })
                    else:
                        error_count += 1
                        log_msg = f"✗ Create failed: {item.cw_name}"
                        result_entry["status"] = "failed"
                        result_entry["message"] = "API returned no result"

                elif item.action == SyncAction.UPDATE:
                    # =========================================================
                    # UPDATE: Existing asset in SDP
                    # =========================================================
                    if not item.sdp_id:
                        error_count += 1
                        log_msg = f"✗ Update failed: {item.cw_name} - No SDP ID"
                        result_entry["status"] = "failed"
                        result_entry["message"] = "Missing SDP ID for update"
                    else:
                        result = sdp.update_asset(item.sdp_id, item.fields_to_sync)
                        if result:
                            success_count += 1
                            if is_dry_run:
                                log_msg = f"[DRY] Would update: {item.cw_name} (ID: {item.sdp_id})"
                                result_entry["status"] = "would_update"
                                result_entry["message"] = f"Would update SDP ID {item.sdp_id} (dry run)"
                            else:
                                log_msg = f"🔄 Updated: {item.cw_name}"
                                result_entry["status"] = "updated"
                                result_entry["message"] = f"Updated SDP ID {item.sdp_id}"
                        else:
                            error_count += 1
                            log_msg = f"✗ Update failed: {item.cw_name}"
                            result_entry["status"] = "failed"
                            result_entry["message"] = "API returned no result"

                else:
                    # SKIP or other action - shouldn't happen but handle gracefully
                    log_msg = f"⊘ Skipped: {item.cw_name} ({item.action.value})"
                    result_entry["status"] = "skipped"
                    result_entry["message"] = f"Action: {item.action.value}"

            except Exception as e:
                error_count += 1
                error_msg = str(e)[:100]
                log_msg = f"✗ Error: {item.cw_name} - {error_msg[:50]}"
                result_entry["status"] = "error"
                result_entry["message"] = error_msg

            sync_results.append(result_entry)

            # Update UI in main thread
            self.root.after(0, lambda i=i, msg=log_msg: self._update_progress(i + 1, len(items), msg))

        # Save created IDs for revert (if real sync - only CREATEs can be reverted)
        if not is_dry_run and created_ids:
            self._save_sync_log(created_ids)

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Done - pass results for results tab
        self.root.after(0, lambda: self._sync_complete(
            success_count, error_count, is_dry_run, sync_results, duration
        ))

    def _save_sync_log(self, created_ids: List[Dict]):
        """Save sync log to database for revert capability."""

        conn = None
        try:
            conn = sqlite3.connect(str(DEFAULT_DB_PATH))
            cursor = conn.cursor()

            # Create sync_log table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sync_time TEXT,
                    items_json TEXT,
                    reverted INTEGER DEFAULT 0
                )
            """)

            cursor.execute(
                "INSERT INTO sync_log (sync_time, items_json) VALUES (?, ?)",
                (datetime.now().isoformat(), json.dumps(created_ids))
            )
            conn.commit()
        finally:
            if conn:
                conn.close()

        # Enable revert button
        self.root.after(0, lambda: self.revert_btn.config(state=tk.NORMAL))

    def _update_progress(self, current: int, total: int, log_msg: str):
        """Update progress UI (guards against closed window)."""
        if not hasattr(self, 'progress_win') or not self.progress_win.winfo_exists():
            return
        self.progress_bar["value"] = current
        self.progress_label.config(text=f"{current} / {total}")

        self.progress_log.config(state=tk.NORMAL)
        self.progress_log.insert(tk.END, log_msg + "\n")
        self.progress_log.see(tk.END)
        self.progress_log.config(state=tk.DISABLED)

    def _sync_error(self, msg: str):
        """Handle sync error."""
        self.sync_in_progress = False
        self._on_real_sync_toggle()  # Reset button text
        if hasattr(self, 'progress_win') and self.progress_win.winfo_exists():
            self.progress_win.destroy()
        messagebox.showerror("Sync Error", msg)

    def _sync_complete(self, success: int, errors: int, is_dry_run: bool,
                       results: List[Dict] = None, duration: float = 0):
        """Handle sync completion and create results tab."""
        self.sync_in_progress = False
        self._on_real_sync_toggle()  # Reset button text

        # Update progress window with summary (guard against closed window)
        if hasattr(self, 'progress_win') and self.progress_win.winfo_exists():
            if is_dry_run:
                self.progress_label.config(text=f"Preview complete: {success} would be created, {errors} would fail")
            else:
                self.progress_label.config(text=f"Complete: {success} created, {errors} errors")

            # Restore X button functionality
            self.progress_win.protocol("WM_DELETE_WINDOW", self.progress_win.destroy)

            # Add close button
            ttk.Button(self.progress_win, text="Close",
                       command=self.progress_win.destroy).pack(pady=10)

        # Create/update results tab
        if results:
            self._create_results_tab(results, success, errors, is_dry_run, duration)

        # Reload data to reflect changes (only if real sync)
        if not is_dry_run:
            self._load_data()

    def _create_results_tab(self, results: List[Dict], success: int, errors: int,
                           is_dry_run: bool, duration: float):
        """Create or update the Sync Results tab."""

        # Remove existing results tab if present
        for tab_id in self.notebook.tabs():
            if "Results" in self.notebook.tab(tab_id, "text"):
                self.notebook.forget(tab_id)

        # Create new results frame
        results_frame = ttk.Frame(self.notebook, padding="5")
        tab_title = "📋 Dry Run Results" if is_dry_run else "✅ Sync Results"
        self.notebook.add(results_frame, text=tab_title)

        # Summary section
        summary_frame = ttk.LabelFrame(results_frame, text="Summary", padding=10)
        summary_frame.pack(fill=tk.X, pady=(0, 10))

        mode = "DRY RUN" if is_dry_run else "REAL SYNC"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        summary_text = f"Mode: {mode}  |  Time: {timestamp}  |  Duration: {duration:.1f}s  |  "
        summary_text += f"Success: {success}  |  Errors: {errors}  |  Total: {len(results)}"

        ttk.Label(summary_frame, text=summary_text, font=("Segoe UI", 10)).pack(anchor=tk.W)

        # Status breakdown
        status_counts = {}
        for r in results:
            status = r["status"]
            status_counts[status] = status_counts.get(status, 0) + 1

        status_text = "Status breakdown: " + ", ".join(f"{k}: {v}" for k, v in sorted(status_counts.items()))
        ttk.Label(summary_frame, text=status_text, foreground="gray").pack(anchor=tk.W)

        # Results tree
        tree_frame = ttk.Frame(results_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("status_icon", "name", "category", "ci_type", "status", "message", "sdp_id")
        headings = ("", "Device Name", "Category", "CI Type", "Status", "Message", "SDP ID")
        widths = (30, 200, 120, 160, 100, 300, 100)

        results_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=20)

        for i, col in enumerate(columns):
            results_tree.heading(col, text=headings[i])
            results_tree.column(col, width=widths[i], minwidth=widths[i])

        # Scrollbars
        v_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=results_tree.yview)
        h_scroll = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=results_tree.xview)
        results_tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        results_tree.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # Configure tags for result statuses
        # CREATE results (green tones)
        results_tree.tag_configure("created", background="#d4edda")      # Light green - created
        results_tree.tag_configure("would_create", background="#c3e6cb") # Pale green - dry run create

        # UPDATE results (blue tones)
        results_tree.tag_configure("updated", background="#cce5ff")      # Light blue - updated
        results_tree.tag_configure("would_update", background="#b8daff") # Pale blue - dry run update

        # Error/failure states (red tones)
        results_tree.tag_configure("failed", background="#f8d7da")       # Light red
        results_tree.tag_configure("error", background="#f5c6cb")        # Darker red
        results_tree.tag_configure("skipped", background="#e2e3e5")      # Gray

        # Status icons
        status_icons = {
            "created": "✓",
            "would_create": "○",
            "updated": "🔄",
            "would_update": "◐",
            "failed": "✗",
            "error": "⚠",
            "skipped": "⊘",
            "pending": "?"
        }

        # Populate tree
        for r in results:
            icon = status_icons.get(r["status"], "?")
            tag = r["status"]
            results_tree.insert("", tk.END, values=(
                icon,
                r["name"],
                r["category"],
                r["ci_type"],
                r["status"].replace("_", " ").title(),
                r["message"],
                r["sdp_id"] or "-"
            ), tags=(tag,))

        # Switch to results tab
        self.notebook.select(results_frame)

    def _revert_sync(self):
        """Revert the last sync operation.

        NOTE: Only CREATE operations are logged and revertable (via DELETE).
        UPDATE operations are not logged because we don't store the previous
        field values needed to restore the original state.
        """
        conn = None
        try:
            # Get last sync log
            conn = sqlite3.connect(str(DEFAULT_DB_PATH))
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, sync_time, items_json FROM sync_log
                WHERE reverted = 0 ORDER BY id DESC LIMIT 1
            """)
            row = cursor.fetchone()

            if not row:
                messagebox.showinfo("No Sync to Revert", "No previous sync operations found to revert.")
                return

            log_id, sync_time, items_json = row
            items = json.loads(items_json)

            msg = f"Revert sync from {sync_time}?\n\n"
            msg += f"This will DELETE {len(items)} items from SDP:\n"
            for item in items[:5]:
                msg += f"  • {item['name']}\n"
            if len(items) > 5:
                msg += f"  ... and {len(items) - 5} more\n"

            if not messagebox.askyesno("Confirm Revert", msg):
                return

            # Execute revert
            from .sdp_client import SDPClient
            sdp = SDPClient(dry_run=False)
            success = 0
            for item in items:
                try:
                    sdp.delete_asset(item['sdp_id'])
                    success += 1
                except Exception as e:
                    logger.error(f"Failed to delete {item['name']}: {e}")

            # Mark as reverted
            cursor.execute("UPDATE sync_log SET reverted = 1 WHERE id = ?", (log_id,))
            conn.commit()

            messagebox.showinfo("Revert Complete", f"Deleted {success}/{len(items)} items from SDP.")
            self.revert_btn.config(state=tk.DISABLED)
            self._load_data()

        except Exception as e:
            messagebox.showerror("Revert Error", f"Failed to revert: {e}")
        finally:
            if conn:
                conn.close()

    def _refresh_cw_data(self):
        """Refresh ConnectWise data with progress dialog."""
        if messagebox.askyesno("Refresh CW Data",
                               "This will re-fetch all data from ConnectWise.\n"
                               "This may take several minutes for detailed data.\n\n"
                               "Proceed?"):
            self.sync_btn.config(state=tk.DISABLED)
            self._cw_client = None  # Will be set in thread
            self._cw_cancelled = False
            self._create_cw_progress_dialog()
            thread = threading.Thread(target=self._do_refresh_cw)
            thread.daemon = True
            thread.start()

    def _create_cw_progress_dialog(self):
        """Create progress dialog for CW refresh with live feed."""
        self.cw_progress_win = tk.Toplevel(self.root)
        self.cw_progress_win.title("Refreshing ConnectWise Data")
        self.cw_progress_win.geometry("500x350")
        self.cw_progress_win.transient(self.root)
        self.cw_progress_win.protocol("WM_DELETE_WINDOW", self._cancel_cw_refresh)

        # Center on parent
        self.cw_progress_win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 500) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 350) // 2
        self.cw_progress_win.geometry(f"+{x}+{y}")

        ttk.Label(self.cw_progress_win, text="Fetching ConnectWise Endpoints",
                  font=("Segoe UI", 12, "bold")).pack(pady=(15, 10))

        self.cw_progress_bar = ttk.Progressbar(self.cw_progress_win, length=450,
                                                mode="determinate", maximum=100)
        self.cw_progress_bar.pack(pady=5)

        self.cw_progress_label = ttk.Label(self.cw_progress_win, text="Connecting...")
        self.cw_progress_label.pack(pady=3)

        self.cw_status_label = ttk.Label(self.cw_progress_win, text="", foreground="gray")
        self.cw_status_label.pack(pady=3)

        # Live feed frame - shows recently fetched items
        feed_frame = ttk.LabelFrame(self.cw_progress_win, text="Recently Fetched", padding=5)
        feed_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        # Listbox for live feed (shows last N items)
        self.cw_feed_list = tk.Listbox(feed_frame, height=6, font=("Consolas", 9))
        self.cw_feed_list.pack(fill=tk.BOTH, expand=True)

        # Initialize feed items list
        self._cw_feed_items = []

        ttk.Button(self.cw_progress_win, text="Cancel",
                   command=self._cancel_cw_refresh).pack(pady=10)

    def _cancel_cw_refresh(self):
        """Cancel the CW refresh operation."""
        self._cw_cancelled = True
        if self._cw_client:
            self._cw_client.cancel()
        if hasattr(self, 'cw_progress_win') and self.cw_progress_win.winfo_exists():
            self.cw_progress_label.config(text="Cancelling...")
        logger.info("CW refresh cancelled by user")

    def _update_cw_progress(self, current: int, total: int, status: str, detail: str = ""):
        """Update CW progress dialog from main thread."""
        if hasattr(self, 'cw_progress_win') and self.cw_progress_win.winfo_exists():
            pct = (current / total * 100) if total > 0 else 0
            self.cw_progress_bar["value"] = pct
            self.cw_progress_label.config(text=status)
            self.cw_status_label.config(text=detail)

    def _monitor_rate_limit(self):
        """Periodically update rate limit stats independent of fetch loop."""
        if hasattr(self, 'cw_progress_win') and self.cw_progress_win.winfo_exists() and self._cw_client:
            try:
                status = self._cw_client.rate_limiter.get_status_line()
                # Update status label directly
                self.cw_status_label.config(text=status)
            except Exception:
                pass
            # Schedule next update in 500ms
            self.root.after(500, self._monitor_rate_limit)

    def _add_to_cw_feed(self, device_name: str, device_type: str):
        """Add a fetched device to the live feed display."""
        if hasattr(self, 'cw_progress_win') and self.cw_progress_win.winfo_exists():
            # Format: "✓ DeviceName (Type)"
            entry = f"✓ {device_name[:40]}{'...' if len(device_name) > 40 else ''} ({device_type})"

            # Add to internal list
            self._cw_feed_items.append(entry)

            # Keep only last 6 items
            if len(self._cw_feed_items) > 6:
                self._cw_feed_items = self._cw_feed_items[-6:]

            # Update listbox
            self.cw_feed_list.delete(0, tk.END)
            for item in self._cw_feed_items:
                self.cw_feed_list.insert(tk.END, item)

            # Auto-scroll to bottom
            self.cw_feed_list.see(tk.END)

    def _do_refresh_cw(self):
        """
        Background thread for CW refresh with incremental fetch.
        Refactored to use standard Database class and cw_devices table.
        """
        db = None
        try:
            from .cw_client import ConnectWiseClient
            from .config import load_config
            from .db import Database

            # Load config and create client
            config = load_config()
            self._cw_client = ConnectWiseClient(config.connectwise)
            db = Database()

            # Fetch basic endpoint list first
            self.root.after(0, lambda: self._update_cw_progress(0, 100, "Fetching endpoint list...", ""))
            logger.info("Fetching CW endpoint list...")
            endpoints = self._cw_client.get_devices()
            total_endpoints = len(endpoints)
            logger.info(f"Found {total_endpoints} endpoints")

            # Check which endpoints need detailed fetch (incremental)
            self.root.after(0, lambda: self._update_cw_progress(0, 100,
                "Checking for existing data...", "Optimizing API calls"))

            # Get existing endpoint IDs via public API
            existing_ids = db.get_cw_device_ids()

            incomplete_ids = []
            for ep in endpoints:
                ep_id = ep.get("endpointId")
                if ep_id and ep_id not in existing_ids:
                    incomplete_ids.append(ep_id)

            already_complete = total_endpoints - len(incomplete_ids)
            need_fetch = len(incomplete_ids)

            if need_fetch == 0:
                # All endpoints already have complete data
                logger.info(f"All {total_endpoints} endpoints already have complete data - skipping API calls")
                self.root.after(0, lambda: self._update_cw_progress(100, 100,
                    "All data up to date!", f"{total_endpoints} endpoints already complete"))
                db.close()
                db = None
                self.root.after(0, lambda: self._cw_refresh_done(total_endpoints))
                return

            logger.info(f"Incremental fetch: {already_complete} complete, {need_fetch} need fetch")

            # Start rate monitor
            self.root.after(100, self._monitor_rate_limit)

            # Parallel Execution
            import concurrent.futures
            # 2 workers is optimal — the rate limiter serializes requests via
            # _next_allowed_time slots, so more threads just queue up waiting.
            # 2 threads allow one to sleep while the other fires, keeping the
            # pipeline full without wasting OS resources on idle threads.
            max_workers = 2

            fetched = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit tasks
                future_to_ep = {
                    executor.submit(self._cw_client.get_endpoint_details, ep["endpointId"]): ep
                    for ep in endpoints
                    if ep.get("endpointId") and ep.get("endpointId") not in existing_ids
                }

                for future in concurrent.futures.as_completed(future_to_ep):
                    if self._cw_cancelled:
                        break

                    ep = future_to_ep[future]
                    fetched += 1

                    # Update progress bar only (rate limit is handled by monitor)
                    status = f"Fetching {fetched} of {need_fetch} (skipped {already_complete} complete)"
                    self.root.after(0, lambda f=fetched, n=need_fetch, s=status:
                                    self._update_cw_progress(f, n, s, ""))

                    try:
                        details = future.result()

                        # Store
                        # Ensure endpointId is present (API detail view might omit it)
                        if "endpointId" not in details:
                            details["endpointId"] = ep["endpointId"]
                        db.store_cw_devices([details])

                        # Feed
                        d_name = details.get("friendlyName", ep.get("endpointId", "")[:20])
                        d_type = details.get("endpointType", "Unknown")
                        self.root.after(0, lambda n=d_name, t=d_type: self._add_to_cw_feed(n, t))

                    except Exception as e:
                        logger.warning(f"Failed to fetch {ep.get('endpointId')}: {e}")

            db.close()
            db = None

            if self._cw_cancelled:
                self.root.after(0, self._cw_refresh_cancelled)
                return

            # Final count
            final_db = Database()
            try:
                final_count = final_db.get_cw_device_count()
            finally:
                final_db.close()

            logger.info(f"CW refresh complete: {final_count} endpoints with full data")
            self.root.after(0, lambda: self._cw_refresh_done(final_count))

        except Exception as e:
            if "cancelled" in str(e).lower():
                self.root.after(0, self._cw_refresh_cancelled)
            else:
                logger.error(f"CW refresh failed: {e}")
                self.root.after(0, lambda: self._cw_refresh_error(str(e)))
        finally:
            if db:
                db.close()

    def _cw_refresh_done(self, count: int):
        """Handle successful CW refresh completion."""
        if hasattr(self, 'cw_progress_win') and self.cw_progress_win.winfo_exists():
            self.cw_progress_win.destroy()
        self._refresh_complete("ConnectWise", count)

    def _cw_refresh_cancelled(self):
        """Handle CW refresh cancellation."""
        if hasattr(self, 'cw_progress_win') and self.cw_progress_win.winfo_exists():
            self.cw_progress_win.destroy()
        self.sync_btn.config(state=tk.NORMAL)
        messagebox.showinfo("Cancelled", "ConnectWise refresh was cancelled.")

    def _cw_refresh_error(self, error: str):
        """Handle CW refresh error."""
        if hasattr(self, 'cw_progress_win') and self.cw_progress_win.winfo_exists():
            self.cw_progress_win.destroy()
        self.sync_btn.config(state=tk.NORMAL)
        messagebox.showerror("Error", f"CW refresh failed:\n{error}")

    def _refresh_sdp_data(self):
        """Refresh ServiceDesk Plus data with progress dialog."""
        if messagebox.askyesno("Refresh SDP Data",
                               "This will re-fetch all data from ServiceDesk Plus.\n"
                               "This may take several minutes.\n\n"
                               "Proceed?"):
            self.sync_btn.config(state=tk.DISABLED)
            self._sdp_client = None  # Will be set in thread
            self._sdp_cancelled = False
            self._create_sdp_progress_dialog()
            thread = threading.Thread(target=self._do_refresh_sdp)
            thread.daemon = True
            thread.start()

    def _create_sdp_progress_dialog(self):
        """Create progress dialog for SDP refresh with live feed."""
        self.sdp_progress_win = tk.Toplevel(self.root)
        self.sdp_progress_win.title("Refreshing ServiceDesk Plus Data")
        self.sdp_progress_win.geometry("500x350")
        self.sdp_progress_win.transient(self.root)
        self.sdp_progress_win.protocol("WM_DELETE_WINDOW", self._cancel_sdp_refresh)

        # Center on parent
        self.sdp_progress_win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 500) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 350) // 2
        self.sdp_progress_win.geometry(f"+{x}+{y}")

        ttk.Label(self.sdp_progress_win, text="Fetching ServiceDesk Plus Workstations",
                  font=("Segoe UI", 12, "bold")).pack(pady=(15, 10))

        self.sdp_progress_bar = ttk.Progressbar(self.sdp_progress_win, length=450,
                                                mode="determinate", maximum=100)
        self.sdp_progress_bar.pack(pady=5)

        self.sdp_progress_label = ttk.Label(self.sdp_progress_win, text="Connecting...")
        self.sdp_progress_label.pack(pady=3)

        self.sdp_status_label = ttk.Label(self.sdp_progress_win, text="", foreground="gray")
        self.sdp_status_label.pack(pady=3)

        # Live feed frame - shows recently fetched items
        feed_frame = ttk.LabelFrame(self.sdp_progress_win, text="Recently Fetched", padding=5)
        feed_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        # Listbox for live feed (shows last N items)
        self.sdp_feed_list = tk.Listbox(feed_frame, height=6, font=("Consolas", 9))
        self.sdp_feed_list.pack(fill=tk.BOTH, expand=True)

        # Initialize feed items list
        self._sdp_feed_items = []

        ttk.Button(self.sdp_progress_win, text="Cancel",
                   command=self._cancel_sdp_refresh).pack(pady=10)

    def _cancel_sdp_refresh(self):
        """Cancel the SDP refresh operation."""
        self._sdp_cancelled = True
        if self._sdp_client:
            self._sdp_client.cancel()
        if hasattr(self, 'sdp_progress_win') and self.sdp_progress_win.winfo_exists():
            self.sdp_progress_label.config(text="Cancelling...")
        logger.info("SDP refresh cancelled by user")

    def _update_sdp_progress(self, current: int, total: int, status: str, detail: str = ""):
        """Update SDP progress dialog from main thread."""
        if hasattr(self, 'sdp_progress_win') and self.sdp_progress_win.winfo_exists():
            pct = (current / total * 100) if total > 0 else 0
            self.sdp_progress_bar["value"] = pct
            self.sdp_progress_label.config(text=status)
            self.sdp_status_label.config(text=detail)

    def _add_to_sdp_feed(self, ws_name: str, ws_type: str):
        """Add a fetched workstation to the live feed display."""
        if hasattr(self, 'sdp_progress_win') and self.sdp_progress_win.winfo_exists():
            # Format: "✓ WorkstationName (Type)"
            entry = f"✓ {ws_name[:40]}{'...' if len(ws_name) > 40 else ''} ({ws_type})"

            # Add to internal list
            self._sdp_feed_items.append(entry)

            # Keep only last 6 items
            if len(self._sdp_feed_items) > 6:
                self._sdp_feed_items = self._sdp_feed_items[-6:]

            # Update listbox
            self.sdp_feed_list.delete(0, tk.END)
            for item in self._sdp_feed_items:
                self.sdp_feed_list.insert(tk.END, item)

            # Auto-scroll to bottom
            self.sdp_feed_list.see(tk.END)

    def _do_refresh_sdp(self):
        """
        Background thread for SDP refresh with incremental fetch optimization.
        Refactored to use standard Database class and sdp_assets table.
        """
        db = None
        try:
            from .sdp_client import ServiceDeskPlusClient
            from .config import load_sdp_config
            from .db import Database

            # Load config and create client
            config = load_sdp_config()
            self._sdp_client = ServiceDeskPlusClient(config)
            db = Database()

            # INCREMENTAL: Get existing IDs from database first
            self.root.after(0, lambda: self._update_sdp_progress(0, 100,
                "Checking existing data...", "Optimizing API calls"))

            # Get existing asset IDs via public API
            existing_ids = db.get_sdp_asset_ids()

            already_have = len(existing_ids)
            logger.info(f"Found {already_have} existing SDP assets in database")

            # Update initial status
            self.root.after(0, lambda: self._update_sdp_progress(0, 100,
                f"Fetching assets... ({already_have} already in DB)", ""))
            logger.info("Fetching SDP assets...")

            # Track new vs existing during fetch
            new_count = 0
            skipped_count = 0

            # Define progress callback
            def on_progress(fetched, total, page):
                nonlocal new_count, skipped_count
                if self._sdp_cancelled:
                    return

                # Count new vs existing in this page
                for ws in page:
                    ws_id = str(ws.get("id", ""))
                    if ws_id and ws_id not in existing_ids:
                        new_count += 1
                        # Add to live feed (only new ones)
                        ws_name = ws.get("name", ws.get("id", "Unknown"))
                        self.root.after(0, lambda n=ws_name: self._add_to_sdp_feed(n, "NEW"))
                    else:
                        skipped_count += 1

                status = f"Fetching: {fetched} of {total if total > 0 else '?'} ({new_count} new, {skipped_count} existing)"
                rate_status = self._sdp_client.rate_limiter.get_status_line()
                self.root.after(0, lambda f=fetched, t=total, s=status, d=rate_status:
                                self._update_sdp_progress(f, t if t > 0 else fetched, s, d))

            # Fetch all assets with progress callback
            # (API requires fetching all pages - we optimize by not storing existing)
            workstations = self._sdp_client.get_all_assets(progress_callback=on_progress)

            if self._sdp_cancelled:
                db.close()
                db = None
                self.root.after(0, self._sdp_refresh_cancelled)
                return

            # Store ALL records to ensure we have fresh data (updates handled by DB)
            self.root.after(0, lambda: self._update_sdp_progress(100, 100,
                f"Storing {len(workstations)} records...", ""))

            stored = 0
            if workstations:
                stored = db.store_sdp_assets(workstations)

            db.close()
            db = None
            logger.info(f"Stored {stored} SDP assets (Total fetched: {len(workstations)})")
            self.root.after(0, lambda: self._sdp_refresh_done_incremental(stored, skipped_count))

        except Exception as e:
            logger.error(f"SDP refresh failed: {e}")
            self.root.after(0, lambda: self._sdp_refresh_error(str(e)))
        finally:
            if db:
                db.close()

    def _sdp_refresh_done(self, count: int):
        """Handle successful SDP refresh completion."""
        if hasattr(self, 'sdp_progress_win') and self.sdp_progress_win.winfo_exists():
            self.sdp_progress_win.destroy()
        self._refresh_complete("ServiceDesk Plus", count)

    def _sdp_refresh_done_incremental(self, new_count: int, skipped_count: int):
        """Handle successful SDP refresh with incremental stats."""
        if hasattr(self, 'sdp_progress_win') and self.sdp_progress_win.winfo_exists():
            self.sdp_progress_win.destroy()
        self.sync_btn.config(state=tk.NORMAL)

        # Build detailed message
        total = new_count + skipped_count
        msg = f"ServiceDesk Plus data refreshed successfully.\n\n"
        msg += f"Total workstations: {total}\n"
        msg += f"  • New (stored): {new_count}\n"
        msg += f"  • Existing (refreshed): {skipped_count}"

        if new_count == 0 and skipped_count > 0:
            msg += "\n\n✓ All data up to date - no new records found."

        messagebox.showinfo("Refresh Complete", msg)
        self._load_data()

    def _sdp_refresh_cancelled(self):
        """Handle SDP refresh cancellation."""
        if hasattr(self, 'sdp_progress_win') and self.sdp_progress_win.winfo_exists():
            self.sdp_progress_win.destroy()
        self.sync_btn.config(state=tk.NORMAL)
        messagebox.showinfo("Cancelled", "ServiceDesk Plus refresh was cancelled.")

    def _sdp_refresh_error(self, error: str):
        """Handle SDP refresh error."""
        if hasattr(self, 'sdp_progress_win') and self.sdp_progress_win.winfo_exists():
            self.sdp_progress_win.destroy()
        self.sync_btn.config(state=tk.NORMAL)
        messagebox.showerror("Error", f"SDP refresh failed:\n{error}")

    def _refresh_complete(self, source: str, count: int = 0):
        """Handle refresh completion."""
        self.sync_btn.config(state=tk.NORMAL)
        msg = f"{source} data refreshed successfully."
        if count > 0:
            msg += f"\n\nFetched and stored {count} records."
        messagebox.showinfo("Refresh Complete", msg)
        self._load_data()

    def _check_orphans(self):
        """Check for orphaned entries and database status."""
        conn = None
        cw_count = 0
        sdp_count = 0
        pending_syncs = 0
        fetch_info = []

        try:
            conn = sqlite3.connect(str(DEFAULT_DB_PATH))
            cursor = conn.cursor()

            # Get counts (handle missing tables on first run)
            try:
                cursor.execute("SELECT COUNT(*) FROM cw_devices")
                cw_count = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                pass  # Table doesn't exist yet

            try:
                cursor.execute("SELECT COUNT(*) FROM sdp_assets")
                sdp_count = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                pass  # Table doesn't exist yet

            # Check for sync log entries
            try:
                cursor.execute("SELECT COUNT(*) FROM sync_log WHERE reverted = 0")
                result = cursor.fetchone()
                pending_syncs = result[0] if result else 0
            except sqlite3.OperationalError:
                pass  # Table doesn't exist yet

            # Check last fetch times from cw_devices and sdp_assets
            try:
                cursor.execute("""
                    SELECT 'ConnectWise' AS source, MAX(fetched_at) AS last_fetch, COUNT(*) AS total
                    FROM cw_devices
                    UNION ALL
                    SELECT 'ServiceDesk Plus', MAX(fetched_at), COUNT(*)
                    FROM sdp_assets
                """)
                fetch_info = [(r[0], r[1], r[2]) for r in cursor.fetchall() if r[1]]
            except sqlite3.OperationalError:
                pass  # Tables don't exist yet
        finally:
            if conn:
                conn.close()

        # Check for orphaned CW entries (not in current API response)
        # This would require comparing with a fresh API call - for now show what we have

        # Check matches vs creates
        create_count = len([i for i in self.items if i.action == SyncAction.CREATE])
        update_count = len([i for i in self.items if i.action == SyncAction.UPDATE])

        # Show results in popup
        win = tk.Toplevel(self.root)
        win.title("Database Status & Orphan Check")
        win.geometry("550x500")
        win.transient(self.root)

        ttk.Label(win, text="Database Status", font=("Segoe UI", 14, "bold")).pack(pady=10)

        info_frame = ttk.Frame(win, padding=20)
        info_frame.pack(fill=tk.BOTH, expand=True)

        info = f"""
DATABASE RECORDS:
─────────────────────────────────────────
  • ConnectWise devices: {cw_count}
  • ServiceDesk Plus workstations: {sdp_count}

SYNC ANALYSIS:
─────────────────────────────────────────
  • Devices matching (UPDATE): {update_count}
  • Devices to create (CREATE): {create_count}
  • Pending (un-reverted) syncs: {pending_syncs}

LAST FETCH TIMES:
─────────────────────────────────────────
"""
        if fetch_info:
            for source, last_fetch, total in fetch_info:
                info += f"  • {source}: {last_fetch}\n    ({total} records fetched)\n"
        else:
            info += "  No fetch records found.\n"

        info += f"""
ORPHAN CHECK:
─────────────────────────────────────────
  To identify orphaned entries (records in DB that
  no longer exist in source systems), use the
  "Refresh CW Data" or "Refresh SDP Data" buttons
  to re-fetch current data.

  After refresh, records not in the new API response
  will be automatically replaced.
"""

        text = tk.Text(info_frame, wrap=tk.WORD, font=("Consolas", 10))
        text.insert(tk.END, info)
        text.config(state=tk.DISABLED)
        text.pack(fill=tk.BOTH, expand=True)

        ttk.Button(win, text="Close", command=win.destroy).pack(pady=10)

    def _open_settings(self):
        """Open the settings/credentials configuration dialog."""
        SettingsDialog(self.root)

    def _open_help(self):
        """Open the help dialog with automation instructions."""
        HelpDialog(self.root)

    def run(self):
        """Run the application."""
        self.root.mainloop()
        self.engine.close()


class SettingsDialog:
    """Dialog for configuring API credentials and settings."""

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Settings - API Credentials")
        self.dialog.geometry("650x550")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # Center on parent
        self.dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 650) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 550) // 2
        self.dialog.geometry(f"+{x}+{y}")

        self._create_widgets()
        self._load_credentials()

    def _create_widgets(self):
        """Create the settings form."""
        main = ttk.Frame(self.dialog, padding="20")
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        ttk.Label(main, text="API Credentials Configuration",
                  font=("Segoe UI", 14, "bold")).pack(anchor=tk.W)
        ttk.Label(main, text="Configure your ConnectWise and ServiceDesk Plus API credentials.",
                  foreground="gray").pack(anchor=tk.W, pady=(0, 15))

        # Notebook for sections
        notebook = ttk.Notebook(main)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: ConnectWise
        cw_frame = ttk.Frame(notebook, padding="15")
        notebook.add(cw_frame, text="ConnectWise RMM")
        self._create_cw_fields(cw_frame)

        # Tab 2: ServiceDesk Plus
        sdp_frame = ttk.Frame(notebook, padding="15")
        notebook.add(sdp_frame, text="ServiceDesk Plus")
        self._create_sdp_fields(sdp_frame)

        # Tab 3: API Endpoints
        endpoints_frame = ttk.Frame(notebook, padding="15")
        notebook.add(endpoints_frame, text="API Endpoints")
        self._create_endpoint_fields(endpoints_frame)

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(15, 0))

        ttk.Button(btn_frame, text="Test Connections",
                   command=self._test_connections).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Cancel",
                   command=self.dialog.destroy).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Save",
                   command=self._save_credentials).pack(side=tk.RIGHT)

    def _create_cw_fields(self, parent):
        """Create ConnectWise credential fields."""
        ttk.Label(parent, text="ConnectWise RMM API Credentials",
                  font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        ttk.Label(parent, text="Client ID:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.cw_client_id = ttk.Entry(parent, width=50)
        self.cw_client_id.grid(row=1, column=1, sticky=tk.W, padx=(10, 0))

        ttk.Label(parent, text="Client Secret:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.cw_client_secret = ttk.Entry(parent, width=50, show="•")
        self.cw_client_secret.grid(row=2, column=1, sticky=tk.W, padx=(10, 0))

        # Show/hide button
        self.cw_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="Show secret", variable=self.cw_show_var,
                        command=lambda: self.cw_client_secret.config(
                            show="" if self.cw_show_var.get() else "•"
                        )).grid(row=3, column=1, sticky=tk.W, padx=(10, 0))

        ttk.Label(parent, text="Get these from ConnectWise Control admin panel.",
                  foreground="gray").grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(15, 0))

    def _create_sdp_fields(self, parent):
        """Create ServiceDesk Plus credential fields."""
        ttk.Label(parent, text="Zoho OAuth 2.0 Credentials",
                  font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        ttk.Label(parent, text="Client ID:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.zoho_client_id = ttk.Entry(parent, width=50)
        self.zoho_client_id.grid(row=1, column=1, sticky=tk.W, padx=(10, 0))

        ttk.Label(parent, text="Client Secret:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.zoho_client_secret = ttk.Entry(parent, width=50, show="•")
        self.zoho_client_secret.grid(row=2, column=1, sticky=tk.W, padx=(10, 0))

        ttk.Label(parent, text="Refresh Token:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.zoho_refresh_token = ttk.Entry(parent, width=50, show="•")
        self.zoho_refresh_token.grid(row=3, column=1, sticky=tk.W, padx=(10, 0))

        # Show/hide button
        self.sdp_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="Show secrets", variable=self.sdp_show_var,
                        command=self._toggle_sdp_secrets).grid(row=4, column=1, sticky=tk.W, padx=(10, 0))

        ttk.Label(parent, text="Get these from Zoho API Console: https://api-console.zoho.com/",
                  foreground="gray").grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(15, 0))

    def _toggle_sdp_secrets(self):
        """Toggle visibility of SDP secrets."""
        show = "" if self.sdp_show_var.get() else "•"
        self.zoho_client_secret.config(show=show)
        self.zoho_refresh_token.config(show=show)

    def _create_endpoint_fields(self, parent):
        """Create API endpoint fields."""
        ttk.Label(parent, text="API Endpoints",
                  font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        ttk.Label(parent, text="Zoho Accounts URL:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.zoho_accounts_url = ttk.Entry(parent, width=50)
        self.zoho_accounts_url.grid(row=1, column=1, sticky=tk.W, padx=(10, 0))

        ttk.Label(parent, text="Zoho Token URL:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.zoho_token_url = ttk.Entry(parent, width=50)
        self.zoho_token_url.grid(row=2, column=1, sticky=tk.W, padx=(10, 0))

        ttk.Label(parent, text="SDP API Base URL:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.sdp_api_url = ttk.Entry(parent, width=50)
        self.sdp_api_url.grid(row=3, column=1, sticky=tk.W, padx=(10, 0))

        ttk.Label(parent, text="Data Center Presets:",
                  font=("Segoe UI", 10, "bold")).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(20, 5))

        preset_frame = ttk.Frame(parent)
        preset_frame.grid(row=5, column=0, columnspan=2, sticky=tk.W)
        ttk.Button(preset_frame, text="EU (Europe)", command=lambda: self._set_preset("EU")).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_frame, text="US (United States)", command=lambda: self._set_preset("US")).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_frame, text="IN (India)", command=lambda: self._set_preset("IN")).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_frame, text="AU (Australia)", command=lambda: self._set_preset("AU")).pack(side=tk.LEFT, padx=2)

    def _set_preset(self, region: str):
        """Set endpoint URLs based on region preset."""
        presets = {
            "EU": {
                "accounts": "https://accounts.zoho.eu",
                "token": "https://accounts.zoho.eu/oauth/v2/token",
                "sdp": "https://sdpondemand.manageengine.eu/api/v3"
            },
            "US": {
                "accounts": "https://accounts.zoho.com",
                "token": "https://accounts.zoho.com/oauth/v2/token",
                "sdp": "https://sdpondemand.manageengine.com/api/v3"
            },
            "IN": {
                "accounts": "https://accounts.zoho.in",
                "token": "https://accounts.zoho.in/oauth/v2/token",
                "sdp": "https://sdpondemand.manageengine.in/api/v3"
            },
            "AU": {
                "accounts": "https://accounts.zoho.com.au",
                "token": "https://accounts.zoho.com.au/oauth/v2/token",
                "sdp": "https://sdpondemand.manageengine.com.au/api/v3"
            }
        }
        if region in presets:
            self.zoho_accounts_url.delete(0, tk.END)
            self.zoho_accounts_url.insert(0, presets[region]["accounts"])
            self.zoho_token_url.delete(0, tk.END)
            self.zoho_token_url.insert(0, presets[region]["token"])
            self.sdp_api_url.delete(0, tk.END)
            self.sdp_api_url.insert(0, presets[region]["sdp"])

    def _load_credentials(self):
        """Load existing credentials from file."""
        creds_file = Path("credentials.env")
        if not creds_file.exists():
            # Set default EU endpoints
            self._set_preset("EU")
            return

        creds = {}
        with open(creds_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    creds[key.strip()] = value.strip()

        # Populate fields
        self.cw_client_id.insert(0, creds.get("CLIENT_ID", ""))
        self.cw_client_secret.insert(0, creds.get("CLIENT_SECRET", ""))
        self.zoho_client_id.insert(0, creds.get("ZOHO_CLIENT_ID", ""))
        self.zoho_client_secret.insert(0, creds.get("ZOHO_CLIENT_SECRET", ""))
        self.zoho_refresh_token.insert(0, creds.get("ZOHO_REFRESH_TOKEN", ""))
        self.zoho_accounts_url.insert(0, creds.get("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.eu"))
        self.zoho_token_url.insert(0, creds.get("ZOHO_TOKEN_URL", "https://accounts.zoho.eu/oauth/v2/token"))
        self.sdp_api_url.insert(0, creds.get("SDP_API_BASE_URL", "https://sdpondemand.manageengine.eu/api/v3"))

    def _save_credentials(self):
        """Save credentials to file."""
        content = f"""# CWtoSDP API Credentials
# Auto-generated by Settings dialog

# ConnectWise RMM API Credentials
CLIENT_ID={self.cw_client_id.get()}
CLIENT_SECRET={self.cw_client_secret.get()}

# Zoho OAuth 2.0 Credentials (ServiceDesk Plus)
ZOHO_CLIENT_ID={self.zoho_client_id.get()}
ZOHO_CLIENT_SECRET={self.zoho_client_secret.get()}
ZOHO_REFRESH_TOKEN={self.zoho_refresh_token.get()}

# API Endpoints
ZOHO_ACCOUNTS_URL={self.zoho_accounts_url.get()}
ZOHO_TOKEN_URL={self.zoho_token_url.get()}
SDP_API_BASE_URL={self.sdp_api_url.get()}

# Granted Scopes
SCOPES=SDPOnDemand.assets.ALL,SDPOnDemand.cmdb.ALL,SDPOnDemand.requests.READ
"""
        with open("credentials.env", "w") as f:
            f.write(content)

        messagebox.showinfo("Settings Saved", "Credentials saved to credentials.env\n\nRestart the application for changes to take effect.")
        self.dialog.destroy()

    def _test_connections(self):
        """Test API connections using the current form field values (not saved file)."""
        from .config import ConnectWiseConfig, ServiceDeskPlusConfig

        results = []

        # Test ConnectWise — build config from form fields
        try:
            from .cw_client import ConnectWiseClient
            cw_config = ConnectWiseConfig(
                client_id=self.cw_client_id.get().strip(),
                client_secret=self.cw_client_secret.get().strip(),
            )
            client = ConnectWiseClient(cw_config)
            client.authenticate()
            results.append("✅ ConnectWise: Authentication successful")
        except Exception as e:
            results.append(f"❌ ConnectWise: {str(e)[:80]}")

        # Test ServiceDesk Plus — build config from form fields
        try:
            from .sdp_client import ServiceDeskPlusClient
            sdp_config = ServiceDeskPlusConfig(
                client_id=self.zoho_client_id.get().strip(),
                client_secret=self.zoho_client_secret.get().strip(),
                refresh_token=self.zoho_refresh_token.get().strip(),
                accounts_url=self.zoho_accounts_url.get().strip(),
                api_base_url=self.sdp_api_url.get().strip(),
            )
            client = ServiceDeskPlusClient(sdp_config)
            client.refresh_access_token()
            results.append("✅ ServiceDesk Plus: Authentication successful")
        except Exception as e:
            results.append(f"❌ ServiceDesk Plus: {str(e)[:80]}")

        messagebox.showinfo("Connection Test Results", "\n".join(results))


# =============================================================================
# HELP DIALOG CLASS
# =============================================================================

class HelpDialog:
    """
    Help dialog with automation setup instructions.

    Provides a tabbed interface with:
    - Getting Started guide
    - Automation setup for Windows, Mac, Linux
    - Troubleshooting tips
    """

    def __init__(self, parent):
        """
        Create the help dialog.

        Args:
            parent: Parent window
        """
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Help - CWtoSDP Sync Manager")
        self.dialog.geometry("700x600")
        self.dialog.resizable(True, True)
        self.dialog.transient(parent)

        # Center on parent
        self.dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 700) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 600) // 2
        self.dialog.geometry(f"+{x}+{y}")

        self._create_content()

    def _create_content(self):
        """Create the help content with tabs."""
        notebook = ttk.Notebook(self.dialog)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Tab 1: Getting Started
        self._create_getting_started_tab(notebook)

        # Tab 2: How It Works (NEW - Legend, behavior, etc.)
        self._create_how_it_works_tab(notebook)

        # Tab 3: Automation Setup
        self._create_automation_tab(notebook)

        # Tab 4: Troubleshooting
        self._create_troubleshooting_tab(notebook)

        # Close button
        ttk.Button(self.dialog, text="Close", command=self.dialog.destroy).pack(pady=10)

    def _create_getting_started_tab(self, notebook):
        """Create the Getting Started tab."""
        frame = ttk.Frame(notebook, padding="10")
        notebook.add(frame, text="Getting Started")

        text = tk.Text(frame, wrap=tk.WORD, font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)

        content = """CWtoSDP SYNC MANAGER - GETTING STARTED
======================================

This tool synchronizes devices from ConnectWise RMM to ServiceDesk Plus CMDB.

QUICK START:
1. Click ⚙️ Settings to configure your API credentials
2. Click 🔄 Refresh CW Data to fetch devices from ConnectWise
3. Click 🔄 Refresh SDP Data to fetch existing CMDB entries
4. Review the Sync Preview tab to see what will be synced
5. Use checkboxes to select which items to sync
6. Click 🔍 Preview Sync to see what would happen (dry run)
7. Check ☑️ Enable Real Sync to enable live mode
8. Click ⚠️ Execute Real Sync to create records in SDP

TABS:
• Sync Preview - All devices with their sync status
• By Category - Devices grouped by type (Laptop, Server, etc.)
• Field Mapping - How CW fields map to SDP fields
• Results - Shows details after sync execution

SAFETY FEATURES:
• Dry run mode is ON by default (no changes made)
• Confirmation dialog before real sync
• Revert button to undo last sync
• All actions are logged to logs/ folder

DEVICE CLASSIFICATION:
• Laptops: ThinkPad, ProBook, and similar models
• Desktops: Standard workstations
• Virtual Servers: VMware/Hyper-V VMs (detected by serial)
• Physical Servers: Real hardware servers
• Network Devices: Switches, routers, firewalls
"""
        text.insert("1.0", content)
        text.config(state=tk.DISABLED)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _create_how_it_works_tab(self, notebook):
        """Create the How It Works tab with legend and behavior info."""
        frame = ttk.Frame(notebook, padding="10")
        notebook.add(frame, text="How It Works")

        text = tk.Text(frame, wrap=tk.WORD, font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)

        content = """HOW CWtoSDP WORKS
=================

This tool syncs device data from ConnectWise RMM to ServiceDesk Plus CMDB.

═══════════════════════════════════════════════════════════
WHAT THE PROGRAM DOES
═══════════════════════════════════════════════════════════

1. FETCH DATA
   • Connects to ConnectWise RMM API → fetches all endpoints
   • Connects to ServiceDesk Plus API → fetches existing CMDB CIs
   • Stores data locally in SQLite database for comparison

2. CLASSIFY DEVICES
   • Analyzes each CW device (model, serial, etc.)
   • Assigns category: Laptop, Desktop, Virtual Server,
     Physical Server, or Network Device
   • Maps to appropriate SDP CI type

3. MATCH & COMPARE
   • Tries to match CW devices to existing SDP records
   • Match by hostname (primary) or serial number (secondary)
   • Compares field values to detect changes

4. SYNC TO SDP
   • CREATE: New devices not in SDP → creates new CI
   • UPDATE: Matched devices with changes → updates CI fields

═══════════════════════════════════════════════════════════
PREVIEW LEGEND - ROW COLORS
═══════════════════════════════════════════════════════════

  🟢 GREEN ROWS = CREATE (New Items)
     Device not found in SDP, will be created as new CI

  🔵 BLUE ROWS = UPDATE (Existing Items)
     Device matched to existing SDP CI, will update fields

  ☑ = Selected for sync
  ☐ = Not selected (will be skipped)

═══════════════════════════════════════════════════════════
PREVIEW LEGEND - FIELD INDICATORS
═══════════════════════════════════════════════════════════

For each field in the preview, indicators show what will happen:

  ★ value           = NEW FIELD
                      Empty in SDP, this value will be added
                      Example: ★ 192.168.1.50

  old → new         = CHANGED FIELD
                      Different value in SDP, will be updated
                      Example: Win 10 Pro → Windows 11 Pro

  value (no prefix) = UNCHANGED FIELD
                      Same value in both systems, no change

═══════════════════════════════════════════════════════════
MATCHING LOGIC
═══════════════════════════════════════════════════════════

Devices are matched to SDP records in this order:

1. HOSTNAME MATCH (Primary)
   • CW "friendlyName" compared to SDP "name"
   • Case-insensitive comparison
   • Most reliable method

2. SERIAL NUMBER MATCH (Secondary)
   • Only if hostname doesn't match
   • Excludes VMware UUIDs (virtual machines)
   • Useful for renamed machines

If no match found → CREATE action
If match found → UPDATE action

═══════════════════════════════════════════════════════════
CI TYPE MAPPING
═══════════════════════════════════════════════════════════

  Category          → SDP CI Type
  ─────────────────────────────────────────────────────────
  Laptop            → asset_workstations
  Desktop           → asset_workstations
  Virtual Server    → asset_virtual_machines
  Physical Server   → asset_servers
  Network Device    → asset_switches

═══════════════════════════════════════════════════════════
FIELD MAPPING (ConnectWise → ServiceDesk Plus)
═══════════════════════════════════════════════════════════

  CW Field                → SDP CI Attribute
  ─────────────────────────────────────────────────────────
  friendlyName            → name
  system.serialNumber     → ci_attributes.txt_serial_number
  operatingSystem.name    → ci_attributes.txt_os
  system.manufacturer     → ci_attributes.txt_manufacturer
  addresses[0].ipAddress  → ci_attributes.txt_ip_address
  addresses[0].macAddress → ci_attributes.txt_mac_address

═══════════════════════════════════════════════════════════
SELECTION BEHAVIOR
═══════════════════════════════════════════════════════════

• Single-click on any row toggles its selection
• ✓ All / ✗ All: Select/deselect all items (including hidden)
• ✓ Filtered / ✗ Filtered: Select/deselect only visible items
• Use Action/Category filters to narrow down the list
• Selections persist when filters change

═══════════════════════════════════════════════════════════
DRY RUN VS REAL SYNC
═══════════════════════════════════════════════════════════

DRY RUN (Default - Safe):
  • Shows what WOULD happen without making any changes
  • Two-level safety: write methods return dummy success,
    and all POST/PUT/DELETE HTTP requests are blocked
  • No API calls made — instant and completely safe
  • Results show "would_create" or "would_update"

REAL SYNC (☑ Enable Real Sync):
  • Actually creates/updates CIs in SDP
  • Requires confirmation dialog with summary
  • Results show "created" or "updated"
  • Can be reverted with Revert button (created items)

═══════════════════════════════════════════════════════════
RATE LIMITING
═══════════════════════════════════════════════════════════

The tool automatically manages API call speed:

  • Backoff: Doubles wait time on 429 errors (max 120s)
  • Recovery: Gradually speeds back up after limit clears
  • Dynamic: Halves interval when far above target,
    fine-tunes when close to normal speed
  • Per-API: CW and SDP have independent rate limiters

No configuration needed — fully automatic.
"""
        text.insert("1.0", content)
        text.config(state=tk.DISABLED)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _create_automation_tab(self, notebook):
        """Create the Automation Setup tab."""
        frame = ttk.Frame(notebook, padding="10")
        notebook.add(frame, text="Automation Setup")

        text = tk.Text(frame, wrap=tk.WORD, font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)

        content = """AUTOMATED SYNC SETUP
====================

Use automation scripts to run syncs without user interaction.

AUTOMATION SCRIPTS:
• run_sync.bat     - Windows
• run_sync.command - macOS
• run_sync.sh      - Linux

COMMAND-LINE OPTIONS:
  python run_sync.py --dry-run      # Preview only (safe)
  python run_sync.py                # Real sync with prompt
  python run_sync.py --yes          # Real sync, no prompts
  python run_sync.py --create-only  # Only create new items
  python run_sync.py --preview-only # Just show plan

═══════════════════════════════════════════════════════════
WINDOWS TASK SCHEDULER
═══════════════════════════════════════════════════════════

1. Press Win+R, type: taskschd.msc

2. Click "Create Basic Task..."
   • Name: CWtoSDP Sync
   • Trigger: Daily at 2:00 AM
   • Action: Start a program

3. Set program:
   • Program: C:\\Path\\To\\CWtoSDP\\run_sync.bat
   • Start in: C:\\Path\\To\\CWtoSDP

4. Configure settings:
   • Run whether user is logged on or not
   • Run with highest privileges

═══════════════════════════════════════════════════════════
MACOS LAUNCHD
═══════════════════════════════════════════════════════════

1. Create file: ~/Library/LaunchAgents/com.cwtosdp.sync.plist

2. Add content:
   <plist version="1.0">
   <dict>
     <key>Label</key>
     <string>com.cwtosdp.sync</string>
     <key>ProgramArguments</key>
     <array>
       <string>/path/to/run_sync.command</string>
     </array>
     <key>StartCalendarInterval</key>
     <dict>
       <key>Hour</key><integer>2</integer>
       <key>Minute</key><integer>0</integer>
     </dict>
   </dict>
   </plist>

3. Load with:
   launchctl load ~/Library/LaunchAgents/com.cwtosdp.sync.plist

═══════════════════════════════════════════════════════════
LINUX CRON
═══════════════════════════════════════════════════════════

1. Edit crontab:
   crontab -e

2. Add line (runs daily at 2:00 AM):
   0 2 * * * cd /path/to/CWtoSDP && ./run_sync.sh >> logs/cron.log 2>&1

═══════════════════════════════════════════════════════════
BEST PRACTICES
═══════════════════════════════════════════════════════════

• Run at off-peak hours (2-4 AM)
• Use --create-only initially for safety
• Check logs regularly for errors
• Test with --dry-run before scheduling
• Keep credentials.env secure (600 permissions)
"""
        text.insert("1.0", content)
        text.config(state=tk.DISABLED)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _create_troubleshooting_tab(self, notebook):
        """Create the Troubleshooting tab."""
        frame = ttk.Frame(notebook, padding="10")
        notebook.add(frame, text="Troubleshooting")

        text = tk.Text(frame, wrap=tk.WORD, font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)

        content = """TROUBLESHOOTING GUIDE
=====================

COMMON ISSUES:
─────────────────────────────────────────────────────────

❌ "Credentials not found"
   → Copy credentials.env.template to credentials.env
   → Fill in your API credentials
   → Or use ⚙️ Settings to configure

❌ "401 Unauthorized" error
   → Check CLIENT_ID and CLIENT_SECRET are correct
   → For SDP, refresh token may have expired
   → Generate new Zoho OAuth tokens

❌ "Rate limit exceeded" (429 errors)
   → No action needed — handled automatically
   → The rate limiter will slow down on 429 errors
   → It recovers gradually once the limit clears
   → Halves the wait time when far above target
   → Fine-tunes when close to normal speed
   → Typical recovery: 5-10 minutes from max throttle

❌ "No devices found"
   → Click 🔄 Refresh CW Data to fetch devices
   → Check ConnectWise API credentials
   → Verify API has device permissions

❌ Script not running (automation)
   → Check file has execute permission (chmod +x)
   → Verify path in scheduler is correct
   → Check Task Scheduler history or cron logs

❌ "tkinter not found"
   → Windows: Usually included with Python
   → macOS: brew install python-tk
   → Linux: sudo apt install python3-tk

─────────────────────────────────────────────────────────
DRY RUN SAFETY
─────────────────────────────────────────────────────────

Dry run mode is ON by default. Two levels of protection:

Level 1 (Method): Each write method (create, update,
  delete) returns simulated success without any HTTP call

Level 2 (Request): All POST/PUT/DELETE HTTP requests are
  blocked even if something bypasses Level 1

Dry run is instant (no network calls) and completely safe.

─────────────────────────────────────────────────────────
LOG FILES
─────────────────────────────────────────────────────────

Application logs: logs/cwtosdp.log (rotates at 5MB, 3 backups)
Sync results:     logs/sync_results_*.json

Log levels:
• INFO  - Normal operations (includes rate limiter status)
• WARN  - Non-critical issues (rate limit hits)
• ERROR - Failures requiring attention

─────────────────────────────────────────────────────────
GETTING HELP
─────────────────────────────────────────────────────────

1. Check the README.md for documentation
2. Review logs/ folder for error details
3. Test API connections with ⚙️ Settings → Test Connections
4. For API issues, check:
   • ConnectWise: Partner portal
   • ServiceDesk Plus: Zoho API console
"""
        text.insert("1.0", content)
        text.config(state=tk.DISABLED)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)


def launch_sync_gui():
    """Launch the sync GUI."""
    app = SyncGUI()
    app.run()

