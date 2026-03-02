import os
import json
import sys
import shutil
import uuid
import zipfile
import io
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# Versuche iracingdataapi zu importieren
try:
    from iracingdataapi.client import irDataClient
    IRACING_AVAILABLE = True
except Exception as e: # Fange ALLE Fehler, nicht nur ImportError!
    IRACING_AVAILABLE = False
    print(f"Warnung: iracingdataapi konnte nicht geladen werden: {e}")

# --- Eigener Mini-Client (Fallback) ---
import hashlib
import base64
import requests

class SimpleIRacingClient:
    def __init__(self, username, password):
        self.session = requests.Session()
        self.username = username
        self.password = password
        self.authenticated = False
        self.login()

    def login(self):
        # 1. Passwort Hashen (Standard iRacing Hash)
        hash_val = hashlib.sha256((self.password + self.username.lower()).encode('utf-8')).digest()
        pw_hash = base64.b64encode(hash_val).decode('utf-8')
        
        # 2. Login Request
        url = "https://members-ng.iracing.com/auth"
        headers = {'Content-Type': 'application/json'}
        data = {"email": self.username, "password": pw_hash}
        
        try:
            resp = self.session.post(url, json=data, headers=headers, timeout=10)
            if resp.status_code == 200:
                self.authenticated = True
                print("SimpleClient: Login erfolgreich!")
            else:
                print(f"SimpleClient: Login fehlgeschlagen ({resp.status_code}): {resp.text[:100]}")
                raise Exception(f"Login Failed: {resp.status_code}")
        except Exception as e:
            print(f"SimpleClient: Connection Error: {e}")
            raise e

    def get_stats(self, cust_id):
        if not self.authenticated:
            raise Exception("Not authenticated")
            
        url = "https://members-ng.iracing.com/data/stats/member_career"
        params = {"cust_id": cust_id}
        
        resp = self.session.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json().get('stats', [])
        else:
            print(f"Stats Error {cust_id}: {resp.status_code}")
            return None

# Lade Umgebungsvariablen
try:
    load_dotenv()
except Exception as e:
    print(f"Warnung: Konnte .env nicht laden: {e}")

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'super-secret-key-for-dev') # Notwendig für Flash-Messages

# --- PERSISTENZ KONFIGURATION (Volume Support) ---
RAILWAY_VOLUME_MOUNT_POINT = os.environ.get('RAILWAY_VOLUME_MOUNT_POINT', '/app/persistent')

if os.path.exists(RAILWAY_VOLUME_MOUNT_POINT):
    print(f"Persistentes Volume gefunden unter: {RAILWAY_VOLUME_MOUNT_POINT}")
    BASE_DATA_DIR = RAILWAY_VOLUME_MOUNT_POINT
else:
    print("Kein persistentes Volume gefunden, nutze lokales Verzeichnis.")
    BASE_DATA_DIR = os.path.dirname(os.path.abspath(__file__))

DRIVERS_FILE = os.path.join(BASE_DATA_DIR, 'drivers.json')
CONFIG_FILE = os.path.join(BASE_DATA_DIR, 'site_config.json')
CARS_FILE = os.path.join(BASE_DATA_DIR, 'cars.json')
EVENTS_FILE = os.path.join(BASE_DATA_DIR, 'events.json')
NEWS_FILE = os.path.join(BASE_DATA_DIR, 'news.json')
MESSAGES_FILE = os.path.join(BASE_DATA_DIR, 'messages.json')
LIVERIES_FILE = os.path.join(BASE_DATA_DIR, 'liveries.json')
SETUPS_FILE = os.path.join(BASE_DATA_DIR, 'setups.json')
APPLICATIONS_FILE = os.path.join(BASE_DATA_DIR, 'applications.json')
RESULTS_META_FILE = os.path.join(BASE_DATA_DIR, 'results_meta.json')
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123") # Default Passwort

# ...

