# CLAUDE.md – TSBot Projektkontext

## Projektübersicht

**TSBot** ist ein TeamSpeak-Aufnahme- und Protokoll-Generator.
Er nimmt TS3-Sitzungen auf, transkribiert sie mit Whisper und erstellt per Claude API ein Word-Protokoll.

Zwei Betriebsmodi:
- **Windows (lokal):** VB-Cable + ffmpeg, manuelle Steuerung per `.bat`-Dateien
- **Linux-Server (Bot):** PulseAudio Null-Sink, automatisch via FastAPI Web-Interface

Live unter: `https://tsbot.devprops.de`

---

## Projektstruktur

```
core/                    # Whisper-Transkription + Claude-Protokollerstellung
bot/                     # TS3 ServerQuery, Audio-Aufnahme, Session-Zustandsmaschine
api/                     # FastAPI App, HTTP Basic Auth, Web-Dashboard
api/routes/              # session, status, files, channels, agenda
api/static/index.html    # Web-Dashboard (Single Page)
scripts/                 # Shell-Skripte: Setup, PulseAudio, Backup
systemd/                 # Service-Dateien: tsbot-api, tsbot-pulseaudio
config/                  # config.example.env (Template; config.env ist in .gitignore)
data/                    # agenda.txt + sessions/YYYYMMDD_HHMMSS/
nginx/                   # nginx-Reverse-Proxy-Konfiguration
```

---

## Technologie-Stack

- **Python 3.11**, FastAPI, Uvicorn
- **Whisper** (openai-whisper) / optional **whisperx** für Diarization
- **Claude API** (Anthropic) für Protokollerstellung – Modell aus `config.env`
- **TS3 ServerQuery** (telnet-basiert, Port 10011) für Teilnehmer-Tracking
- **TS3 ClientQuery** (Port 25639) für Bot-Steuerung
- **PulseAudio** Null-Sink + ffmpeg für headless Audio-Aufnahme (Linux)
- **python-docx** für Word-Protokoll-Erzeugung
- **nginx** + **Let's Encrypt** als HTTPS Reverse Proxy

---

## Wichtige Konventionen

- `config/config.env` enthält Secrets – **niemals committen** (in `.gitignore`)
- Session-Zustände: `IDLE → RECORDING → TRANSCRIBING → GENERATING → DONE`
- Session-Daten liegen unter `data/sessions/YYYYMMDD_HHMMSS/`
- Deployment über **Docker/Portainer** (kein `/opt/tsbot/`-Verzeichnis)
- Image: `ghcr.io/regover13/tsbot:latest` (gebaut via GitHub Actions bei Push auf `master`)
- Compose-Stack auf Server: `/var/lib/docker/volumes/portainer_data/_data/compose/5/docker-compose.yml`
- Secrets als Umgebungsvariablen im Compose-Stack hinterlegt

---

## Konfigurationsvariablen (config.env)

| Variable | Beschreibung |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API-Key |
| `CLAUDE_MODEL` | z.B. `claude-sonnet-4-5-20250929` |
| `TS_HOST` | TS3-Server IP |
| `TS_QUERY_PORT` | ServerQuery Port (Standard: `10011`) |
| `TS_QUERY_USER` | z.B. `serveradmin` |
| `TS_QUERY_PASS` | ServerQuery-Passwort |
| `TS_SERVER_ID` | Virtual Server ID (Standard: `1`) |
| `TS_CHANNEL_ID` | Standard-Kanal für Aufnahme |
| `WHISPER_MODEL` | `small` / `medium` / `large` |
| `API_PORT` | Web-UI Port (Standard: `8080`) |
| `API_USER` | Web-UI Benutzername |
| `API_SECRET` | Web-UI Passwort |

---

## Häufige Befehle

```bash
# Container-Status prüfen
docker ps | grep tsbot

# Live-Log
docker logs -f tsbot

# API lokal testen
curl -u admin:PASSWORT http://localhost:8080/status

# Image manuell aktualisieren
docker pull ghcr.io/regover13/tsbot:latest
```

---

## Hinweise für Claude

- Ändere `config/config.env` nie direkt – nur `config.example.env` als Template
- Windows-`.bat`-Dateien sind nur für lokalen Betrieb, nicht für den Server relevant
- Der TS3-Client läuft headless unter Xvfb `:99` (kein physisches Display)
- Die FastAPI-App stellt das Web-Dashboard unter `/` aus `api/static/index.html` bereit
- Diarization wurde entfernt (nur noch plain openai-whisper)
- `USE_DIARIZATION` und `HF_TOKEN` existieren nicht mehr im Code
