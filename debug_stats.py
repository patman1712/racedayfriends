
import os
import json
from app import app, load_events, secure_filename

def debug_driver_stats(driver_id):
    print(f"--- DEBUGGING DRIVER {driver_id} ---")
    
    with app.app_context():
        # Config check
        res_folder = app.config['RESULTS_FOLDER']
        print(f"RESULTS_FOLDER: {res_folder}")
        if not os.path.exists(res_folder):
            print("ERROR: Results folder does not exist!")
            return

        events = load_events()
        d_id_str = str(driver_id)
        
        print(f"Loaded {len(events)} events.")
        
        for e in events:
            # Check participation
            d_ids = e.get('drivers', [])
            d_ids_str = [str(did) for did in d_ids]
            
            if d_id_str in d_ids_str:
                print(f"\nEvent found for driver: {e['title']} (ID: {e['id']})")
                
                # Check result file
                res_file = e.get('result_file')
                print(f"  Result file in event data: '{res_file}'")
                
                if res_file:
                    full_path = os.path.join(res_folder, secure_filename(res_file))
                    print(f"  Full path: {full_path}")
                    
                    if os.path.exists(full_path):
                        print("  File EXISTS on disk.")
                        try:
                            with open(full_path, 'r') as f:
                                res_data = json.load(f)
                                
                            sessions = res_data.get('data', {}).get('session_results', [])
                            race_session = next((s for s in sessions if s.get('simsession_type_name') == 'Race'), sessions[-1] if sessions else None)
                            
                            if race_session:
                                print("  Race session found in JSON.")
                                results = race_session.get('results', [])
                                print(f"  Found {len(results)} driver results in session.")
                                
                                # Search for driver
                                d_res = next((r for r in results if str(r.get('cust_id')) == d_id_str), None)
                                
                                if d_res:
                                    print("  SUCCESS: Driver found in results!")
                                    print(f"  Best Lap: {d_res.get('best_lap_time')}")
                                    print(f"  Incidents: {d_res.get('incidents')}")
                                else:
                                    print("  FAILURE: Driver NOT found in results by ID.")
                                    # List available IDs
                                    available_ids = [str(r.get('cust_id')) for r in results]
                                    print(f"  Available IDs in result: {available_ids}")
                                    
                                    # Try Name Match
                                    # driver name not available here easily without loading driver list, skipping
                            else:
                                print("  FAILURE: No race session found.")
                                
                        except Exception as ex:
                            print(f"  ERROR reading/parsing JSON: {ex}")
                    else:
                        print("  FAILURE: File does NOT exist on disk.")
                else:
                    print("  No result file linked.")
            else:
                # print(f"Skipping event {e['title']} (driver not participating)")
                pass

if __name__ == "__main__":
    # Test with Patrick Scheiber ID
    debug_driver_stats(1771591892)
