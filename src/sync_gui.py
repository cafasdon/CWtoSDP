"""
Sync GUI for CWtoSDP.

Integrated interface showing:
1. Sync preview (what will be created/updated)
2. Field mappings
3. Category breakdown
"""

import json
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Dict, List

from .logger import get_logger
from .sync_engine import SyncEngine, SyncAction, SyncItem

logger = get_logger("cwtosdp.sync_gui")


class SyncGUI:
    """Main sync GUI application."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CWtoSDP - Sync Manager")
        self.root.geometry("1400x850")
        self.root.minsize(1200, 700)
        
        # Load sync engine
        self.engine = SyncEngine()
        self.items: List[SyncItem] = []
        self.summary: Dict = {}
        
        self._create_layout()
        self._load_data()
    
    def _create_layout(self):
        """Create the main layout."""
        # Main container
        main = ttk.Frame(self.root, padding="10")
        main.pack(fill=tk.BOTH, expand=True)
        
        # Top: Summary cards
        self._create_summary_section(main)
        
        # Middle: Notebook with tabs
        notebook = ttk.Notebook(main)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        # Tab 1: Sync Preview
        self.preview_frame = ttk.Frame(notebook, padding="5")
        notebook.add(self.preview_frame, text="Sync Preview")
        self._create_preview_tab()
        
        # Tab 2: By Category
        self.category_frame = ttk.Frame(notebook, padding="5")
        notebook.add(self.category_frame, text="By Category")
        self._create_category_tab()
        
        # Tab 3: Field Mapping
        self.mapping_frame = ttk.Frame(notebook, padding="5")
        notebook.add(self.mapping_frame, text="Field Mapping")
        self._create_mapping_tab()
    
    def _create_summary_section(self, parent):
        """Create summary cards at top."""
        summary_frame = ttk.Frame(parent)
        summary_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Title
        ttk.Label(summary_frame, text="CW → SDP Sync Preview", 
                  font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
        
        # Stats will be added after data loads
        self.stats_frame = ttk.Frame(summary_frame)
        self.stats_frame.pack(side=tk.RIGHT)
    
    def _create_preview_tab(self):
        """Create the sync preview tab."""
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
        
        # Tree view
        columns = ("cw_name", "category", "action", "sdp_ci_type", "match_reason")
        self.tree = ttk.Treeview(self.preview_frame, columns=columns, show="headings", height=25)
        
        self.tree.heading("cw_name", text="CW Device Name")
        self.tree.heading("category", text="Category")
        self.tree.heading("action", text="Action")
        self.tree.heading("sdp_ci_type", text="SDP CI Type")
        self.tree.heading("match_reason", text="Match/Notes")
        
        self.tree.column("cw_name", width=250)
        self.tree.column("category", width=120)
        self.tree.column("action", width=80)
        self.tree.column("sdp_ci_type", width=180)
        self.tree.column("match_reason", width=300)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(self.preview_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind selection
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        
        # Configure tags for colors
        self.tree.tag_configure("create", background="#fff3cd")  # Yellow
        self.tree.tag_configure("update", background="#d4edda")  # Green
    
    def _create_category_tab(self):
        """Create category breakdown tab."""
        # Will be populated after data loads
        self.category_text = tk.Text(self.category_frame, wrap=tk.WORD, font=("Consolas", 10))
        self.category_text.pack(fill=tk.BOTH, expand=True)
    
    def _create_mapping_tab(self):
        """Create field mapping reference tab."""
        mapping_text = tk.Text(self.mapping_frame, wrap=tk.WORD, font=("Consolas", 10))
        mapping_text.pack(fill=tk.BOTH, expand=True)
        
        mapping_info = """
FIELD MAPPING: ConnectWise → ServiceDesk Plus
══════════════════════════════════════════════════════════════════════════════

SDP Field                    │ CW Source                    │ Notes
─────────────────────────────┼──────────────────────────────┼─────────────────────────────
name                         │ friendlyName                 │ Direct copy
serial_number                │ system.serialNumber          │ Skip VMware UUIDs
service_tag                  │ system.serialNumber          │ Same as serial
os                           │ os.product                   │ Direct copy
manufacturer                 │ bios.manufacturer            │ Normalized (LENOVO→Lenovo)
ip_address                   │ networks[0].ipv4             │ First valid internal IP
mac_address                  │ networks[].macAddress        │ Comma-separated list
processor_name               │ processor.product            │ Direct copy


CATEGORY MAPPING: CW → SDP CI Type
══════════════════════════════════════════════════════════════════════════════

CW Category          │ SDP CI Type               │ Description
─────────────────────┼───────────────────────────┼────────────────────────────────
Laptop               │ ci_windows_workstation    │ ThinkPads, ProBooks, etc.
Desktop              │ ci_windows_workstation    │ Physical workstations
Virtual Server       │ ci_virtual_machine        │ VMware VMs
Physical Server      │ ci_windows_server         │ Physical servers
Network Device       │ ci_switch/ci_firewall     │ Switches, routers, firewalls
"""
        mapping_text.insert(tk.END, mapping_info)
        mapping_text.config(state=tk.DISABLED)

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
        """Populate the tree view."""
        self.tree.delete(*self.tree.get_children())

        items = items or self.items
        for item in items:
            tag = item.action.value
            self.tree.insert("", tk.END, values=(
                item.cw_name,
                item.cw_category,
                item.action.value.upper(),
                item.sdp_ci_type,
                item.match_reason or "-"
            ), tags=(tag,))

    def _populate_category_tab(self):
        """Populate category breakdown."""
        self.category_text.delete(1.0, tk.END)

        text = "CATEGORY BREAKDOWN\n"
        text += "=" * 60 + "\n\n"

        for category in sorted(self.summary.get("by_category", {}).keys()):
            count = self.summary["by_category"][category]
            text += f"\n{category} ({count} devices)\n"
            text += "-" * 40 + "\n"

            cat_items = [i for i in self.items if i.cw_category == category]
            creates = len([i for i in cat_items if i.action == SyncAction.CREATE])
            updates = len([i for i in cat_items if i.action == SyncAction.UPDATE])

            text += f"  → CREATE: {creates}\n"
            text += f"  → UPDATE: {updates}\n\n"

            # Sample devices
            text += "  Sample devices:\n"
            for item in cat_items[:5]:
                action = "✓" if item.action == SyncAction.UPDATE else "+"
                text += f"    {action} {item.cw_name}\n"
            if len(cat_items) > 5:
                text += f"    ... and {len(cat_items) - 5} more\n"

        self.category_text.insert(tk.END, text)

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

    def run(self):
        """Run the application."""
        self.root.mainloop()
        self.engine.close()


def launch_sync_gui():
    """Launch the sync GUI."""
    app = SyncGUI()
    app.run()

