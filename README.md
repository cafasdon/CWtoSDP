# CWtoSDP - ConnectWise to ServiceDesk Plus Integration

## Project Overview

Integration tool for syncing device/asset data between:

- **ConnectWise** (PSA/RMM) → Source of truth for devices
- **ManageEngine ServiceDesk Plus Cloud** (ITSM/CMDB) → Target for CMDB

For DMH Stallard, a UK-based legal firm.

## Folder Structure

```
CWtoSDP/
├── src/                      # Source code
│   ├── __init__.py
│   ├── config.py             # Configuration management
│   ├── logger.py             # Logging setup
│   ├── cw_client.py          # ConnectWise API client
│   ├── sdp_client.py         # ServiceDesk Plus API client
│   └── main.py               # Entry point
├── docs/
│   └── ManageEngine-ServiceDesk-API.md  # API documentation
├── credentials.env           # API credentials (DO NOT COMMIT)
├── requirements.txt          # Python dependencies
└── README.md
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Credentials

Create a `credentials.env` file with:

```env
# ConnectWise
CLIENT_ID=your_cw_client_id
CLIENT_SECRET=your_cw_client_secret

# ServiceDesk Plus (Zoho)
ZOHO_CLIENT_ID=your_zoho_client_id
ZOHO_CLIENT_SECRET=your_zoho_client_secret
ZOHO_REFRESH_TOKEN=your_refresh_token
```

### 3. Run the Tool

```bash
# Fetch ConnectWise data and export to CSV
python -m src.main --fetch-cw --export

# Fetch ServiceDesk Plus data (READ-ONLY)
python -m src.main --fetch-sdp --export

# Fetch both
python -m src.main --fetch-cw --fetch-sdp --export
```

## Safety Features

⚠️ **DRY_RUN mode is ENABLED by default** - No write operations will be performed.

| Feature      | Default  | Description                                     |
| ------------ | -------- | ----------------------------------------------- |
| `--dry-run`  | ON       | Blocks all write operations to ServiceDesk Plus |
| Batch limits | 50       | Max items processed per batch                   |
| Confirmation | Required | Prompts before write operations                 |

## API Access Summary

| System           | Endpoint                  | Access    |
| ---------------- | ------------------------- | --------- |
| ConnectWise      | Devices, Sites, Companies | Read      |
| ServiceDesk Plus | Requests                  | Read-only |
| ServiceDesk Plus | Assets                    | Full CRUD |
| ServiceDesk Plus | CMDB                      | Full CRUD |

## Data Centers

- **ConnectWise EU**: https://openapi.service.euplatform.connectwise.com
- **Zoho EU**: https://accounts.zoho.eu
- **SDP EU**: https://sdpondemand.manageengine.eu

## Documentation

See `docs/ManageEngine-ServiceDesk-API.md` for complete API documentation.
