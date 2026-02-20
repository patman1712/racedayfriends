import os
import requests
from dotenv import load_dotenv
from iracingdataapi.client import irDataClient

load_dotenv()

username = os.getenv("IRACING_USERNAME")
password = os.getenv("IRACING_PASSWORD")

print(f"Versuche Login mit: {username}")

# Wir nutzen requests direkt, um die Antwort zu sehen, wenn irDataClient versagt
session = requests.Session()
login_url = "https://members-ng.iracing.com/auth"
headers = {"Content-Type": "application/json"}
data = {"email": username, "password": password}

print(f"POST an {login_url}...")
try:
    r = session.post(login_url, headers=headers, json=data)
    print(f"Status Code: {r.status_code}")
    print("Response Headers:")
    print(r.headers)
    print("\nResponse Body (erste 1000 Zeichen):")
    print(r.text[:1000])
    
    # Versuche JSON parsing
    try:
        print("\nJSON Parsing Versuch:")
        print(r.json())
    except Exception as e:
        print(f"\nKEIN JSON: {e}")

except Exception as e:
    print(f"Request Fehler: {e}")
