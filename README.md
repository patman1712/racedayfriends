# iRacing Data API Demo

Dieses Projekt demonstriert, wie man mit Python Daten von der iRacing API abruft.

## Voraussetzungen

- Python 3.x
- Ein aktiver iRacing Account

## Installation

1. Installiere die Abhängigkeiten:
   ```bash
   pip install -r requirements.txt
   ```

2. Konfiguration:
   - Kopiere `.env.example` zu `.env`
   - Trage deine iRacing Zugangsdaten in die `.env` Datei ein.

## Nutzung

Führe das Skript aus:
```bash
python iracing_demo.py
```

## Funktionen

Das Skript `iracing_demo.py` zeigt grundlegend, wie die Verbindung hergestellt wird. Es kann erweitert werden, um:
- Fahrerdaten (iRating, Safety Rating) abzurufen
- Rennergebnisse zu laden
- Rundenzeiten zu analysieren
