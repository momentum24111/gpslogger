# GPSLogger

Serverseitiger GPSLogger mit WebUI, Geräteverwaltung, Theme-System und optionaler Request-Weiterleitung.

## Start

```bash
python app.py
```

Danach ist die Anwendung unter `http://localhost:8080` erreichbar.

## Struktur

- `backend/`: API, Persistenz, NAS-Flush, Weiterleitung
- `static/`: WebUI (Material-orientierte Komponenten + Kartenansicht)
- `themes/`: getrennte Theme-Variablen (`light`, `dark`)
- `data/`: Laufzeitdaten (wird automatisch angelegt)
- `.gitignore`: ignoriert Laufzeit-/IDE-Artefakte

## Sicherheits- und Validierungsregeln

- Öffentliche API mit `Authorization: Bearer <API_KEY>`
- Jeder Request wird serverseitig verarbeitet und gespeichert
- GPS-Endpoint akzeptiert nur `application/x-www-form-urlencoded`
- GPS-Datenvalidierung:
  - Koordinatenbereich (`lat`, `lon`)
  - `accuracy` nur >= 0
  - `timestamp` im ISO-Format
- Gerätevalidierung:
  - Name erforderlich
  - maximal 80 Zeichen
  - keine doppelten Namen (case-insensitive)
- Geräte-Listing enthält **keine API-Keys**
- Forwarding ist asynchron und blockiert den Hauptprozess nicht
- Weiterleitungsheader werden bereinigt (z. B. kein `Host`, `Content-Length`)
- Forwarding-URL nur `http://` oder `https://`

## Wichtige Endpunkte

- `POST /api/gps` (Bearer + `application/x-www-form-urlencoded`)
- `GET /api/health`
- `GET/POST/PUT/DELETE /api/devices`
- `POST /api/devices/{id}/rotate-key`
- `GET /api/devices/status`
- `GET/PUT /api/settings`
- `GET /api/system/status`
- `GET /api/forwarding/errors`
- `POST /api/forwarding/errors/clear`
- `GET /api/gps/recent`
- `POST /api/save-now`
- `GET /api/themes`
- `GET /api/positions`

## Hinweise für Entwicklung

- Start: `python app.py`
- WebUI: `http://localhost:8080`
- Für Kartenfilter (`from`, `to`) gilt ISO-Zeitformat