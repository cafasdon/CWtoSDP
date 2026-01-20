"""
Sync GUI for CWtoSDP.

Integrated interface showing:
1. Sync preview (what will be created/updated) with ALL fields visible
2. Field mappings as proper table
3. Category breakdown as proper GUI
4. Sync execution (create only, no overwrites)
"""

import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Dict, List, Optional

from .logger import get_logger
from .sync_engine import SyncEngine, SyncAction, SyncItem

logger = get_logger("cwtosdp.sync_gui")


class ScrollableTreeview(ttk.Frame):
    """Treeview with both horizontal and vertical scrollbars."""

    def __init__(self, parent, columns, headings, widths=None, **kwargs):
        super().__init__(parent)

        # Create canvas and scrollbars
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.h_scroll = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.v_scroll = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)

        # Create inner frame for treeview
        self.inner_frame = ttk.Frame(self.canvas)

        # Create treeview
        self.tree = ttk.Treeview(self.inner_frame, columns=columns, show="headings", **kwargs)

        # Configure columns
        for i, col in enumerate(columns):
            heading = headings[i] if i < len(headings) else col
            width = widths[i] if widths and i < len(widths) else 120
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=width, minwidth=width)

        # Tree scrollbar
        tree_scroll = ttk.Scrollbar(self.inner_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        # Pack tree
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Create window in canvas
        self.canvas.create_window((0, 0), window=self.inner_frame, anchor="nw")

        # Configure canvas scrolling
        self.canvas.configure(xscrollcommand=self.h_scroll.set)
        self.inner_frame.bind("<Configure>", self._on_frame_configure)

        # Pack scrollbars and canvas
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Configure tags
        self.tree.tag_configure("create", background="#fff3cd")
        self.tree.tag_configure("update", background="#d4edda")

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))


