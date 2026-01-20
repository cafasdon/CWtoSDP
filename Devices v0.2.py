import requests
import os
import pandas as pd
import json
from dotenv import load_dotenv
import os

load_dotenv()

# Credentials & Variables
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
BASE_URL = "https://openapi.service.euplatform.connectwise.com"
FILEPATH = "/Users/macbook_air/"


def get_oauth2_token():
    # get OAuth2 token
    payload = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }

    headers = {"Content-Type": "application/json"}

    TOKEN_ENDPOINT = "/v1/token"
    TOKEN_URL = f"{BASE_URL}{TOKEN_ENDPOINT}"

    resp = requests.post(TOKEN_URL, json=payload, headers=headers)

    if resp.status_code == 200:
        return resp.json()["access_token"]
    else:
        raise Exception(f"Token request failed: {resp.status_code} {resp.text}")



def get_devices(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    ENDPOINT_URL = "/api/platform/v1/device/endpoints"

    API_URL = f"{BASE_URL}{ENDPOINT_URL}"
    resp = requests.get(API_URL, headers=headers)

    if resp.status_code == 200:
        data = resp.json()

        # Extract the list of devices from the "endpoints" key
        if isinstance(data, dict) and "endpoints" in data:
            return data["endpoints"]

        raise Exception("Unexpected response format: 'endpoints' key missing")
    else:
        raise Exception(f"Devices request failed: {resp.status_code} {resp.text}")



def get_site_list(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    ENDPOINT_URL = "/api/platform/v1/company/sites"

    API_URL = f"{BASE_URL}{ENDPOINT_URL}"
    resp = requests.get(API_URL, headers=headers)

    if resp.status_code == 200:
        data = resp.json()
        return data
    
    else:
        raise Exception(f"Endpoint System State Info request failed: {resp.status_code} {resp.text}")



def get_companies_list(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    ENDPOINT_URL = "/api/platform/v1/company/companies"

    API_URL = f"{BASE_URL}{ENDPOINT_URL}"
    resp = requests.get(API_URL, headers=headers)

    if resp.status_code == 200:
        data = resp.json()
        return data
    
    else:
        raise Exception(f"Endpoint System State Info request failed: {resp.status_code} {resp.text}")


def get_endpoint_system_state_info(token, endpointId):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    ENDPOINT_URL = f"/api/platform/v1/device/endpoints/{endpointId}/system-state-info"
    API_URL = f"{BASE_URL}{ENDPOINT_URL}"
    resp = requests.get(API_URL, headers=headers)

    if resp.status_code == 200:
        data = resp.json()
        return data
    
    else:
        raise Exception(f"Endpoint System State Info request failed: {resp.status_code} {resp.text}")

def get_endpoint_details(token, endpointId):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    ENDPOINT_URL = f"/api/platform/v1/device/endpoints/{endpointId}"
    API_URL = f"{BASE_URL}{ENDPOINT_URL}"
    resp = requests.get(API_URL, headers=headers)

    if resp.status_code == 200:
        data = resp.json()
        
        #with open('/Users/macbook_air/endpoint_data_json.json', 'w') as file:
        #    json.dump(data, file)
        
        return data
    
    else:
        raise Exception(f"Endpoint System State Info request failed: {resp.status_code} {resp.text} {endpointId}")


def convert_to_dataframe(data):
    # Convert list of devices to pandas DataFrame
    df = pd.json_normalize(data)
    #df = pd.json_normalize(devices, max_level=0)
    return df

def save_df_to_csv(df, filename):
    FILENAME = f"{FILEPATH}/{filename}"
    df.to_csv(FILENAME, index=False)
    print(f"Data saved to {filename}")


if __name__ == "__main__":
    token = get_oauth2_token()

    data = get_devices(token)
    devices_df = convert_to_dataframe(data)
    save_df_to_csv(devices_df, "devices_v2.csv")

    data = get_site_list(token)
    sites_df = convert_to_dataframe(data)
    save_df_to_csv(sites_df, "sites_v2.csv")

    data = get_companies_list(token)
    companies_df = convert_to_dataframe(data)
    save_df_to_csv(companies_df, "companies_v2.csv")

    cum_df_test = pd.DataFrame()

    number_of_devices = devices_df.shape[0]
    #for n in range(number_of_devices):
    n = 16
    print("TEST:")
    print(devices_df.at[n, 'regId'])
    if devices_df.at[n, 'regId'] != 0:
        endpointId = devices_df.at[n, 'endpointId']
        print(endpointId)
        data = get_endpoint_system_state_info(token=token, endpointId=endpointId)
        endpoint_system_state_info_df = convert_to_dataframe(data)
        cum_df_test = pd.concat([cum_df_test, endpoint_system_state_info_df], ignore_index=True)

            #data = get_endpoint_details(token=token, endpointId=endpointId)
            #endpoint_details_df = convert_to_dataframe(data)

        save_df_to_csv(cum_df_test, "endpoint_system_state_info_v3.csv")

    #print(endpoint_details_df.columns)

    #devices = get_devices(token)
    #df = devices_to_dataframe(devices)

    #df.to_csv("/Users/mf1_home/test_devices6.csv", index=False)

    #test = get_endpoint_system_state_info(token=token, endpointId='d1cebd02-044b-4d1f-b6d3-f51bc57f5707')
    #print("test:")
    #print(test)

    #df_test = devices_to_dataframe(test)

    #df_test.to_csv("/Users/mf1_home/test_devices_status1.csv", index=False)

    #test2 = get_endpoint_details(token=token, endpointId='d1cebd02-044b-4d1f-b6d3-f51bc57f5707')
    #print("test2:")
    #print(test2)

    #df_test2 = devices_to_dataframe_flatten(test2)

    #df_test2.to_csv("/Users/macbook_air/test_devices_detail2.csv", index=False)

    #print(df_test2.shape)
    #print(df_test2.columns)



    #test3 = get_site_list(token=token)
    #print("test3:")
    #print(test3)