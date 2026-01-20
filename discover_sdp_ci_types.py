"""Discover available CI types in SDP."""
import os
import requests
from dotenv import load_dotenv

load_dotenv('credentials.env')

# Get access token
def get_access_token():
    """Get OAuth access token using refresh token."""
    url = "https://accounts.zoho.eu/oauth/v2/token"
    data = {
        "refresh_token": os.getenv("ZOHO_REFRESH_TOKEN"),
        "client_id": os.getenv("ZOHO_CLIENT_ID"),
        "client_secret": os.getenv("ZOHO_CLIENT_SECRET"),
        "grant_type": "refresh_token"
    }
    response = requests.post(url, data=data)
    return response.json().get("access_token")

token = get_access_token()
print(f"Got access token: {token[:20]}...")

base_url = "https://sdpondemand.manageengine.eu/api/v3"
headers = {
    "Authorization": f"Zoho-oauthtoken {token}",
    "Accept": "application/vnd.manageengine.sdp.v3+json"
}

# Try to list CI types
print("\n" + "="*80)
print("DISCOVERING SDP CI TYPES")
print("="*80)

# Common CI type API names to try
ci_types_to_try = [
    "ci_workstation",
    "ci_windows_workstation",
    "ci_server",
    "ci_windows_server",
    "ci_linux_server",
    "ci_network_device",
    "ci_router",
    "ci_switch",
    "ci_firewall",
    "ci_printer",
    "ci_laptop",
    "ci_desktop",
    "ci_virtual_machine",
    "ci_vm",
]

print("\nTrying common CI type endpoints:")
for ci_type in ci_types_to_try:
    url = f"{base_url}/cmdb/{ci_type}"
    params = {"input_data": '{"list_info": {"row_count": 1}}'}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            count = data.get("list_info", {}).get("total_count", 0)
            print(f"  ✓ {ci_type}: {count} records")
        elif response.status_code == 400:
            # Check error message
            err = response.json().get("response_status", {})
            msg = err.get("messages", [{}])[0].get("message", "")
            if "Invalid CI Type" in msg or "not found" in msg.lower():
                print(f"  ✗ {ci_type}: Not available")
            else:
                print(f"  ? {ci_type}: {response.status_code} - {msg[:50]}")
        else:
            print(f"  ? {ci_type}: {response.status_code}")
    except Exception as e:
        print(f"  ! {ci_type}: Error - {e}")

# Try to get CI type metadata
print("\n" + "="*80)
print("TRYING CI TYPE METADATA ENDPOINT")
print("="*80)

# Get actual counts for all available types
print("\n" + "="*80)
print("AVAILABLE SDP CI TYPES FOR CW SYNC")
print("="*80)

available_types = {
    "ci_windows_workstation": "Laptop/Desktop (Windows)",
    "ci_windows_server": "Windows Server",
    "ci_linux_server": "Linux Server",
    "ci_virtual_machine": "Virtual Machine",
    "ci_switch": "Network Switch",
    "ci_router": "Network Router",
    "ci_firewall": "Firewall",
}

print("\nCW Category -> SDP CI Type Mapping:")
print("-"*60)
print(f"  {'CW Category':<20} -> {'SDP CI Type':<25} | Status")
print("-"*60)

mapping = {
    "Laptop": "ci_windows_workstation",
    "Desktop": "ci_windows_workstation",
    "Virtual Server": "ci_virtual_machine",
    "Physical Server": "ci_windows_server",
    "Network Device": "ci_switch",  # or ci_firewall depending on type
}

for cw_cat, sdp_type in mapping.items():
    url = f"{base_url}/cmdb/{sdp_type}"
    params = {"input_data": '{"list_info": {"row_count": 1}}'}
    response = requests.get(url, headers=headers, params=params, timeout=10)
    status = "✓ Available" if response.status_code == 200 else "✗ Not found"
    print(f"  {cw_cat:<20} -> {sdp_type:<25} | {status}")

