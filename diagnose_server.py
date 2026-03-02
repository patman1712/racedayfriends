
import os
import json
from app import app, load_events, load_drivers, secure_filename

def diagnose():
    print("--- DIAGNOSTIC START ---")
    
    with app.app_context():
        # 1. Check Directories
        res_folder = app.config['RESULTS_FOLDER']
        print(f"RESULTS_FOLDER config: {res_folder}")
        print(f"Exists? {os.path.exists(res_folder)}")
        if os.path.exists(res_folder):
            print(f"Contents: {os.listdir(res_folder)}")
        
        # 2. Check Drivers
        drivers = load_drivers()
        print(f"Loaded Drivers: {drivers}")
        
        # 3. Check Events
        events = load_events()
        print(f"Loaded {len(events)} events.")
        
        for e in events:
            print(f"\nEvent: {e['title']} (ID: {e['id']})")
            print(f"  Result File: {e.get('result_file')}")
            
            if e.get('result_file'):
                full_path = os.path.join(res_folder, secure_filename(e['result_file']))
                print(f"  Expected Path: {full_path}")
                exists = os.path.exists(full_path)
                print(f"  File Exists? {exists}")
                
                if exists:
                    try:
                        with open(full_path, 'r') as f:
                            data = json.load(f)
                        
                        sessions = data.get('data', {}).get('session_results', [])
                        race_session = next((s for s in sessions if s.get('simsession_type_name') == 'Race'), None)
                        
                        if race_session:
                            print("  Race Session Found.")
                            results = race_session.get('results', [])
                            print(f"  Driver IDs in result: {[r.get('cust_id') for r in results]}")
                            
                            # Check for matches
                            for d_id in drivers:
                                match = next((r for r in results if str(r.get('cust_id')) == str(d_id)), None)
                                if match:
                                    print(f"  -> MATCH found for Driver {d_id}: Pos {match.get('finish_position')}, Inc {match.get('incidents')}")
                                else:
                                    print(f"  -> NO MATCH for Driver {d_id}")
                        else:
                            print("  No Race Session in JSON.")
                    except Exception as ex:
                        print(f"  Error reading JSON: {ex}")

if __name__ == "__main__":
    diagnose()
