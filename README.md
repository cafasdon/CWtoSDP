# CWtoSDP - ConnectWise to ServiceDesk Plus Integration

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Dual-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

Integration tool for syncing device/asset data between **ConnectWise RMM** and **ManageEngine ServiceDesk Plus Cloud** Assets. Includes a full GUI for interactive use and CLI scripts for automated scheduled syncs.

## 🖥️ Easy Installation (Windows)

> **You don't need Python, Git, or any technical knowledge.** One file does everything.

**1.** [**⬇️ Download setup_cwtosdp.bat**](https://raw.githubusercontent.com/cafasdon/CWtoSDP/main/setup_cwtosdp.bat) *(right-click → "Save link as")*
**2.** Double-click the downloaded file.
**3.** That's it. The app will open.

**What it does automatically:**
- ✅ Installs Python (if you don't have it)
- ✅ Downloads the latest CWtoSDP from GitHub
- ✅ Installs all dependencies
- ✅ Creates a **Desktop shortcut** for next time
- ✅ Launches the app

> [!TIP]
> After the first install, just double-click **CWtoSDP** on your Desktop to launch.

### First Time Setup

1. Click **⚙️ Settings** in the app
2. Enter your API credentials ([how to get them](SETUP.md))
3. Click **Test Connections** → **Save**
4. Click **🔄 CW** and **🔄 SDP** to fetch data
5. Review the sync preview and execute when ready

---

### Alternative Install (macOS / Linux / Manual)

<details>
<summary>Click to expand</summary>

**Prerequisites:** Python 3.8+ ([Download](https://www.python.org/downloads/))

| Platform | Command |
|----------|---------|
| **Windows** | Double-click `start.bat` |
| **macOS** | Double-click `start.command` |
| **Linux** | `chmod +x start.sh && ./start.sh` |

Or install manually:

```bash
git clone https://github.com/cafasdon/CWtoSDP.git
cd CWtoSDP
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m src.main --sync
```

</details>

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **Sync Manager GUI** | Visual interface for previewing and executing syncs |
| **Dry Run Mode** | Two-level safety: preview changes before committing (enabled by default) |
| **Selective Sync** | Choose which items to sync with checkboxes |
| **Create & Update** | Creates new Assets in SDP and updates existing ones with changed fields |
| **Device Classification** | Auto-categorizes: Laptop, Desktop, Server, VM, Network Device |
| **Field Mapping** | Maps CW fields to SDP CMDB attributes with visual preview |
| **Diff View** | Side-by-side comparison of CW vs SDP data |
| **Full DB View** | See all records from both systems with match status |
| **Revert Capability** | Undo last sync operation (created items) |
| **Incremental Fetch** | Only downloads new/changed data since last fetch |
| **Adaptive Rate Limiting** | Dynamic backoff and recovery — automatically adjusts API call speed |
| **Settings GUI** | Configure and test API credentials without editing files |
| **Automated Sync** | CLI script with scheduling support for Windows, macOS, and Linux |

---

## 📦 Installation Options

### Option 1: One-File Installer (Recommended for New Users)

Download and double-click [`setup_cwtosdp.bat`](https://raw.githubusercontent.com/cafasdon/CWtoSDP/main/setup_cwtosdp.bat) — it does everything automatically (installs Python, downloads the app, creates a shortcut, launches).

### Option 2: One-Click Start (If You Have the Repo)

| Platform | Command |
|----------|---------|
| **Windows** | Double-click `start.bat` |
| **macOS** | Double-click `start.command` |
| **Linux** | `./start.sh` |

### Option 3: Manual Install

```bash
# Clone repository
git clone https://github.com/cafasdon/CWtoSDP.git
cd CWtoSDP

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Configure credentials
cp credentials.env.template credentials.env
# Edit credentials.env with your API keys

# Launch
python -m src.main --sync
```

## Configuration

### Using the GUI (Recommended)

1. Launch the Sync Manager
2. Click **⚙️ Settings** button
3. Enter your API credentials
4. Click **Test Connections** to verify
5. Click **Save**

### Manual Configuration

Create `credentials.env` from the template:

```env
# ConnectWise RMM
CLIENT_ID=your_cw_client_id
CLIENT_SECRET=your_cw_client_secret

# ServiceDesk Plus (Zoho OAuth)
ZOHO_CLIENT_ID=your_zoho_client_id
ZOHO_CLIENT_SECRET=your_zoho_client_secret
ZOHO_REFRESH_TOKEN=your_refresh_token

# API Endpoints (EU data center)
ZOHO_ACCOUNTS_URL=https://accounts.zoho.eu
ZOHO_TOKEN_URL=https://accounts.zoho.eu/oauth/v2/token
SDP_API_BASE_URL=https://sdpondemand.manageengine.eu/api/v3
```

## Usage

### Sync Manager GUI

```bash
python -m src.main --sync
```

**GUI Features:**

- **Sync Preview** - See all devices with CW → SDP field mapping
- **By Category** - Browse devices by classification
- **Field Mapping** - View CW to SDP field translations
- **Results Tab** - Detailed sync results after execution

**Controls:**

- ☐ **Enable Real Sync** - Toggle between dry run and live mode
- 🔍 **Preview Sync** - Run dry run to see what would happen
- ⚠️ **Execute Real Sync** - Actually create records in SDP
- ↩️ **Revert Last Sync** - Delete items created by last sync
- 🔄 **Refresh Data** - Re-fetch from CW or SDP
- ⚙️ **Settings** - Configure API credentials

### Command Line

```bash
# Launch Sync Manager GUI
python -m src.main --sync

# Fetch data only
python -m src.main --fetch-cw --fetch-sdp --export
```

---

## How It Works

### Sync Process

1. **Fetch Data** - Connects to both APIs and stores data in local SQLite database
2. **Classify Devices** - Analyzes each device and assigns a category (Laptop, Server, etc.)
3. **Match & Compare** - Finds existing SDP records by hostname or serial number
4. **Sync to SDP** - Creates new CIs or updates existing ones based on matches

### Matching Logic

Devices are matched to existing SDP records in this order:

| Priority | Method        | Description                                       |
| -------- | ------------- | ------------------------------------------------- |
| 1        | Hostname      | CW `friendlyName` = SDP `name` (case-insensitive) |
| 2        | Serial Number | Only for non-VM devices (excludes VMware UUIDs)   |

- **Match found** → UPDATE action (update existing Asset fields)
- **No match** → CREATE action (create new Asset)

### Preview Legend - Row Colors

| Color    | Action | Meaning                                 |
| -------- | ------ | --------------------------------------- |
| 🟢 Green | CREATE | New device, will create new Asset in SDP   |
| 🔵 Blue  | UPDATE | Matched device, will update existing Asset |

### Preview Legend - Field Indicators

For UPDATE items, each field shows what will happen:

| Indicator   | Meaning                                         |
| ----------- | ----------------------------------------------- |
| `★ value`   | **NEW** - Field is empty in SDP, will be added  |
| `old → new` | **CHANGED** - Different value, will be updated  |
| `value`     | **UNCHANGED** - Same in both systems, no change |

### Selection Behavior

- **Single-click** on any row toggles its selection (☑/☐)
- **Shift+click** to highlight multiple, then press **Space** to toggle all highlighted
- Selections persist when filters change

**Selection Buttons:**

| Button | Action |
|--------|--------|
| **Select All** | Ticks every item in the list |
| **Select None** | Unticks everything |
| **Select Filtered** | Ticks only the currently visible (filtered) items |
| **Deselect Filtered** | Unticks only the currently visible items |
| **Select Creates Only** | Ticks only items that would be created (new CIs) |

**What happens when you sync:**

| Scenario | Behavior |
|---|---|
| Some items ticked | Only those ticked items (CREATE or UPDATE) are synced |
| Nothing ticked | Falls back to syncing **all** CREATE and UPDATE items |
| Ticked items are all SKIP | Shows alert: *"No CREATE or UPDATE items in your selection"* |
| No items need syncing | Shows alert: *"All CW devices are already up-to-date in SDP"* |

The confirmation dialog always shows **"Selection: SELECTED (N items)"** or **"Selection: ALL (N items)"** so you know exactly what will be processed before confirming.

### Dry Run vs Real Sync

| Mode | Checkbox State | What Happens |
| ---- | -------------- | ------------ |
| Dry Run | ☐ Unchecked | Preview only — no API calls, no changes to SDP |
| Real Sync | ☑ Checked | Actually creates/updates CIs in SDP |

**Dry run is the default.** When enabled, the SDP client has **two levels of safety**:

1. **Method level** — Each write method (`create_asset`, `update_asset`, `delete_asset`) returns a simulated success immediately without making any HTTP request
2. **Request level** — Even if something bypasses level 1, all POST/PUT/DELETE HTTP requests are blocked

This means dry run is **instant** (no network calls) and **completely safe** — nothing is sent to SDP.

After a dry run, the Results tab shows exactly what *would* happen with color-coded rows:
- 🟢 `would_create` — new item that would be created
- 🔵 `would_update` — existing item that would be updated
- 🔴 `failed` — item that would fail

---

## Field Mapping

### ConnectWise → ServiceDesk Plus

| CW Field | SDP Asset Field | Notes |
| --- | --- | --- |
| `friendlyName` | `name` | Primary match key |
| `system.serialNumber` | `serial_number` | Secondary match (non-VM only) |
| `os.product` | `operating_system.os` | Nested field |
| `os.buildNumber` | `operating_system.build_number` | Nested field |
| `os.displayVersion` | `operating_system.service_pack` | Nested field |
| `os.version` | `operating_system.version` | Nested field |
| `system.model` | `computer_system.model` | Nested field |
| `bios.manufacturer` | `computer_system.system_manufacturer` | Nested field |
| `system.totalRam` | `memory.physical_memory` | Nested field (bytes) |
| `networks[].ipv4` | `ip_address` + `network_adapters[].ip_address` | Flat + sub-resource |
| `networks[].macAddress` | `mac_address` + `network_adapters[].mac_address` | Flat + sub-resource |
| `networks[].description` | `network_adapters[].name` + `description` | Sub-resource array |
| `networks[].subnetMask` | `network_adapters[].ipnet_mask` | Sub-resource array |
| `networks[].defaultGateway` | `network_adapters[].default_gateway` | Sub-resource array |
| `networks[].dhcp` | `network_adapters[].dhcp` | Sub-resource array |
| `processors[].name` | `processors[].name` | Sub-resource array |
| `processors[].cores` | `processors[].number_of_cores` | Sub-resource array |
| `processors[].speed` | `processors[].speed` | Sub-resource array (MHz) |
| `processors[].manufacturer` | `processors[].manufacturer` | Sub-resource array |

> [!NOTE]
> Nested fields (`operating_system`, `computer_system`, `memory`) are sent via the **type-specific endpoint** (e.g. `/asset_virtual_machines/{id}`) because the generic `/assets/{id}` endpoint ignores them.

### SDP Asset Types

Assets are sent to type-specific API endpoints based on device classification:

| Classification | SDP Endpoint |
| -------------- | ------------ |
| Laptop/Desktop | `asset_workstations` |
| Virtual Server | `asset_virtual_machines` |
| Physical Server | `asset_servers` |
| Network Device | `asset_switches` |

---

## Automated Sync (Scheduled Tasks)

The automation scripts allow you to run syncs without user interaction, perfect for scheduled tasks.

### Quick Start

| Platform    | Script             | One-time Run                   |
| ----------- | ------------------ | ------------------------------ |
| **Windows** | `run_sync.bat`     | Double-click or Task Scheduler |
| **macOS**   | `run_sync.command` | Double-click or launchd        |
| **Linux**   | `run_sync.sh`      | `./run_sync.sh` or cron        |

### Command-Line Options

```bash
# Preview what would happen (dry run - safe)
python run_sync.py --dry-run

# Execute real sync with confirmation prompt
python run_sync.py

# Execute real sync without prompts (for automation)
python run_sync.py --yes

# Only create new items, skip updates
python run_sync.py --create-only

# Preview only (no execution even if prompted)
python run_sync.py --preview-only
```

### Setting Up Scheduled Automation

#### Windows Task Scheduler

1. **Open Task Scheduler**: Press `Win + R`, type `taskschd.msc`, press Enter

2. **Create Basic Task**:
   - Click "Create Basic Task..." in the right panel
   - Name: `CWtoSDP Sync`
   - Description: `Sync ConnectWise devices to ServiceDesk Plus`

3. **Set Trigger**:
   - Choose frequency (Daily recommended)
   - Set time (e.g., 2:00 AM when systems are idle)

4. **Set Action**:
   - Action: "Start a program"
   - Program/script: `C:\Path\To\CWtoSDP\run_sync.bat`
   - Start in: `C:\Path\To\CWtoSDP`

5. **Configure Settings**:
   - ✅ Run whether user is logged on or not
   - ✅ Run with highest privileges
   - Configure for: Windows 10/11

#### macOS launchd

1. **Create plist file**: Save as `~/Library/LaunchAgents/com.cwtosdp.sync.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cwtosdp.sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/CWtoSDP/run_sync.command</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>2</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>/path/to/CWtoSDP</string>
    <key>StandardOutPath</key>
    <string>/path/to/CWtoSDP/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/CWtoSDP/logs/launchd_error.log</string>
</dict>
</plist>
```

2. **Load the job**:

```bash
launchctl load ~/Library/LaunchAgents/com.cwtosdp.sync.plist
```

#### Linux Cron

1. **Edit crontab**:

```bash
crontab -e
```

2. **Add schedule** (runs daily at 2:00 AM):

```cron
0 2 * * * cd /path/to/CWtoSDP && ./run_sync.sh >> logs/cron.log 2>&1
```

### Automation Best Practices

| Recommendation                | Reason                                              |
| ----------------------------- | --------------------------------------------------- |
| Run at off-peak hours         | Avoid API rate limits during business hours         |
| Use `--create-only` initially | Safer than updating existing records                |
| Check logs regularly          | Monitor `logs/` folder for errors                   |
| Test with `--dry-run` first   | Verify behavior before scheduling                   |
| Keep credentials secure       | Ensure `credentials.env` has restricted permissions |

### Sync Results

After each run, results are saved to `logs/sync_results_YYYYMMDD_HHMMSS.json`:

```json
{
  "timestamp": "2026-01-20T02:00:00",
  "dry_run": false,
  "total_items": 204,
  "created": 15,
  "updated": 32,
  "skipped": 157,
  "errors": 0,
  "items": [...]
}
```

### Troubleshooting Automation

| Issue | Solution |
| ----- | -------- |
| Script not running | Check file permissions (`chmod +x` on Unix) |
| Credentials not found | Ensure `credentials.env` exists in project root |
| Rate limit errors | The tool handles this automatically — it will slow down and recover on its own |
| No output | Check Task Scheduler history or cron logs |
| Slow after rate limit | Normal behavior — the tool recovers gradually, halving the wait time with each success |

---

## Safety Features

⚠️ **DRY RUN mode is ENABLED by default** — you cannot accidentally modify SDP data.

| Feature | Default | Description |
| ------- | ------- | ----------- |
| Dry Run | ON | Two-level safety — no API calls made, instant preview |
| Selective Sync | ON | Choose specific items to sync via checkboxes |
| Confirmation | Required | Detailed confirmation dialog before any real sync |
| Revert | Available | Undo last sync by deleting created items |
| Adaptive Rate Limiting | ON | Prevents API throttling with automatic backoff and recovery |

### Adaptive Rate Limiting

The tool automatically manages API call speed to avoid rate limit errors (HTTP 429):

- **Backoff**: When a rate limit is hit, the interval doubles (up to 120s max)
- **Recovery**: After the rate limit clears, the interval gradually decreases back toward minimum
- **Dynamic speedup**: Recovery speed adapts based on how far above target — halves the interval when very far away, fine-tunes when close
- **Per-API tracking**: ConnectWise and SDP have independent rate limiters with separate settings

You don't need to configure anything — rate limiting is fully automatic and transparent.

## Folder Structure

```text
CWtoSDP/
├── src/                          # Source code
│   ├── __init__.py               # Package init
│   ├── main.py                   # CLI entry point
│   ├── sync_gui.py               # Sync Manager GUI (main interface)
│   ├── sync_engine.py            # Sync logic, matching, and comparison
│   ├── cw_client.py              # ConnectWise RMM API client
│   ├── sdp_client.py             # ServiceDesk Plus API client (with dry-run)
│   ├── config.py                 # Configuration and credential management
│   ├── db.py                     # Primary SQLite database operations
│   ├── db_compare.py             # Comparison database for sync preview
│   ├── field_mapper.py           # CW→SDP field mapping and device classification
│   ├── asset_matcher.py          # Asset matching GUI for manual matching
│   ├── gui.py                    # Field mapper GUI
│   ├── rate_limiter.py           # Adaptive rate limiting with dynamic recovery
│   └── logger.py                 # Logging configuration
├── data/                         # SQLite databases (auto-created)
├── logs/                         # Application and sync result logs
├── docs/                         # API reference documentation
├── setup_cwtosdp.bat             # ⭐ One-file installer (download & run)
├── start.bat/.command/.sh        # One-click installer + launcher
├── install.bat/.command/.sh      # Standalone installer
├── launch_sync.bat/.command/.sh  # GUI-only launcher (no install)
├── run_sync.bat/.command/.sh     # Automation launcher (headless)
├── run_sync.py                   # Automation sync script
├── credentials.env.template      # Credential template with instructions
├── requirements.txt              # Python dependencies
└── LICENSE                       # Dual license (Non-Commercial / Commercial)
```

## Device Classification

Devices are automatically classified using model name, serial number, and CW device type:

| CW Type | Classification | SDP Asset Type | Detection Method |
| ------- | -------------- | -------------- | ---------------- |
| Desktop (ThinkPad/ProBook/etc.) | Laptop | asset_workstations | Model name keywords |
| Desktop (other) | Desktop | asset_workstations | Default for desktops |
| Server + VMware serial | Virtual Server | asset_virtual_machines | VMware UUID pattern |
| Server + real serial | Physical Server | asset_servers | Hardware serial number |
| NetworkDevice | Network Device | asset_switches | CW device type |
| Mobile | Mobile Device | asset_workstations | CW device type |

## API Access

| System | Endpoint | Access | Used For |
| ------ | -------- | ------ | -------- |
| ConnectWise | Devices, Sites, Companies | Read | Fetching endpoint data |
| ServiceDesk Plus | Assets API | Full CRUD | Creating/updating/deleting Assets |
| ServiceDesk Plus | Requests | Read-only | Future ticket integration |

## Data Centers

Configure the correct URLs for your ServiceDesk Plus region:

| Region | Zoho Accounts | SDP API |
| ------ | ------------- | ------- |
| EU | accounts.zoho.eu | sdpondemand.manageengine.eu |
| US | accounts.zoho.com | sdpondemand.manageengine.com |
| IN | accounts.zoho.in | sdpondemand.manageengine.in |
| AU | accounts.zoho.com.au | sdpondemand.manageengine.com.au |

You can set the data center in **⚙️ Settings** or in `credentials.env` — see [SETUP.md](SETUP.md) for details.

## Documentation

- [Setup Guide](SETUP.md) — Installation, API credentials, first run
- [API Reference](docs/ManageEngine-ServiceDesk-API.md) — ServiceDesk Plus API documentation
- [License](LICENSE) — Dual license (free for non-commercial use)

## Troubleshooting

### Log Files

Logs are stored at `logs/cwtosdp.log` (rotating, up to 5 files of 5MB each):

```bash
# Windows
type logs\cwtosdp.log

# macOS / Linux
cat logs/cwtosdp.log
```

On Windows with the installer, the full path is: `%USERPROFILE%\CWtoSDP\logs\cwtosdp.log`

You can also navigate there directly: press **Win + R**, paste `%USERPROFILE%\CWtoSDP\logs`, and press Enter.

---

## Version History

| Version | Date | Changes |
| ------- | ---- | ------- |
| 1.4.0 | 2026-02-13 | **Expanded field mapping**: OS version/build/SP, memory, model, processors, network adapters (sub-resources). Fixed nested field updates via type-specific endpoints. Fixed DHCP validation (`true`/`false`). Fixed stale GUI after refresh (SyncEngine connection reuse). Product auto-injection for new assets. |
| 1.3.0 | 2026-02-12 | **CMDB → Assets API migration**: all sync operations now use the Assets API with nested field mapping (`operating_system`, `computer_system`). DB schema updated (`sdp_assets`). |
| 1.2.0 | 2026-02-12 | Fixed SDP create/update failures (HTTP 2xx acceptance), fixed unclosable progress window, fixed first-run crash when credentials are missing, improved error logging with device names |
| 1.1.0 | 2026-02-06 | Adaptive rate limiting with dynamic recovery, two-level dry run safety, CREATE + UPDATE sync, improved error handling |
| 1.0.0 | 2026-01-20 | Initial release — GUI sync manager, device classification, field mapping, dry run |