class SyncGUI:
    """Main sync GUI application."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CWtoSDP - Sync Manager")
        self.root.geometry("1600x900")
        self.root.minsize(1400, 800)

        # Load sync engine
        self.engine = SyncEngine()
        self.items: List[SyncItem] = []
        self.summary: Dict = {}
        self.sync_in_progress = False

        self._create_layout()
        self._load_data()

    def _create_layout(self):
        """Create the main layout."""
        # Main container
        main = ttk.Frame(self.root, padding="10")
        main.pack(fill=tk.BOTH, expand=True)

        # Top: Summary cards and sync button
        self._create_summary_section(main)

        # Middle: Notebook with tabs
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        # Tab 1: Sync Preview (all fields)
        self.preview_frame = ttk.Frame(self.notebook, padding="5")
        self.notebook.add(self.preview_frame, text="Sync Preview")
        self._create_preview_tab()

        # Tab 2: By Category (proper GUI)
        self.category_frame = ttk.Frame(self.notebook, padding="5")
        self.notebook.add(self.category_frame, text="By Category")
        self._create_category_tab()
        
        # Tab 3: Field Mapping (proper GUI)
        self.mapping_frame = ttk.Frame(self.notebook, padding="5")
        self.notebook.add(self.mapping_frame, text="Field Mapping")
        self._create_mapping_tab()

    def _create_summary_section(self, parent):
        """Create summary cards at top with sync button and controls."""
        summary_frame = ttk.Frame(parent)
        summary_frame.pack(fill=tk.X, pady=(0, 10))

        # Title
        ttk.Label(summary_frame, text="CW → SDP Sync Manager",
                  font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)

        # Right side controls frame
        controls_frame = ttk.Frame(summary_frame)
        controls_frame.pack(side=tk.RIGHT)

        # Row 1: Sync controls
        sync_row = ttk.Frame(controls_frame)
        sync_row.pack(fill=tk.X, pady=2)

        # Dry run checkbox (checked by default = dry run mode)
        self.real_sync_var = tk.BooleanVar(value=False)
        self.real_sync_check = ttk.Checkbutton(
            sync_row, text="Enable Real Sync", variable=self.real_sync_var,
            command=self._on_real_sync_toggle
        )
        self.real_sync_check.pack(side=tk.LEFT, padx=5)

        # Sync button (dry run by default)
        self.sync_btn = ttk.Button(sync_row, text="🔍 Preview Sync (Dry Run)",
                                   command=self._execute_sync)
        self.sync_btn.pack(side=tk.LEFT, padx=5)

        # Revert button
        self.revert_btn = ttk.Button(sync_row, text="↩️ Revert Last Sync",
                                     command=self._revert_sync, state=tk.DISABLED)
        self.revert_btn.pack(side=tk.LEFT, padx=5)

        # Row 2: Data refresh controls
        refresh_row = ttk.Frame(controls_frame)
        refresh_row.pack(fill=tk.X, pady=2)

        ttk.Button(refresh_row, text="🔄 Refresh CW Data",
                   command=self._refresh_cw_data).pack(side=tk.LEFT, padx=5)
        ttk.Button(refresh_row, text="🔄 Refresh SDP Data",
                   command=self._refresh_sdp_data).pack(side=tk.LEFT, padx=5)
        ttk.Button(refresh_row, text="🔍 Check Orphans",
                   command=self._check_orphans).pack(side=tk.LEFT, padx=5)

        # Stats will be added after data loads
        self.stats_frame = ttk.Frame(summary_frame)
        self.stats_frame.pack(side=tk.RIGHT, padx=20)

    def _on_real_sync_toggle(self):
        """Update sync button text based on real sync checkbox."""
        if self.real_sync_var.get():
            self.sync_btn.config(text="⚠️ Execute Real Sync")
        else:
            self.sync_btn.config(text="🔍 Preview Sync (Dry Run)")

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

        # Selection controls
        ttk.Separator(filter_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)
        ttk.Button(filter_frame, text="Select All", command=self._select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(filter_frame, text="Select None", command=self._select_none).pack(side=tk.LEFT, padx=2)
        ttk.Button(filter_frame, text="Select CREATE Only", command=self._select_create_only).pack(side=tk.LEFT, padx=2)

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

        # Bind selection (double-click to toggle checkbox)
        self.tree.bind("<Double-1>", self._toggle_selection)
        self.tree.bind("<space>", self._toggle_selected_items)

        # Configure tags for colors
        self.tree.tag_configure("create", background="#fff3cd")  # Yellow
        self.tree.tag_configure("update", background="#d4edda")  # Green
        self.tree.tag_configure("selected_create", background="#ffc107")  # Darker yellow for selected
        self.tree.tag_configure("selected_update", background="#28a745")  # Darker green for selected

        # Track selected items by their ID (cw_name)
        self.selected_items = set()
    
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

        # Tags for coloring
        self.cat_device_tree.tag_configure("create", background="#fff3cd")
        self.cat_device_tree.tag_configure("update", background="#d4edda")

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

    def _load_data(self):
        """Load sync preview data."""
        try:
            self.items = self.engine.build_sync_preview()
            self.summary = self.engine.get_summary(self.items)
            self._update_stats()
            self._populate_tree()
            self._populate_category_tab()
            self._update_filters()
        except Exception as e:
            logger.error(f"Failed to load data: {e}")
            messagebox.showerror("Error", f"Failed to load data: {e}")

    def _update_stats(self):
        """Update summary statistics."""
        for widget in self.stats_frame.winfo_children():
            widget.destroy()

        total = self.summary.get("total", 0)
        creates = self.summary.get("by_action", {}).get("create", 0)
        updates = self.summary.get("by_action", {}).get("update", 0)

        stats = [
            (f"Total: {total}", "#333"),
            (f"Create: {creates}", "#856404"),
            (f"Update: {updates}", "#155724"),
        ]

        for text, color in stats:
            lbl = ttk.Label(self.stats_frame, text=text, font=("Segoe UI", 11, "bold"))
            lbl.pack(side=tk.LEFT, padx=15)

    def _update_filters(self):
        """Update filter dropdowns."""
        categories = ["All"] + sorted(self.summary.get("by_category", {}).keys())
        self.category_filter["values"] = categories
        self.category_filter.set("All")

    def _populate_tree(self, items=None):
        """Populate the tree view with ALL fields and selection checkbox."""
        self.tree.delete(*self.tree.get_children())

        items = items or self.items
        for item in items:
            is_selected = item.cw_name in self.selected_items
            check_mark = "☑" if is_selected else "☐"

            # Determine tag based on action and selection
            if is_selected:
                tag = f"selected_{item.action.value}"
            else:
                tag = item.action.value

            fields = item.fields_to_sync
            self.tree.insert("", tk.END, iid=item.cw_name, values=(
                check_mark,
                item.cw_name,
                item.cw_category,
                item.action.value.upper(),
                item.sdp_ci_type,
                item.match_reason or "-",
                # SDP fields
                fields.get("name", ""),
                fields.get("ci_attributes_txt_serial_number", ""),
                fields.get("ci_attributes_txt_os", ""),
                fields.get("ci_attributes_txt_manufacturer", ""),
                fields.get("ci_attributes_txt_ip_address", ""),
                fields.get("ci_attributes_txt_mac_address", ""),
            ), tags=(tag,))

        self._update_selection_label()

    def _populate_category_tab(self):
        """Populate category breakdown as proper GUI."""
        # Clear existing
        self.cat_tree.delete(*self.cat_tree.get_children())

        ci_type_map = {
            "Laptop": "ci_windows_workstation",
            "Desktop": "ci_windows_workstation",
            "Virtual Server": "ci_virtual_machine",
            "Physical Server": "ci_windows_server",
            "Network Device": "ci_switch",
        }

        for category in sorted(self.summary.get("by_category", {}).keys()):
            count = self.summary["by_category"][category]
            cat_items = [i for i in self.items if i.cw_category == category]
            creates = len([i for i in cat_items if i.action == SyncAction.CREATE])
            updates = len([i for i in cat_items if i.action == SyncAction.UPDATE])
            sdp_type = ci_type_map.get(category, "ci_windows_workstation")

            self.cat_tree.insert("", tk.END, values=(
                category, count, creates, updates, sdp_type
            ), iid=category)

        # Also populate the CI type mapping tree
        self._populate_ci_mapping()

    def _populate_ci_mapping(self):
        """Populate CI type mapping in Field Mapping tab."""
        self.ci_tree.delete(*self.ci_tree.get_children())

        ci_mappings = [
            ("Laptop", "ci_windows_workstation", "ThinkPads, ProBooks, etc.", 0),
            ("Desktop", "ci_windows_workstation", "Physical workstations", 0),
            ("Virtual Server", "ci_virtual_machine", "VMware VMs", 0),
            ("Physical Server", "ci_windows_server", "Physical servers", 0),
            ("Network Device", "ci_switch", "Switches, routers, firewalls", 0),
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

    def _toggle_selection(self, event):
        """Toggle selection checkbox on double-click."""
        item_id = self.tree.identify_row(event.y)
        if item_id:
            if item_id in self.selected_items:
                self.selected_items.discard(item_id)
            else:
                self.selected_items.add(item_id)
            self._refresh_item_display(item_id)
            self._update_selection_label()

    def _toggle_selected_items(self, event):
        """Toggle selection for all currently highlighted items (space key)."""
        selection = self.tree.selection()
        for item_id in selection:
            if item_id in self.selected_items:
                self.selected_items.discard(item_id)
            else:
                self.selected_items.add(item_id)
            self._refresh_item_display(item_id)
        self._update_selection_label()

    def _refresh_item_display(self, item_id):
        """Refresh a single item's display in the tree."""
        item = next((i for i in self.items if i.cw_name == item_id), None)
        if not item:
            return

        is_selected = item_id in self.selected_items
        check_mark = "☑" if is_selected else "☐"
        tag = f"selected_{item.action.value}" if is_selected else item.action.value

        fields = item.fields_to_sync
        self.tree.item(item_id, values=(
            check_mark,
            item.cw_name,
            item.cw_category,
            item.action.value.upper(),
            item.sdp_ci_type,
            item.match_reason or "-",
            fields.get("name", ""),
            fields.get("ci_attributes_txt_serial_number", ""),
            fields.get("ci_attributes_txt_os", ""),
            fields.get("ci_attributes_txt_manufacturer", ""),
            fields.get("ci_attributes_txt_ip_address", ""),
            fields.get("ci_attributes_txt_mac_address", ""),
        ), tags=(tag,))

    def _select_all(self):
        """Select all visible items."""
        for item_id in self.tree.get_children():
            self.selected_items.add(item_id)
            self._refresh_item_display(item_id)
        self._update_selection_label()

    def _select_none(self):
        """Deselect all items."""
        self.selected_items.clear()
        self._apply_filter()  # Refresh display

    def _select_create_only(self):
        """Select only CREATE items."""
        self.selected_items.clear()
        for item in self.items:
            if item.action == SyncAction.CREATE:
                self.selected_items.add(item.cw_name)
        self._apply_filter()  # Refresh display

    def _update_selection_label(self):
        """Update the selection count label."""
        count = len(self.selected_items)
        create_count = len([i for i in self.items if i.cw_name in self.selected_items and i.action == SyncAction.CREATE])
        self.selection_label.config(text=f"Selected: {count} ({create_count} CREATE)")

    def _execute_sync(self):
        """Execute sync: CREATE only (no overwrites). Dry run by default. Uses selection if any."""
        if self.sync_in_progress:
            messagebox.showwarning("Sync in Progress", "A sync operation is already running.")
            return

        is_dry_run = not self.real_sync_var.get()

        # Get items to sync - use selection if any, otherwise all CREATE items
        if self.selected_items:
            # Only selected CREATE items
            sync_items = [i for i in self.items
                         if i.cw_name in self.selected_items and i.action == SyncAction.CREATE]
            selection_mode = "SELECTED"
        else:
            # All CREATE items
            sync_items = [i for i in self.items if i.action == SyncAction.CREATE]
            selection_mode = "ALL"

        if not sync_items:
            if self.selected_items:
                messagebox.showinfo("Nothing to Sync",
                    "No CREATE items in your selection.\n\nNote: Only CREATE items can be synced (UPDATE items are skipped).")
            else:
                messagebox.showinfo("Nothing to Create", "All CW devices already exist in SDP. Nothing to create.")
            return

        # Build confirmation message
        mode_text = "DRY RUN (preview only)" if is_dry_run else "REAL SYNC"
        msg = f"Mode: {mode_text}\n"
        msg += f"Selection: {selection_mode} ({len(sync_items)} items)\n\n"
        msg += f"This will CREATE {len(sync_items)} new assets in SDP.\n\n"
        msg += "By Category:\n"
        for cat in sorted(set(i.cw_category for i in sync_items)):
            count = len([i for i in sync_items if i.cw_category == cat])
            msg += f"  • {cat}: {count}\n"
        msg += "\nExisting matches will be SKIPPED (no overwrites).\n"

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
        """Run sync in background thread."""
        from .sdp_client import SDPClient
        from datetime import datetime

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
                "status": "pending",
                "message": "",
                "sdp_id": None
            }

            try:
                # Create the asset in SDP
                result = sdp.create_ci(item.sdp_ci_type, item.fields_to_sync)
                if result:
                    success_count += 1
                    if is_dry_run:
                        log_msg = f"[DRY] Would create: {item.cw_name} → {item.sdp_ci_type}"
                        result_entry["status"] = "would_create"
                        result_entry["message"] = "Would be created (dry run)"
                    else:
                        log_msg = f"✓ Created: {item.cw_name}"
                        result_entry["status"] = "success"
                        result_entry["message"] = "Created successfully"
                        # Track for revert
                        sdp_id = result.get(item.sdp_ci_type, {}).get("id")
                        if sdp_id:
                            result_entry["sdp_id"] = sdp_id
                            created_ids.append({
                                "sdp_id": sdp_id,
                                "ci_type": item.sdp_ci_type,
                                "name": item.cw_name
                            })
                else:
                    error_count += 1
                    log_msg = f"✗ Failed: {item.cw_name}"
                    result_entry["status"] = "failed"
                    result_entry["message"] = "API returned no result"
            except Exception as e:
                error_count += 1
                error_msg = str(e)[:100]
                log_msg = f"✗ Error: {item.cw_name} - {error_msg[:50]}"
                result_entry["status"] = "error"
                result_entry["message"] = error_msg

            sync_results.append(result_entry)

            # Update UI in main thread
            self.root.after(0, lambda i=i, msg=log_msg: self._update_progress(i + 1, len(items), msg))

        # Save created IDs for revert (if real sync)
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
        import sqlite3
        import json
        from datetime import datetime

        conn = sqlite3.connect("data/cwtosdp_compare.db")
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
        conn.close()

        # Enable revert button
        self.root.after(0, lambda: self.revert_btn.config(state=tk.NORMAL))

    def _update_progress(self, current: int, total: int, log_msg: str):
        """Update progress UI."""
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
        if hasattr(self, 'progress_win'):
            self.progress_win.destroy()
        messagebox.showerror("Sync Error", msg)

    def _sync_complete(self, success: int, errors: int, is_dry_run: bool,
                       results: List[Dict] = None, duration: float = 0):
        """Handle sync completion and create results tab."""
        self.sync_in_progress = False
        self._on_real_sync_toggle()  # Reset button text

        # Update progress window with summary
        if is_dry_run:
            self.progress_label.config(text=f"Preview complete: {success} would be created, {errors} would fail")
        else:
            self.progress_label.config(text=f"Complete: {success} created, {errors} errors")

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
        from datetime import datetime

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

        # Configure tags
        results_tree.tag_configure("success", background="#d4edda")
        results_tree.tag_configure("would_create", background="#d1ecf1")
        results_tree.tag_configure("failed", background="#f8d7da")
        results_tree.tag_configure("error", background="#f5c6cb")

        # Status icons
        status_icons = {
            "success": "✓",
            "would_create": "○",
            "failed": "✗",
            "error": "⚠",
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
        """Revert the last sync operation."""
        import sqlite3
        import json

        # Get last sync log
        conn = sqlite3.connect("data/cwtosdp_compare.db")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, sync_time, items_json FROM sync_log
            WHERE reverted = 0 ORDER BY id DESC LIMIT 1
        """)
        row = cursor.fetchone()

        if not row:
            messagebox.showinfo("No Sync to Revert", "No previous sync operations found to revert.")
            conn.close()
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
            conn.close()
            return

        # Execute revert
        from .sdp_client import SDPClient
        try:
            sdp = SDPClient(dry_run=False)
            success = 0
            for item in items:
                try:
                    sdp.delete_ci(item['ci_type'], item['sdp_id'])
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
            conn.close()

    def _refresh_cw_data(self):
        """Refresh ConnectWise data."""
        if messagebox.askyesno("Refresh CW Data",
                               "This will re-fetch all data from ConnectWise.\nThis may take a few minutes.\n\nProceed?"):
            self.sync_btn.config(state=tk.DISABLED)
            thread = threading.Thread(target=self._do_refresh_cw)
            thread.daemon = True
            thread.start()

    def _do_refresh_cw(self):
        """Background thread for CW refresh."""
        try:
            from .db_compare import ComparisonDatabase
            db = ComparisonDatabase()
            db.fetch_cw_devices_full()
            db.close()
            self.root.after(0, lambda: self._refresh_complete("ConnectWise"))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", f"CW refresh failed: {e}"))
            self.root.after(0, lambda: self.sync_btn.config(state=tk.NORMAL))

    def _refresh_sdp_data(self):
        """Refresh ServiceDesk Plus data."""
        if messagebox.askyesno("Refresh SDP Data",
                               "This will re-fetch all data from ServiceDesk Plus.\nThis may take a few minutes.\n\nProceed?"):
            self.sync_btn.config(state=tk.DISABLED)
            thread = threading.Thread(target=self._do_refresh_sdp)
            thread.daemon = True
            thread.start()

    def _do_refresh_sdp(self):
        """Background thread for SDP refresh."""
        try:
            from .db_compare import ComparisonDatabase
            db = ComparisonDatabase()
            db.fetch_sdp_workstations_full()
            db.close()
            self.root.after(0, lambda: self._refresh_complete("ServiceDesk Plus"))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", f"SDP refresh failed: {e}"))
            self.root.after(0, lambda: self.sync_btn.config(state=tk.NORMAL))

    def _refresh_complete(self, source: str):
        """Handle refresh completion."""
        self.sync_btn.config(state=tk.NORMAL)
        messagebox.showinfo("Refresh Complete", f"{source} data refreshed successfully.")
        self._load_data()

    def _check_orphans(self):
        """Check for orphaned entries and database status."""
        import sqlite3

        conn = sqlite3.connect("data/cwtosdp_compare.db")
        cursor = conn.cursor()

        # Get counts
        cursor.execute("SELECT COUNT(*) FROM cw_devices_full")
        cw_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sdp_workstations_full")
        sdp_count = cursor.fetchone()[0]

        # Check for sync log entries
        pending_syncs = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM sync_log WHERE reverted = 0")
            result = cursor.fetchone()
            pending_syncs = result[0] if result else 0
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

        # Check fetch tracker
        fetch_info = []
        try:
            cursor.execute("SELECT source, last_fetch, total_fetched FROM fetch_tracker")
            fetch_info = cursor.fetchall()
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

        # Check for orphaned CW entries (not in current API response)
        # This would require comparing with a fresh API call - for now show what we have

        # Check matches vs creates
        create_count = len([i for i in self.items if i.action == SyncAction.CREATE])
        update_count = len([i for i in self.items if i.action == SyncAction.UPDATE])

        conn.close()

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

    def run(self):
        """Run the application."""
        self.root.mainloop()
        self.engine.close()


def launch_sync_gui():
    """Launch the sync GUI."""
    app = SyncGUI()
    app.run()

