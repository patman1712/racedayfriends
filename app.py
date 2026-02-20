import os
import json
import sys
import shutil
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session
from functools import wraps
from werkzeug.utils import secure_filename

# Versuche iracingdataapi zu importieren
try:
    from iracingdataapi.client import irDataClient
    IRACING_AVAILABLE = True
except ImportError:
    IRACING_AVAILABLE = False
    print("Warnung: iracingdataapi nicht installiert. iRacing Features deaktiviert.")

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
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123") # Default Passwort

UPLOAD_FOLDER = os.path.join(BASE_DATA_DIR, 'static/uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
LOCAL_STATIC_UPLOADS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads')

# Initialisierung der Daten
def init_persistence():
    # 1. Ordner erstellen
    if not os.path.exists(BASE_DATA_DIR):
        try:
            os.makedirs(BASE_DATA_DIR)
        except OSError:
            pass 

    # 2. Upload Ordner im Persistenten Bereich erstellen
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    # 3. Symlink für Uploads
    if os.path.abspath(LOCAL_STATIC_UPLOADS) != os.path.abspath(UPLOAD_FOLDER):
        if os.path.exists(LOCAL_STATIC_UPLOADS) and not os.path.islink(LOCAL_STATIC_UPLOADS):
            print("Kopiere bestehende Uploads ins Volume...")
            for item in os.listdir(LOCAL_STATIC_UPLOADS):
                s = os.path.join(LOCAL_STATIC_UPLOADS, item)
                d = os.path.join(UPLOAD_FOLDER, item)
                if os.path.isfile(s):
                    shutil.copy2(s, d)
            shutil.rmtree(LOCAL_STATIC_UPLOADS)
        
        if not os.path.exists(LOCAL_STATIC_UPLOADS):
            try:
                os.symlink(UPLOAD_FOLDER, LOCAL_STATIC_UPLOADS)
                print(f"Symlink erstellt: {LOCAL_STATIC_UPLOADS} -> {UPLOAD_FOLDER}")
            except Exception as e:
                print(f"Konnte Symlink nicht erstellen: {e}")

    # 4. JSON Dateien initialisieren (Kopieren falls nicht im Volume)
    for filename in ['drivers.json', 'site_config.json', 'cars.json', 'events.json']:
        target_file = os.path.join(BASE_DATA_DIR, filename)
        source_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        
        if not os.path.exists(target_file) and os.path.exists(source_file) and os.path.abspath(target_file) != os.path.abspath(source_file):
            print(f"Kopiere {filename} ins Volume...")
            shutil.copy2(source_file, target_file)

init_persistence()

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# iRacing Zugangsdaten
IRACING_USER = os.getenv('IRACING_USERNAME', '')
IRACING_PASSWORD = os.getenv('IRACING_PASSWORD', '')

# --- Hilfsfunktionen ---

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
                
        except Exception:
            pass

        data_list.append(driver_entry)

    return data_list

# --- Admin Routen ---

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
    return render_template('admin_dashboard.html')

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
        "result": ""
    }
    all_drivers = get_drivers_data()
    cars_data = load_cars()
    return render_template('admin_event_edit.html', event=event, all_drivers=all_drivers, cars_data=cars_data, mode="new")

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
    return render_template('admin_event_edit.html', event=event, all_drivers=all_drivers, cars_data=cars_data, mode="edit")

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

    # Wir bauen ein Fake-Config Objekt, damit das Template nicht umgebaut werden muss
    # Das Template erwartet config.next_race.*
    # Wir könnten das Template anpassen, aber einfacher ist es, die Datenstruktur passend zu machen
    
    # BESSER: Template anpassen, um 'event' Objekt zu nutzen statt config.next_race
    return render_template('event_info.html', event=event, drivers=event_drivers, config=config, is_past=is_past)

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
    return render_template('admin_team.html', drivers=drivers)

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

@app.route('/admin/save_drivers_list', methods=['POST'])
@login_required
def admin_save_drivers_list():
    # Route für Drag&Drop Sortierung oder ähnliches
    return redirect(url_for('admin_team'))

