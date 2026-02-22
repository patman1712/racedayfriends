import os
import requests
import sys
from dotenv import load_dotenv

# Wir nutzen requests direkt, um die Antwort zu sehen, da die Library den Fehler verschluckt
try:
    from iracingdataapi.client import irDataClient
except ImportError:
    print("FEHLER: Bitte installiere die Library: pip install iracingdataapi")
    sys.exit(1)

load_dotenv()

# --- KONFIGURATION ---
RAILWAY_URL = os.getenv('RAILWAY_URL', 'https://racedayfriends.up.railway.app')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')
IRACING_USER = os.getenv('IRACING_USERNAME', '')
IRACING_PASSWORD = os.getenv('IRACING_PASSWORD', '')

if not IRACING_USER or not IRACING_PASSWORD:
    sys.exit(1)

def main():
    print("--- iRacing Sync Tool v3 (Deep Debug) ---")
    
    # 1. Login
    print(f"Login als {IRACING_USER}...")
    try:
        # Wir nutzen den Client, um die Session zu bekommen
        client = irDataClient(username=IRACING_USER, password=IRACING_PASSWORD)
        print("Login OK!")
    except Exception as e:
        print(f"Login Fehler: {e}")
        sys.exit(1)
    
    # 2. Manueller Request mit der Client-Session
    # Wir nehmen ID 716131 (Patrick), da die valide aussieht
    test_id = 716131
    print(f"Versuche manuellen Abruf für ID {test_id} um Antwort zu sehen...")
    
    url = "https://members-ng.iracing.com/data/stats/member_career"
    params = {"cust_id": test_id}
    
    # Wir nutzen die Session aus der Library (Versuch: session oder _session)
    try:
        session = getattr(client, 'session', getattr(client, '_session', None))
        if not session:
            print("Konnte Session-Objekt nicht finden. Breche ab.")
            sys.exit(1)
            
        resp = session.get(url, params=params)
        print(f"Status Code: {resp.status_code}")
        
        try:
            data = resp.json()
            print("JSON Antwort erhalten (Wunder!):")
            print(str(data)[:100])
        except:
            print("KEIN JSON ERHALTEN! Hier ist der Text (die ersten 500 Zeichen):")
            print("-" * 40)
            print(resp.text[:500])
            print("-" * 40)
            
            if "Incapsula" in resp.text:
                print("DIAGNOSE: Bot-Schutz (Incapsula) blockiert uns.")
            elif "Cloudflare" in resp.text:
                print("DIAGNOSE: Cloudflare blockiert uns.")
            elif "maintenance" in resp.text.lower():
                print("DIAGNOSE: iRacing ist in Wartung.")
            elif "terms" in resp.text.lower() or "eula" in resp.text.lower():
                print("DIAGNOSE: Du musst auf der Webseite neue AGBs akzeptieren!")
                
    except Exception as e:
        print(f"Request Fehler: {e}")

if __name__ == "__main__":
    main()