def load_results_meta():
    if not os.path.exists(RESULTS_META_FILE):
        return {}
    try:
        with open(RESULTS_META_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_results_meta(data):
    with open(RESULTS_META_FILE, 'w') as f:
        json.dump(data, f, indent=4)

UPLOAD_FOLDER = os.path.join(BASE_DATA_DIR, 'static/uploads')
RESULTS_FOLDER = os.path.join(BASE_DATA_DIR, 'static/results')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
LOCAL_STATIC_UPLOADS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads')
LOCAL_STATIC_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/results')

# Initialisierung der Daten
def init_persistence():
    print("Starte init_persistence...")
    # 1. Ordner erstellen
    if not os.path.exists(BASE_DATA_DIR):
        try:
            os.makedirs(BASE_DATA_DIR)
            print(f"Ordner erstellt: {BASE_DATA_DIR}")
        except OSError as e:
            print(f"Fehler beim Erstellen von {BASE_DATA_DIR}: {e}")

    # 2. Upload & Results Ordner im Persistenten Bereich erstellen
    for folder in [UPLOAD_FOLDER, RESULTS_FOLDER]:
        if not os.path.exists(folder):
            try:
                os.makedirs(folder)
                print(f"Ordner erstellt: {folder}")
            except Exception as e:
                print(f"Fehler beim Erstellen von {folder}: {e}")

    # 3. Symlink für Uploads & Results
    # Uploads
    try:
        if os.path.abspath(LOCAL_STATIC_UPLOADS) != os.path.abspath(UPLOAD_FOLDER):
            if os.path.islink(LOCAL_STATIC_UPLOADS):
                print("Symlink uploads existiert bereits.")
            elif os.path.exists(LOCAL_STATIC_UPLOADS):
                print("Kopiere bestehende Uploads ins Volume...")
                for item in os.listdir(LOCAL_STATIC_UPLOADS):
                    s = os.path.join(LOCAL_STATIC_UPLOADS, item)
                    d = os.path.join(UPLOAD_FOLDER, item)
                    if os.path.isfile(s):
                        shutil.copy2(s, d)
                shutil.rmtree(LOCAL_STATIC_UPLOADS)
                print("Lokaler Upload Ordner bereinigt.")
            
            if not os.path.exists(LOCAL_STATIC_UPLOADS) and not os.path.islink(LOCAL_STATIC_UPLOADS):
                os.symlink(UPLOAD_FOLDER, LOCAL_STATIC_UPLOADS)
                print(f"Symlink erstellt: {LOCAL_STATIC_UPLOADS} -> {UPLOAD_FOLDER}")
    except Exception as e:
        print(f"Fehler beim Symlink Handling (Uploads): {e}")

    # Results
    try:
        if os.path.abspath(LOCAL_STATIC_RESULTS) != os.path.abspath(RESULTS_FOLDER):
            if os.path.islink(LOCAL_STATIC_RESULTS):
                print("Symlink results existiert bereits.")
            elif os.path.exists(LOCAL_STATIC_RESULTS):
                print("Kopiere bestehende Results ins Volume...")
                for item in os.listdir(LOCAL_STATIC_RESULTS):
                    s = os.path.join(LOCAL_STATIC_RESULTS, item)
                    d = os.path.join(RESULTS_FOLDER, item)
                    if os.path.isfile(s):
                        shutil.copy2(s, d)
                shutil.rmtree(LOCAL_STATIC_RESULTS)
                print("Lokaler Results Ordner bereinigt.")
            
            if not os.path.exists(LOCAL_STATIC_RESULTS) and not os.path.islink(LOCAL_STATIC_RESULTS):
                os.symlink(RESULTS_FOLDER, LOCAL_STATIC_RESULTS)
                print(f"Symlink erstellt: {LOCAL_STATIC_RESULTS} -> {RESULTS_FOLDER}")
    except Exception as e:
        print(f"Fehler beim Symlink Handling (Results): {e}")

    # 4. JSON Dateien initialisieren
    for filename in ['drivers.json', 'site_config.json', 'cars.json', 'events.json', 'news.json', 'applications.json', 'results_meta.json']:
        target_file = os.path.join(BASE_DATA_DIR, filename)
        source_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        
        try:
            if not os.path.exists(target_file):
                if os.path.exists(source_file):
                    print(f"Kopiere {filename} ins Volume...")
                    shutil.copy2(source_file, target_file)
                else:
                    print(f"Erstelle leere {filename}...")
                    with open(target_file, 'w') as f:
                        if filename == 'results_meta.json':
                            json.dump({}, f)
                        else:
                            json.dump([], f) # Leeres Array als Standard
        except Exception as e:
            print(f"Fehler bei Datei {filename}: {e}")

    print("init_persistence abgeschlossen.")

init_persistence()

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['RESULTS_FOLDER'] = RESULTS_FOLDER

# iRacing Zugangsdaten
IRACING_USER = os.getenv('IRACING_USERNAME', '')
IRACING_PASSWORD = os.getenv('IRACING_PASSWORD', '')

# --- Hilfsfunktionen ---

def load_messages():
    if not os.path.exists(MESSAGES_FILE):
        return []
    try:
        with open(MESSAGES_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_messages(data):
    with open(MESSAGES_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def load_liveries():
    if not os.path.exists(LIVERIES_FILE):
        return []
    try:
        with open(LIVERIES_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_liveries(data):
    with open(LIVERIES_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def load_setups():
    if not os.path.exists(SETUPS_FILE):
        return []
    try:
        with open(SETUPS_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_setups(data):
    with open(SETUPS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def load_applications():
    if not os.path.exists(APPLICATIONS_FILE):
        return []
    try:
        with open(APPLICATIONS_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_applications(data):
    with open(APPLICATIONS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def load_events():
    if not os.path.exists(EVENTS_FILE):
        return []
    with open(EVENTS_FILE, 'r') as f:
        try:
            events = json.load(f)
            # Sortieren nach Datum (aufsteigend)
            events.sort(key=lambda x: x.get('date', ''))
            return events
        except json.JSONDecodeError:
            return []

def save_events(events):
    with open(EVENTS_FILE, 'w') as f:
        json.dump(events, f, indent=4)

def load_news():
    if not os.path.exists(NEWS_FILE):
        return []
    with open(NEWS_FILE, 'r') as f:
        try:
            news = json.load(f)
            # Sortieren: Erst nach Datum (neu -> alt), dann nach ID (Timestamp, neu -> alt)
            # Damit landen die neuesten Artikel wirklich oben
            news.sort(key=lambda x: (x.get('date', ''), x.get('id', '')), reverse=True)
            return news
        except json.JSONDecodeError:
            return []

def save_news(news):
    with open(NEWS_FILE, 'w') as f:
        json.dump(news, f, indent=4)

def get_next_event():
    events = load_events()
    now = datetime.now()
    now_iso = now.isoformat()
    
    # 1. Prüfen ob ein Event GERADE läuft (Start <= Jetzt < Ende + 2h Puffer)
    for event in events:
        if not event.get('date'): continue
        
        try:
            start_time = datetime.fromisoformat(event['date'])
            duration_hours = float(event.get('duration', 1)) # Default 1h
            end_time = start_time + timedelta(hours=duration_hours + 2) # +2h Puffer
            
            if start_time <= now < end_time:
                event['is_live'] = True # Markierung für Frontend
                return event
        except ValueError:
            continue

    # 2. Wenn keins läuft, nimm das nächste zukünftige
    # Filtere Events, die in der Zukunft liegen (Start > Jetzt)
    future_events = [e for e in events if e.get('date') > now_iso]
    
    if future_events:
        return future_events[0] # Das nächste Event
    return None # Keine Events geplant

def load_cars():
    if not os.path.exists(CARS_FILE):
        return {}
    with open(CARS_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {} # Fallback, sollte nicht passieren
    with open(CONFIG_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

# Context Processor: Macht 'config' in allen Templates verfügbar
@app.context_processor
def inject_config():
    # Wir injizieren jetzt auch das 'next_event'
    return dict(site_config=load_config(), next_event=get_next_event())

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('admin_login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def driver_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'driver_logged_in' not in session:
            return redirect(url_for('driver_login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# ... (Rest der Funktionen load_drivers, get_client etc. bleiben gleich)

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

# --- Daten-Migration (Quick Fix) ---
def run_migrations():
    print("Starte Daten-Migration...")
    try:
        events = load_events()
        changed = False
        
        # 1. IEC Imola
        imola = next((e for e in events if str(e.get('id')) == "1771600365"), None)
        if imola:
            if not imola.get('result_file'):
                print("Migriere IEC Imola Event...")
                imola['result_file'] = "iec_imola_result.json"
                imola['result'] = "P8"
                imola['title'] = "IEC Ligarennen 6"
                changed = True
        
        # 2. Daytona
        daytona = next((e for e in events if str(e.get('id')) == "1"), None)
        if daytona:
            if not daytona.get('result_file'):
                print("Migriere Daytona Event...")
                daytona['result_file'] = "daytona24_result.json"
                changed = True
                
        if changed:
            save_events(events)
            print("Migration gespeichert.")
        else:
            print("Keine Migration notwendig.")
            
    except Exception as e:
        print(f"Fehler bei Migration: {e}")

run_migrations()

@app.context_processor
def inject_config():
    return dict(site_config=load_config())

# --- Mock Client für Demo-Zwecke ---
class MockDataClient:
    def __init__(self, username=None, password=None):
        pass
        
    def member(self, cust_id=None):
        # Simuliert die Antwort von /data/member/get
        # Kann eine ID oder Liste empfangen, wir vereinfachen
        return {
            "members": [
                {
                    "cust_id": cust_id if cust_id else 123456,
                    "display_name": "Max Mustermann",
                    "club_name": "DE-AT-CH",
                    "licenses": [
                        {"category": "sports_car", "category_name": "Sports Car", "irating": 1350, "group_name": "C", "safety_rating": 3.45},
                        {"category": "formula", "category_name": "Formula", "irating": 1280, "group_name": "D", "safety_rating": 2.10},
                        {"category": "oval", "category_name": "Oval", "irating": 1100, "group_name": "R", "safety_rating": 2.50},
                        {"category": "dirt_oval", "category_name": "Dirt Oval", "irating": 1000, "group_name": "R", "safety_rating": 2.50},
                    ]
                }
            ]
        }

    def stats_member_recent_races(self, cust_id=None):
        # Simuliert /data/stats/member_recent_races
        return {
            "races": [
                {
                    "session_start_time": "2023-10-27T18:00:00Z",
                    "series_name": "Global Mazda MX-5 Cup",
                    "track": {"track_name": "Lime Rock Park"},
                    "start_position": 5,
                    "finish_position": 2,
                    "incidents": 0,
                    "strength_of_field": 1450
                },
                {
                    "session_start_time": "2023-10-26T20:30:00Z",
                    "series_name": "Ferrari GT3 Challenge",
                    "track": {"track_name": "Spa Francorchamps"},
                    "start_position": 12,
                    "finish_position": 10,
                    "incidents": 4,
                    "strength_of_field": 1600
                }
            ]
        }

    def stats_member_career(self, cust_id=None):
        return {
            "stats": [
                {"category": "Sports Car", "starts": 50, "wins": 2, "top5": 15, "poles": 1, "avg_start_position": 8, "avg_finish_position": 7},
                {"category": "Formula", "starts": 20, "wins": 0, "top5": 3, "poles": 0, "avg_start_position": 12, "avg_finish_position": 10}
            ]
        }

def get_client():
    username = os.getenv("IRACING_USERNAME")
    password = os.getenv("IRACING_PASSWORD")
    
    # Versuche echten Login
    if username and password:
        try:
            print(f"Versuche Login mit {username}...") # Debug
            # client = irDataClient(username=username, password=password)
            # Test-Aufruf um Login zu bestätigen
            # client.series()
            # print("Login erfolgreich!")
            # return client
            pass
        except Exception as e:
            print(f"LOGIN FEHLER: {e}")
            pass
            
    print("Nutze Mock-Client (Demo-Modus)")
    return MockDataClient()

def get_drivers_data():
    drivers = load_drivers()
    if not drivers:
        return []

    client = get_client()
    if not client:
        return []

    data_list = []
    
    # 1. Allgemeine Infos holen
    # Wir müssen iterieren, da die API keine Liste mag
    members_info = []
    for d_id in drivers:
        try:
            res = client.member(cust_id=d_id)
            if res and 'members' in res:
                members_info.extend(res['members'])
        except Exception as e:
            print(f"Fehler bei Fahrer {d_id}: {e}")

    for m in members_info:
        cust_id = m['cust_id']
        
        # Basis Daten
        driver_entry = {
            'id': cust_id,
            'name': m['display_name'],
            'club': m['club_name'],
            'ir_sports': '-', 'sr_sports': '-',
            'ir_formula': '-', 'sr_formula': '-',
            'last_race_date': '-',
            'last_race_track': '-',
            'last_race_pos': '-',
            'last_race_inc': '-'
        }

        # Lizenzen extrahieren
        for lic in m.get('licenses', []):
            cat = lic.get('category')
            if cat == 'sports_car':
                driver_entry['ir_sports'] = lic.get('irating')
                driver_entry['sr_sports'] = f"{lic.get('group_name')} {lic.get('safety_rating')}"
            elif cat == 'formula':
                driver_entry['ir_formula'] = lic.get('irating')
                driver_entry['sr_formula'] = f"{lic.get('group_name')} {lic.get('safety_rating')}"

        # Letztes Rennen
        try:
            recent = client.stats_member_recent_races(cust_id=cust_id)
            if recent and 'races' in recent and len(recent['races']) > 0:
                last_race = recent['races'][0]
                
                raw_date = last_race['session_start_time']
                dt = datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
                driver_entry['last_race_date'] = dt.strftime('%d.%m.%Y')
                
                driver_entry['last_race_track'] = last_race.get('track', {}).get('track_name', 'Unknown')
                
                start = last_race.get('start_position', '?')
                finish = last_race.get('finish_position', '?')
                driver_entry['last_race_pos'] = f"P{start} &rarr; P{finish}"
                driver_entry['last_race_inc'] = last_race.get('incidents', 0)
                
                # Check for RDF Result Link
                # We need to match this race with our stored results
                # Criteria: Track Name AND Date (approximate)
                meta = load_results_meta()
                for filename, m in meta.items():
                    # Simple matching: Track name must be in our result track name
                    # AND Date string should match day
                    
                    # Convert our meta date to object if possible
                    try:
                        res_date = m.get('date', '') # Expect YYYY-MM-DD HH:MM
                        res_dt = datetime.fromisoformat(res_date)
                        
                        # Compare dates (day level)
                        if res_dt.date() == dt.date():
                            # Compare track (loose match)
                            t1 = driver_entry['last_race_track'].lower()
                            t2 = m.get('track', '').lower()
                            if t1 in t2 or t2 in t1:
                                driver_entry['result_link'] = filename
                                
                                # If we have a link, try to get specific stats from that file for this driver
                                # Optimization: Maybe load this on demand or cache it?
                                # For now, let's peek into the file if it exists
                                res_path = os.path.join(app.config['RESULTS_FOLDER'], filename)
                                if os.path.exists(res_path):
                                    try:
                                        with open(res_path, 'r') as f:
                                            res_data = json.load(f)
                                            # ... (find driver in result logic similar to before)
                                            sessions = res_data.get('data', {}).get('session_results', [])
                                            race_session = next((s for s in sessions if s.get('simsession_type_name') == 'Race'), sessions[-1] if sessions else None)
                                            if race_session:
                                                # Look for driver ID
                                                d_res = next((r for r in race_session.get('results', []) if r.get('cust_id') == cust_id), None)
                                                if d_res:
                                                    # Found him!
                                                    def format_time(val):
                                                        if val <= 0: return "-"
                                                        seconds = val / 10000
                                                        minutes = int(seconds // 60)
                                                        rem_seconds = seconds % 60
                                                        return f"{minutes}:{rem_seconds:06.3f}"
                                                        
                                                    driver_entry['best_lap'] = format_time(d_res.get('best_lap_time', 0))
                                                    driver_entry['inc'] = d_res.get('incidents', 0)
                                    except: pass
                                break
                    except: pass
                
        except Exception:
            pass

        data_list.append(driver_entry)

    return data_list

# --- Admin Routen ---

@app.route('/login', methods=['GET', 'POST'])
def driver_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        drivers = load_drivers()
        # Suche Fahrer mit passendem Username
        user = next((d for d in drivers if d.get('username') == username), None)
        
        if user and user.get('password_hash'):
            if check_password_hash(user['password_hash'], password):
                session['driver_logged_in'] = True
                session['driver_id'] = user['id']
                session['driver_name'] = user['name']
                session.permanent = True # Bleibt eingeloggt
                flash(f"Willkommen zurück, {user['name']}!", "success")
                return redirect(url_for('boxengasse'))
            else:
                flash("Falsches Passwort.", "error")
        else:
            flash("Benutzer nicht gefunden oder keine Zugangsdaten hinterlegt.", "error")
            
    return render_template('driver_login.html')

@app.route('/logout')
def driver_logout():
    session.pop('driver_logged_in', None)
    session.pop('driver_id', None)
    session.pop('driver_name', None)
    flash("Du wurdest ausgeloggt.", "info")
    return redirect(url_for('index'))

@app.route('/boxengasse/setup/upload', methods=['POST'])
@driver_login_required
def upload_setup():
    driver_id = session.get('driver_id')
    drivers = load_drivers()
    driver = next((d for d in drivers if str(d['id']) == str(driver_id)), None)
    
    car = request.form.get('car_model')
    track = request.form.get('track')
    
    if 'setup_files' in request.files:
        files = request.files.getlist('setup_files')
        saved_files = []
        
        entry_id = str(uuid.uuid4())
        
        for file in files:
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                ts = int(datetime.now().timestamp())
                stored_filename = f"setup_{ts}_{filename}"
                
                if not os.path.exists(app.config['UPLOAD_FOLDER']):
                    os.makedirs(app.config['UPLOAD_FOLDER'])
                    
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)
                file.save(filepath)
                
                saved_files.append({
                    "filename": file.filename,
                    "stored_filename": stored_filename
                })
        
        if saved_files:
            setups = load_setups()
            new_setup = {
                "id": entry_id,
                "car": car,
                "track": track,
                "uploader": driver['name'],
                "uploader_id": str(driver_id),
                "date": datetime.now().isoformat(),
                "files": saved_files
            }
            setups.insert(0, new_setup)
            save_setups(setups)
            flash(f"{len(saved_files)} Setup-Dateien hochgeladen!", "success")
        else:
            flash("Keine gültigen Dateien ausgewählt.", "warning")
            
    return redirect(url_for('boxengasse'))

@app.route('/boxengasse/setup/download/<setup_id>')
@driver_login_required
def download_setup(setup_id):
    setups = load_setups()
    setup = next((s for s in setups if s['id'] == setup_id), None)
    
    if not setup:
        flash("Setup nicht gefunden.", "error")
        return redirect(url_for('boxengasse'))
    
    files = setup.get('files', [])
    if not files:
        flash("Keine Dateien in diesem Setup.", "error")
        return redirect(url_for('boxengasse'))
        
    if len(files) == 1:
        file_info = files[0]
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_info['stored_filename'])
        if os.path.exists(filepath):
            return send_file(filepath, as_attachment=True, download_name=file_info['filename'])
        else:
             flash("Datei nicht gefunden.", "error")
             return redirect(url_for('boxengasse'))
    
    else:
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w') as zf:
            for file_info in files:
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_info['stored_filename'])
                if os.path.exists(filepath):
                    zf.write(filepath, arcname=file_info['filename'])
        
        memory_file.seek(0)
        zip_filename = f"Setups_{setup['car']}_{setup['track']}.zip".replace(" ", "_")
        return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name=zip_filename)

@app.route('/boxengasse/setup/delete/<setup_id>')
@driver_login_required
def delete_setup(setup_id):
    driver_id = str(session.get('driver_id'))
    is_admin = session.get('admin_logged_in', False)
    
    setups = load_setups()
    setup = next((s for s in setups if s['id'] == setup_id), None)
    
    if setup:
        if is_admin or str(setup.get('uploader_id')) == driver_id:
            for file_info in setup.get('files', []):
                try:
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_info['stored_filename'])
                    if os.path.exists(filepath):
                        os.remove(filepath)
                except Exception as e:
                    print(f"Error deleting file: {e}")
            
            setups.remove(setup)
            save_setups(setups)
            flash("Setup gelöscht.", "success")
        else:
            flash("Keine Berechtigung.", "error")
            
    return redirect(url_for('boxengasse'))

@app.route('/boxengasse')
@driver_login_required
def boxengasse():
    driver_id = session.get('driver_id')
    drivers = load_drivers()
    current_driver = next((d for d in drivers if str(d['id']) == str(driver_id)), None)
    
    # Nachrichten laden
    messages = load_messages()
    
    # Liveries und Autos laden
    liveries = load_liveries()
    setups = load_setups()
    cars = load_cars()
    
    # Events laden (eigene)
    all_events = load_events()
    my_events = []
    now_minus_12h = (datetime.now() - timedelta(hours=12)).isoformat()
    
    for e in all_events:
        # Check ob erstellt ODER Fahrer drin ist
        if str(e.get('created_by')) == str(driver_id) or str(driver_id) in [str(d) for d in e.get('drivers', [])]:
            # Nur zukünftige Events anzeigen (oder solche die vor kurzem waren)
            if e.get('date') and e.get('date') > now_minus_12h:
                my_events.append(e)
            
    return render_template('boxengasse.html', driver=current_driver, messages=messages, liveries=liveries, cars=cars, events=my_events, setups=setups)

@app.route('/admin/results')
@login_required
def admin_results():
    results = []
    meta = load_results_meta()
    
    if os.path.exists(app.config['RESULTS_FOLDER']):
        for filename in os.listdir(app.config['RESULTS_FOLDER']):
            if filename.endswith('.json'):
                # Basic info from filename/meta
                file_meta = meta.get(filename, {})
                results.append({
                    'filename': filename,
                    'title': file_meta.get('title', filename),
                    'date': file_meta.get('date', 'Unknown')
                })
    
    return render_template('admin_results.html', results=results)

@app.route('/admin/results/upload', methods=['POST'])
@login_required
def admin_results_upload():
    if 'result_file' in request.files:
        file = request.files['result_file']
        if file and file.filename.endswith('.json'):
            filename = secure_filename(file.filename)
            # Timestamp to avoid overwrites? Maybe not, user might want to re-upload.
            # Let's keep original name but secure it.
            
            filepath = os.path.join(app.config['RESULTS_FOLDER'], filename)
            file.save(filepath)
            
            # Initial metadata parsing
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    info = data.get('data', {})
                    
                    # Extract defaults
                    meta = load_results_meta()
                    
                    # Format Date
                    start_time = info.get('start_time', '')
                    date_str = start_time
                    try:
                        dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                        date_str = dt.strftime('%Y-%m-%d %H:%M')
                    except: pass

                    meta[filename] = {
                        'title': f"{info.get('series_name', 'Race')} @ {info.get('track', {}).get('track_name', 'Unknown')}",
                        'series': info.get('series_name'),
                        'track': info.get('track', {}).get('track_name'),
                        'date': date_str,
                        'uploaded_at': datetime.now().isoformat()
                    }
                    save_results_meta(meta)
                    
            except Exception as e:
                print(f"Error parsing uploaded result: {e}")
            
            flash("Ergebnisdatei hochgeladen!", "success")
        else:
            flash("Ungültige Datei. Bitte JSON verwenden.", "error")
            
    return redirect(url_for('admin_results'))

@app.route('/admin/results/edit/<filename>', methods=['GET', 'POST'])
@login_required
def admin_results_edit(filename):
    meta = load_results_meta()
    
    if request.method == 'POST':
        if filename not in meta: meta[filename] = {}
        
        meta[filename]['title'] = request.form.get('title')
        meta[filename]['series'] = request.form.get('series')
        meta[filename]['track'] = request.form.get('track')
        meta[filename]['date'] = request.form.get('date')
        meta[filename]['description'] = request.form.get('description')
        
        save_results_meta(meta)
        flash("Metadaten gespeichert.", "success")
        return redirect(url_for('admin_results'))
    
    file_meta = meta.get(filename, {})
    return render_template('admin_results_edit.html', filename=filename, meta=file_meta)

@app.route('/admin/results/delete/<filename>')
@login_required
def admin_results_delete(filename):
    filepath = os.path.join(app.config['RESULTS_FOLDER'], secure_filename(filename))
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            # Clean meta
            meta = load_results_meta()
            if filename in meta:
                del meta[filename]
                save_results_meta(meta)
            flash("Ergebnis gelöscht.", "success")
        except Exception as e:
            flash(f"Fehler beim Löschen: {e}", "error")
    else:
        flash("Datei nicht gefunden.", "error")
        
    return redirect(url_for('admin_results'))

@app.route('/results')
def public_results():
    results = []
    meta = load_results_meta()
    
    if os.path.exists(app.config['RESULTS_FOLDER']):
        for filename in os.listdir(app.config['RESULTS_FOLDER']):
            if filename.endswith('.json'):
                # Prefer meta, fallback to file reading if needed (lazy load)
                if filename in meta:
                    m = meta[filename]
                    results.append({
                        'filename': filename,
                        'track': m.get('track', 'Unknown'),
                        'date': m.get('date', 'Unknown'),
                        'series': m.get('series', 'Unknown'),
                        'title': m.get('title', 'Race Result'),
                        'id': filename
                    })
                else:
                    # Fallback: Read file to get basic info (and maybe update meta?)
                    # For performance, better to rely on admin upload to set meta.
                    # But for existing files:
                    filepath = os.path.join(app.config['RESULTS_FOLDER'], filename)
                    try:
                        with open(filepath, 'r') as f:
                            data = json.load(f)
                            track_name = data.get('data', {}).get('track', {}).get('track_name', 'Unknown Track')
                            start_time = data.get('data', {}).get('start_time', 'Unknown Date')
                            series_name = data.get('data', {}).get('series_name', 'Unknown Series')
                            
                            try:
                                 dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                                 date_str = dt.strftime('%d.%m.%Y %H:%M')
                            except:
                                date_str = start_time
                                
                            results.append({
                                'filename': filename,
                                'track': track_name,
                                'date': date_str,
                                'series': series_name,
                                'title': f"{series_name} @ {track_name}",
                                'id': filename
                            })
                    except: pass
                    
    # Sort by date descending
    results.sort(key=lambda x: x['date'], reverse=True)
    return render_template('public_results.html', results=results)

@app.route('/results/view/<filename>')
def public_result_detail(filename):
    filepath = os.path.join(app.config['RESULTS_FOLDER'], secure_filename(filename))
    if not os.path.exists(filepath):
        flash("Ergebnisdatei nicht gefunden.", "error")
        return redirect(url_for('public_results'))
        
    meta = load_results_meta()
    file_meta = meta.get(filename, {})
    
    try:
        with open(filepath, 'r') as f:
            full_data = json.load(f)
            data = full_data.get('data', {})
            
            # Sessions find race
            sessions = data.get('session_results', [])
            race_session = next((s for s in sessions if s.get('simsession_type_name') == 'Race'), sessions[-1] if sessions else None)
            
            # Prepare Results Grouped by Class
            class_results = {}
            all_drivers_combined = [] # New: Collect all drivers for "Overall" view
            
            if race_session:
                # Find Overall Winner Laps (max laps of any driver)
                overall_winner_laps = 0
                if race_session.get('results'):
                    overall_winner_laps = max([r.get('laps_complete', 0) for r in race_session.get('results', [])])

                # 1. Identify Class Winners (for Laps Down calculation)
                class_winners = {} # class_id -> max_laps
                for entry in race_session.get('results', []):
                    cid = entry.get('car_class_id')
                    laps = entry.get('laps_complete', 0)
                    if cid not in class_winners or laps > class_winners[cid]:
                        class_winners[cid] = laps

                for entry in race_session.get('results', []):
                    cid = entry.get('car_class_id')
                    cname = entry.get('car_class_short_name') or "Unknown"
                    
                    if cid not in class_results:
                        class_results[cid] = {
                            'id': cid,
                            'name': cname,
                            'full_name': entry.get('car_class_name'),
                            'drivers': []
                        }
                    
                    # Format Gap
                    interval = entry.get('interval', 0)
                    class_interval = entry.get('class_interval', 0)
                    laps_complete = entry.get('laps_complete', 0)
                    
                    # Gap Calculation (Complex in iRacing JSON)
                    # interval: time behind LEADER (overall) in microseconds?
                    # class_interval: time behind CLASS LEADER?
                    
                    # Let's use class_interval for class views
                    gap_str = "-"
                    if class_interval > 0:
                        seconds = class_interval / 10000
                        if seconds > 60:
                             gap_str = f"+{int(seconds//60)}:{seconds%60:05.2f}"
                        else:
                             gap_str = f"+{seconds:.3f}s"
                    elif class_interval == -1:
                        # Laps down relative to class leader? 
                        # Usually iRacing provides 'laps_complete'.
                        # We need to find the winner of THIS class to calc laps down.
                        pass # handled later if we sort list first
                        
                    # Overall Gap
                    overall_gap_str = "-"
                    if interval > 0:
                        seconds = interval / 10000
                        if seconds > 60:
                             overall_gap_str = f"+{int(seconds//60)}:{seconds%60:05.2f}"
                        else:
                             overall_gap_str = f"+{seconds:.3f}s"
                        
                    # Format Best Lap
                    best_lap = entry.get('best_lap_time', 0)
                    best_lap_str = "-"
                    if best_lap > 0:
                        seconds = best_lap / 10000
                        minutes = int(seconds // 60)
                        rem_seconds = seconds % 60
                        best_lap_str = f"{minutes}:{rem_seconds:06.3f}"
                        
                    # Average Lap
                    avg_lap = entry.get('average_lap', 0)
                    avg_lap_str = "-"
                    if avg_lap > 0:
                        seconds = avg_lap / 10000
                        minutes = int(seconds // 60)
                        rem_seconds = seconds % 60
                        avg_lap_str = f"{minutes}:{rem_seconds:06.3f}"

                    # Helper for time formatting
                    def format_time(val):
                        if val <= 0: return "-"
                        seconds = val / 10000
                        minutes = int(seconds // 60)
                        rem_seconds = seconds % 60
                        return f"{minutes}:{rem_seconds:06.3f}"

                    # Driver Name(s)
                    driver_name = entry.get('display_name')
                    # Team Drivers
                    team_drivers = []
                    team_drivers_detailed = []
                    
                    if entry.get('driver_results'):
                        for d in entry.get('driver_results'):
                            team_drivers.append(d.get('display_name'))
                            team_drivers_detailed.append({
                                'name': d.get('display_name'),
                                'laps': d.get('laps_complete', 0),
                                'best_lap': format_time(d.get('best_lap_time', 0)),
                                'avg_lap': format_time(d.get('average_lap', 0)),
                                'inc': d.get('incidents', 0),
                                'irating': d.get('oldi_rating', 0),
                                'new_irating': d.get('newi_rating', 0),
                                'sr': d.get('old_safety_rating', 0),
                                'new_sr': d.get('new_safety_rating', 0)
                            })
                    
                    driver_data = {
                        'pos': entry.get('finish_position_in_class', entry.get('position', 0) + 1) + 1, # 0-indexed usually
                        'overall_pos': entry.get('finish_position', 0) + 1,
                        'car_number': entry.get('livery', {}).get('car_number', '#'),
                        'name': driver_name,
                        'team_drivers': team_drivers,
                        'team_drivers_detailed': team_drivers_detailed,
                        'laps': laps_complete,
                        'gap_raw': class_interval, # for sorting/calc
                        'gap': gap_str, # Will be overwritten for class view
                        'overall_gap': overall_gap_str,
                        'best_lap': best_lap_str,
                        'avg_lap': avg_lap_str,
                        'inc': entry.get('incidents'),
                        'car_name': entry.get('car_name'),
                        'class_name': cname, # For overall view
                        'class_id': cid, # For filtering
                        'club': entry.get('club_name'), 
                        'id': entry.get('cust_id')
                    }
                    
                    class_results[cid]['drivers'].append(driver_data)
                    all_drivers_combined.append(driver_data) # Add to overall list

            # Post-Process: Sort and Fix Gaps per Class
            sorted_classes = []
            for cid, data in class_results.items():
                # Sort drivers by position
                data['drivers'].sort(key=lambda x: x['pos'])
                
                # Fix Gaps (Laps down)
                class_winner_laps = data['drivers'][0]['laps'] if data['drivers'] else 0
                
                for d in data['drivers']:
                    if d['laps'] < class_winner_laps:
                        diff = class_winner_laps - d['laps']
                        d['gap'] = f"+{diff} Lap{'s' if diff > 1 else ''}"
                    elif d['gap_raw'] > 0:
                        # Recalc gap string just to be safe
                        seconds = d['gap_raw'] / 10000
                        if seconds > 60:
                             d['gap'] = f"+{int(seconds//60)}:{seconds%60:05.2f}"
                        else:
                             d['gap'] = f"+{seconds:.3f}s"
                    else:
                        d['gap'] = "-" # Winner
                
                sorted_classes.append(data)
            
            # Sort classes by something (maybe name or ID)
            sorted_classes.sort(key=lambda x: x['name'])
            
            # Post-Process Overall List
            all_drivers_combined.sort(key=lambda x: x['overall_pos'])
            
            # Fix Overall Gaps (Laps down)
            if all_drivers_combined:
                overall_winner_laps = all_drivers_combined[0]['laps']
                for d in all_drivers_combined:
                     if d['laps'] < overall_winner_laps:
                        diff = overall_winner_laps - d['laps']
                        d['overall_gap'] = f"+{diff} Lap{'s' if diff > 1 else ''}"
                     elif d['overall_pos'] == 1:
                        d['overall_gap'] = "-"

            result_info = {
                'track': file_meta.get('track') or data.get('track', {}).get('track_name'),
                'config': data.get('track', {}).get('config_name'),
                'series': file_meta.get('series') or data.get('series_name'),
                'date': file_meta.get('date') or 'Unknown Date',
                'title': file_meta.get('title') or f"{data.get('series_name')} @ {data.get('track', {}).get('track_name')}",
                'description': file_meta.get('description', '')
            }
                    
            return render_template('boxengasse_result_detail.html', 
                                 info=result_info, 
                                 classes=sorted_classes,
                                 overall=all_drivers_combined, # New: Pass overall list
                                 filename=filename,
                                 meta=file_meta,
                                 public=True) # Flag for template
                                 
    except Exception as e:
        flash(f"Fehler beim Lesen der Datei: {e}", "error")
        return redirect(url_for('public_results'))

@app.route('/results/view/<filename>/driver/<int:cust_id>')
def public_result_driver(filename, cust_id):
    filepath = os.path.join(app.config['RESULTS_FOLDER'], secure_filename(filename))
    if not os.path.exists(filepath):
        flash("Ergebnisdatei nicht gefunden.", "error")
        return redirect(url_for('public_results'))
    
    meta = load_results_meta()
    file_meta = meta.get(filename, {})
    
    try:
        with open(filepath, 'r') as f:
            full_data = json.load(f)
            data = full_data.get('data', {})
            
            # Basic Info
            result_info = {
                'track': file_meta.get('track') or data.get('track', {}).get('track_name'),
                'config': data.get('track', {}).get('config_name'),
                'series': file_meta.get('series') or data.get('series_name'),
                'date': file_meta.get('date') or 'Unknown Date',
                'title': file_meta.get('title') or f"{data.get('series_name')} @ {data.get('track', {}).get('track_name')}"
            }
            
            # Find Race Session
            sessions = data.get('session_results', [])
            race_session = next((s for s in sessions if s.get('simsession_type_name') == 'Race'), sessions[-1] if sessions else None)
            
            if not race_session:
                flash("Keine Rennsession gefunden.", "error")
                return redirect(url_for('public_result_detail', filename=filename))
                
            # Find Driver Result
            driver_result = next((r for r in race_session.get('results', []) if r.get('cust_id') == cust_id), None)
            
            if not driver_result:
                flash("Fahrer in diesem Ergebnis nicht gefunden.", "error")
                return redirect(url_for('public_result_detail', filename=filename))
                
            # Helper for time formatting
            def format_time(val):
                if val <= 0: return "-"
                seconds = val / 10000
                minutes = int(seconds // 60)
                rem_seconds = seconds % 60
                return f"{minutes}:{rem_seconds:06.3f}"
            
            # Statistics from driver_result
            stats = {
                'pos': driver_result.get('finish_position', 0) + 1,
                'class_pos': driver_result.get('finish_position_in_class', 0) + 1,
                'car': driver_result.get('car_name', 'Unknown'),
                'number': driver_result.get('livery', {}).get('car_number', '#'),
                'laps_completed': driver_result.get('laps_complete', 0),
                'inc': driver_result.get('incidents', 0),
                'best_lap': format_time(driver_result.get('best_lap_time', 0)),
                'avg_lap': format_time(driver_result.get('average_lap', 0)),
                'qual_lap': format_time(driver_result.get('best_qual_lap_at', 0)), # might be 0 if no qual
                'reason_out': driver_result.get('reason_out', 'Running'),
                'champ_points': driver_result.get('champ_points', 0)
            }
            
            return render_template('boxengasse_result_driver.html', 
                                 info=result_info, 
                                 stats=stats,
                                 driver_name=driver_result.get('display_name'),
                                 filename=filename,
                                 public=True) # Flag for template to adjust links
                                 
    except Exception as e:
        flash(f"Fehler: {e}", "error")
        return redirect(url_for('public_result_detail', filename=filename))
@app.route('/boxengasse/event/new', methods=['POST'])
@driver_login_required
def boxengasse_new_event():
    driver_id = session.get('driver_id')
    drivers = load_drivers()
    driver = next((d for d in drivers if str(d['id']) == str(driver_id)), None)
    
    # Daten aus Formular
    title = request.form.get('title')
    date = request.form.get('date') # Format: YYYY-MM-DDTHH:MM
    track = request.form.get('track')
    series = request.form.get('series')
    car = request.form.get('car')
    
    events = load_events()
    new_event = {
        "id": str(uuid.uuid4()),
        "title": title,
        "date": date,
        "track": track,
        "series": series,
        "car_model": car,
        "created_by": str(driver_id),
        "created_by_name": driver['name'],
        "status": "pending", # Muss freigegeben werden
        "drivers": [str(driver_id)] # Ersteller ist automatisch Fahrer
    }
    
    events.append(new_event)
    save_events(events)
    flash("Event beantragt! Warte auf Freigabe durch Admin.", "info")
    return redirect(url_for('boxengasse'))

@app.route('/boxengasse/event/delete/<event_id>')
@driver_login_required
def boxengasse_delete_event(event_id):
    driver_id = str(session.get('driver_id'))
    events = load_events()
    event = next((e for e in events if e['id'] == event_id), None)
    
    if event:
        # Nur Ersteller darf löschen
        if str(event.get('created_by')) == driver_id:
            events.remove(event)
            save_events(events)
            flash("Event gelöscht.", "success")
        else:
            flash("Keine Berechtigung.", "error")
            
    return redirect(url_for('boxengasse'))

@app.route('/boxengasse/livery/upload', methods=['POST'])
@driver_login_required
def upload_livery():
    driver_id = session.get('driver_id')
    drivers = load_drivers()
    driver = next((d for d in drivers if str(d['id']) == str(driver_id)), None)
    
    car_model = request.form.get('car_model')
    
    if 'livery_file' in request.files:
        file = request.files['livery_file']
        if file and file.filename != '':
            # Erlaube auch .tga, .mip, .psd etc.
            filename = secure_filename(file.filename)
            ts = int(datetime.now().timestamp())
            filename = f"livery_{ts}_{filename}"
            
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
                
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            liveries = load_liveries()
            new_livery = {
                "id": str(uuid.uuid4()),
                "filename": file.filename, # Original Name für Anzeige
                "url": url_for('static', filename=f'uploads/{filename}'),
                "car_model": car_model,
                "uploaded_by": driver['name'],
                "uploader_id": str(driver_id),
                "date": datetime.now().isoformat()
            }
            liveries.insert(0, new_livery)
            save_liveries(liveries)
            flash("Livery erfolgreich hochgeladen!", "success")
            
    return redirect(url_for('boxengasse'))

@app.route('/boxengasse/livery/delete/<livery_id>')
@driver_login_required
def delete_livery(livery_id):
    driver_id = str(session.get('driver_id'))
    # Admin Check? Wir haben keine echte Admin Rolle in der Session ausser 'admin_logged_in'
    # Wir erlauben es dem Uploader UND dem Admin.
    
    is_admin = session.get('admin_logged_in', False)
    
    liveries = load_liveries()
    livery = next((l for l in liveries if l['id'] == livery_id), None)
    
    if livery:
        if is_admin or str(livery.get('uploader_id')) == driver_id:
            # Datei löschen
            try:
                # URL parsen um Dateinamen zu bekommen
                filename = livery['url'].split('/')[-1]
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception as e:
                print(f"Fehler beim Löschen der Livery Datei: {e}")
                
            liveries.remove(livery)
            save_liveries(liveries)
            flash("Livery gelöscht.", "success")
        else:
            flash("Keine Berechtigung zum Löschen.", "error")
            
    return redirect(url_for('boxengasse'))

@app.route('/boxengasse/message/new', methods=['POST'])
@driver_login_required
def new_team_message():
    content = request.form.get('content')
    if content:
        driver_id = session.get('driver_id')
        drivers = load_drivers()
        driver = next((d for d in drivers if str(d['id']) == str(driver_id)), None)
        
        msgs = load_messages()
        if not isinstance(msgs, list): msgs = []
        
        new_msg = {
            "id": str(uuid.uuid4()),
            "driver_id": str(driver_id),
            "driver_name": driver['name'] if driver else "Unbekannt",
            "driver_image": driver.get('image_url') if driver else None,
            "content": content,
            "date": datetime.now().isoformat()
        }
        
        msgs.insert(0, new_msg)
        msgs = msgs[:50]
        save_messages(msgs)
        flash("Nachricht gepostet!", "success")
        
    return redirect(url_for('boxengasse'))

@app.route('/boxengasse/message/delete/<msg_id>')
@driver_login_required
def delete_team_message(msg_id):
    driver_id = str(session.get('driver_id'))
    msgs = load_messages()
    
    msg = next((m for m in msgs if m['id'] == msg_id), None)
    
    if msg:
        if str(msg.get('driver_id')) == driver_id:
            msgs.remove(msg)
            save_messages(msgs)
            flash("Nachricht gelöscht.", "success")
        else:
            flash("Du kannst nur deine eigenen Nachrichten löschen.", "error")
    
    return redirect(url_for('boxengasse'))

@app.route('/boxengasse/rig/save', methods=['POST'])
@driver_login_required
def save_rig():
    driver_id = session.get('driver_id')
    drivers = load_drivers()
    driver = next((d for d in drivers if str(d['id']) == str(driver_id)), None)
    
    if not driver:
        flash("Fahrer nicht gefunden.", "error")
        return redirect(url_for('boxengasse'))
        
    # Rig Daten initialisieren falls nicht vorhanden
    if 'rig' not in driver:
        driver['rig'] = {}
        
    driver['rig']['type'] = request.form.get('rig_type')
    driver['rig']['monitors'] = request.form.get('rig_monitors')
    driver['rig']['base'] = request.form.get('rig_base')
    driver['rig']['wheel'] = request.form.get('rig_wheel')
    driver['rig']['pedals'] = request.form.get('rig_pedals')
    driver['rig']['extras'] = request.form.get('rig_extras')
    
    # Bilder Upload (Max 3)
    if 'rig_images' in request.files:
        files = request.files.getlist('rig_images')
        new_images = []
        
        for file in files:
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                ts = int(datetime.now().timestamp())
                filename = f"rig_{driver_id}_{ts}_{filename}"
                
                if not os.path.exists(app.config['UPLOAD_FOLDER']):
                    os.makedirs(app.config['UPLOAD_FOLDER'])
                    
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                new_images.append(url_for('static', filename=f'uploads/{filename}'))
        
        # Nur ersetzen, wenn neue Bilder hochgeladen wurden
        if new_images:
            driver['rig']['images'] = new_images

    save_drivers(drivers)
    flash("Rig-Daten gespeichert!", "success")
    return redirect(url_for('boxengasse'))

@app.route('/boxengasse/rig/delete_image', methods=['GET'])
@driver_login_required
def delete_rig_image():
    driver_id = session.get('driver_id')
    try:
        index = int(request.args.get('index'))
    except (ValueError, TypeError):
        flash("Ungültiger Bild-Index", "error")
        return redirect(url_for('boxengasse'))

    drivers = load_drivers()
    driver = next((d for d in drivers if str(d['id']) == str(driver_id)), None)
    
    if driver and 'rig' in driver and 'images' in driver['rig']:
        if 0 <= index < len(driver['rig']['images']):
            # Optional: Datei vom Server löschen (wenn man ganz sauber sein will)
            # image_path = ...
            # os.remove(image_path)
            
            del driver['rig']['images'][index]
            save_drivers(drivers)
            flash("Bild gelöscht!", "success")
        else:
            flash("Bild nicht gefunden", "error")
            
    return redirect(url_for('boxengasse'))

@app.route('/boxengasse/profil/save', methods=['POST'])
@driver_login_required
def save_profil():
    driver_id = session.get('driver_id')
    drivers = load_drivers()
    driver = next((d for d in drivers if str(d['id']) == str(driver_id)), None)
    
    if not driver:
        flash("Fahrer nicht gefunden", "error")
        return redirect(url_for('boxengasse'))
        
    # Daten aktualisieren
    driver['username'] = request.form.get('username')
    driver['number'] = request.form.get('number')
    driver['twitch'] = request.form.get('twitch')
    
    # Passwort ändern (Optional)
    password = request.form.get('password')
    password_confirm = request.form.get('password_confirm')
    
    if password:
        if password == password_confirm:
            driver['password'] = generate_password_hash(password)
            flash("Passwort erfolgreich geändert!", "success")
        else:
            flash("Passwörter stimmen nicht überein! (Profil gespeichert, Passwort NICHT)", "error")
            # Wir speichern trotzdem den Rest, aber warnen den User
    
    # Bild Upload
    if 'driver_image' in request.files:
        file = request.files['driver_image']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            ts = int(datetime.now().timestamp())
            filename = f"driver_{driver_id}_{ts}_{filename}"
            
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
                
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # NICHT sofort live schalten, sondern als Pending markieren
            driver['pending_image_url'] = url_for('static', filename=f'uploads/{filename}')
            flash("Profilbild hochgeladen! Es wird vom Admin geprüft und dann freigeschaltet.", "info")
    
    save_drivers(drivers)
    # Wenn kein Bild hochgeladen wurde, aber andere Daten geändert wurden:
    if 'driver_image' not in request.files or request.files['driver_image'].filename == '':
        flash("Profil gespeichert!", "success")
        
    return redirect(url_for('boxengasse'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Falsches Passwort!", "error")
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('index'))

@app.route('/admin')
@login_required
def admin_dashboard():
    # Zeigt jetzt die Übersichtskacheln
    drivers = load_drivers()
    events = load_events()
    all_apps = load_applications()
    
    # Filter applications
    applications = [a for a in all_apps if a.get('status', 'new') == 'new']
    # Archived applications jetzt im Team Management
    
    pending_drivers = [d for d in drivers if d.get('pending_image_url')]
    pending_events = [e for e in events if e.get('status') == 'pending']
    
    return render_template('admin_dashboard.html', 
                         pending_drivers=pending_drivers, 
                         pending_events=pending_events, 
                         applications=applications)

@app.route('/admin/application/archive/<app_id>')
@login_required
def archive_application(app_id):
    apps = load_applications()
    app_item = next((a for a in apps if a['id'] == app_id), None)
    
    if app_item:
        app_item['status'] = 'archived'
        save_applications(apps)
        flash("Bewerbung ins Archiv verschoben.", "success")
    else:
        flash("Bewerbung nicht gefunden.", "error")
        
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/application/delete/<app_id>')
@login_required
def delete_application(app_id):
    apps = load_applications()
    app_item = next((a for a in apps if a['id'] == app_id), None)
    
    if app_item:
        apps.remove(app_item)
        save_applications(apps)
        flash("Bewerbung endgültig gelöscht.", "info")
    else:
        flash("Bewerbung nicht gefunden.", "error")
        
    # Redirect checken: Woher kam der User?
    # Einfacher: Wenn archiviert, dann Team. Wenn neu, dann Dashboard.
    # Da wir hier aber keinen Status mehr haben (gelöscht), nehmen wir Referer oder Default.
    if request.referrer and 'team' in request.referrer:
        return redirect(url_for('admin_team'))
        
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/approve_event/<event_id>')
@login_required
def admin_approve_event(event_id):
    events = load_events()
    event = next((e for e in events if e['id'] == event_id), None)
    if event:
        event['status'] = 'approved'
        save_events(events)
        flash(f"Event '{event['title']}' freigegeben.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reject_event/<event_id>')
@login_required
def admin_reject_event(event_id):
    events = load_events()
    event = next((e for e in events if e['id'] == event_id), None)
    if event:
        events.remove(event)
        save_events(events)
        flash(f"Event '{event['title']}' abgelehnt.", "warning")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/approve_image/<driver_id>')
@login_required
def approve_image(driver_id):
    drivers = load_drivers()
    driver = next((d for d in drivers if str(d['id']) == str(driver_id)), None)
    
    if driver and driver.get('pending_image_url'):
        # Pending -> Live
        driver['image_url'] = driver['pending_image_url']
        del driver['pending_image_url']
        save_drivers(drivers)
        flash(f"Profilbild für {driver['name']} freigegeben!", "success")
    else:
        flash("Kein ausstehendes Bild gefunden.", "error")
        
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reject_image/<driver_id>')
@login_required
def reject_image(driver_id):
    drivers = load_drivers()
    driver = next((d for d in drivers if str(d['id']) == str(driver_id)), None)
    
    if driver and driver.get('pending_image_url'):
        # Datei auch vom Server löschen
        try:
            pending_url = driver['pending_image_url']
            # URL ist z.B. /static/uploads/filename.png -> wir brauchen nur filename
            filename = pending_url.split('/')[-1]
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            if os.path.exists(filepath):
                os.remove(filepath)
                print(f"Gelöscht: {filepath}")
        except Exception as e:
            print(f"Fehler beim Löschen der Datei: {e}")

        # Link aus DB entfernen
        del driver['pending_image_url']
        save_drivers(drivers)
        flash(f"Profilbild für {driver['name']} abgelehnt und Datei gelöscht.", "warning")
    else:
        flash("Kein ausstehendes Bild gefunden.", "error")
        
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/settings')
@login_required
def admin_settings():
    config = load_config()
    return render_template('admin_settings.html', config=config)

@app.route('/admin/settings/save', methods=['POST'])
@login_required
def admin_settings_save():
    config = load_config()
    
    # Nav Logo Upload
    if 'nav_logo' in request.files:
        file = request.files['nav_logo']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            ts = int(datetime.now().timestamp())
            filename = f"nav_logo_{ts}_{filename}"
            
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
                
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            config['nav_logo_url'] = url_for('static', filename=f'uploads/{filename}')
            flash("Nav Logo aktualisiert!", "success")
    
    # Social Media Links speichern
    config['social_discord'] = request.form.get('social_discord')
    config['social_instagram'] = request.form.get('social_instagram')
    config['social_twitter'] = request.form.get('social_twitter')
    config['social_twitch'] = request.form.get('social_twitch')
    config['social_youtube'] = request.form.get('social_youtube')
            
    save_config(config)
    return redirect(url_for('admin_settings'))

@app.route('/admin/hero')
@login_required
def admin_hero():
    config = load_config()
    return render_template('admin_hero.html', config=config)

@app.route('/admin/events')
@login_required
def admin_events():
    events = load_events()
    now = datetime.now().isoformat()
    
    # Aufteilen in Upcoming (Zukunft) und Archive (Vergangenheit)
    upcoming = [e for e in events if e.get('date') > now]
    archive = [e for e in events if e.get('date') <= now]
    
    # Archiv sortieren: Neueste zuerst
    archive.reverse()
    
    return render_template('admin_events.html', upcoming=upcoming, archive=archive)

@app.route('/admin/event/new')
@login_required
def admin_event_new():
    # Leeres Event Template
    event = {
        "id": "",
        "title": "",
        "series": "",
        "track": "",
        "date": "",
        "league": "",
        "car_class": "",
        "car_model": "",
        "description": "",
        "twitch": "",
        "drivers": [],
        "result": "",
        "result_file": "" # New
    }
    all_drivers = get_drivers_data()
    cars_data = load_cars()
    
    # Load available results
    results = []
    meta = load_results_meta()
    if os.path.exists(app.config['RESULTS_FOLDER']):
        for filename in os.listdir(app.config['RESULTS_FOLDER']):
            if filename.endswith('.json'):
                file_meta = meta.get(filename, {})
                results.append({
                    'filename': filename,
                    'title': file_meta.get('title', filename),
                    'date': file_meta.get('date', 'Unknown')
                })
    results.sort(key=lambda x: x['date'], reverse=True)
    
    # Load News for selection
    all_news = load_news()
    
    return render_template('admin_event_edit.html', event=event, all_drivers=all_drivers, cars_data=cars_data, mode="new", result_files=results, all_news=all_news)

@app.route('/admin/event/edit/<event_id>')
@login_required
def admin_event_edit(event_id):
    events = load_events()
    event = next((e for e in events if e['id'] == event_id), None)
    if not event:
        flash("Event nicht gefunden", "error")
        return redirect(url_for('admin_events'))
        
    all_drivers = get_drivers_data()
    cars_data = load_cars()
    
    # Load available results
    results = []
    meta = load_results_meta()
    if os.path.exists(app.config['RESULTS_FOLDER']):
        for filename in os.listdir(app.config['RESULTS_FOLDER']):
            if filename.endswith('.json'):
                file_meta = meta.get(filename, {})
                results.append({
                    'filename': filename,
                    'title': file_meta.get('title', filename),
                    'date': file_meta.get('date', 'Unknown')
                })
    results.sort(key=lambda x: x['date'], reverse=True)
    
    # Load News for selection
    all_news = load_news()
    
    return render_template('admin_event_edit.html', event=event, all_drivers=all_drivers, cars_data=cars_data, mode="edit", result_files=results, all_news=all_news)

@app.route('/admin/event/save', methods=['POST'])
@login_required
def admin_event_save():
    events = load_events()
    event_id = request.form.get('id')
    mode = request.form.get('mode')
    
    if mode == 'new':
        # Neue ID generieren (Timestamp ist einfach und unique genug)
        event_id = str(int(datetime.now().timestamp()))
        new_event = {"id": event_id}
        events.append(new_event)
        event = new_event
    else:
        event = next((e for e in events if e['id'] == event_id), None)
        if not event:
            flash("Fehler beim Speichern", "error")
            return redirect(url_for('admin_events'))

    # Daten update
    event['title'] = request.form.get('title')
    event['series'] = request.form.get('series')
    event['track'] = request.form.get('track')
    event['date'] = request.form.get('date')
    event['duration'] = request.form.get('duration') # Dauer in Stunden
    event['league'] = request.form.get('league')
    event['car_class'] = request.form.get('car_class')
    event['car_model'] = request.form.get('car_model')
    event['twitch'] = request.form.get('twitch')
    event['description'] = request.form.get('description')
    event['result'] = request.form.get('result') # Ergebnis
    event['result_file'] = request.form.get('result_file') # Verknüpftes JSON File
    event['news_ids'] = request.form.getlist('news_ids') # Verknüpfte News (Multi-Select)
    
    # Bild Upload
    if 'event_image' in request.files:
        file = request.files['event_image']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            ts = int(datetime.now().timestamp())
            filename = f"event_{event_id}_{ts}_{filename}"
            
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
                
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            event['image_url'] = url_for('static', filename=f'uploads/{filename}')
    
    # Drivers
    event['drivers'] = request.form.getlist('driver_ids')

    save_events(events)
    flash("Event gespeichert!", "success")
    return redirect(url_for('admin_events'))

@app.route('/admin/event/delete/<event_id>')
@login_required
def admin_event_delete(event_id):
    events = load_events()
    events = [e for e in events if e['id'] != event_id]
    save_events(events)
    flash("Event gelöscht.", "info")
    return redirect(url_for('admin_events'))

@app.route('/calendar')
def calendar():
    events = load_events()
    now = datetime.now().isoformat()
    
    # Aufteilen in Upcoming und Past
    upcoming = [e for e in events if e.get('date') > now]
    past = [e for e in events if e.get('date') <= now]
    
    # Past events umkehren (neueste zuerst)
    past.reverse()
    
    return render_template('calendar.html', upcoming=upcoming, past=past)

@app.route('/event-info')
def event_info_redirect():
    # Redirect zur Info-Seite des nächsten Events
    next_ev = get_next_event()
    if next_ev:
        return redirect(url_for('event_detail', event_id=next_ev['id']))
    else:
        return redirect(url_for('calendar'))

@app.route('/event/<event_id>')
def event_detail(event_id):
    events = load_events()
    event = next((e for e in events if e['id'] == event_id), None)
    
    if not event:
        return redirect(url_for('calendar'))
        
    config = load_config() # Für globale Settings
    
    # Drivers laden
    selected_driver_ids = event.get('drivers', [])
    all_drivers = get_drivers_data()
    event_drivers = [d for d in all_drivers if str(d['id']) in selected_driver_ids or d['id'] in selected_driver_ids]

    # Check if event is past
    is_past = False
    try:
        if event.get('date'):
            event_dt = datetime.fromisoformat(event['date'])
            if event_dt < datetime.now():
                is_past = True
    except Exception:
        pass

    # Load Linked News
    linked_news = []
    if event.get('news_ids'):
        all_news = load_news()
        linked_news = [n for n in all_news if n['id'] in event['news_ids']]
        
    # Load Result Summary if file exists
    rdf_result_summary = []
    if event.get('result_file'):
        try:
            filepath = os.path.join(app.config['RESULTS_FOLDER'], secure_filename(event['result_file']))
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    
                    # Get RDF Driver Names from Event Lineup
                    rdf_names = [d['name'] for d in event_drivers]
                    
                    # Find these drivers in the result
                    sessions = data.get('data', {}).get('session_results', [])
                    race_session = next((s for s in sessions if s.get('simsession_type_name') == 'Race'), sessions[-1] if sessions else None)
                    
                    if race_session:
                        # 1. Identify Class Winners (for Laps Down calculation)
                        class_winners = {} # class_id -> max_laps
                        for entry in race_session.get('results', []):
                            cid = entry.get('car_class_id')
                            laps = entry.get('laps_complete', 0)
                            if cid not in class_winners or laps > class_winners[cid]:
                                class_winners[cid] = laps

                        # Helper
                        def format_time(val):
                            if val <= 0: return "-"
                            seconds = val / 10000
                            minutes = int(seconds // 60)
                            rem_seconds = seconds % 60
                            return f"{minutes}:{rem_seconds:06.3f}"

                        for entry in race_session.get('results', []):
                            is_rdf = False
                            # Check main driver name
                            if entry.get('display_name') in rdf_names:
                                is_rdf = True
                            
                            # Check team drivers
                            drivers_details = []
                            if entry.get('driver_results'):
                                for d in entry.get('driver_results'):
                                    dname = d.get('display_name')
                                    
                                    drivers_details.append({
                                        'name': dname,
                                        'best_lap': format_time(d.get('best_lap_time', 0)),
                                        'laps': d.get('laps_complete', 0),
                                        'inc': d.get('incidents', 0)
                                    })
                                    
                                    if dname in rdf_names:
                                        is_rdf = True
                            else:
                                # Single driver entry
                                dname = entry.get('display_name')
                                drivers_details.append({
                                    'name': dname,
                                    'best_lap': format_time(entry.get('best_lap_time', 0)),
                                    'laps': entry.get('laps_complete', 0),
                                    'inc': entry.get('incidents', 0)
                                })
                            
                            # Also check if "RaceDayFriends" is in team name (if available) or just assume matched by driver
                            # If no drivers matched but we want to be sure, maybe check 'team_name'? 
                            # But 'display_name' is often the team name in team events.
                            if "RaceDayFriends" in str(entry.get('display_name')):
                                is_rdf = True
                            
                            if is_rdf:
                                # Calc Gap
                                cid = entry.get('car_class_id')
                                winner_laps = class_winners.get(cid, 0)
                                laps = entry.get('laps_complete', 0)
                                class_interval = entry.get('class_interval', 0)
                                
                                gap_str = "-"
                                if laps < winner_laps:
                                    gap_str = f"+{winner_laps - laps} Laps"
                                elif class_interval > 0:
                                    seconds = class_interval / 10000
                                    if seconds > 60:
                                         gap_str = f"+{int(seconds//60)}:{seconds%60:05.2f}"
                                    else:
                                         gap_str = f"+{seconds:.3f}s"
                                elif class_interval == 0 and laps == winner_laps:
                                    gap_str = "Winner"

                                rdf_result_summary.append({
                                    'pos': entry.get('finish_position_in_class', entry.get('position', 0) + 1) + 1,
                                    'class': entry.get('car_class_short_name'),
                                    'car_number': entry.get('livery', {}).get('car_number', '#'),
                                    'inc': entry.get('incidents', 0),
                                    'laps': laps,
                                    'gap': gap_str,
                                    'best_lap': format_time(entry.get('best_lap_time', 0)),
                                    'drivers': drivers_details
                                })
        except Exception as e:
            print(f"Error loading result summary: {e}")

    # Wir bauen ein Fake-Config Objekt, damit das Template nicht umgebaut werden muss
    # Das Template erwartet config.next_race.*
    # Wir könnten das Template anpassen, aber einfacher ist es, die Datenstruktur passend zu machen
    
    # BESSER: Template anpassen, um 'event' Objekt zu nutzen statt config.next_race
    return render_template('event_info.html', event=event, drivers=event_drivers, config=config, is_past=is_past, linked_news=linked_news, rdf_result_summary=rdf_result_summary)

@app.route('/admin/nav')
@login_required
def admin_nav():
    config = load_config()
    return render_template('admin_nav.html', config=config)

@app.route('/admin/update_hero', methods=['POST'])
@login_required
def update_hero():
    print("--- UPDATE HERO START ---") # Debug
    print(f"Form Data: {request.form}") # Debug
    print(f"Files: {request.files}") # Debug

    config = load_config()
    config['hero']['badge'] = request.form.get('badge')
    # ... (Rest wie vorher) ...
    
    # Bild Upload
    if 'hero_image' in request.files:
        file = request.files['hero_image']
        print(f"Datei im Request gefunden: {file.filename}") # Debug
        
        if file and file.filename != '':
            if allowed_file(file.filename): # Check ob Dateityp erlaubt ist
                filename = secure_filename(file.filename)
                # Timestamp anhängen um Caching Probleme zu vermeiden
                ts = int(datetime.now().timestamp())
                filename = f"{ts}_{filename}"
                
                # Sicherstellen, dass der Ordner existiert
                if not os.path.exists(app.config['UPLOAD_FOLDER']):
                    os.makedirs(app.config['UPLOAD_FOLDER'])
                
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                print(f"Versuche zu speichern nach: {filepath}") # Debug
                try:
                    file.save(filepath)
                    print("Speichern erfolgreich!") # Debug
                    
                    # Pfad in Config speichern
                    image_url = url_for('static', filename=f'uploads/{filename}')
                    config['hero']['image_url'] = image_url
                    flash(f"Bild erfolgreich hochgeladen: {filename}", "success")
                except Exception as e:
                    print(f"FEHLER beim Speichern: {e}") # Debug
                    flash(f"Fehler beim Speichern: {e}", "error")
            else:
                 flash("Ungültiges Dateiformat (nur jpg, png, gif, webp)", "error")
    else:
        print("Kein 'hero_image' in request.files gefunden!") # Debug

    # ... (Rest wie vorher) ...
    
    # Fallback Code für URL-Input entfernt, da Feld gelöscht wurde
    # url_input = request.form.get('image_url')
    # if url_input and url_input.strip() != "":
    #      config['hero']['image_url'] = url_input

    save_config(config)
    flash("Hero Section aktualisiert!", "success")
    return redirect(url_for('admin_hero')) # Bleibt auf der Seite

# Alte Admin Routen entfernen oder umleiten
@app.route('/admin/next-race')
@login_required
def admin_next_race():
    return redirect(url_for('admin_events'))

@app.route('/admin/update_nav', methods=['POST'])
@login_required
def update_nav():
    config = load_config()
    new_nav = []
    titles = request.form.getlist('nav_title')
    links = request.form.getlist('nav_link')
    
    for t, l in zip(titles, links):
        if t and l:
            new_nav.append({"text": t, "link": l})
            
    config['navigation'] = new_nav
    save_config(config)
    flash("Navigation aktualisiert!", "success")
    return redirect(url_for('admin_nav')) # Bleibt auf der Seite

# --- Admin Driver Routen ---

@app.route('/admin/team')
@login_required
def admin_team():
    # Lädt die Fahrerliste für den Admin Bereich
    drivers = get_drivers_data()
    
    # Archivierte Bewerbungen laden
    all_apps = load_applications()
    archived_applications = [a for a in all_apps if a.get('status') == 'archived']
    
    return render_template('admin_team.html', drivers=drivers, archived_applications=archived_applications)

@app.route('/admin/driver/new')
@login_required
def admin_driver_new():
    driver = {
        "id": "",
        "name": "",
        "iracing_id": "",
        "role": "",
        "number": "",
        "nationality": "",
        "image_url": ""
    }
    return render_template('admin_edit_driver.html', driver=driver, mode="new")

@app.route('/admin/driver/edit/<driver_id>')
@login_required
def admin_driver_edit(driver_id):
    # Wir laden die gespeicherten Rohdaten, nicht die angereicherten
    drivers_raw = load_drivers()
    
    # Check ob drivers_raw eine Liste von Objekten oder IDs ist
    # Migration: Wenn es IDs sind, konvertieren wir sie on-the-fly zu Objekten
    if drivers_raw and isinstance(drivers_raw[0], int):
        # Alte Struktur -> Konvertierung
        new_list = []
        for d_id in drivers_raw:
             new_list.append({"id": str(d_id), "iracing_id": str(d_id), "name": f"Driver {d_id}"})
        drivers_raw = new_list
        save_drivers(drivers_raw)

    driver = next((d for d in drivers_raw if str(d.get('id')) == str(driver_id)), None)
    
    if not driver:
        flash("Fahrer nicht gefunden", "error")
        return redirect(url_for('admin_team'))
        
    return render_template('admin_edit_driver.html', driver=driver, mode="edit")

@app.route('/admin/driver/save', methods=['POST'])
@login_required
def admin_driver_save():
    drivers = load_drivers()
    
    # Migration Check
    if drivers and isinstance(drivers[0], int):
        new_list = []
        for d_id in drivers:
             new_list.append({"id": str(d_id), "iracing_id": str(d_id), "name": f"Driver {d_id}"})
        drivers = new_list

    mode = request.form.get('mode')
    driver_id = request.form.get('id')
    
    if mode == 'new':
        # Neue ID generieren
        driver_id = str(int(datetime.now().timestamp()))
        driver = {"id": driver_id}
        drivers.append(driver)
    else:
        driver = next((d for d in drivers if str(d.get('id')) == str(driver_id)), None)
        if not driver:
            flash("Fehler beim Speichern", "error")
            return redirect(url_for('admin_team'))

    # Daten update
    driver['name'] = request.form.get('name')
    driver['nickname'] = request.form.get('nickname') # Neu
    driver['iracing_id'] = request.form.get('iracing_id')
    driver['role'] = request.form.get('role')
    driver['number'] = request.form.get('number')
    driver['nationality'] = request.form.get('nationality')
    driver['twitch'] = request.form.get('twitch') # Twitch Kanal
    
    # Login Daten
    driver['username'] = request.form.get('username')
    new_password = request.form.get('password')
    if new_password:
        driver['password_hash'] = generate_password_hash(new_password)
    
    # Manuelle Stats
    driver['ir_sports'] = request.form.get('ir_sports')
    driver['sr_sports'] = request.form.get('sr_sports')
    
    # Bild Upload
    if 'driver_image' in request.files:
        file = request.files['driver_image']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            ts = int(datetime.now().timestamp())
            filename = f"driver_{driver_id}_{ts}_{filename}"
            
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
                
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            driver['image_url'] = url_for('static', filename=f'uploads/{filename}')

    save_drivers(drivers)
    flash("Fahrer gespeichert!", "success")
    return redirect(url_for('admin_team'))

@app.route('/admin/driver/delete/<driver_id>')
@login_required
def admin_driver_delete(driver_id):
    drivers = load_drivers()
    # Migration Check
    if drivers and isinstance(drivers[0], int):
        drivers = [{"id": str(d), "iracing_id": str(d)} for d in drivers]
        
    drivers = [d for d in drivers if str(d.get('id')) != str(driver_id)]
    save_drivers(drivers)
    flash("Fahrer gelöscht.", "info")
    return redirect(url_for('admin_team'))

@app.route('/news/<news_id>')
def news_detail(news_id):
    news = load_news()
    news_item = next((n for n in news if str(n.get('id')) == str(news_id)), None)
    
    if not news_item:
        return redirect(url_for('index'))
    
    linked_event = None
    event_drivers = []
    
    event_id = news_item.get('event_id')
    if event_id:
        events = load_events()
        linked_event = next((e for e in events if str(e['id']) == str(event_id)), None)
        
        if linked_event:
            # Fahrer für das Event laden
            selected_driver_ids = linked_event.get('drivers', [])
            all_drivers = get_drivers_data()
            event_drivers = [d for d in all_drivers if str(d['id']) in selected_driver_ids or d['id'] in selected_driver_ids]

    return render_template('news_detail.html', news=news_item, event=linked_event, event_drivers=event_drivers)

@app.route('/admin/save_drivers_list', methods=['POST'])
@login_required
def admin_save_drivers_list():
    # Route für Drag&Drop Sortierung oder ähnliches
    return redirect(url_for('admin_team'))

# --- Admin News Routen ---

@app.route('/admin/news')
@login_required
def admin_news():
    news = load_news()
    return render_template('admin_news.html', news=news)

@app.route('/admin/news/new')
@login_required
def admin_news_new():
    news_item = {
        "id": "",
        "title": "",
        "category": "ARTICLE", # Default
        "image_url": "",
        "link": "",
        "date": datetime.now().strftime('%Y-%m-%d'),
        "event_id": "" # Link zu einem Event
    }
    events = load_events()
    # Sort events by date descending for easier selection
    events.sort(key=lambda x: x.get('date', ''), reverse=True)
    return render_template('admin_edit_news.html', news=news_item, mode="new", events=events)

@app.route('/admin/news/edit/<news_id>')
@login_required
def admin_news_edit(news_id):
    news = load_news()
    news_item = next((n for n in news if str(n.get('id')) == str(news_id)), None)
    
    if not news_item:
        flash("News-Eintrag nicht gefunden", "error")
        return redirect(url_for('admin_news'))
        
    events = load_events()
    events.sort(key=lambda x: x.get('date', ''), reverse=True)
    return render_template('admin_edit_news.html', news=news_item, mode="edit", events=events)

@app.route('/admin/news/save', methods=['POST'])
@login_required
def admin_news_save():
    news = load_news()
    mode = request.form.get('mode')
    news_id = request.form.get('id')
    
    if mode == 'new':
        news_id = str(int(datetime.now().timestamp()))
        news_item = {"id": news_id}
        news.append(news_item)
    else:
        news_item = next((n for n in news if str(n.get('id')) == str(news_id)), None)
        if not news_item:
            flash("Fehler beim Speichern", "error")
            return redirect(url_for('admin_news'))

    # Daten update
    news_item['title'] = request.form.get('title')
    news_item['category'] = request.form.get('category').upper() # Immer Großbuchstaben
    news_item['date'] = request.form.get('date')
    news_item['link'] = request.form.get('link')
    news_item['content'] = request.form.get('content') # Neuer Inhalt
    news_item['event_id'] = request.form.get('event_id') # Verknüpftes Event

    
    # Bild Upload
    if 'news_image' in request.files:
        file = request.files['news_image']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            ts = int(datetime.now().timestamp())
            filename = f"news_{news_id}_{ts}_{filename}"
            
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
                
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            news_item['image_url'] = url_for('static', filename=f'uploads/{filename}')

    save_news(news)
    flash("News gespeichert!", "success")
    return redirect(url_for('admin_news'))

@app.route('/admin/news/delete/<news_id>')
@login_required
def admin_news_delete(news_id):
    news = load_news()
    news = [n for n in news if str(n.get('id')) != str(news_id)]
    save_news(news)
    flash("News gelöscht.", "info")
    return redirect(url_for('admin_news'))

@app.route('/admin/results')
@login_required
def admin_results():
    results = []
    if os.path.exists(app.config['RESULTS_FOLDER']):
        for filename in os.listdir(app.config['RESULTS_FOLDER']):
            if filename.endswith('.json'):
                filepath = os.path.join(app.config['RESULTS_FOLDER'], filename)
                try:
                    size_kb = os.path.getsize(filepath) / 1024
                    mod_time = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S')
                    
                    results.append({
                        'filename': filename,
                        'size': f"{size_kb:.1f} KB",
                        'date': mod_time
                    })
                except Exception as e:
                    print(f"Fehler bei Datei {filename}: {e}")
    
    # Sortieren nach Datum (neueste zuerst)
    results.sort(key=lambda x: x['date'], reverse=True)
    return render_template('admin_results.html', results=results)

@app.route('/admin/results/upload', methods=['POST'])
@login_required
def admin_results_upload():
    if 'result_file' not in request.files:
        flash('Keine Datei ausgewählt', 'error')
        return redirect(url_for('admin_results'))
        
    file = request.files['result_file']
    if file.filename == '':
        flash('Keine Datei ausgewählt', 'error')
        return redirect(url_for('admin_results'))
        
    if file and file.filename.endswith('.json'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['RESULTS_FOLDER'], filename)
        file.save(filepath)
        flash(f'Datei {filename} erfolgreich hochgeladen', 'success')
    else:
        flash('Nur .json Dateien erlaubt', 'error')
        
    return redirect(url_for('admin_results'))

@app.route('/admin/results/edit/<filename>')
@login_required
def admin_results_edit(filename):
    filepath = os.path.join(app.config['RESULTS_FOLDER'], secure_filename(filename))
    if not os.path.exists(filepath):
        flash('Datei nicht gefunden', 'error')
        return redirect(url_for('admin_results'))
        
    with open(filepath, 'r') as f:
        content = f.read()
        
    return render_template('admin_result_edit.html', filename=filename, content=content)

@app.route('/admin/results/save/<filename>', methods=['POST'])
@login_required
def admin_results_save(filename):
    filepath = os.path.join(app.config['RESULTS_FOLDER'], secure_filename(filename))
    content = request.form.get('content')
    
    try:
        # Validierung: Ist es valides JSON?
        json.loads(content)
        
        # Backup erstellen (Sicherheit)
        if os.path.exists(filepath):
            backup_path = filepath + ".bak"
            import shutil
            shutil.copy2(filepath, backup_path)
            
        with open(filepath, 'w') as f:
            f.write(content)
            
        flash('Datei erfolgreich gespeichert (Backup wurde erstellt)', 'success')
    except json.JSONDecodeError as e:
        flash(f'Fehler: Ungültiges JSON! ({str(e)})', 'error')
        return render_template('admin_result_edit.html', filename=filename, content=content, error=str(e))
        
    return redirect(url_for('admin_results'))

@app.route('/admin/results/delete/<filename>')
@login_required
def admin_results_delete(filename):
    filepath = os.path.join(app.config['RESULTS_FOLDER'], secure_filename(filename))
    if os.path.exists(filepath):
        os.remove(filepath)
        flash(f'Datei {filename} gelöscht', 'success')
    else:
        flash('Datei nicht gefunden', 'error')
    return redirect(url_for('admin_results'))

@app.route('/admin/debug_iracing')
def debug_iracing():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
        
    debug_info = []
    
    # 1. Check Import
    try:
        import iracingdataapi
        debug_info.append(f"Import iracingdataapi: OK (Version: {getattr(iracingdataapi, '__version__', 'unknown')})")
    except Exception as e:
        debug_info.append(f"Import iracingdataapi: FAILED ({e})")
        
    # 2. Check Pydantic
    try:
        import pydantic
        debug_info.append(f"Import pydantic: OK (Version: {getattr(pydantic, '__version__', 'unknown')})")
    except Exception as e:
        debug_info.append(f"Import pydantic: FAILED ({e})")

    # 3. Check Credentials (maskiert)
    u = IRACING_USER
    p = IRACING_PASSWORD
    debug_info.append(f"Username set: {'YES' if u else 'NO'} ({len(u)} chars)")
    debug_info.append(f"Password set: {'YES' if p else 'NO'} ({len(p)} chars)")
    
    # 4. Check Client Init & Login Test
    try:
        from iracingdataapi.client import irDataClient
        debug_info.append("irDataClient Class: Found")
        
        # Test Login (Klartext)
        if u and p:
            try:
                idc = irDataClient(username=u, password=p)
                # Versuche simplen Call
                cars = idc.cars
                if cars:
                    debug_info.append("Login (Plaintext): SUCCESS (Cars loaded)")
                else:
                    debug_info.append("Login (Plaintext): FAILED (No cars returned)")
            except Exception as e:
                debug_info.append(f"Login (Plaintext): ERROR ({e})")

            # Test Login (Hashed) - Workaround Versuch
            import hashlib, base64
            try:
                hashed = base64.b64encode(hashlib.sha256((p + u.lower()).encode('utf-8')).digest()).decode('utf-8')
                idc_hash = irDataClient(username=u, password=hashed)
                cars = idc_hash.cars
                if cars:
                    debug_info.append("Login (Hashed): SUCCESS (Cars loaded)")
                else:
                    debug_info.append("Login (Hashed): FAILED (No cars returned)")
            except Exception as e:
                debug_info.append(f"Login (Hashed): ERROR ({e})")

        # 5. Röntgen-Blick: Manueller Request um Antwort zu sehen
        import requests
        try:
            url = "https://members-ng.iracing.com/auth"
            headers = {'Content-Type': 'application/json'}
            data = {"email": u, "password": base64.b64encode(hashlib.sha256((p + u.lower()).encode('utf-8')).digest()).decode('utf-8')}
            
            resp = requests.post(url, json=data, headers=headers, timeout=10)
            
            debug_info.append(f"<br>--- RAW RESPONSE CHECK ---")
            debug_info.append(f"Status Code: {resp.status_code}")
            
            # Zeige die ersten 300 Zeichen der Antwort
            content_preview = resp.text[:300].replace('<', '&lt;').replace('>', '&gt;')
            debug_info.append(f"Response Preview: {content_preview}...")
            
            if resp.status_code == 403:
                debug_info.append("<b>DIAGNOSE: 403 Forbidden -> Wahrscheinlich IP-Block durch Cloudflare.</b>")
            elif resp.status_code == 429:
                debug_info.append("<b>DIAGNOSE: 429 Too Many Requests -> Rate Limit.</b>")
            
        except Exception as e:
            debug_info.append(f"Raw Request Failed: {e}")

    except Exception as e:
        debug_info.append(f"irDataClient Import/Test: FAILED ({e})")

    return "<br>".join(debug_info)

@app.route('/admin/update_iracing_stats')
@login_required
def update_iracing_stats():
    # Debugging Info
    if not IRACING_USER or not IRACING_PASSWORD:
        flash(f"Keine iRacing Zugangsdaten konfiguriert.", "error")
        return redirect(url_for('admin_dashboard'))

    drivers = load_drivers()
    updated_count = 0
    errors = []
    
    # Wir versuchen ZUERST den SimpleClient, da der robuster ist
    client_to_use = None
    
    try:
        # 1. Versuch: SimpleClient (Requests + Hash)
        try:
            client_to_use = SimpleIRacingClient(username=IRACING_USER, password=IRACING_PASSWORD)
            print("Nutze SimpleIRacingClient")
        except Exception as e:
            print(f"SimpleClient Init Failed: {e}")
            # 2. Versuch: Library Client (Falls installiert)
            if IRACING_AVAILABLE:
                try:
                    from iracingdataapi.client import irDataClient
                    client_to_use = irDataClient(username=IRACING_USER, password=IRACING_PASSWORD)
                    print("Nutze iracingdataapi Library")
                except Exception as lib_e:
                    print(f"Library Client Init Failed: {lib_e}")
    
        if not client_to_use:
            flash("Login bei iRacing mit allen Methoden fehlgeschlagen.", "error")
            return redirect(url_for('admin_dashboard'))
            
        for driver in drivers:
            # ID Logik
            cust_id = driver.get('iracing_id')
            if not cust_id: cust_id = driver.get('id')
            
            if not cust_id or not str(cust_id).isdigit(): 
                continue

            try:
                # API Call - Unterscheidung je nach Client Typ
                stats = []
                if isinstance(client_to_use, SimpleIRacingClient):
                    stats = client_to_use.get_stats(cust_id=int(cust_id))
                else:
                    # Library Client
                    stats = client_to_use.stats_member_career(cust_id=int(cust_id))

                if not stats: 
                    errors.append(f"Keine Daten für ID {cust_id}")
                    continue

                # Kategorie Suche
                target_stats = None
                for cat_id in [2, 1, 3, 4]:
                    target_stats = next((s for s in stats if s['category_id'] == cat_id), None)
                    if target_stats: break
                
                if target_stats:
                    driver['ir_sports'] = target_stats['irating']
                    driver['sr_sports'] = f"{target_stats['license_class']} {target_stats['safety_rating']}"
                    updated_count += 1
                else:
                    errors.append(f"ID {cust_id}: Keine passende Kategorie.")

            except Exception as inner_e:
                errors.append(f"Fehler bei ID {cust_id}: {str(inner_e)}")
                continue
                
        if updated_count > 0:
            save_drivers(drivers)
            msg = f"{updated_count} Fahrer erfolgreich aktualisiert!"
            if errors:
                msg += f" (Aber {len(errors)} Fehler: {'; '.join(errors[:3])})"
            flash(msg, "success")
        else:
            if errors:
                flash(f"Fehler: {'; '.join(errors[:3])}", "error")
            else:
                flash("Keine Fahrer aktualisiert.", "warning")
            
    except Exception as e:
        flash(f"Kritischer Fehler: {str(e)}", "error")

    return redirect(url_for('admin_dashboard'))

# --- Helper Update: get_drivers_data muss jetzt mit Objekten umgehen ---
def get_drivers_data():
    drivers = load_drivers()
    if not drivers:
        return []
    
    # Migration Check
    if drivers and isinstance(drivers[0], int):
         # On-the-fly Konvertierung für Anzeige (speichert noch nicht)
         drivers = [{"id": str(d), "iracing_id": str(d), "name": "Unknown"} for d in drivers]

    client = get_client()
    data_list = []
    
    # Wir iterieren über unsere lokalen DB-Objekte
    for driver_obj in drivers:
        # Basis-Daten aus DB nehmen
        driver_entry = driver_obj.copy() # Kopie damit wir Original nicht verändern
        
        # API Daten holen (wenn Client da und iRacing ID vorhanden)
        ir_id = driver_obj.get('iracing_id')
        
        # Defaults
        driver_entry.setdefault('ir_sports', '-')
        driver_entry.setdefault('sr_sports', '-')
        
        # HINWEIS: Wir holen hier KEINE Live-Daten mehr, sondern nutzen die gespeicherten!
        # Das spart API Calls und macht die Seite schneller.
        # Die Daten werden nur über den Admin-Button aktualisiert.
        
        data_list.append(driver_entry)

    return data_list

@app.route('/admin/api/update_drivers', methods=['POST'])
def api_update_drivers():
    # Einfacher Schutz: Wir prüfen einen API-Key oder das Admin-Passwort im Header
    api_key = request.headers.get('X-API-Key')
    if api_key != ADMIN_PASSWORD:
        return {"error": "Unauthorized"}, 401
        
    try:
        data = request.json
        if not data or 'drivers' not in data:
            return {"error": "Invalid data"}, 400
            
        # Wir überschreiben die bestehenden Fahrer mit den neuen Daten
        # Aber wir müssen vorsichtig sein, dass wir keine Felder löschen, die das Skript nicht kennt
        current_drivers = load_drivers()
        updated_drivers = data['drivers']
        
        # Merge-Logik: Wir aktualisieren nur die Stats, behalten den Rest
        count = 0
        for new_d in updated_drivers:
            # Suche passenden Fahrer in DB
            target = next((d for d in current_drivers if str(d.get('id')) == str(new_d.get('id'))), None)
            if target:
                if 'ir_sports' in new_d: target['ir_sports'] = new_d['ir_sports']
                if 'sr_sports' in new_d: target['sr_sports'] = new_d['sr_sports']
                count += 1
                
        save_drivers(current_drivers)
        return {"status": "success", "updated": count}
        
    except Exception as e:
        return {"error": str(e)}, 500

@app.route('/admin/api/get_drivers')
def api_get_drivers():
    # Damit das Skript weiß, wen es aktualisieren muss
    # Auch hier: Auth Check
    api_key = request.headers.get('X-API-Key')
    if api_key != ADMIN_PASSWORD:
        return {"error": "Unauthorized"}, 401
        
    return {"drivers": load_drivers()}

# --- Public Routen ---

@app.route('/adddriver', methods=['GET', 'POST'])
def add_driver_application():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        discord = request.form.get('discord')
        iracing_class = request.form.get('iracing_class')
        irating = request.form.get('irating')
        motivation = request.form.get('motivation')
        
        if not name or not email or not discord:
            flash("Bitte fülle alle Pflichtfelder aus.", "error")
            return redirect(url_for('add_driver_application'))
            
        apps = load_applications()
        new_app = {
            "id": str(uuid.uuid4()),
            "name": name,
            "email": email,
            "discord": discord,
            "iracing_class": iracing_class,
            "irating": irating,
            "motivation": motivation,
            "status": "new",
            "date": datetime.now().isoformat()
        }
        
        apps.insert(0, new_app)
        save_applications(apps)
        
        flash("Deine Bewerbung wurde erfolgreich gesendet! Wir melden uns bei dir.", "success")
        return redirect(url_for('index'))
        
    return render_template('add_driver.html')

@app.route('/')
def index():
    try:
        # Für die Home-Seite laden wir auch die Fahrerdaten, um die "Top Fahrer" anzuzeigen
        data = get_drivers_data()
        
        # News laden (limitiert auf die neuesten 6 für die Startseite)
        all_news = load_news()
        latest_news = all_news[:6]
        
        # Events laden und filtern (Nur Approved)
        events = load_events()
        public_events = [e for e in events if e.get('status', 'approved') == 'approved']
        
        # Nächstes Event finden
        now = datetime.now().isoformat()
        future_events = [e for e in public_events if e['date'] > now]
        future_events.sort(key=lambda x: x['date'])
        
        next_event = future_events[0] if future_events else None
        
        # Check if LIVE (Server-Side Check)
        if next_event:
            event_start = datetime.fromisoformat(next_event['date'])
            # Live wenn Startzeit vorbei ist, aber nicht länger als 4h
            diff = datetime.now() - event_start
            hours_since_start = diff.total_seconds() / 3600
            
            if 0 < hours_since_start < 4:
                next_event['is_live'] = True
            else:
                next_event['is_live'] = False

        site_config = load_config()
        return render_template('home.html', drivers=data, news=latest_news, next_event=next_event, site_config=site_config)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"<h1>Fehler beim Laden der Seite:</h1><p>{e}</p>"

@app.route('/team')
def team():
    try:
        data = get_drivers_data()
        return render_template('team.html', drivers=data)
    except Exception as e:
        return f"<h1>Fehler:</h1><p>{e}</p>"

@app.route('/driver/<driver_id>')
def driver_detail(driver_id):
    drivers = get_drivers_data()
    # Driver ID can be string or int in JSON, so check both
    driver = next((d for d in drivers if str(d['id']) == str(driver_id)), None)
    
    if not driver:
        flash("Fahrer nicht gefunden.", "error")
        return redirect(url_for('team'))
        
    # Get upcoming and past events for this driver
    events = load_events()
    now = datetime.now().isoformat()
    
    # Filter by driver ID participation
    d_id_str = str(driver_id)
    d_id_int = int(driver_id) if str(driver_id).isdigit() else None
    
    # Determine the ID to search for in result files (prefer iRacing ID)
    search_id_str = d_id_str
    if driver.get('iracing_id'):
        search_id_str = str(driver.get('iracing_id'))
    
    driver_events = []
    for e in events:
        d_ids = e.get('drivers', [])
        # Convert all to string for comparison
        d_ids_str = [str(did) for did in d_ids]
        
        if d_id_str in d_ids_str:
            # Add extra info if available (result link, stats)
            # We need to enrich the event object with result data specifically for this driver
            
            # Check if event has a result file linked
            if e.get('result_file'):
                # Try to load stats from that file
                res_path = os.path.join(app.config['RESULTS_FOLDER'], secure_filename(e['result_file']))
                if os.path.exists(res_path):
                    try:
                        with open(res_path, 'r') as f:
                            res_data = json.load(f)
                        
                        sessions = res_data.get('data', {}).get('session_results', [])
                        race_session = next((s for s in sessions if s.get('simsession_type_name') == 'Race'), sessions[-1] if sessions else None)
                        
                        if race_session:
                            # Always set result link if file exists and has race session
                            e['result_link'] = e['result_file']
                            
                            # Find driver (Single or Team Event)
                            d_res = None
                            scanned_teams = 0
                            scanned_drivers = 0
                            
                            for r in race_session.get('results', []):
                                scanned_teams += 1
                                # 1. Single Driver Match (ID)
                                if str(r.get('cust_id')) == search_id_str:
                                    d_res = r
                                    e['debug'] = "Found via Single ID"
                                    break
                                
                                # 2. Team Driver Match (search inside driver_results)
                                if 'driver_results' in r:
                                    for team_driver in r.get('driver_results', []):
                                        scanned_drivers += 1
                                        if str(team_driver.get('cust_id')) == search_id_str:
                                            # Found driver in team!
                                            # We need to COMBINE team info (Position) with Driver Info (Incidents, Laps)
                                            d_res = r.copy() # Copy team result
                                            # Override specific driver stats
                                            d_res['incidents'] = team_driver.get('incidents', 0)
                                            # Best lap might be team best lap, or driver best lap?
                                            # Usually we want the driver's best lap if available
                                            if 'best_lap_time' in team_driver:
                                                d_res['best_lap_time'] = team_driver.get('best_lap_time')
                                                
                                            e['debug'] = "Found via Team ID"
                                            break
                                if d_res: break
                                
                            # If not found by ID, maybe by name? (less reliable, only top level)
                            if not d_res:
                                d_res = next((r for r in race_session.get('results', []) if r.get('display_name') == driver['name']), None)
                                if d_res: e['debug'] = "Found via Name"
                                
                            if d_res:
                                def format_time(val):
                                    if val <= 0: return "-"
                                    # iRacing time is in 1/10000 seconds
                                    seconds = val / 10000
                                    minutes = int(seconds // 60)
                                    rem_seconds = seconds % 60
                                    return f"{minutes}:{rem_seconds:06.3f}"
                                
                                e['best_lap'] = format_time(d_res.get('best_lap_time', 0))
                                e['inc'] = d_res.get('incidents', 0)
                                if not e.get('debug'): e['debug'] = "Found via ID (Standard)"
                            else:
                                # Debug info
                                first_res = race_session.get('results', [])[0] if race_session.get('results') else {}
                                keys = list(first_res.keys())
                                
                                # Deep inspection of driver_results
                                dr_info = ""
                                if 'driver_results' in first_res:
                                    drs = first_res.get('driver_results', [])
                                    if drs:
                                        dr_keys = list(drs[0].keys())
                                        dr_ids = [str(d.get('cust_id', 'N/A')) for d in drs]
                                        dr_info = f" | DR Keys: {','.join(dr_keys)} | DR IDs in Team 1: {','.join(dr_ids)}"
                                    else:
                                        dr_info = " | driver_results empty"
                                else:
                                    dr_info = " | No driver_results key"

                                e['debug'] = f"Search: {search_id_str} (Internal: {d_id_str}) | Scanned: {scanned_teams} Teams, {scanned_drivers} Drivers | Not found. Keys: {','.join(keys)}{dr_info}"
                        else:
                            e['debug'] = "No Race session found"
                    except Exception as ex: 
                        e['debug'] = f"Error: {str(ex)}"
                else:
                    e['debug'] = f"File not found: {res_path}"
            else:
                e['debug'] = "No result file linked"

            driver_events.append(e)
            
    upcoming_events = [e for e in driver_events if e.get('date') > now]
    past_events = [e for e in driver_events if e.get('date') <= now]
    past_events.sort(key=lambda x: x.get('date'), reverse=True) # Newest first
    
    return render_template('driver_detail.html', driver=driver, upcoming_events=upcoming_events, past_events=past_events)

@app.route('/add', methods=['POST'])
def add():
    try:
        new_id_str = request.form['driver_id']
        if not new_id_str:
            flash("Bitte eine ID eingeben.", "error")
            return redirect(url_for('index'))
            
        new_id = int(new_id_str)
        drivers = load_drivers()
        
        if new_id in drivers:
            flash(f"Fahrer mit ID {new_id} ist bereits in der Liste.", "info")
            return redirect(url_for('index'))

        # Prüfung über API
        client = get_client()
        if client:
            try:
                # API 1.4.x erwartet einzelne ID
                info = client.member(cust_id=new_id)
                
                if info and 'members' in info and len(info['members']) > 0:
                    driver_name = info['members'][0]['display_name']
                    drivers.append(new_id)
                    save_drivers(drivers)
                    flash(f"Fahrer '{driver_name}' erfolgreich hinzugefügt!", "success")
                else:
                    flash(f"Kein Fahrer mit ID {new_id} gefunden.", "error")
            except Exception as e:
                flash(f"Fehler bei der Überprüfung: {e}", "error")
        else:
             flash("Verbindung zur iRacing API fehlgeschlagen.", "error")
            
    except ValueError:
        flash("Ungültige ID eingegeben.", "error")
        
    return redirect(url_for('index'))

@app.route('/delete/<int:cust_id>')
def delete(cust_id):
    drivers = load_drivers()
    if cust_id in drivers:
        drivers.remove(cust_id)
        save_drivers(drivers)
        flash(f"Fahrer ID {cust_id} entfernt.", "info")
    return redirect(url_for('index'))

if __name__ == "__main__":
    # Starte den Webserver auf Port 8083
    print("Starte Webserver auf http://127.0.0.1:8083")
    app.run(debug=True, host='0.0.0.0', port=8083)
