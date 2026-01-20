# DMH Stallard - ServiceDesk Plus & ConnectWise Integration

## Project Overview

This project contains documentation and tools for integrating:
- **ManageEngine ServiceDesk Plus Cloud** (ITSM)
- **ConnectWise** (PSA/RMM)

For DMH Stallard, a UK-based legal firm.

## Folder Structure

```
DMH-SDP-CW/
├── credentials.env          # API credentials (DO NOT COMMIT)
├── docs/
│   └── ManageEngine-ServiceDesk-API.md  # Full API documentation
└── README.md
```

## Quick Start

### 1. Refresh Access Token

```bash
curl -X POST "https://accounts.zoho.eu/oauth/v2/token" \
  -d "refresh_token=YOUR_REFRESH_TOKEN" \
  -d "grant_type=refresh_token" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET"
```

### 2. Test API

```bash
curl -X GET "https://sdpondemand.manageengine.eu/api/v3/assets" \
  -H "Authorization: Zoho-oauthtoken YOUR_ACCESS_TOKEN" \
  -H "Accept: application/vnd.manageengine.sdp.v3+json"
```

## API Access Summary

| Endpoint | Scope | Access |
|----------|-------|--------|
| Requests | SDPOnDemand.requests.READ | Read-only |
| Assets | SDPOnDemand.assets.ALL | Full CRUD |
| CMDB | SDPOnDemand.cmdb.ALL | Full CRUD |

## Data Center

DMH Stallard is on the **EU Data Center**:
- Accounts: https://accounts.zoho.eu
- API: https://sdpondemand.manageengine.eu

## Documentation

See docs/ManageEngine-ServiceDesk-API.md for complete API documentation including:
- OAuth 2.0 authentication flow
- All working endpoints
- Data schemas
- CRUD examples
- Pagination

