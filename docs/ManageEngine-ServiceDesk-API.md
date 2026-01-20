# ManageEngine ServiceDesk Plus Cloud API Documentation

## Overview

This document covers the REST API for ManageEngine ServiceDesk Plus Cloud (SDP Cloud), which uses Zoho OAuth 2.0 for authentication.

---

## 1. Authentication

### 1.1 Zoho OAuth 2.0 Flow

ServiceDesk Plus Cloud uses Zoho's OAuth 2.0 for authentication. The flow consists of:

1. **Authorization Code** → Single-use, expires in 1-2 minutes
2. **Access Token** → Valid for 1 hour, used in API calls
3. **Refresh Token** → Never expires, used to generate new access tokens

### 1.2 Data Centers

| Region | Accounts URL        | API Base URL                   |
| ------ | ------------------- | ------------------------------ |
| US     | `accounts.zoho.com` | `sdpondemand.manageengine.com` |
| EU     | `accounts.zoho.eu`  | `sdpondemand.manageengine.eu`  |
| UK     | `accounts.zoho.uk`  | `servicedeskplus.uk`           |
| IN     | `accounts.zoho.in`  | `sdpondemand.manageengine.in`  |

### 1.3 Available Scopes

| Scope                       | Access Level                       |
| --------------------------- | ---------------------------------- |
| `SDPOnDemand.requests.ALL`  | Full access to service requests    |
| `SDPOnDemand.requests.READ` | Read-only access to requests       |
| `SDPOnDemand.assets.ALL`    | Full access to assets              |
| `SDPOnDemand.cmdb.ALL`      | Full access to CMDB                |
| `SDPOnDemand.changes.ALL`   | Full access to change management   |
| `SDPOnDemand.problems.ALL`  | Full access to problem management  |
| `SDPOnDemand.setup.ALL`     | Full access to admin settings      |
| `SDPOnDemand.setup.READ`    | Read-only access to admin settings |

### 1.4 Step 1: Create Self Client

1. Go to Zoho API Console: `https://api-console.zoho.eu/` (use correct region)
2. Click **"Add Client"** → Select **"Self Client"**
3. Save the **Client ID** and **Client Secret**

### 1.5 Step 2: Generate Authorization Code

In the Self Client, go to **"Generate Code"** tab:

- Enter required scopes (comma-separated)
- Set duration (e.g., 10 minutes)
- Click **Generate**

### 1.6 Step 3: Exchange Code for Tokens

**⚠️ Must be done within 1-2 minutes of code generation!**

```bash
curl -X POST "https://accounts.zoho.eu/oauth/v2/token" \
  -d "code=AUTHORIZATION_CODE" \
  -d "grant_type=authorization_code" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET"
```

**Response:**

```json
{
  "access_token": "1000.xxxx.yyyy",
  "refresh_token": "1000.xxxx.yyyy",
  "scope": "SDPOnDemand.assets.ALL SDPOnDemand.cmdb.ALL",
  "api_domain": "https://www.zohoapis.eu",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

### 1.7 Refreshing Access Tokens

```bash
curl -X POST "https://accounts.zoho.eu/oauth/v2/token" \
  -d "refresh_token=YOUR_REFRESH_TOKEN" \
  -d "grant_type=refresh_token" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET"
