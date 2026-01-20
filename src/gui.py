"""
GUI Viewer for CWtoSDP Field Mapping.

Cross-platform tkinter GUI for viewing ConnectWise and ServiceDesk Plus
data side-by-side, comparing fields, and creating mappings.
"""

import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Any, Dict, List, Optional

from .db import Database
from .logger import get_logger

logger = get_logger("cwtosdp.gui")


class FieldMapperApp:
    """Main GUI application for field mapping between CW and SDP."""

    def __init__(self, db: Database):
        """Initialize the application."""
        self.db = db
        self.root = tk.Tk()
        self.root.title("CWtoSDP - Field Mapper")
        self.root.geometry("1400x800")
        self.root.minsize(1000, 600)

        # Configure style
        self.style = ttk.Style()
        self.style.theme_use("clam")

        self._create_menu()
        self._create_main_layout()
        self._create_status_bar()

        # Load initial data
        self._refresh_data()

    def _create_menu(self):
        """Create the menu bar."""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Export Mappings...", command=self._export_mappings)
        file_menu.add_command(label="Import Mappings...", command=self._import_mappings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Refresh Data", command=self._refresh_data)
        view_menu.add_command(label="Database Stats", command=self._show_stats)

    def _create_main_layout(self):
        """Create the main application layout."""
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab 1: Data Browser
        self.browser_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.browser_frame, text="Data Browser")
        self._create_browser_tab()

        # Tab 2: Field Comparison
        self.compare_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.compare_frame, text="Field Comparison")
        self._create_compare_tab()

        # Tab 3: Mappings
        self.mapping_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.mapping_frame, text="Field Mappings")
        self._create_mapping_tab()

    def _create_browser_tab(self):
        """Create the data browser tab with side-by-side tables."""
        # Split into left (CW) and right (SDP) panes
        paned = ttk.PanedWindow(self.browser_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # ConnectWise pane
        cw_frame = ttk.LabelFrame(paned, text="ConnectWise Devices", padding=5)
        paned.add(cw_frame, weight=1)

        # CW Treeview
        cw_cols = ("Name", "Site", "Company", "OS", "Last Seen")
        self.cw_tree = ttk.Treeview(cw_frame, columns=cw_cols, show="headings", height=20)
        for col in cw_cols:
            self.cw_tree.heading(col, text=col)
            self.cw_tree.column(col, width=120)

        cw_scroll = ttk.Scrollbar(cw_frame, orient=tk.VERTICAL, command=self.cw_tree.yview)
        self.cw_tree.configure(yscrollcommand=cw_scroll.set)
        self.cw_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cw_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.cw_tree.bind("<Double-1>", lambda e: self._show_raw_json("cw"))

        # ServiceDesk Plus pane
        sdp_frame = ttk.LabelFrame(paned, text="ServiceDesk Plus Workstations", padding=5)
        paned.add(sdp_frame, weight=1)

        # SDP Treeview
        sdp_cols = ("Name", "Serial", "IP Address", "OS", "Manufacturer")
        self.sdp_tree = ttk.Treeview(sdp_frame, columns=sdp_cols, show="headings", height=20)
        for col in sdp_cols:
            self.sdp_tree.heading(col, text=col)
            self.sdp_tree.column(col, width=120)

        sdp_scroll = ttk.Scrollbar(sdp_frame, orient=tk.VERTICAL, command=self.sdp_tree.yview)
        self.sdp_tree.configure(yscrollcommand=sdp_scroll.set)
        self.sdp_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sdp_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.sdp_tree.bind("<Double-1>", lambda e: self._show_raw_json("sdp"))

    def _create_compare_tab(self):
        """Create the field comparison tab."""
        # Split into CW fields, SDP fields, and mapping area
        paned = ttk.PanedWindow(self.compare_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # CW Fields
        cw_field_frame = ttk.LabelFrame(paned, text="ConnectWise Fields", padding=5)
        paned.add(cw_field_frame, weight=1)

        cw_field_cols = ("Field Path", "Type", "Sample Value", "Count")
        self.cw_field_tree = ttk.Treeview(cw_field_frame, columns=cw_field_cols, show="headings")
        for col in cw_field_cols:
            self.cw_field_tree.heading(col, text=col)
            self.cw_field_tree.column(col, width=100)

        cw_field_scroll = ttk.Scrollbar(cw_field_frame, orient=tk.VERTICAL, command=self.cw_field_tree.yview)
        self.cw_field_tree.configure(yscrollcommand=cw_field_scroll.set)
        self.cw_field_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cw_field_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Center control panel
        control_frame = ttk.Frame(paned, padding=10)
        paned.add(control_frame, weight=0)

        ttk.Button(control_frame, text="→ Create Mapping →",
                   command=self._create_mapping_from_selection).pack(pady=20)
        ttk.Label(control_frame, text="Select a field\nfrom each side\nand click to map").pack()

        # SDP Fields
        sdp_field_frame = ttk.LabelFrame(paned, text="ServiceDesk Plus Fields", padding=5)
        paned.add(sdp_field_frame, weight=1)

        sdp_field_cols = ("Field Path", "Type", "Sample Value", "Count")
        self.sdp_field_tree = ttk.Treeview(sdp_field_frame, columns=sdp_field_cols, show="headings")
        for col in sdp_field_cols:
            self.sdp_field_tree.heading(col, text=col)
            self.sdp_field_tree.column(col, width=100)

        sdp_field_scroll = ttk.Scrollbar(sdp_field_frame, orient=tk.VERTICAL, command=self.sdp_field_tree.yview)
        self.sdp_field_tree.configure(yscrollcommand=sdp_field_scroll.set)
        self.sdp_field_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sdp_field_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _create_mapping_tab(self):
        """Create the field mappings tab."""
        # Toolbar
        toolbar = ttk.Frame(self.mapping_frame)
        toolbar.pack(fill=tk.X, pady=5)

        ttk.Button(toolbar, text="Delete Selected", command=self._delete_mapping).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="Refresh", command=self._load_mappings).pack(side=tk.LEFT, padx=5)

        # Mappings table
        mapping_cols = ("ID", "CW Field", "SDP Field", "Transform", "Created")
        self.mapping_tree = ttk.Treeview(self.mapping_frame, columns=mapping_cols, show="headings")
        for col in mapping_cols:
            self.mapping_tree.heading(col, text=col)
            width = 50 if col == "ID" else 200
            self.mapping_tree.column(col, width=width)

        mapping_scroll = ttk.Scrollbar(self.mapping_frame, orient=tk.VERTICAL, command=self.mapping_tree.yview)
        self.mapping_tree.configure(yscrollcommand=mapping_scroll.set)
        self.mapping_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        mapping_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _create_status_bar(self):
        """Create the status bar."""
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _refresh_data(self):
        """Refresh all data from database."""
        self._load_cw_devices()
        self._load_sdp_workstations()
        self._load_field_metadata()
        self._load_mappings()
        stats = self.db.get_stats()
        self.status_var.set(f"Loaded: {stats['cw_devices']} CW devices, {stats['sdp_workstations']} SDP workstations, {stats['field_mappings']} mappings")

    def _load_cw_devices(self):
        """Load ConnectWise devices into browser tree."""
        for item in self.cw_tree.get_children():
            self.cw_tree.delete(item)

        devices = self.db.get_cw_devices()
        for dev in devices:
            self.cw_tree.insert("", tk.END, iid=dev["endpoint_id"], values=(
                dev["name"], dev["site_name"], dev["company_name"],
                dev["os_type"], dev["last_seen"][:10] if dev["last_seen"] else ""
            ))

    def _load_sdp_workstations(self):
        """Load SDP workstations into browser tree."""
        for item in self.sdp_tree.get_children():
            self.sdp_tree.delete(item)

        workstations = self.db.get_sdp_workstations()
        for ws in workstations:
            self.sdp_tree.insert("", tk.END, iid=ws["ci_id"], values=(
                ws["name"], ws["serial_number"], ws["ip_address"],
                ws["os"], ws["manufacturer"]
            ))

    def _load_field_metadata(self):
        """Load field metadata into comparison trees."""
        # Clear existing
        for item in self.cw_field_tree.get_children():
            self.cw_field_tree.delete(item)
        for item in self.sdp_field_tree.get_children():
            self.sdp_field_tree.delete(item)

        # Load CW fields
        cw_fields = self.db.get_field_metadata("cw")
        for field in cw_fields:
            self.cw_field_tree.insert("", tk.END, values=(
                field["field_path"], field["field_type"],
                (field["sample_value"] or "")[:50], field["occurrence_count"]
            ))

        # Load SDP fields
        sdp_fields = self.db.get_field_metadata("sdp")
        for field in sdp_fields:
            self.sdp_field_tree.insert("", tk.END, values=(
                field["field_path"], field["field_type"],
                (field["sample_value"] or "")[:50], field["occurrence_count"]
            ))

    def _load_mappings(self):
        """Load field mappings into mapping tree."""
        for item in self.mapping_tree.get_children():
            self.mapping_tree.delete(item)

        mappings = self.db.get_field_mappings()
        for m in mappings:
            self.mapping_tree.insert("", tk.END, iid=m["id"], values=(
                m["id"], m["cw_field"], m["sdp_field"],
                m["transform_type"] or "direct", m["created_at"][:10]
            ))

    def _show_raw_json(self, source: str):
        """Show raw JSON for selected item."""
        if source == "cw":
            selection = self.cw_tree.selection()
            if not selection:
                return
            endpoint_id = selection[0]
            raw = self.db.get_cw_device_raw(endpoint_id)
            title = f"ConnectWise Device: {endpoint_id}"
        else:
            selection = self.sdp_tree.selection()
            if not selection:
                return
            ci_id = selection[0]
            raw = self.db.get_sdp_workstation_raw(ci_id)
            title = f"ServiceDesk Plus Workstation: {ci_id}"

        if raw:
            self._show_json_window(title, raw)

    def _show_json_window(self, title: str, data: Dict[str, Any]):
        """Display JSON data in a new window."""
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("800x600")

        text = tk.Text(win, wrap=tk.WORD, font=("Consolas", 10))
        scroll = ttk.Scrollbar(win, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scroll.set)

        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        text.insert(tk.END, json.dumps(data, indent=2, default=str))
        text.config(state=tk.DISABLED)

    def _create_mapping_from_selection(self):
        """Create a field mapping from selected fields."""
        cw_selection = self.cw_field_tree.selection()
        sdp_selection = self.sdp_field_tree.selection()

        if not cw_selection or not sdp_selection:
            messagebox.showwarning("Selection Required",
                                   "Please select a field from both CW and SDP lists.")
            return

        cw_field = self.cw_field_tree.item(cw_selection[0])["values"][0]
        sdp_field = self.sdp_field_tree.item(sdp_selection[0])["values"][0]

        self.db.save_field_mapping(cw_field, sdp_field)
        self._load_mappings()
        self.status_var.set(f"Created mapping: {cw_field} → {sdp_field}")
        messagebox.showinfo("Mapping Created", f"Mapped:\n{cw_field}\n→\n{sdp_field}")

    def _delete_mapping(self):
        """Delete selected mapping."""
        selection = self.mapping_tree.selection()
        if not selection:
            messagebox.showwarning("Selection Required", "Please select a mapping to delete.")
            return

        mapping_id = int(selection[0])
        if messagebox.askyesno("Confirm Delete", "Delete this mapping?"):
            self.db.delete_field_mapping(mapping_id)
            self._load_mappings()
            self.status_var.set("Mapping deleted")

    def _export_mappings(self):
        """Export mappings to JSON file."""
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if filepath:
            mappings = self.db.get_field_mappings()
            with open(filepath, "w") as f:
                json.dump(mappings, f, indent=2)
            self.status_var.set(f"Exported {len(mappings)} mappings to {filepath}")

    def _import_mappings(self):
        """Import mappings from JSON file."""
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if filepath:
            with open(filepath, "r") as f:
                mappings = json.load(f)
            for m in mappings:
                self.db.save_field_mapping(m["cw_field"], m["sdp_field"], m.get("transform_type"))
            self._load_mappings()
            self.status_var.set(f"Imported {len(mappings)} mappings")

    def _show_stats(self):
        """Show database statistics."""
        stats = self.db.get_stats()
        msg = "\n".join([f"{k}: {v}" for k, v in stats.items()])
        messagebox.showinfo("Database Statistics", msg)

    def run(self):
        """Run the application main loop."""
        logger.info("Starting GUI application")
        self.root.mainloop()


def launch_gui():
    """Launch the GUI application."""
    db = Database()
    app = FieldMapperApp(db)
    app.run()


if __name__ == "__main__":
    launch_gui()
