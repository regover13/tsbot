# CLAUDE.md – TSBot Projektkontext

## Projektübersicht

**TSBot** ist ein TeamSpeak-Aufnahme- und Protokoll-Generator.
Er nimmt TS3-Sitzungen auf, transkribiert sie mit faster-whisper und erstellt per Claude API ein Word-Protokoll.

Zwei Betriebsmodi:
- **Windows (lokal):** VB-Cable + ffmpeg, manuelle Steuerung per `.bat`-Dateien
- **Linux-Server (Bot):** PulseAudio Null-Sink, automatisch via FastAPI Web-Interface

Live unter: `https://tsbot.devprops.de`

---

## Projektstruktur

```
core/                    # faster-whisper-Transkription + Claude-Protokollerstellung
bot/                     # TS3 ServerQuery + ClientQuery, Audio-Aufnahme, Session-Zustandsmaschine
api/                     # FastAPI App, HTTP Basic Auth, Web-Dashboard
api/routes/              # session, status, files, channels, agenda, settings
api/static/index.html    # Web-Dashboard (Single Page, 3 Tabs)
scripts/                 # Shell-Skripte: Setup, PulseAudio
systemd/                 # Service-Dateien: tsbot-api, tsbot-pulseaudio
config/                  # config.example.env (Template; config.env ist in .gitignore)
data/                    # agenda.txt + sessions/YYYYMMDD_HHMMSS/
nginx/                   # nginx-Reverse-Proxy-Konfiguration
```

---

## Technologie-Stack

- **Python 3.11**, FastAPI, Uvicorn
- **faster-whisper** (CTranslate2-Backend, 3–5× schneller als openai-whisper) für Transkription
- **Claude API** (Anthropic) für Protokollerstellung – Modell aus `config.env`
- **TS3 ServerQuery** (Port 10011, `ts3`-Library) für Teilnehmer-Tracking
- **TS3 ClientQuery** (Port 25639, raw socket) für Sprecher-Tracking + Bot-Steuerung
- **PulseAudio** Null-Sink + ffmpeg für headless Audio-Aufnahme (Linux)
- **python-docx** für Word-Protokoll-Erzeugung
- **nginx** + **Let's Encrypt** als HTTPS Reverse Proxy

---

## Wichtige Konventionen

- `config/config.env` enthält Secrets – **niemals committen** (in `.gitignore`)
- Session-Zustände: `IDLE → RECORDING → TRANSCRIBING → GENERATING → DONE | ERROR`
- Session-Daten liegen unter `data/sessions/YYYYMMDD_HHMMSS/`
- Deployment über **Docker/Portainer** (kein systemd im Container)
- Image: `ghcr.io/regover13/tsbot:latest` (gebaut via GitHub Actions bei Push auf `master`)
- Compose-Stack auf Server: `/var/lib/docker/volumes/portainer_data/_data/compose/5/docker-compose.yml`
- Secrets als Umgebungsvariablen im Compose-Stack hinterlegt
- **GHCR Registry** muss in Portainer hinterlegt sein (Registries → GitHub → ghcr.io / regover13 / PAT mit `read:packages`), sonst schlägt Deploy still fehl
- **CI/CD:** GitHub Actions baut Image → pushed zu GHCR → ruft Portainer API direkt auf (PUT /api/stacks/5) mit `pullImage:true`. Kein Webhook (Portainer-Webhooks setzen Docker Swarm voraus). Secrets: `PORTAINER_URL`, `PORTAINER_USER`, `PORTAINER_PASS`, `PORTAINER_STACK_ID`, `PORTAINER_ENDPOINT_ID`
- **`cap_add: [SYS_NICE]`** im docker-compose.yml nötig damit `chrt` im Container funktioniert
- **Vor jedem Push prüfen:** `GET /status` → nur bei `state == IDLE` pushen, sonst Transkription-Abbruch durch Container-Neustart

---

## Teilnehmer-Tracking (`bot/ts_query.py`)

- Tracking per TS3 **ServerQuery** (Port 10011) – nicht ClientQuery
- Nur Clients **im Aufnahme-Kanal** werden erfasst: `cid`-Filter in `clientlist()`, `ctid`-Filter in `notifycliententerview`
- `channel_id == 0` deaktiviert den Filter (alle Server-Clients), als Fallback für unkonfigurierte Setups
- Fallback-Poll: alle 30 s wird die Clientliste neu eingelesen → erfasst Teilnehmer, die vor Bot-Start im Kanal waren
- Beim Kanalwechsel (`switch_channel`): Teilnehmer des alten Kanals gespeichert, Liste geleert, `_channel_id` aktualisiert → Event-Loop filtert sofort auf neuen Kanal
- Nickname-Parsing: FRS-Muster `FRS(\d+[A-Z]?)`, diverse Trennzeichen und Klammer-Suffixe werden korrekt geparst