```

---

## 2. API Request Format

### 2.1 Headers

All API requests require:

```http
Authorization: Zoho-oauthtoken YOUR_ACCESS_TOKEN
Accept: application/vnd.manageengine.sdp.v3+json
Content-Type: application/x-www-form-urlencoded
```

### 2.2 Base URL

```text
https://sdpondemand.manageengine.eu/api/v3/
```

---

## 3. Working Endpoints

### 3.1 Requests

| Method | Endpoint                | Description        |
| ------ | ----------------------- | ------------------ |
| GET    | `/api/v3/requests`      | List all requests  |
| GET    | `/api/v3/requests/{id}` | Get single request |
| POST   | `/api/v3/requests`      | Create request     |
| PUT    | `/api/v3/requests/{id}` | Update request     |
| DELETE | `/api/v3/requests/{id}` | Delete request     |

### 3.2 Assets

| Method | Endpoint              | Description      |
| ------ | --------------------- | ---------------- |
| GET    | `/api/v3/assets`      | List all assets  |
| GET    | `/api/v3/assets/{id}` | Get single asset |
| POST   | `/api/v3/assets`      | Create asset     |
| PUT    | `/api/v3/assets/{id}` | Update asset     |
| DELETE | `/api/v3/assets/{id}` | Delete asset     |

### 3.3 CMDB (Configuration Items)

**Endpoint Pattern:** `/api/v3/cmdb/{ci_type_api_name}`

| Method | Endpoint                           | Description               |
| ------ | ---------------------------------- | ------------------------- |
| GET    | `/api/v3/cmdb/ci_workstation`      | List Windows workstations |
| GET    | `/api/v3/cmdb/ci_workstation/{id}` | Get single workstation    |
| POST   | `/api/v3/cmdb/ci_workstation`      | Create workstation CI     |
| PUT    | `/api/v3/cmdb/ci_workstation/{id}` | Update workstation CI     |
| DELETE | `/api/v3/cmdb/ci_workstation/{id}` | Delete workstation CI     |

---

## 4. Error Responses

| Error              | Meaning                                     |
| ------------------ | ------------------------------------------- |
| `invalid_client`   | Wrong Client ID/Secret or wrong data center |
| `invalid_code`     | Authorization code expired or already used  |
| `INVALID_TOKEN`    | Access token invalid or expired             |
| `missing_org_info` | Credentials valid but missing org context   |
| `4007 Invalid URL` | Endpoint does not exist                     |

---

## 5. Data Schemas

### 5.1 Request Schema

| Field          | Type     | Description                                     |
| -------------- | -------- | ----------------------------------------------- |
| `id`           | long     | Unique request ID                               |
| `display_id`   | string   | Display ID (e.g., "DMHIT-47")                   |
| `subject`      | string   | Request subject (max 250 chars)                 |
| `description`  | html     | Request description                             |
| `status`       | object   | `{id, name, color, in_progress, stop_timer}`    |
| `requester`    | object   | User object with email, phone, site, department |
| `technician`   | object   | Assigned technician                             |
| `group`        | object   | Support group                                   |
| `template`     | object   | Request template                                |
| `created_time` | datetime | `{value (ms), display_value}`                   |
| `due_by_time`  | datetime | Due date/time                                   |
| `priority`     | object   | Priority level                                  |
| `urgency`      | object   | Urgency level                                   |
| `impact`       | object   | Impact level                                    |
| `mode`         | object   | Request mode (email, phone, etc.)               |
| `site`         | object   | Site location                                   |

### 5.2 Asset Schema

| Field               | Type     | Description                             |
| ------------------- | -------- | --------------------------------------- |
| `id`                | long     | Unique asset ID                         |
| `name`              | string   | Asset name                              |
| `asset_tag`         | string   | Asset tag identifier                    |
| `product`           | object   | Product details with type, manufacturer |
| `site`              | object   | Site location                           |
| `state`             | object   | Asset state (In Use, Disposed, etc.)    |
| `created_time`      | datetime | Creation timestamp                      |
| `last_updated_time` | datetime | Last modification timestamp             |

### 5.3 CMDB Workstation Schema

| Field               | Type     | Description                           |
| ------------------- | -------- | ------------------------------------- |
| `id`                | long     | Unique CI ID                          |
| `name`              | string   | Computer/workstation name             |
| `description`       | string   | Description (optional)                |
| `ci_type`           | object   | CI type info (api_name, display_name) |
| `state`             | object   | CI state                              |
| `created_time`      | datetime | `{value (ms), display_value}`         |
| `last_updated_time` | datetime | Last modification timestamp           |
| `created_by`        | user     | Creator user object                   |
| `last_updated_by`   | user     | Last modifier user object             |
| `data_source`       | array    | Data sources                          |
| `ci_attributes`     | object   | **See CI Attributes below**           |

#### CI Attributes (ci_attributes)

| Field Key             | Type   | Description                                 |
| --------------------- | ------ | ------------------------------------------- |
| `ref_model`           | object | Product model (name, manufacturer, part_no) |
| `txt_service_tag`     | string | Device service tag                          |
| `txt_serial_number`   | string | Serial number                               |
| `txt_os`              | string | Operating system                            |
| `txt_ip_address`      | string | IP address(es)                              |
| `txt_mac_address`     | string | MAC address(es)                             |
| `txt_location`        | string | Physical location                           |
| `txt_processor_name`  | string | Processor info                              |
| `num_processor_count` | number | Number of processors                        |
| `txt_service_pack`    | string | Service pack version                        |
| `ref_owned_by`        | object | Owner reference                             |
| `ref_managed_by`      | object | Manager reference                           |
| `ref_business_impact` | object | Business impact level                       |

---

## 6. CRUD Operations

### 6.1 GET - List Items

```bash
curl -X GET "https://sdpondemand.manageengine.eu/api/v3/cmdb/ci_workstation" \
  -H "Authorization: Zoho-oauthtoken YOUR_ACCESS_TOKEN" \
  -H "Accept: application/vnd.manageengine.sdp.v3+json"
