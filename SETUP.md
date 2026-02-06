# CWtoSDP Setup Guide

This guide walks you through setting up CWtoSDP from scratch.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [API Credentials Setup](#api-credentials-setup)
4. [Configuration](#configuration)
5. [First Run](#first-run)
6. [Troubleshooting](#troubleshooting)

---

## Prerequisites

Before you begin, ensure you have:

| Requirement | Details |
|-------------|---------|
| **Python 3.8+** | Download from [python.org](https://www.python.org/downloads/) |
| **ConnectWise RMM Access** | Admin access to generate API keys |
| **ServiceDesk Plus Access** | Admin access to Zoho API Console |
| **Internet Connection** | Required for API calls |

### Verify Python Installation

```bash
python --version
# Should show: Python 3.8.x or higher
```

---

## Installation

### Option 1: One-Click Install (Recommended)

| Platform | Steps |
|----------|-------|
| **Windows** | Double-click `start.bat` |
| **macOS** | Double-click `start.command` (or right-click → Open) |
| **Linux** | Run `chmod +x start.sh && ./start.sh` |

The start script will automatically:

1. Check Python version
2. Create virtual environment
3. Install dependencies
4. Launch the GUI

### Option 2: Manual Install

```bash
# Clone the repository
git clone https://github.com/cafasdon/CWtoSDP.git
cd CWtoSDP

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate
# Activate (macOS/Linux)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy credentials template
cp credentials.env.template credentials.env

# Launch
python -m src.main --sync
```

---

## API Credentials Setup

### Step 1: ConnectWise RMM API Keys

1. Log into **ConnectWise RMM** as an administrator
2. Navigate to **Admin** → **Integrations** → **API Keys**
3. Click **Create New API Key**
4. Set permissions: Read access to Devices
5. Click **Create** and **copy the Client ID and Client Secret**

### Step 2: ServiceDesk Plus (Zoho) OAuth

ServiceDesk Plus uses Zoho OAuth2 authentication.

#### 2a. Register Application

1. Go to the Zoho API Console for your region:
   - EU: `https://api-console.zoho.eu`
   - US: `https://api-console.zoho.com`

2. Click **ADD CLIENT** → **Server-based Applications**

3. Fill in:
   - Client Name: `CWtoSDP Integration`
   - Homepage URL: `http://localhost`
   - Redirect URI: `http://localhost/callback`

4. Click **CREATE** and copy Client ID and Secret

#### 2b. Get Authorization Code

Open this URL in browser (replace YOUR_CLIENT_ID):

```text
https://accounts.zoho.eu/oauth/v2/auth?scope=SDPOnDemand.cmdb.ALL,SDPOnDemand.requests.ALL&client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http://localhost/callback&access_type=offline
```

After authorizing, copy the `code` parameter from the redirect URL.

#### 2c. Exchange for Refresh Token

```bash
curl -X POST "https://accounts.zoho.eu/oauth/v2/token" \
  -d "grant_type=authorization_code" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "redirect_uri=http://localhost/callback" \
  -d "code=YOUR_AUTHORIZATION_CODE"
```

Copy the `refresh_token` from the response.

---

## Configuration

### Option A: Using the GUI (Recommended)

1. Launch: `python -m src.main --sync`
2. Click **⚙️ Settings**
3. Enter your credentials
4. Select your data center region
5. Click **Test Connections**
6. Click **Save**

### Option B: Edit credentials.env

Copy template and edit:

```bash
cp credentials.env.template credentials.env
```

See `credentials.env.template` for detailed instructions on each field.

---

## First Run

1. **Launch** the Sync Manager
2. **Refresh Data**: Click 🔄 CW and 🔄 SDP buttons to fetch data from both APIs
3. **Review Preview**: Check the sync actions — green rows are new CIs, blue rows are updates
4. **Test with Dry Run**: Click the sync button (dry run is ON by default — no changes are made, no API calls sent)
5. **Check Results**: Review the Results tab to see exactly what would happen
6. **Execute Sync**: When satisfied, check ☑ **Enable Real Sync** and click ⚠️ **Execute Real Sync**

> **Note:** The first data fetch may take a while depending on how many devices you have. The tool uses adaptive rate limiting — if the API starts throttling, it will slow down automatically and recover once the limit clears. Subsequent fetches are incremental and much faster.

---

## Troubleshooting

### Common Issues

#### "Python not found" or wrong version

**Problem:** The start script can't find Python.

**Solution:**

1. Download Python 3.8+ from [python.org](https://www.python.org/downloads/)
2. During installation, check "Add Python to PATH"
3. Restart your terminal
4. Verify: `python --version`

#### "Failed to authenticate with ConnectWise"

**Solutions:**

1. Double-check your Client ID and Secret
2. Ensure the API key has read access to devices
3. Check if the API key has been revoked
4. Try regenerating the API key

#### "Failed to authenticate with ServiceDesk Plus"

**Solutions:**

1. Verify your refresh token is correct
2. Check you're using the correct data center URLs
3. Ensure the OAuth scopes include `SDPOnDemand.cmdb.ALL`
4. Authorization codes expire after 1 minute - regenerate if needed

#### "Rate limit exceeded" (429 errors)

The app has built-in adaptive rate limiting that handles this automatically:

1. **You don't need to do anything** — the rate limiter will slow down when it hits a 429 and speed back up once the limit clears
2. **Backoff**: When rate limited, the wait between requests doubles (up to 120 seconds max)
3. **Recovery**: After the limit clears, wait times decrease dynamically — halving when far above target, fine-tuning when close
4. **Typical recovery**: From max throttle (120s) back to normal (~0.3s) takes about 5–10 minutes
5. For very large initial syncs, the first run may take longer — subsequent runs use incremental fetch and are much faster

#### Database errors on first run

This is normal - the database is created automatically. If errors persist:

1. Delete the `data/` folder contents
2. Restart the application
3. Click Refresh to repopulate

### Log Files

Logs are stored in `logs/cwtosdp_YYYYMMDD.log`. Check for detailed errors:

```bash
# Windows
type logs\cwtosdp_*.log

# macOS/Linux
cat logs/cwtosdp_*.log
```

---

## Security Notes

⚠️ **Keep your credentials secure:**

- **Never commit `credentials.env`** to version control
- File is already in `.gitignore`
- Restrict file permissions on Unix: `chmod 600 credentials.env`
- Use separate API keys for production vs testing
- Rotate credentials periodically

---

## Next Steps

Once setup is complete:

1. Review **README.md** for detailed usage
2. Test with **Dry Run** before real syncs
3. Set up **automation** for scheduled syncs (see README)
4. Back up your **databases** in the `data/` folder