## Sprecher-Tracking (`bot/ts_client_control.py`)

- Verbindung per raw socket auf **ClientQuery Port 25639**
- Überwacht `notifytalkstatuschange` Events → schreibt `talk_log.json` (Sprecher + Start/Ende in Sekunden relativ zum Aufnahmestart)
- Keepalive: alle 60 s `whoami` → verhindert ClientQuery-Timeout (600 s)
- Weitere Events: `notifyclientmoved` (Kanalwechsel), `notifyclientkicked` / `notifyconnectstatuschange status=disconnected` → Session automatisch stoppen
- API-Key-Pfad: `/home/tsbot/.ts3client/clientquery.ini`

## Audio-Aufnahme (`bot/audio_capture.py`)

- Segmentierte Aufnahme: `audio_001.mp3`, `audio_002.mp3`, … (Standard: **600 s / 10 Min** pro Segment)
- Overlap: **1,5 s** zwischen Segmenten → kein Audio-Gap bei Rotation
- Format: **16 kHz mono, 32 kbps MP3** (Whisper-optimiert)
- Freeze-Watchdog: prüft alle **30 s**, Freeze nach **2× gleicher Dateigröße** (60 s Fenster) → automatische Rotation
- Schonfrist: **90 s** nach Segment-Start keine Freeze-Prüfung (ffmpeg startet bei 0 Bytes)
- ffmpeg mit `chrt -f 50` (SCHED_FIFO Echtzeit-Scheduling) + Fallback ohne chrt wenn `CAP_SYS_NICE` fehlt
- `setcap cap_sys_nice+eip /usr/bin/chrt` im Dockerfile → wirkt auch als non-root User (UID 1000)
- `-fflags +flush_packets` → ffmpeg schreibt nach jedem Frame auf Disk → Watchdog sieht echten Stand
- PulseAudio Null-Sink `tsbot_sink` muss vor Aufnahme laufen (`scripts/start_pulseaudio.sh`)

## Transkription (`core/transkribieren.py`)

- **faster-whisper** (CTranslate2), Modell per `WHISPER_MODEL` konfigurierbar (default: `medium`)
- Auto-Erkennung GPU (float16) vs. CPU (int8) via `ctranslate2.get_cuda_device_count()`
- Modell wird gecacht (`_whisper_model_cache`) – nur einmal pro Prozess geladen
- Sprache: Deutsch (`language="de"`), VAD-Filter aktiv, kein Kontext über Segmentgrenzen
- Mehrere Audio-Dateien: Timestamps werden mit Offset zusammengeführt, 2 s Overlap-Toleranz
- Transkript-Format: `[MM:SS - MM:SS] Text` + `VOLLTEXT:` am Ende
- Sprecher-Annotation: Nachträgliche Annotation via `talk_log.json` (dominant speaker pro Zeitfenster)
- **Keine** pyannote.audio / Diarization – Speaker-Tracking läuft über ClientQuery-Events

## Protokollerstellung (`core/protokoll_erstellen.py`)

- Claude-Modell: aus `CLAUDE_MODEL` Env-Variable (Fallback: `claude-sonnet-4-5-20250929`)
- Max Tokens: 8192, Temperature: 0.3
- Prompt enthält: Datum, Teilnehmer-Block, Agenda, annotiertes Transkript, Kanalwechsel-Events, Extra-Instruktionen
- Claude gibt strukturiertes JSON zurück: `agenda_punkte[]` mit `zusammenfassung`, `details[]`, `beschluesse[]`, `zeitraum`
- Word-Dokument: Inhaltsverzeichnis (Word TOC-Feld), Metadaten-Tabelle, Teilnehmertabelle, Kanalwechsel-Hinweis, Agenda-Struktur, Protokoll-Abschnitte
- Kanalwechsel im Protokoll: Bullet-Liste vor dem TOC + Zeitangabe (`14:32 Uhr: Kanal A → Kanal B`)
- Windows-Modus: Teilnehmer per Claude Vision aus TS3-Screenshots (`.png` im Skript-Ordner)

---

## API-Endpoints