```

### 6.2 POST - Create Item

```bash
curl -X POST "https://sdpondemand.manageengine.eu/api/v3/cmdb/ci_workstation" \
  -H "Authorization: Zoho-oauthtoken YOUR_ACCESS_TOKEN" \
  -H "Accept: application/vnd.manageengine.sdp.v3+json" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d 'input_data={
    "ci_workstation": {
      "name": "NEW-WORKSTATION-01",
      "description": "Test workstation",
      "ci_attributes": {
        "txt_ip_address": "192.168.1.100",
        "txt_os": "Windows 11 Pro",
        "txt_serial_number": "ABC123XYZ"
      }
    }
  }'
```

### 6.3 PUT - Update Item

```bash
curl -X PUT "https://sdpondemand.manageengine.eu/api/v3/cmdb/ci_workstation/{id}" \
  -H "Authorization: Zoho-oauthtoken YOUR_ACCESS_TOKEN" \
  -H "Accept: application/vnd.manageengine.sdp.v3+json" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d 'input_data={
    "ci_workstation": {
      "ci_attributes": {
        "txt_ip_address": "192.168.1.200"
      }
    }
  }'
```

### 6.4 DELETE - Remove Item

```bash
curl -X DELETE "https://sdpondemand.manageengine.eu/api/v3/cmdb/ci_workstation/{id}" \
  -H "Authorization: Zoho-oauthtoken YOUR_ACCESS_TOKEN" \
  -H "Accept: application/vnd.manageengine.sdp.v3+json"
```

---

## 7. Pagination

API responses include `list_info` with pagination details:

```json
{
  "list_info": {
    "has_more_rows": true,
    "sort_field": "name",
    "row_count": 10
  }
}
```

To paginate, use query parameters:

```bash
# Get page 2 with 50 rows per page
curl -X GET "https://sdpondemand.manageengine.eu/api/v3/cmdb/ci_workstation?list_info.row_count=50&list_info.start_index=51" \
  -H "Authorization: Zoho-oauthtoken YOUR_ACCESS_TOKEN"
```

---

## 8. Live Data Examples (from DMH Stallard Instance)

### 8.1 Sample Workstations Retrieved

| Name            | Model              | Manufacturer | OS             | Serial     | IP            |
| --------------- | ------------------ | ------------ | -------------- | ---------- | ------------- |
| DESKTOP-2974G47 | HP ProBook 450 G7  | HP           | Win 11 Pro x64 | 5CD038D9FK | 192.168.1.188 |
| DESKTOP-2C4AGHS | HP ProBook 450 G7  | HP           | Win 11 Pro x64 | 5CD038D9D2 | 192.168.0.110 |
| DESKTOP-OQGU3H5 | ThinkPad L14 Gen 2 | LENOVO       | Win 11 Pro x64 | PF3VGE79   | 172.19.30.32  |
| DHM09749        | ThinkPad L14 Gen 2 | LENOVO       | Win 11 Pro x64 | PF3VQ1SM   | 172.19.20.21  |
| DMH008537       | HP ProBook 450 G7  | HP           | Win 11 Pro x64 | 5CD038D9D6 | 192.168.0.154 |

### 8.2 Sites

| Site     | ID                | Default |
| -------- | ----------------- | ------- |
| Gatwick  | 11873000000233001 | Yes     |
| London   | 11873000000227121 | No      |
| Brighton | 11873000005913161 | No      |

---

## 9. Current Credentials

```text
Client ID:      1000.MRFPAUP5TT668XSZZKC85XCR9V58GW
Client Secret:  b359c175f3f47d397b9721d8fc0b60d7071b1243a1
Refresh Token:  1000.6889d091a0e47de19bad4654a80e3329.354767c5a7b7b7a03ee533ff1076342f
API Domain:     https://sdpondemand.manageengine.eu
Scopes:         SDPOnDemand.assets.ALL, SDPOnDemand.cmdb.ALL, SDPOnDemand.requests.READ
```

### Quick Token Refresh Command

```bash
curl -X POST "https://accounts.zoho.eu/oauth/v2/token" \
  -d "refresh_token=1000.6889d091a0e47de19bad4654a80e3329.354767c5a7b7b7a03ee533ff1076342f" \
  -d "grant_type=refresh_token" \
  -d "client_id=1000.MRFPAUP5TT668XSZZKC85XCR9V58GW" \
  -d "client_secret=b359c175f3f47d397b9721d8fc0b60d7071b1243a1"
```
