
import os
import json
from app import app, get_drivers_data, load_events, secure_filename

# Mock request context if needed, but we are just calling logic
def debug_driver_logic(driver_id):
    print(f"Checking for Driver ID: {driver_id}")
    
    with app.app_context():
        # Setup paths (simulate app running)
        # Assuming app.config is already set correctly by import
        print(f"RESULTS_FOLDER: {app.config['RESULTS_FOLDER']}")
        
        events = load_events()
        d_id_str = str(driver_id)
        
        driver_events = []
        for e in events:
            d_ids = e.get('drivers', [])
            d_ids_str = [str(did) for did in d_ids]
            
            if d_id_str in d_ids_str:
                print(f"Found event: {e['title']}")
                if e.get('result_file'):
                    print(f"  Has result file: {e['result_file']}")
                    res_path = os.path.join(app.config['RESULTS_FOLDER'], secure_filename(e['result_file']))
                    print(f"  Checking path: {res_path}")
                    
                    if os.path.exists(res_path):
                        print("  File exists!")
                        try:
                            with open(res_path, 'r') as f:
                                res_data = json.load(f)
                                sessions = res_data.get('data', {}).get('session_results', [])
                                race_session = next((s for s in sessions if s.get('simsession_type_name') == 'Race'), sessions[-1] if sessions else None)
                                
                                if race_session:
                                    print("  Race session found.")
                                    # Find driver
                                    d_res = next((r for r in race_session.get('results', []) if str(r.get('cust_id')) == d_id_str), None)
                                    
                                    if d_res:
                                        print(f"  Driver found in results! Inc: {d_res.get('incidents')}")
                                    else:
                                        print("  Driver NOT found in results by ID.")
                                        # Dump all IDs in result
                                        ids = [r.get('cust_id') for r in race_session.get('results', [])]
                                        print(f"  IDs in result: {ids}")
                                else:
                                    print("  No race session found in JSON.")
                        except Exception as e:
                            print(f"  Error reading file: {e}")
                    else:
                        print("  File does NOT exist.")
                else:
                    print("  No result_file key.")

if __name__ == "__main__":
    debug_driver_logic(1771591892)
