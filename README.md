# CWtoSDP - ConnectWise to ServiceDesk Plus Integration

## Project Overview

Integration tool for syncing device/asset data between:

- **ConnectWise RMM** → Source of truth for devices
- **ManageEngine ServiceDesk Plus Cloud** (ITSM/CMDB) → Target for CMDB

For DMH Stallard, a UK-based legal firm.

## Features

- ✅ **Sync Manager GUI** - Visual interface for previewing and executing syncs
- ✅ **Dry Run Mode** - Preview changes before committing (enabled by default)
- ✅ **Selective Sync** - Choose which items to sync
- ✅ **Device Classification** - Auto-categorizes devices (Laptop, Server, VM, Network)
- ✅ **Field Mapping** - Maps CW fields to SDP CMDB fields
- ✅ **Revert Capability** - Undo last sync operation
- ✅ **Settings GUI** - Configure API credentials without editing files

## Quick Start

### Option 1: One-Click Install (Recommended)

| Platform    | Installer                      | Launcher                           |
| ----------- | ------------------------------ | ---------------------------------- |
| **Windows** | Double-click `install.bat`     | Double-click `launch_sync.bat`     |
| **macOS**   | Double-click `install.command` | Double-click `launch_sync.command` |
| **Linux**   | Run `./install.sh`             | Run `./launch_sync.sh`             |

### Option 2: Manual Install

```bash
# 1. Create virtual environment
python -m venv venv

# 2. Activate it
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure credentials (or use GUI Settings)
cp credentials.env.template credentials.env
# Edit credentials.env with your API keys

# 5. Launch Sync Manager
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

## Safety Features

⚠️ **DRY_RUN mode is ENABLED by default**

| Feature        | Default   | Description                     |
| -------------- | --------- | ------------------------------- |
| Dry Run        | ON        | Preview changes without writing |
| Selective Sync | ON        | Choose specific items to sync   |
| Confirmation   | Required  | Dialog before real sync         |
| Revert         | Available | Undo last sync operation        |

## Folder Structure

```
CWtoSDP/
├── src/                      # Source code
│   ├── config.py             # Configuration management
│   ├── cw_client.py          # ConnectWise API client
│   ├── sdp_client.py         # ServiceDesk Plus API client
│   ├── sync_engine.py        # Sync logic and matching
│   ├── sync_gui.py           # Sync Manager GUI
│   ├── field_mapper.py       # Device classification
│   └── main.py               # Entry point
├── data/                     # SQLite databases
├── logs/                     # Application logs
├── install.bat/.command/.sh  # Platform installers
├── launch_sync.bat/.command/.sh  # Platform launchers
├── credentials.env.template  # Credential template
└── requirements.txt          # Python dependencies
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