@app.route('/admin/update_iracing_stats')
def update_iracing_stats():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if not IRACING_AVAILABLE:
        flash("iRacing API Bibliothek ist nicht installiert.", "error")
        return redirect(url_for('admin_dashboard'))

    # Debugging Info (nur für uns, damit wir sehen ob Vars da sind)
    if not IRACING_USER or not IRACING_PASSWORD:
        flash(f"Keine iRacing Zugangsdaten konfiguriert. User: {'Gesetzt' if IRACING_USER else 'Fehlt'}", "error")
        return redirect(url_for('admin_dashboard'))

    updated_count = 0
    
    try:
        # Versuche Login explizit
        try:
            idc = irDataClient(username=IRACING_USER, password=IRACING_PASSWORD)
        except Exception as e:
            # Login Fehler detailliert ausgeben
            flash(f"Login bei iRacing fehlgeschlagen: {str(e)}", "error")
            return redirect(url_for('admin_dashboard'))
            
        for driver in drivers:
            cust_id = driver.get('id')
            # Prüfen ob ID gültig ist
            if not cust_id or not str(cust_id).isdigit(): 
                continue

            try:
                # API Call
                stats = idc.stats_member_career(cust_id=int(cust_id))
                if not stats: continue

                # Suche Sports Car (2) oder Formula (1)
                target_stats = next((s for s in stats if s['category_id'] == 2), 
                                  next((s for s in stats if s['category_id'] == 1), None))
                
                if target_stats:
                    driver['ir_sports'] = target_stats['irating']
                    driver['sr_sports'] = f"{target_stats['license_class']} {target_stats['safety_rating']}"
                    updated_count += 1
            except Exception as inner_e:
                print(f"Fehler bei Fahrer {cust_id}: {inner_e}")
                # Wir machen weiter mit dem nächsten Fahrer
                continue
                
        if updated_count > 0:
            save_data()
            flash(f"{updated_count} Fahrer erfolgreich aktualisiert!", "success")
        else:
            flash("Keine Fahrer aktualisiert. Sind die IDs korrekt?", "warning")
            
    except Exception as e:
        # Globaler Catch-All für alles andere
        flash(f"Kritischer Fehler beim Update: {str(e)}", "error")
        print(f"CRITICAL ERROR: {e}")

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
        
        if client and ir_id:
            try:
                # API Call (vereinfacht, hier könnte man Caching einbauen)
                # Wir nutzen Mock oder Echte API
                # Um API Calls zu sparen, könnte man das nur alle X Stunden machen
                pass 
                # Für Demo nehmen wir an, die API liefert was zurück, wenn wir wollen
                # Aber da wir jetzt "Manuelle" Fahrer haben, ist die API optional
            except:
                pass
        
        data_list.append(driver_entry)

    return data_list

# --- Public Routen ---

@app.route('/')
def index():
    try:
        # Für die Home-Seite laden wir auch die Fahrerdaten, um die "Top Fahrer" anzuzeigen
        data = get_drivers_data()
        # Sortieren nach iRating (Sports Car) absteigend für die Anzeige
        # Hinweis: Mock-Daten sind strings oder ints, wir müssen aufpassen. 
        # Im echten Leben: Sortierlogik einbauen.
        return render_template('home.html', drivers=data)
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
    try:
        # 1. Fahrer aus lokaler DB laden
        drivers = load_drivers()
        # Migration Check (falls noch alte IDs drin sind)
        if drivers and isinstance(drivers[0], int):
             drivers = [{"id": str(d), "iracing_id": str(d), "name": "Unknown"} for d in drivers]

        # Fahrer suchen (ID ist jetzt String in JSON)
        driver = next((d for d in drivers if str(d.get('id')) == str(driver_id)), None)
        
        if not driver:
            flash("Fahrer nicht gefunden", "error")
            return redirect(url_for('team')) # Besser zur Team-Seite

        # 2. iRacing Daten anreichern (optional)
        client = get_client()
        recent_races = []
        # career_stats = [] # Nicht mehr benötigt

        # Initiale Lizenz-Liste (leer)
        driver['licenses'] = []

        if client and driver.get('iracing_id'):
            try:
                ir_id = int(driver['iracing_id'])
                
                # Member Info für Lizenzen (könnte man auch entfernen, wenn nicht gewünscht)
                # Aber wir lassen es drin falls wir es später brauchen
                # member_resp = client.member(cust_id=ir_id) 
                
                # Recent Races
                recent_resp = client.stats_member_recent_races(cust_id=ir_id)
                if recent_resp and 'races' in recent_resp:
                    for race in recent_resp['races'][:10]:
                        raw_date = race['session_start_time']
                        dt = datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
                        race['date_str'] = dt.strftime('%d.%m.%Y %H:%M')
                        
                        start = race.get('start_position', 0)
                        finish = race.get('finish_position', 0)
                        race['pos_diff'] = start - finish
                        recent_races.append(race)

            except Exception as e:
                print(f"API Fehler für {driver.get('name')}: {e}")
                # Wir machen weiter, zeigen halt keine Stats an

        # 3. Events laden (wo der Fahrer dabei ist)
        all_events = load_events()
        now_iso = datetime.now().isoformat()
        
        upcoming_events = []
        past_events = []
        
        for ev in all_events:
            # Check ob Fahrer im Lineup (Strings vergleichen)
            if str(driver_id) in ev.get('drivers', []):
                if ev.get('date') and ev.get('date') > now_iso:
                    upcoming_events.append(ev)
                else:
                    past_events.append(ev)
        
        # Sortieren
        upcoming_events.sort(key=lambda x: x.get('date', ''))
        past_events.sort(key=lambda x: x.get('date', ''), reverse=True) # Neueste zuerst

        # Alle Fahrer für die Navigation laden
        all_drivers = sorted(drivers, key=lambda x: x.get('name', ''))

        return render_template('driver_detail.html', 
                             driver=driver, 
                             upcoming_events=upcoming_events,
                             past_events=past_events,
                             all_drivers=all_drivers) # Neu übergeben

    except Exception as e:
        print(f"FEHLER in driver_detail: {e}")
        import traceback
        traceback.print_exc()
        return f"<h1>Fehler beim Laden der Details:</h1><p>{e}</p>"

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
