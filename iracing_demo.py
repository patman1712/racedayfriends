import os
import json
import sys
from datetime import datetime
from dotenv import load_dotenv
from iracingdataapi.client import irDataClient
from tabulate import tabulate

# Lade Umgebungsvariablen
load_dotenv()

DRIVERS_FILE = 'drivers.json'

def load_drivers():
    if not os.path.exists(DRIVERS_FILE):
        return []
    with open(DRIVERS_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_drivers(drivers):
    with open(DRIVERS_FILE, 'w') as f:
        json.dump(drivers, f, indent=4)

def get_client():
    username = os.getenv("IRACING_USERNAME")
    password = os.getenv("IRACING_PASSWORD")
    
    if not username or not password:
        print("Fehler: Bitte IRACING_USERNAME und IRACING_PASSWORD in der .env Datei setzen.")
        return None
        
    try:
        return irDataClient(username=username, password=password)
    except Exception as e:
        print(f"Verbindungsfehler: {e}")
        return None

def add_driver():
    try:
        new_id = int(input("Bitte die iRacing Customer ID eingeben: "))
        drivers = load_drivers()
        
        if new_id in drivers:
            print(f"Fahrer {new_id} ist bereits in der Liste.")
            return

        # Optional: Prüfen ob der Fahrer existiert (braucht API Call)
        client = get_client()
        if client:
            try:
                # Wir holen kurz die Info um den Namen zu checken und zu bestätigen
                info = client.member(cust_id=[new_id])
                if info and 'members' in info and len(info['members']) > 0:
                    driver_name = info['members'][0]['display_name']
                    print(f"Fahrer gefunden: {driver_name}")
                    drivers.append(new_id)
                    save_drivers(drivers)
                    print(f"Fahrer {driver_name} ({new_id}) wurde hinzugefügt.")
                else:
                    print(f"Kein Fahrer mit ID {new_id} gefunden.")
            except Exception as e:
                print(f"Fehler beim Überprüfen der ID: {e}")
                # Trotzdem hinzufügen? Besser fragen.
                choice = input("Fehler bei der Überprüfung. Trotzdem hinzufügen? (j/n): ")
                if choice.lower() == 'j':
                    drivers.append(new_id)
                    save_drivers(drivers)
                    print("Fahrer hinzugefügt.")
    except ValueError:
        print("Ungültige Eingabe. Bitte eine Zahl eingeben.")

def remove_driver():
    drivers = load_drivers()
    if not drivers:
        print("Keine Fahrer in der Liste.")
        return
        
    print("Gespeicherte Fahrer-IDs:", drivers)
    try:
        id_to_remove = int(input("Welche ID soll entfernt werden? "))
        if id_to_remove in drivers:
            drivers.remove(id_to_remove)
            save_drivers(drivers)
            print(f"ID {id_to_remove} entfernt.")
        else:
            print("ID nicht gefunden.")
    except ValueError:
        print("Ungültige Eingabe.")

def list_drivers_stats():
    drivers = load_drivers()
    if not drivers:
        print("Keine Fahrer gespeichert. Bitte füge erst Fahrer hinzu.")
        return

    client = get_client()
    if not client:
        return

    print(f"\nLade Daten für {len(drivers)} Fahrer...")
    
    try:
        # 1. Allgemeine Infos holen
        members_info = client.member(cust_id=drivers)
        
        table_data = []
        
        if members_info and 'members' in members_info:
            for m in members_info['members']:
                cust_id = m['cust_id']
                name = m['display_name']
                club = m['club_name']
                
                # Lizenzen extrahieren (z.B. Sports Car und Formula)
                irating_road = "N/A"
                sr_road = "N/A"
                irating_formula = "N/A"
                sr_formula = "N/A"
                
                for lic in m.get('licenses', []):
                    cat = lic.get('category')
                    if cat == 'sports_car':
                        irating_road = lic.get('irating')
                        sr_road = f"{lic.get('group_name')} {lic.get('safety_rating')}"
                    elif cat == 'formula':
                        irating_formula = lic.get('irating')
                        sr_formula = f"{lic.get('group_name')} {lic.get('safety_rating')}"

                # Letztes Rennen (kurzer separater Call pro Fahrer nötig oder Batch wenn möglich)
                # Die stats_member_recent_races ist pro User.
                last_race_info = "Keine Daten"
                last_race_track = "-"
                last_race_pos = "-"
                last_race_inc = "-"

                try:
                    recent = client.stats_member_recent_races(cust_id=cust_id)
                    if recent and 'races' in recent and len(recent['races']) > 0:
                        last_race = recent['races'][0]
                        
                        # Datum formatieren
                        raw_date = last_race['session_start_time']
                        dt = datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
                        date_str = dt.strftime('%d.%m.%Y')
                        
                        # Details extrahieren
                        track_name = last_race.get('track', {}).get('track_name', 'Unknown')
                        start_pos = last_race.get('start_position', '?')
                        finish_pos = last_race.get('finish_position', '?')
                        incidents = last_race.get('incidents', 0)
                        
                        last_race_info = date_str
                        last_race_track = track_name
                        last_race_pos = f"P{start_pos} -> P{finish_pos}"
                        last_race_inc = str(incidents)
                        
                except Exception as e:
                    # print(f"Fehler bei Recent Races für {cust_id}: {e}")
                    pass

                table_data.append([cust_id, name, irating_road, sr_road, irating_formula, sr_formula, last_race_info, last_race_track, last_race_pos, last_race_inc])

        headers = ["ID", "Name", "iR (S)", "SR (S)", "iR (F)", "SR (F)", "Datum", "Strecke", "Pos", "Incs"]
        print("\n" + tabulate(table_data, headers=headers, tablefmt="grid"))

    except Exception as e:
        print(f"Fehler beim Laden der Daten: {e}")

def main():
    while True:
        print("\n--- iRacing Manager ---")
        print("1. Fahrer hinzufügen")
        print("2. Fahrer entfernen")
        print("3. Fahrer-Daten & Statistiken anzeigen")
        print("4. Beenden")
        
        choice = input("Auswahl: ")
        
        if choice == '1':
            add_driver()
        elif choice == '2':
            remove_driver()
        elif choice == '3':
            list_drivers_stats()
        elif choice == '4':
            print("Ciao!")
            sys.exit()
        else:
            print("Ungültige Auswahl.")

if __name__ == "__main__":
    main()