| Endpoint | Methode | Beschreibung |
|---|---|---|
| `/session/start` | POST | Aufnahme starten (`thema`, `agenda`, `extra_instruktionen`, `channel_id`) |
| `/session/stop` | POST | Aufnahme stoppen + Pipeline starten |
| `/session/meta` | PATCH | Thema/Agenda/Prompt während laufender Aufnahme ändern |
| `/session/channel` | POST | TS3-Kanal wechseln während Aufnahme |
| `/status` | GET | Zustand inkl. Segment-Info, `freeze_warning`, Hintergrund-Pipelines |
| `/protocols` | GET | Liste aller Sessions mit Dateien |
| `/protocols/{id}/{file}` | GET | Download (`.docx`, `.txt`, `.json`, `.mp3`) |
| `/protocols/{id}` | DELETE | Session-Verzeichnis löschen |
| `/protocols/{id}/regenerate` | POST | Protokoll aus bestehendem Transkript neu erstellen |
| `/protocols/{id}/regen-status` | GET | Status einer laufenden Regenerierung |
| `/protocols/{id}/retranscribe` | POST | Transkription aus Audio-Segmenten neu starten (inkl. Sprecher-Annotation) |
| `/protocols/{id}/retranscribe-status` | GET | Status einer laufenden Neu-Transkription |
| `/agenda` | GET / PUT | Server-Agenda laden / speichern |
| `/channels` | GET | TS3-Kanal-Liste (30 s Cache, `force=true` umgeht Cache) |
| `/settings/extra` | GET / PUT | Aktuelle Extra-Instruktionen laden / speichern |
| `/settings/extra/default` | GET / PUT | Standard-Vorlage für Extra-Instruktionen |

---

## Konfigurationsvariablen (config.env)

| Variable | Default | Beschreibung |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Claude API-Key (**Pflicht**) |
| `CLAUDE_MODEL` | `claude-sonnet-4-5-20250929` | Modell für Protokollerstellung |
| `TS_HOST` | `127.0.0.1` | TS3-Server IP |
| `TS_QUERY_PORT` | `10011` | ServerQuery Port |
| `TS_QUERY_USER` | `serveradmin` | ServerQuery Benutzer |
| `TS_QUERY_PASS` | – | ServerQuery-Passwort (**Pflicht**) |
| `TS_SERVER_ID` | `1` | Virtual Server ID |
| `TS_CHANNEL_ID` | `42` | Standard-Kanal für Aufnahme (0 = alle) |
| `TS_PORT` | `9987` | TS3-Client-Port (nur für Anzeige in Web-UI) |
| `WHISPER_MODEL` | `medium` | `small` / `medium` / `large` |
| `PULSE_SINK` | `tsbot_sink` | PulseAudio Null-Sink Name |
| `DATA_DIR` | `/opt/tsbot/data` | Sessions-Verzeichnis |
| `AGENDA_PATH` | `/opt/tsbot/data/agenda.txt` | Pfad zur Server-Agenda |
| `API_PORT` | `8080` | Web-UI Port |
| `API_USER` | `admin` | Web-UI Benutzername |
| `API_SECRET` | – | Web-UI Passwort (**Pflicht**, ändern!) |

---

## Session-Daten (pro Session)

```
sessions/YYYYMMDD_HHMMSS/
├── meta.json                    # Thema, Agenda, Channel-Events, Timestamps
├── agenda.txt                   # Agenda-Snapshot beim Start
├── audio_001.mp3                # Audio-Segmente
├── audio_002.mp3
├── talk_log.json                # Sprecher-Events {clid, name, start_sec, end_sec}
├── participants.json            # Alle Teilnehmer [{name, frs, joined_at}]
├── participants_by_channel.json # Teilnehmer nach Kanal gruppiert
├── audio_transkript_YYYYMMDDHHMM.txt  # Annotiertes Transkript
└── Protokoll_YYYYMMDDHHMM.docx # Fertiges Word-Protokoll
```

---

## Häufige Befehle

```bash
# Container-Status prüfen
docker ps | grep tsbot

# Live-Log
docker logs -f tsbot

# API lokal testen (HTTPS über nginx)
curl -sk -u admin:PASSWORT https://tsbot.devprops.de/status

# Image manuell aktualisieren
docker pull ghcr.io/regover13/tsbot:latest
```

---

## Hinweise für Claude

- Ändere `config/config.env` nie direkt – nur `config.example.env` als Template
- Windows-`.bat`-Dateien sind nur für lokalen Betrieb, nicht für den Server relevant
- Der TS3-Client läuft headless unter Xvfb `:99` (kein physisches Display)
- Die FastAPI-App stellt das Web-Dashboard unter `/` aus `api/static/index.html` bereit
- **Kein** pyannote.audio / whisperx / USE_DIARIZATION / HF_TOKEN – Sprecher-Tracking läuft ausschließlich über ClientQuery
- Vor git push immer `/status` prüfen: nur bei `state == IDLE` pushen
