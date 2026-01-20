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
        """Create summary cards at top with sync button."""
        summary_frame = ttk.Frame(parent)
        summary_frame.pack(fill=tk.X, pady=(0, 10))

        # Title
        ttk.Label(summary_frame, text="CW → SDP Sync Manager",
                  font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)

        # Sync button (right side)
        btn_frame = ttk.Frame(summary_frame)
        btn_frame.pack(side=tk.RIGHT)

        self.sync_btn = ttk.Button(btn_frame, text="🔄 Sync to SDP (Create Only)",
                                   command=self._execute_sync)
        self.sync_btn.pack(side=tk.RIGHT, padx=10)

        # Stats will be added after data loads
        self.stats_frame = ttk.Frame(summary_frame)
        self.stats_frame.pack(side=tk.RIGHT, padx=20)

    def _create_preview_tab(self):
        """Create the sync preview tab with ALL fields visible."""
        # Filter frame
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

        # Info label
        ttk.Label(filter_frame, text="(Scroll right to see all SDP fields →)",
                  foreground="gray").pack(side=tk.RIGHT)

        # Tree container with scrollbars
        tree_container = ttk.Frame(self.preview_frame)
        tree_container.pack(fill=tk.BOTH, expand=True)

        # Define ALL columns including SDP fields
        columns = ("cw_name", "category", "action", "sdp_ci_type", "match_reason",
                   "name", "serial_number", "os", "manufacturer", "ip_address", "mac_address")
        headings = ("CW Device", "Category", "Action", "SDP CI Type", "Match Reason",
                    "→ SDP Name", "→ Serial #", "→ OS", "→ Manufacturer", "→ IP Address", "→ MAC Address")
        widths = (200, 110, 70, 160, 200, 200, 150, 200, 150, 120, 180)

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

        # Bind selection
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Configure tags for colors
        self.tree.tag_configure("create", background="#fff3cd")  # Yellow
        self.tree.tag_configure("update", background="#d4edda")  # Green
    
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
        """Populate the tree view with ALL fields."""
        self.tree.delete(*self.tree.get_children())

        items = items or self.items
        for item in items:
            tag = item.action.value
            fields = item.fields_to_sync
            self.tree.insert("", tk.END, values=(
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

    def _on_select(self, event):
        """Handle tree selection."""
        selection = self.tree.selection()
        if not selection:
            return

        # Get selected item details
        values = self.tree.item(selection[0])["values"]
        cw_name = values[0]

        # Find the full item
        item = next((i for i in self.items if i.cw_name == cw_name), None)
        if item:
            # Could show a detail popup here
            pass

    def _execute_sync(self):
        """Execute sync: CREATE only (no overwrites)."""
        if self.sync_in_progress:
            messagebox.showwarning("Sync in Progress", "A sync operation is already running.")
            return

        # Count items to create
        create_items = [i for i in self.items if i.action == SyncAction.CREATE]
        if not create_items:
            messagebox.showinfo("Nothing to Create", "All CW devices already exist in SDP. Nothing to create.")
            return

        # Confirm with user
        msg = f"This will CREATE {len(create_items)} new assets in SDP.\n\n"
        msg += "By Category:\n"
        for cat in sorted(set(i.cw_category for i in create_items)):
            count = len([i for i in create_items if i.cw_category == cat])
            msg += f"  • {cat}: {count}\n"
        msg += "\nExisting matches will be SKIPPED (no overwrites).\n\nProceed?"

        if not messagebox.askyesno("Confirm Sync", msg):
            return

        # Start sync in background thread
        self.sync_in_progress = True
        self.sync_btn.config(state=tk.DISABLED, text="⏳ Syncing...")

        # Create progress window
        self._create_progress_window(len(create_items))

        # Run sync in thread
        thread = threading.Thread(target=self._run_sync_thread, args=(create_items,))
        thread.daemon = True
        thread.start()

    def _create_progress_window(self, total: int):
        """Create progress window for sync."""
        self.progress_win = tk.Toplevel(self.root)
        self.progress_win.title("Sync Progress")
        self.progress_win.geometry("500x300")
        self.progress_win.transient(self.root)

        ttk.Label(self.progress_win, text="Creating assets in SDP...",
                  font=("Segoe UI", 12, "bold")).pack(pady=10)

        self.progress_bar = ttk.Progressbar(self.progress_win, length=400, mode="determinate",
                                             maximum=total)
        self.progress_bar.pack(pady=10)

        self.progress_label = ttk.Label(self.progress_win, text=f"0 / {total}")
        self.progress_label.pack()

        # Log area
        self.progress_log = tk.Text(self.progress_win, height=10, width=60, state=tk.DISABLED)
        self.progress_log.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

    def _run_sync_thread(self, items: List[SyncItem]):
        """Run sync in background thread."""
        from .sdp_client import SDPClient

        try:
            sdp = SDPClient()
        except Exception as e:
            self.root.after(0, lambda: self._sync_error(f"Failed to connect to SDP: {e}"))
            return

        success_count = 0
        error_count = 0

        for i, item in enumerate(items):
            try:
                # Create the asset in SDP
                result = sdp.create_ci(item.sdp_ci_type, item.fields_to_sync)
                if result:
                    success_count += 1
                    log_msg = f"✓ Created: {item.cw_name}"
                else:
                    error_count += 1
                    log_msg = f"✗ Failed: {item.cw_name}"
            except Exception as e:
                error_count += 1
                log_msg = f"✗ Error: {item.cw_name} - {str(e)[:50]}"

            # Update UI in main thread
            self.root.after(0, lambda i=i, msg=log_msg: self._update_progress(i + 1, len(items), msg))

        # Done
        self.root.after(0, lambda: self._sync_complete(success_count, error_count))

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
        self.sync_btn.config(state=tk.NORMAL, text="🔄 Sync to SDP (Create Only)")
        if hasattr(self, 'progress_win'):
            self.progress_win.destroy()
        messagebox.showerror("Sync Error", msg)

    def _sync_complete(self, success: int, errors: int):
        """Handle sync completion."""
        self.sync_in_progress = False
        self.sync_btn.config(state=tk.NORMAL, text="🔄 Sync to SDP (Create Only)")

        # Update progress window with summary
        self.progress_label.config(text=f"Complete: {success} created, {errors} errors")

        # Add close button
        ttk.Button(self.progress_win, text="Close",
                   command=self.progress_win.destroy).pack(pady=10)

        # Reload data to reflect changes
        self._load_data()

    def run(self):
        """Run the application."""
        self.root.mainloop()
        self.engine.close()


def launch_sync_gui():
    """Launch the sync GUI."""
    app = SyncGUI()
    app.run()

