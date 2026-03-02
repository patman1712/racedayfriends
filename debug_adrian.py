
import os
import json
from app import app, load_events, load_drivers, secure_filename

def debug_adrian():
    print("--- DEBUGGING ADRIAN BEUME (1771594254) ---")
    d_id_target = "1771594254"
    
    with app.app_context():
        res_folder = app.config['RESULTS_FOLDER']
        
        # Load IEC Event
        events = load_events()
        iec_event = next((e for e in events if str(e['id']) == "1771600365"), None)
        
        if not iec_event:
            print("IEC Event not found in events.json")
            return
            
        print(f"Event Found: {iec_event['title']}")
        print(f"Result File: {iec_event.get('result_file')}")
        
        res_file = iec_event.get('result_file')
        if not res_file:
            print("No result file linked.")
            return
            
        full_path = os.path.join(res_folder, secure_filename(res_file))
        print(f"Reading file: {full_path}")
        
        if not os.path.exists(full_path):
            print("File does not exist.")
            return
            
        with open(full_path, 'r') as f:
            data = json.load(f)
            
        sessions = data.get('data', {}).get('session_results', [])
        print(f"Sessions found: {len(sessions)}")
        
        for i, s in enumerate(sessions):
            print(f"Session {i}: {s.get('simsession_type_name')}")
            
        race_session = next((s for s in sessions if s.get('simsession_type_name') == 'Race'), None)
        
        if race_session:
            print("Race Session identified.")
            results = race_session.get('results', [])
            print(f"Total results in race: {len(results)}")
            
            # Find Adrian
            adrian_res = next((r for r in results if str(r.get('cust_id')) == d_id_target), None)
            
            if adrian_res:
                print("MATCH FOUND for Adrian!")
                print(f"Best Lap Raw: {adrian_res.get('best_lap_time')}")
                print(f"Incidents: {adrian_res.get('incidents')}")
                
                # Test Formatting
                val = adrian_res.get('best_lap_time', 0)
                if val > 0:
                    seconds = val / 10000
                    minutes = int(seconds // 60)
                    rem_seconds = seconds % 60
                    formatted = f"{minutes}:{rem_seconds:06.3f}"
                    print(f"Formatted Time: {formatted}")
            else:
                print("Adrian NOT found in results.")
                print("Available IDs:")
                for r in results:
                    print(f" - {r.get('cust_id')} ({r.get('display_name')})")
        else:
            print("No Race session found.")

if __name__ == "__main__":
    debug_adrian()
