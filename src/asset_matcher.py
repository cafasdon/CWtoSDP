"""
Asset Matcher GUI for CWtoSDP.

Focused interface for matching assets between ConnectWise and ServiceDesk Plus
using key identifiers like hostname, serial number, and IP address.
"""

import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .logger import get_logger
from .db import DEFAULT_DB_PATH

logger = get_logger("cwtosdp.asset_matcher")

DB_PATH = DEFAULT_DB_PATH


class AssetMatcherApp:
    """Asset matching GUI - find matches between CW and SDP."""

    # Key fields for matching (CW field -> display name)
    CW_KEY_FIELDS = {
        "friendlyName": "Hostname",
        "system_serialNumber": "Serial Number",
        "remoteAddress": "IP Address",
        "os_product": "Operating System",
        "system_model": "Model",
        "endpointType": "Type",
    }
    
    # Key fields for matching (SDP field -> display name)
    SDP_KEY_FIELDS = {
        "name": "Name",
        "ci_attributes_txt_serial_number": "Serial Number",
        "ci_attributes_txt_ip_address": "IP Address",
        "ci_attributes_txt_os": "Operating System",
        "ci_attributes_ref_model_name": "Model",
        "ci_attributes_ref_model_manufacturer": "Manufacturer",
    }

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CWtoSDP - Asset Matcher")
        self.root.geometry("1600x900")
        self.root.minsize(1200, 700)
        
        self.conn = sqlite3.connect(str(DB_PATH))
        self.conn.row_factory = sqlite3.Row
        
        # Style
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("Match.TLabel", foreground="green", font=("Helvetica", 10, "bold"))
        self.style.configure("NoMatch.TLabel", foreground="red")
        self.style.configure("Header.TLabel", font=("Helvetica", 11, "bold"))
        
        self._create_layout()
        self._load_data()
        
    def _create_layout(self):
        """Create the main layout."""
        # Top frame with controls
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)
        
        ttk.Label(top_frame, text="Match By:", style="Header.TLabel").pack(side=tk.LEFT)
        self.match_var = tk.StringVar(value="hostname")
        ttk.Radiobutton(top_frame, text="Hostname", variable=self.match_var, 
                       value="hostname", command=self._find_matches).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(top_frame, text="Serial Number", variable=self.match_var,
                       value="serial", command=self._find_matches).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(top_frame, text="IP Address", variable=self.match_var,
                       value="ip", command=self._find_matches).pack(side=tk.LEFT, padx=10)
        
        ttk.Button(top_frame, text="Find Matches", command=self._find_matches).pack(side=tk.LEFT, padx=20)
        ttk.Button(top_frame, text="Show All CW", command=self._show_all_cw).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="Show All SDP", command=self._show_all_sdp).pack(side=tk.LEFT, padx=5)
        
        # Stats label
        self.stats_label = ttk.Label(top_frame, text="")
        self.stats_label.pack(side=tk.RIGHT, padx=10)
        
        # Main paned window
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Left: Matches / CW Assets
        left_frame = ttk.LabelFrame(paned, text="ConnectWise Devices", padding=5)
        paned.add(left_frame, weight=1)
        
        # CW Treeview
        cw_cols = ("hostname", "serial", "ip", "os", "type")
        self.cw_tree = ttk.Treeview(left_frame, columns=cw_cols, show="headings", height=25)
        for col, heading in zip(cw_cols, ("Hostname", "Serial", "IP Address", "OS", "Type")):
            self.cw_tree.heading(col, text=heading)
            self.cw_tree.column(col, width=120)
        
        cw_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.cw_tree.yview)
        self.cw_tree.configure(yscrollcommand=cw_scroll.set)
        self.cw_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cw_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.cw_tree.bind("<<TreeviewSelect>>", self._on_cw_select)
        
        # Right: SDP Assets
        right_frame = ttk.LabelFrame(paned, text="ServiceDesk Plus Workstations", padding=5)
        paned.add(right_frame, weight=1)
        
        sdp_cols = ("name", "serial", "ip", "os", "manufacturer")
        self.sdp_tree = ttk.Treeview(right_frame, columns=sdp_cols, show="headings", height=25)
        for col, heading in zip(sdp_cols, ("Name", "Serial", "IP Address", "OS", "Manufacturer")):
            self.sdp_tree.heading(col, text=heading)
            self.sdp_tree.column(col, width=120)
        
        sdp_scroll = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.sdp_tree.yview)
        self.sdp_tree.configure(yscrollcommand=sdp_scroll.set)
        self.sdp_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sdp_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bottom: Match details
        bottom_frame = ttk.LabelFrame(self.root, text="Match Details", padding=10)
        bottom_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.detail_text = tk.Text(bottom_frame, height=8, wrap=tk.WORD)
        self.detail_text.pack(fill=tk.X)

    def _load_data(self):
        """Load data from database."""
        cursor = self.conn.cursor()
        
        # Count records
        cursor.execute("SELECT COUNT(*) FROM cw_devices_full")
        cw_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM sdp_workstations_full")
        sdp_count = cursor.fetchone()[0]
        
        self.stats_label.config(text=f"CW: {cw_count} devices | SDP: {sdp_count} workstations")
        
        # Load all data
        self._show_all_cw()
        self._show_all_sdp()
        
    def _show_all_cw(self):
        """Show all CW devices."""
        self.cw_tree.delete(*self.cw_tree.get_children())
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT friendlyName, system_serialNumber, remoteAddress, os_product, endpointType, endpointID
            FROM cw_devices_full ORDER BY friendlyName
        """)
        for row in cursor.fetchall():
            self.cw_tree.insert("", tk.END, values=(
                row[0] or "", row[1] or "", row[2] or "", 
                (row[3] or "")[:40], row[4] or ""
            ), tags=(row[5],))  # Store endpointID as tag

    def _show_all_sdp(self):
        """Show all SDP workstations."""
        self.sdp_tree.delete(*self.sdp_tree.get_children())
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name, ci_attributes_txt_serial_number, ci_attributes_txt_ip_address,
                   ci_attributes_txt_os, ci_attributes_ref_model_manufacturer, sdp_id
            FROM sdp_workstations_full ORDER BY name
        """)
        for row in cursor.fetchall():
            self.sdp_tree.insert("", tk.END, values=(
                row[0] or "", row[1] or "", row[2] or "",
                (row[3] or "")[:40], row[4] or ""
            ), tags=(row[5],))

    def _find_matches(self):
        """Find matching assets between CW and SDP."""
        match_by = self.match_var.get()
        cursor = self.conn.cursor()

        # Clear both trees
        self.cw_tree.delete(*self.cw_tree.get_children())
        self.sdp_tree.delete(*self.sdp_tree.get_children())
        self.detail_text.delete(1.0, tk.END)

        if match_by == "hostname":
            # Match by hostname/name (case-insensitive)
            query = """
                SELECT
                    cw.friendlyName, cw.system_serialNumber, cw.remoteAddress, cw.os_product, cw.endpointType, cw.endpointID,
                    sdp.name, sdp.ci_attributes_txt_serial_number, sdp.ci_attributes_txt_ip_address,
                    sdp.ci_attributes_txt_os, sdp.ci_attributes_ref_model_manufacturer, sdp.sdp_id
                FROM cw_devices_full cw
                INNER JOIN sdp_workstations_full sdp ON UPPER(cw.friendlyName) = UPPER(sdp.name)
                ORDER BY cw.friendlyName
            """
        elif match_by == "serial":
            query = """
                SELECT
                    cw.friendlyName, cw.system_serialNumber, cw.remoteAddress, cw.os_product, cw.endpointType, cw.endpointID,
                    sdp.name, sdp.ci_attributes_txt_serial_number, sdp.ci_attributes_txt_ip_address,
                    sdp.ci_attributes_txt_os, sdp.ci_attributes_ref_model_manufacturer, sdp.sdp_id
                FROM cw_devices_full cw
                INNER JOIN sdp_workstations_full sdp ON UPPER(cw.system_serialNumber) = UPPER(sdp.ci_attributes_txt_serial_number)
                WHERE cw.system_serialNumber IS NOT NULL AND cw.system_serialNumber != ''
                ORDER BY cw.friendlyName
            """
        else:  # ip
            query = """
                SELECT
                    cw.friendlyName, cw.system_serialNumber, cw.remoteAddress, cw.os_product, cw.endpointType, cw.endpointID,
                    sdp.name, sdp.ci_attributes_txt_serial_number, sdp.ci_attributes_txt_ip_address,
                    sdp.ci_attributes_txt_os, sdp.ci_attributes_ref_model_manufacturer, sdp.sdp_id
                FROM cw_devices_full cw
                INNER JOIN sdp_workstations_full sdp ON cw.remoteAddress = sdp.ci_attributes_txt_ip_address
                WHERE cw.remoteAddress IS NOT NULL AND cw.remoteAddress != ''
                ORDER BY cw.friendlyName
            """

        cursor.execute(query)
        matches = cursor.fetchall()

        for row in matches:
            # CW side
            self.cw_tree.insert("", tk.END, values=(
                row[0] or "", row[1] or "", row[2] or "",
                (row[3] or "")[:40], row[4] or ""
            ), tags=(row[5], "match"))

            # SDP side
            self.sdp_tree.insert("", tk.END, values=(
                row[6] or "", row[7] or "", row[8] or "",
                (row[9] or "")[:40], row[10] or ""
            ), tags=(row[11], "match"))

        match_type = {"hostname": "Hostname", "serial": "Serial Number", "ip": "IP Address"}[match_by]
        self.detail_text.insert(tk.END, f"Found {len(matches)} matches by {match_type}.\n\n")

        if matches:
            self.detail_text.insert(tk.END, "These assets exist in BOTH systems and don't need to be created.\n")
            self.detail_text.insert(tk.END, f"Matched on: {match_type}\n")

        # Configure tag colors
        self.cw_tree.tag_configure("match", background="#d4edda")
        self.sdp_tree.tag_configure("match", background="#d4edda")

    def _on_cw_select(self, event):
        """Handle CW selection - show details."""
        selection = self.cw_tree.selection()
        if not selection:
            return

        item = self.cw_tree.item(selection[0])
        hostname = item["values"][0]

        self.detail_text.delete(1.0, tk.END)
        self.detail_text.insert(tk.END, f"Selected: {hostname}\n\n")

        # Show full details from database
        cursor = self.conn.cursor()
        cursor.execute("SELECT raw_json FROM cw_devices_full WHERE friendlyName = ?", (hostname,))
        row = cursor.fetchone()
        if row:
            data = json.loads(row[0])
            self.detail_text.insert(tk.END, "Key Fields:\n")
            for field, label in self.CW_KEY_FIELDS.items():
                value = data.get(field) or data.get("system", {}).get(field.replace("system_", ""))
                self.detail_text.insert(tk.END, f"  {label}: {value}\n")

    def run(self):
        """Run the application."""
        self.root.mainloop()
        self.conn.close()


def launch_asset_matcher():
    """Launch the asset matcher GUI."""
    if not DB_PATH.exists():
        messagebox.showerror("Error", f"Database not found: {DB_PATH}\nRun --compare first.")
        return
    app = AssetMatcherApp()
    app.run()

