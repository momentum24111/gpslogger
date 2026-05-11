"""OpenAPI-3.0-Spezifikation für die GPSLogger-HTTP-API (manuell an server.py gespiegelt)."""

OPENAPI_VERSION = "3.0.3"


def build_openapi_spec() -> dict:
    return {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": "GPSLogger API",
            "description": (
                "REST- und Form-basierte API von GPSLogger: Geräteverwaltung, "
                "Positionsabfrage, Weiterleitungen, Einstellungen und GPS-Ingest per Bearer-API-Key."
            ),
            "version": "1.0.0",
        },
        "servers": [{"url": "/", "description": "Aktueller Server (gleicher Host und Port wie die Web-UI)"}],
        "tags": [
            {"name": "System", "description": "Laufzeit, Themes und Gesundheitschecks"},
            {"name": "Geräte", "description": "Geräte anlegen, umbenennen, löschen, API-Keys"},
            {"name": "Weiterleitungen", "description": "HTTP-Weiterleitungen für Rohe GPS-Requests"},
            {"name": "Einstellungen", "description": "Globale Einstellungen (NAS, Theme, Forwardings-Liste lesen)"},
            {
                "name": "GPS-Ingest",
                "description": (
                    "Positionsdaten per Mobilgerät: `application/x-www-form-urlencoded`, "
                    "`Authorization: Bearer <api_key>`. "
                    "Werkbank-kompatibel unter `/api/current-location`; Legacy `/api/gps`."
                ),
            },
            {
                "name": "Daten",
                "description": "Gespeicherte Positionen, Live-Stream (SSE) und Diagnose-Metadaten",
            },
        ],
        "paths": {
            "/api/health": {
                "get": {
                    "tags": ["System"],
                    "summary": "Healthcheck",
                    "operationId": "getHealth",
                    "responses": {
                        "200": {
                            "description": "Dienst erreichbar",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/HealthResponse"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/admin/restart": {
                "post": {
                    "tags": ["System"],
                    "summary": "Neustart über Deploy-Webhook",
                    "description": (
                        "Löst asynchron einen POST auf den lokalen Webhook aus (kein systemctl im HTTP-Handler). "
                        "Typischerweise nur nach Authelia erreichbar; nicht für öffentliche GPS-Clients."
                    ),
                    "operationId": "postAdminRestart",
                    "responses": {
                        "200": {
                            "description": "Anfrage angenommen (Neustart läuft im Hintergrund)",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RestartAcceptedResponse"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/themes": {
                "get": {
                    "tags": ["System"],
                    "summary": "Verfügbare UI-Themes",
                    "operationId": "getThemes",
                    "responses": {
                        "200": {
                            "description": "Liste der Theme-Ordnernamen (z. B. dark, light)",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ThemesResponse"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/system/status": {
                "get": {
                    "tags": ["System"],
                    "summary": "Laufzeit- und NAS-Status",
                    "operationId": "getSystemStatus",
                    "responses": {
                        "200": {
                            "description": "Statistik und letzte NAS-Läufe",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/SystemStatusResponse"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/storage/status": {
                "get": {
                    "tags": ["Einstellungen"],
                    "summary": "NDJSON-Speicherstatus je Gerät",
                    "description": (
                        "Optionaler Query-Parameter `nas_path` (URL-kodiert): aktueller Pfad aus der UI; "
                        "ohne Parameter wird der gespeicherte `nas_path` aus den Einstellungen verwendet."
                    ),
                    "operationId": "getStorageStatus",
                    "parameters": [
                        {
                            "name": "nas_path",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string"},
                            "description": "Absoluter Speicherordner zur Vorschau (kann von den persistierten Settings abweichen).",
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Übersicht inkl. Pfadvalidierung und Zähler",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/StorageStatusResponse"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/devices": {
                "get": {
                    "tags": ["Geräte"],
                    "summary": "Geräte auflisten",
                    "description": "Liefert alle Geräte inkl. `api_key` (nur in vertrauenswürdigen Umgebungen exponieren).",
                    "operationId": "listDevices",
                    "responses": {
                        "200": {
                            "description": "Geräteliste",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/DevicesListResponse"}
                                }
                            },
                        }
                    },
                },
                "post": {
                    "tags": ["Geräte"],
                    "summary": "Direktes Anlegen nicht erlaubt",
                    "operationId": "postDevicesDisallowed",
                    "responses": {
                        "400": {
                            "description": "Hinweis auf Draft/Commit-Flow",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                                }
                            },
                        }
                    },
                },
            },
            "/api/devices/status": {
                "get": {
                    "tags": ["Geräte"],
                    "summary": "Letzte Meldung pro Gerät",
                    "operationId": "getDevicesStatus",
                    "responses": {
                        "200": {
                            "description": "Statusobjekte keyed by device_id",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/DeviceStatusesResponse"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/devices/draft": {
                "post": {
                    "tags": ["Geräte"],
                    "summary": "Gerät-Entwurf anlegen",
                    "description": "Erzeugt einen temporären API-Key (`draft_token`), der für `commit` genutzt wird.",
                    "operationId": "createDeviceDraft",
                    "responses": {
                        "200": {
                            "description": "Entwurf inkl. draft_token",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/DeviceDraftResponse"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/devices/commit": {
                "post": {
                    "tags": ["Geräte"],
                    "summary": "Entwurf committen",
                    "operationId": "commitDeviceDraft",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["draft_token", "name"],
                                    "properties": {
                                        "draft_token": {"type": "string"},
                                        "name": {"type": "string", "description": "Anzeigename des Geräts"},
                                        "api_key": {
                                            "type": "string",
                                            "description": (
                                                "Optional: eigener API-Key statt des Draft-Vorschlags; "
                                                "8–128 Zeichen, keine Leerzeichen, muss systemweit eindeutig sein. "
                                                "Feld weglassen oder leer lassen für den generierten Vorschlag."
                                            ),
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "Gerät angelegt",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/DeviceCreatedResponse"}
                                }
                            },
                        },
                        "400": {
                            "description": "Ungültige Parameter oder abgelaufener Entwurf",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                                }
                            },
                        },
                    },
                }
            },
            "/api/devices/{device_id}": {
                "put": {
                    "tags": ["Geräte"],
                    "summary": "Gerät umbenennen",
                    "operationId": "updateDevice",
                    "parameters": [{"$ref": "#/components/parameters/device_id"}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name"],
                                    "properties": {
                                        "name": {"type": "string"},
                                        "map_color_index": {
                                            "type": "integer",
                                            "minimum": 0,
                                            "maximum": 5,
                                            "description": "Farbe auf der Karte (Theme-Palette, persistent)",
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Aktualisiertes Gerät",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/DeviceSingleResponse"}
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/BadRequestJson"},
                        "404": {"$ref": "#/components/responses/NotFoundJson"},
                    },
                },
                "delete": {
                    "tags": ["Geräte"],
                    "summary": "Gerät löschen",
                    "operationId": "deleteDevice",
                    "parameters": [{"$ref": "#/components/parameters/device_id"}],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/OkResponse"}
                                }
                            },
                        },
                        "404": {"$ref": "#/components/responses/NotFoundJson"},
                    },
                },
            },
            "/api/devices/{device_id}/rotate-key": {
                "post": {
                    "tags": ["Geräte"],
                    "summary": "API-Key rotieren",
                    "operationId": "rotateDeviceKey",
                    "parameters": [{"$ref": "#/components/parameters/device_id"}],
                    "responses": {
                        "200": {
                            "description": "Gerät mit neuem api_key",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/DeviceSingleResponse"}
                                }
                            },
                        },
                        "404": {"$ref": "#/components/responses/NotFoundJson"},
                    },
                }
            },
            "/api/forwardings": {
                "post": {
                    "tags": ["Weiterleitungen"],
                    "summary": "Weiterleitung anlegen",
                    "operationId": "createForwarding",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ForwardingWriteBody"}
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "Angelegt",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ForwardingSingleResponse"}
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/BadRequestJson"},
                    },
                }
            },
            "/api/forwardings/{forward_id}": {
                "put": {
                    "tags": ["Weiterleitungen"],
                    "summary": "Weiterleitung vollständig aktualisieren",
                    "operationId": "updateForwarding",
                    "parameters": [{"$ref": "#/components/parameters/forward_id"}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ForwardingWriteBody"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Aktualisiert",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ForwardingSingleResponse"}
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/BadRequestJson"},
                        "404": {"$ref": "#/components/responses/NotFoundJson"},
                    },
                },
                "patch": {
                    "tags": ["Weiterleitungen"],
                    "summary": "Nur Ein/Aus schalten",
                    "operationId": "patchForwardingEnabled",
                    "parameters": [{"$ref": "#/components/parameters/forward_id"}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["enabled"],
                                    "properties": {"enabled": {"type": "boolean"}},
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Aktualisiert",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ForwardingSingleResponse"}
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/BadRequestJson"},
                        "404": {"$ref": "#/components/responses/NotFoundJson"},
                    },
                },
                "delete": {
                    "tags": ["Weiterleitungen"],
                    "summary": "Weiterleitung löschen",
                    "operationId": "deleteForwarding",
                    "parameters": [{"$ref": "#/components/parameters/forward_id"}],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/OkResponse"}
                                }
                            },
                        },
                        "404": {"$ref": "#/components/responses/NotFoundJson"},
                    },
                },
            },
            "/api/forwarding/errors": {
                "get": {
                    "tags": ["Weiterleitungen"],
                    "summary": "Letzte Weiterleitungsfehler",
                    "operationId": "getForwardingErrors",
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
                            "description": "Maximale Anzahl Einträge",
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Fehlerliste (neueste zuerst)",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ForwardingErrorsResponse"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/forwarding/errors/clear": {
                "post": {
                    "tags": ["Weiterleitungen"],
                    "summary": "Fehlerprotokoll leeren",
                    "operationId": "clearForwardingErrors",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/OkResponse"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/settings": {
                "get": {
                    "tags": ["Einstellungen"],
                    "summary": "Einstellungen lesen",
                    "operationId": "getSettings",
                    "responses": {
                        "200": {
                            "description": "Aktuelle Konfiguration",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/SettingsResponse"}
                                }
                            },
                        }
                    },
                },
                "put": {
                    "tags": ["Einstellungen"],
                    "summary": "Einstellungen aktualisieren",
                    "description": "Erwartet Felder wie `nas_path`, `nas_interval_seconds`, `theme`, `forwardings` je nach Server-Implementierung.",
                    "operationId": "putSettings",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "description": "Teilmenge der Settings; unbekannte Felder können ignoriert werden.",
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Neue Settings",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/SettingsResponse"}
                                }
                            },
                        },
                        "400": {
                            "description": "Ungültige Einstellungen (z. B. nicht absoluter Speicherpfad)",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "error": {"type": "string"},
                                            "error_key": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        },
                    },
                },
            },
            "/api/save-now": {
                "post": {
                    "tags": ["Einstellungen"],
                    "summary": "Ausstehende Positionen als NDJSON in den konfigurierten Ordner schreiben",
                    "operationId": "saveNow",
                    "responses": {
                        "200": {
                            "description": "Erfolg",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "ok": {"type": "boolean", "example": True},
                                            "result": {"type": "object", "additionalProperties": True},
                                        },
                                    }
                                }
                            },
                        },
                        "400": {
                            "description": "Pfad ungültig oder nicht beschreibbar; es wurde nichts geschrieben",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "ok": {"type": "boolean", "example": False},
                                            "error_key": {"type": "string"},
                                            "result": {"type": "object", "additionalProperties": True},
                                        },
                                    }
                                }
                            },
                        },
                    },
                }
            },
            "/api/gps": {
                "post": {
                    "tags": ["GPS-Ingest"],
                    "summary": "GPS-Position melden",
                    "description": (
                        "`Authorization: Bearer <api_key>`. Body muss "
                        "`Content-Type: application/x-www-form-urlencoded` sein. "
                        "Koordinaten alternativ als `lat`/`lon`/`lng`."
                    ),
                    "operationId": "postGps",
                    "security": [{"bearerApiKey": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/x-www-form-urlencoded": {
                                "schema": {
                                    "type": "object",
                                    "required": ["latitude", "longitude"],
                                    "properties": {
                                        "latitude": {
                                            "type": "string",
                                            "description": "Breite; Alias: lat",
                                        },
                                        "lat": {"type": "string", "description": "Alias für latitude"},
                                        "longitude": {
                                            "type": "string",
                                            "description": "Länge; Aliasse: lon, lng",
                                        },
                                        "lon": {"type": "string"},
                                        "lng": {"type": "string"},
                                        "accuracy": {"type": "string", "description": "Optional; nicht-negativ"},
                                        "timestamp": {
                                            "type": "string",
                                            "description": "ISO-8601; optional, sonst Serverzeit",
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Position gespeichert (und ggf. in Weiterleitungsqueue)",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/GpsOkResponse"}
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/BadRequestJson"},
                        "401": {"$ref": "#/components/responses/UnauthorizedJson"},
                    },
                }
            },
            "/api/current-location": {
                "post": {
                    "tags": ["GPS-Ingest"],
                    "summary": "Aktuelle Position melden (Werkbank)",
                    "description": (
                        "Gleiches Schema wie Werkbank: `Content-Type: application/x-www-form-urlencoded`, "
                        "`Authorization: Bearer <api_key>`. "
                        "Pflicht: `latitude`, `longitude`. "
                        "Optional (werden gespeichert und bei Weiterleitungen als identischer Request-Body versendet): "
                        "`device`, `accuracy`, `battery`, `speed`, `direction`, `altitude`, `provider`, `activity`, `time`. "
                        "`time` ist ISO-8601 (wie bei Werkbank); fehlt sie, setzt der Server den Zeitstempel."
                    ),
                    "operationId": "postCurrentLocation",
                    "security": [{"bearerApiKey": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/x-www-form-urlencoded": {
                                "schema": {"$ref": "#/components/schemas/CurrentLocationForm"},
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Position gespeichert; Weiterleitungs-Queue wie bei `/api/gps`",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/GpsOkResponse"}
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/BadRequestJson"},
                        "401": {"$ref": "#/components/responses/UnauthorizedJson"},
                    },
                }
            },
            "/api/stream/positions": {
                "get": {
                    "tags": ["Daten"],
                    "summary": "Server-Sent Events: neue Positionen",
                    "description": (
                        "Öffnet einen `text/event-stream`-Kanal. Nach jeder gespeicherten Position "
                        "wird ein `data:`-Frame mit JSON gesendet: `{\"type\":\"position\",\"position\":{...}}` "
                        "(`position` wie Einträge in `/api/positions`). "
                        "Kommentarzeichen (`:`) dienen als Verbindungs-Keepalive."
                    ),
                    "operationId": "streamPositions",
                    "responses": {
                        "200": {
                            "description": "SSE-Datenstrom (unbegrenzt bis Client trennt)",
                            "content": {"text/event-stream": {"schema": {"type": "string", "format": "binary"}}},
                        }
                    },
                }
            },
            "/api/positions": {
                "get": {
                    "tags": ["Daten"],
                    "summary": "Gespeicherte Positionen abfragen",
                    "operationId": "getPositions",
                    "parameters": [
                        {
                            "name": "device",
                            "in": "query",
                            "schema": {"type": "string"},
                            "description": (
                                "Optionaler Gerätefilter nach Anzeigename. "
                                "Mehrfach möglich (`?device=A&device=B`) oder als CSV (`?device=A,B`)."
                            ),
                        },
                        {
                            "name": "from",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "format": "date-time"},
                            "description": "Untergrenze (ISO-8601)",
                        },
                        {
                            "name": "to",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "format": "date-time"},
                            "description": "Obergrenze (ISO-8601)",
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 500},
                            "description": "Maximale Anzahl zurückgegebener Positionen",
                        },
                        {
                            "name": "offset",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 0, "default": 0},
                            "description": "Anzahl passender Positionen, die übersprungen werden",
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Positionsliste",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/PositionsResponse"}
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/BadRequestJson"},
                    },
                }
            },
            "/api/gps/recent": {
                "get": {
                    "tags": ["Daten"],
                    "summary": "Letzte rohen GPS-Requests (Diagnose)",
                    "operationId": "getRecentGpsRequests",
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Letzte empfangene Requests mit Metadaten",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RecentGpsResponse"}
                                }
                            },
                        }
                    },
                }
            },
        },
        "components": {
            "securitySchemes": {
                "bearerApiKey": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "API-Key",
                    "description": "Geräte-API-Key wie in der UI angezeigt.",
                }
            },
            "parameters": {
                "device_id": {
                    "name": "device_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                },
                "forward_id": {
                    "name": "forward_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                },
            },
            "responses": {
                "BadRequestJson": {
                    "description": "Validierungsfehler",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                        }
                    },
                },
                "NotFoundJson": {
                    "description": "Ressource nicht gefunden",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                        }
                    },
                },
                "UnauthorizedJson": {
                    "description": "Fehlender oder ungültiger Bearer-Token",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                        }
                    },
                },
            },
            "schemas": {
                "ErrorResponse": {
                    "type": "object",
                    "properties": {"error": {"type": "string"}},
                    "required": ["error"],
                },
                "OkResponse": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
                "HealthResponse": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "service": {"type": "string", "example": "gpslogger"},
                    },
                },
                "RestartAcceptedResponse": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean", "example": True},
                        "message": {"type": "string"},
                    },
                    "required": ["ok"],
                },
                "ThemesResponse": {
                    "type": "object",
                    "properties": {"themes": {"type": "array", "items": {"type": "string"}}},
                    "required": ["themes"],
                },
                "DevicesListResponse": {
                    "type": "object",
                    "properties": {"devices": {"type": "array", "items": {"type": "object"}}},
                    "required": ["devices"],
                },
                "DeviceStatusesResponse": {
                    "type": "object",
                    "properties": {"statuses": {"type": "object", "additionalProperties": True}},
                    "required": ["statuses"],
                },
                "DeviceDraftResponse": {
                    "type": "object",
                    "description": "Entwurf; enthält u. a. draft_token und temporären Key",
                    "additionalProperties": True,
                },
                "DeviceCreatedResponse": {
                    "type": "object",
                    "properties": {"device": {"type": "object", "additionalProperties": True}},
                    "required": ["device"],
                },
                "DeviceSingleResponse": {
                    "type": "object",
                    "properties": {"device": {"type": "object", "additionalProperties": True}},
                    "required": ["device"],
                },
                "ForwardingWriteBody": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url": {"type": "string", "format": "uri"},
                        "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                        "enabled": {"type": "boolean", "default": True},
                        "incoming_headers_only": {
                            "type": "boolean",
                            "default": True,
                            "description": (
                                "Wenn true: ausschließlich die sanitisierten Header der eingehenden Geräte-Anfrage. "
                                "Wenn false: nur die unter `headers` angegebenen Header plus Content-Type vom Original."
                            ),
                        },
                        "forward_body_from_source": {
                            "type": "boolean",
                            "default": True,
                            "description": (
                                "Wenn true: Roh-Body der Geräte-Anfrage unverändert als POST-Daten weiterleiten. "
                                "Wenn false: leeren Body senden."
                            ),
                        },
                    },
                    "required": ["name", "url"],
                },
                "ForwardingSingleResponse": {
                    "type": "object",
                    "properties": {"forwarding": {"type": "object", "additionalProperties": True}},
                    "required": ["forwarding"],
                },
                "ForwardingErrorsResponse": {
                    "type": "object",
                    "properties": {"errors": {"type": "array", "items": {"type": "string"}}},
                    "required": ["errors"],
                },
                "SettingsResponse": {
                    "type": "object",
                    "properties": {"settings": {"type": "object", "additionalProperties": True}},
                    "required": ["settings"],
                },
                "GpsOkResponse": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                "CurrentLocationForm": {
                    "type": "object",
                    "required": ["latitude", "longitude"],
                    "properties": {
                        "latitude": {"type": "string", "description": "Breitengrad (Dezimal)"},
                        "longitude": {"type": "string", "description": "Längengrad (Dezimal)"},
                        "device": {"type": "string", "description": "Geräte-/Client-Kennung laut Werkbank"},
                        "accuracy": {"type": "string", "description": "Genauigkeit (m), nicht negativ wenn numerisch"},
                        "battery": {
                            "type": "string",
                            "description": "Akku (z. B. 0–100 oder freier Text, z. B. charging)",
                        },
                        "speed": {"type": "string", "description": "Geschwindigkeit (beliebige Einheit, numerisch)"},
                        "direction": {"type": "string", "description": "Richtung / Heading in Grad, numerisch"},
                        "altitude": {"type": "string", "description": "Höhe, numerisch"},
                        "provider": {"type": "string", "description": "Standortdienst / GNSS-Quelle"},
                        "activity": {"type": "string", "description": "Aktivität (z. B. still, walking)"},
                        "time": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Messzeitpunkt ISO-8601; optional, sonst Serverzeit",
                        },
                        "timestamp": {
                            "type": "string",
                            "description": "Alias für time (ISO-8601), falls der Client nicht `time` nutzt",
                        },
                    },
                },
                "PositionsResponse": {
                    "type": "object",
                    "properties": {
                        "positions": {"type": "array", "items": {"type": "object"}},
                        "pagination": {
                            "type": "object",
                            "properties": {
                                "limit": {"type": "integer"},
                                "offset": {"type": "integer"},
                                "returned": {"type": "integer"},
                                "has_more": {"type": "boolean"},
                            },
                            "required": ["limit", "offset", "returned", "has_more"],
                        },
                        "filters": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string", "format": "date-time"},
                                "to": {"type": "string", "format": "date-time"},
                                "device": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["from", "to", "device"],
                        },
                    },
                    "required": ["positions", "pagination", "filters"],
                },
                "RecentGpsResponse": {
                    "type": "object",
                    "properties": {"requests": {"type": "array", "items": {"type": "object"}}},
                    "required": ["requests"],
                },
                "SystemStatusResponse": {
                    "type": "object",
                    "properties": {"status": {"type": "object", "additionalProperties": True}},
                    "required": ["status"],
                },
                "StorageStatusResponse": {
                    "type": "object",
                    "properties": {
                        "overview": {
                            "type": "object",
                            "additionalProperties": True,
                            "description": "Pfadstatus, Geräteliste mit Dateimetadaten und Zählern",
                        }
                    },
                    "required": ["overview"],
                },
            },
        },
    }
