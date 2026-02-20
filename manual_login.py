import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

username = os.getenv("IRACING_USERNAME")
password = os.getenv("IRACING_PASSWORD")

print(f"Testing manual login for: {username}")

urls_to_test = [
    "https://members-ng.iracing.com/auth",
    "https://members-ng.iracing.com/auth/",
    "https://members-ng.iracing.com/auth/login",
    "https://members-ng.iracing.com/login",
    "https://members-ng.iracing.com/api/auth",
]

headers = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
data = {"email": username, "password": password}

for url in urls_to_test:
    print(f"\nTesting URL: {url}")
    try:
        r = requests.post(url, headers=headers, json=data, timeout=5)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            print("SUCCESS!")
            print(r.text[:200])
            break
        elif r.status_code == 401:
            print("401 Unauthorized - Credentials wrong or 2FA required.")
        else:
            print(f"Failed with {r.status_code}")
            
    except Exception as e:
        print(f"Error: {e}")
