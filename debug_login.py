import os
from dotenv import load_dotenv
from iracingdataapi.client import irDataClient
import traceback

load_dotenv()

username = os.getenv("IRACING_USERNAME")
password = os.getenv("IRACING_PASSWORD")

print(f"Versuche Login mit: {username}")
# Passwort nur maskiert anzeigen
if password:
    print(f"Passwort Länge: {len(password)}")
    print(f"Passwort Ende: ...{password[-3:]}")
else:
    print("Kein Passwort gesetzt!")

try:
    idc = irDataClient(username=username, password=password)
    print("Client initialisiert. Versuche Daten abzurufen...")
    
    # Test call
    try:
        # Versuche etwas einfaches wie series oder seasons
        print("Rufe Serien ab...")
        series = idc.series()
        if series:
            print(f"Erfolg! {len(series)} Serien gefunden.")
        else:
            print("Keine Serien gefunden (aber kein Fehler).")
            
    except Exception as e:
        print(f"Fehler beim Datenabruf: {e}")
        traceback.print_exc()

except Exception as e:
    print(f"Fehler bei der Initialisierung: {e}")
    traceback.print_exc()
