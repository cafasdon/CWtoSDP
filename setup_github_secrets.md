# Setting Up GitHub Secrets for CWtoSDP

This guide explains how to add your API credentials as GitHub repository secrets for secure CI/CD workflows.

## Why Use GitHub Secrets?

- Secrets are encrypted and not exposed in logs
- They can be used in GitHub Actions workflows
- Keeps credentials out of your repository code

## Required Secrets

Add these secrets to your GitHub repository:

| Secret Name | Description |
|-------------|-------------|
| `CLIENT_ID` | ConnectWise RMM Client ID |
| `CLIENT_SECRET` | ConnectWise RMM Client Secret |
| `ZOHO_CLIENT_ID` | Zoho/SDP OAuth Client ID |
| `ZOHO_CLIENT_SECRET` | Zoho/SDP OAuth Client Secret |
| `ZOHO_REFRESH_TOKEN` | Zoho/SDP OAuth Refresh Token |

## How to Add Secrets (Web Interface)

1. Go to your repository on GitHub: https://github.com/cafasdon/CWtoSDP
2. Click **Settings** (top menu)
3. Click **Secrets and variables** → **Actions** (left sidebar)
4. Click **New repository secret**
5. Add each secret:
   - **Name**: Enter the secret name (e.g., `CLIENT_ID`)
   - **Secret**: Paste the value
   - Click **Add secret**
6. Repeat for all 5 secrets

## How to Add Secrets (GitHub CLI)

If you have GitHub CLI installed and authenticated:

```bash
# Authenticate first
gh auth login

# Add secrets
gh secret set CLIENT_ID --body "your_client_id_here"
gh secret set CLIENT_SECRET --body "your_client_secret_here"
gh secret set ZOHO_CLIENT_ID --body "your_zoho_client_id_here"
gh secret set ZOHO_CLIENT_SECRET --body "your_zoho_client_secret_here"
gh secret set ZOHO_REFRESH_TOKEN --body "your_zoho_refresh_token_here"

# Verify
gh secret list
```

## Current Values (DMH Stallard)

⚠️ **Keep these secure - do not share publicly**

```
CLIENT_ID=0e31ac825561aa31e8fbe14906bfaf86
CLIENT_SECRET=_33FQU7-qI-gNiSs9OCFG1Iaj3OpuH9tuSVMw3QrnOU
ZOHO_CLIENT_ID=1000.MRFPAUP5TT668XSZZKC85XCR9V58GW
ZOHO_CLIENT_SECRET=b359c175f3f47d397b9721d8fc0b60d7071b1243a1
ZOHO_REFRESH_TOKEN=1000.6889d091a0e47de19bad4654a80e3329.354767c5a7b7b7a03ee533ff1076342f
```

## Using Secrets in GitHub Actions

Example workflow that uses these secrets:

```yaml
name: Sync Workflow
on:
  workflow_dispatch:

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Create credentials file
        run: |
          cat > credentials.env << EOF
          CLIENT_ID=${{ secrets.CLIENT_ID }}
          CLIENT_SECRET=${{ secrets.CLIENT_SECRET }}
          ZOHO_CLIENT_ID=${{ secrets.ZOHO_CLIENT_ID }}
          ZOHO_CLIENT_SECRET=${{ secrets.ZOHO_CLIENT_SECRET }}
          ZOHO_REFRESH_TOKEN=${{ secrets.ZOHO_REFRESH_TOKEN }}
          ZOHO_ACCOUNTS_URL=https://accounts.zoho.eu
          ZOHO_TOKEN_URL=https://accounts.zoho.eu/oauth/v2/token
          SDP_API_BASE_URL=https://sdpondemand.manageengine.eu/api/v3
          EOF
      
      - name: Run sync (dry run)
        run: python -m src.main --fetch-cw --fetch-sdp
```

