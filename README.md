# CWtoSDP - ConnectWise to ServiceDesk Plus Integration

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Dual-green.svg)](LICENSE)

Integration tool for syncing device/asset data between **ConnectWise RMM** and **ManageEngine ServiceDesk Plus Cloud** CMDB.

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+** ([Download](https://www.python.org/downloads/))
- **ConnectWise RMM** admin access for API keys
- **ServiceDesk Plus Cloud** access for Zoho OAuth setup

### Installation

**Windows:** Double-click `start.bat`

**macOS:** Double-click `start.command`

**Linux:** Run `chmod +x start.sh && ./start.sh`

The installer will automatically set up everything and launch the GUI.

### First Time Setup

1. Launch the app using the commands above
2. Click **⚙️ Settings**
3. Enter your API credentials (see [SETUP.md](SETUP.md) for how to get them)
4. Click **Test Connections** → **Save**
5. Click **🔄 CW** and **🔄 SDP** to fetch data
6. Review the sync preview and execute when ready

📖 **Need detailed instructions?** See the complete [Setup Guide](SETUP.md)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **Sync Manager GUI** | Visual interface for previewing and executing syncs |
| **Dry Run Mode** | Preview changes before committing (enabled by default) |
| **Selective Sync** | Choose which items to sync with checkboxes |
| **Device Classification** | Auto-categorizes: Laptop, Desktop, Server, VM, Network |
| **Field Mapping** | Maps CW fields to SDP CMDB attributes |
| **Diff View** | Side-by-side comparison of CW vs SDP data |
| **Full DB View** | See all records from both systems with match status |
| **Revert Capability** | Undo last sync operation |
| **Incremental Fetch** | Only downloads new/changed data |
| **Rate Limiting** | Adaptive rate limiting prevents API throttling |
| **Settings GUI** | Configure credentials without editing files |

---

## 📦 Installation Options

### Option 1: One-Click Start (Recommended)

| Platform | Command |
|----------|---------|
| **Windows** | Double-click `start.bat` |
| **macOS** | Double-click `start.command` |
| **Linux** | `./start.sh` |

### Option 2: Manual Install

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

- **Match found** → UPDATE action (update existing CI fields)
- **No match** → CREATE action (create new CI)

### Preview Legend - Row Colors

| Color    | Action | Meaning                                 |
| -------- | ------ | --------------------------------------- |
| 🟢 Green | CREATE | New device, will create new CI in SDP   |
| 🔵 Blue  | UPDATE | Matched device, will update existing CI |

### Preview Legend - Field Indicators

For UPDATE items, each field shows what will happen:

| Indicator   | Meaning                                         |
| ----------- | ----------------------------------------------- |
| `★ value`   | **NEW** - Field is empty in SDP, will be added  |
| `old → new` | **CHANGED** - Different value, will be updated  |
| `value`     | **UNCHANGED** - Same in both systems, no change |

### Selection Behavior

- **Single-click** on any row toggles its selection (☑/☐)
- **✓ All / ✗ All** - Select/deselect ALL items (including filtered out)
- **✓ Filtered / ✗ Filtered** - Select/deselect only currently visible items
- Selections persist when filters change

### Dry Run vs Real Sync

| Mode      | Checkbox State | What Happens                        |
| --------- | -------------- | ----------------------------------- |
| Dry Run   | ☐ Unchecked    | Preview only, no changes to SDP     |
| Real Sync | ☑ Checked      | Actually creates/updates CIs in SDP |

---

## Field Mapping

### ConnectWise → ServiceDesk Plus

| CW Field                  | SDP CI Attribute                  |
| ------------------------- | --------------------------------- |
| `friendlyName`            | `name`                            |
| `system.serialNumber`     | `ci_attributes.txt_serial_number` |
| `operatingSystem.name`    | `ci_attributes.txt_os`            |
| `system.manufacturer`     | `ci_attributes.txt_manufacturer`  |
| `addresses[0].ipAddress`  | `ci_attributes.txt_ip_address`    |
| `addresses[0].macAddress` | `ci_attributes.txt_mac_address`   |

### SDP Field Types & Limits

| Prefix  | Type    | Character Limit | Example               |
| ------- | ------- | --------------- | --------------------- |
| `txt_`  | Text    | 250 chars       | `txt_serial_number`   |
| `num_`  | Numeric | N/A             | `num_processor_count` |
| `date_` | Date    | N/A             | `date_purchase_date`  |
| `ref_`  | Lookup  | Must exist      | `ref_owned_by`        |

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

| Issue                 | Solution                                        |
| --------------------- | ----------------------------------------------- |
| Script not running    | Check file permissions (`chmod +x` on Unix)     |
| Credentials not found | Ensure `credentials.env` exists in project root |
| Rate limit errors     | Increase delay between runs (hourly → daily)    |
| No output             | Check Task Scheduler history or cron logs       |

---

## Safety Features

⚠️ **DRY_RUN mode is ENABLED by default**

| Feature        | Default   | Description                     |
| -------------- | --------- | ------------------------------- |
| Dry Run        | ON        | Preview changes without writing |
| Selective Sync | ON        | Choose specific items to sync   |
| Confirmation   | Required  | Dialog before real sync         |
| Revert         | Available | Undo last sync operation        |

## Folder Structure

```text
CWtoSDP/
├── src/                          # Source code
│   ├── config.py                 # Configuration management
│   ├── cw_client.py              # ConnectWise API client
│   ├── sdp_client.py             # ServiceDesk Plus API client
│   ├── sync_engine.py            # Sync logic and matching
│   ├── sync_gui.py               # Sync Manager GUI
│   ├── field_mapper.py           # Device classification
│   ├── db_compare.py             # SQLite comparison database
│   ├── rate_limiter.py           # Adaptive rate limiting
│   ├── logger.py                 # Logging configuration
│   └── main.py                   # Entry point
├── data/                         # SQLite databases
├── logs/                         # Application logs
├── docs/                         # API documentation
├── install.bat/.command/.sh      # Platform installers
├── launch_sync.bat/.command/.sh  # GUI launchers
├── run_sync.bat/.command/.sh     # Automation launchers
├── run_sync.py                   # Automation script
├── credentials.env.template      # Credential template
└── requirements.txt              # Python dependencies
```

## Device Classification

| CW Type                    | Classification  | SDP CI Type            |
| -------------------------- | --------------- | ---------------------- |
| Desktop (ThinkPad/ProBook) | Laptop          | ci_windows_workstation |
| Desktop (other)            | Desktop         | ci_windows_workstation |
| Server + VMware serial     | Virtual Server  | ci_virtual_machine     |
| Server + real serial       | Physical Server | ci_windows_server      |
| NetworkDevice              | Network Device  | ci_switch              |

## API Access

| System           | Endpoint                  | Access    |
| ---------------- | ------------------------- | --------- |
| ConnectWise      | Devices, Sites, Companies | Read      |
| ServiceDesk Plus | Requests                  | Read-only |
| ServiceDesk Plus | Assets                    | Full CRUD |
| ServiceDesk Plus | CMDB                      | Full CRUD |

## Data Centers

| Region | Zoho Accounts        | SDP API                         |
| ------ | -------------------- | ------------------------------- |
| EU     | accounts.zoho.eu     | sdpondemand.manageengine.eu     |
| US     | accounts.zoho.com    | sdpondemand.manageengine.com    |
| IN     | accounts.zoho.in     | sdpondemand.manageengine.in     |
| AU     | accounts.zoho.com.au | sdpondemand.manageengine.com.au |

## Documentation

See `docs/ManageEngine-ServiceDesk-API.md` for complete API documentation.
