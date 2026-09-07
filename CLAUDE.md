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
- Compose-Datei auf dem Server: `/opt/tsbot/docker-compose.yml` (bis 2026-09-07 im Portainer-Volume)
- **API bindet auf `127.0.0.1:8080`** (nicht `0.0.0.0`) — via `command:` Override im Compose-Stack. Nur nginx kann von außen drauf zugreifen.
- Secrets als Umgebungsvariablen im Compose-Stack hinterlegt
- **CI/CD:** GitHub Actions baut das Image, pusht es nach GHCR und ruft per SSH `/opt/tsbot/deploy.sh` auf dem Server auf. Einziges Secret: `VPS_SSH_KEY`. Siehe „Deploy".
- **`cap_add: [SYS_NICE]`** im docker-compose.yml nötig damit `chrt` im Container funktioniert
- **Vor jedem Deploy prüfen:** `GET /status`. Entscheidend ist, dass nichts läuft — `state` in `IDLE`/`DONE`/`ERROR` **und** `background_pipelines` leer. Bei `RECORDING`, `TRANSCRIBING` oder `GENERATING` bricht der Container-Neustart die Verarbeitung ab. `DONE` ist der Normalzustand nach jedem Meeting und unbedenklich; der Neustart setzt dann nur die Statusanzeige auf `IDLE`, die Session-Dateien liegen auf der Platte.

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

## On-Demand TS3-Client (Host-Watcher, ab 2026-06)

Der TS3-Client (`ts3client_linux_amd64`) läuft **headless auf dem Host** (Xvfb `:99`, Software-OpenGL/llvmpipe ⇒ ~46 % CPU im Leerlauf). Der Bot läuft im **Container** (`network_mode: host`) und kann den Host-Prozess nicht direkt verwalten. Damit der Client nur **während Aufnahmen** läuft, gibt es einen Flag-Datei-Mechanismus über das geteilte `DATA_DIR`-Volume:

- **Bot** (`bot/session_manager.py`): schreibt bei Session-Start `DATA_DIR/.ts3client.request` = `up` (vor `connect()`), wartet via `_await_clientquery()` (max. 30 s) bis ClientQuery auf `127.0.0.1:25639` bereit ist; bei Session-Stop = `down`. Readiness-Check: `clientquery_ready()` in `bot/ts_client_control.py`.
- **Host** (systemd): `tsbot-ts3client.path` überwacht die Flag-Datei (inotify, funktioniert über den Bind-Mount) → triggert `tsbot-ts3client-apply.service` (root) → `/usr/local/sbin/tsbot-ts3client-apply.sh` → `systemctl start|stop tsbot-ts3client.service`.
- **Client-Services** (User `tsbot`): `tsbot-ts3client.service` (`dbus-run-session -- ts3client_runscript.sh`, braucht `XDG_RUNTIME_DIR=/run/user/1000` + eigene D-Bus-Session, sonst Crash „mutex lock failed: Invalid argument"; `ExecStartPre` wartet per `xdpyinfo` auf Display-Bereitschaft) zieht via `Requires=` `tsbot-xvfb.service` hoch (`PartOf=` ⇒ stoppt mit). `tsbot-pulseaudio.service` bleibt wie gehabt.
- **Manuell:** `systemctl start|stop tsbot-ts3client.service` (als root). Kein 24/7-Betrieb mehr nötig.
- **Folge:** Session-Start dauert ~15–20 s länger (Client-Hochlauf), spart aber ~46 % CPU zwischen Aufnahmen.

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
- **Provider:** umschaltbar per Toggle im Dashboard (Aufnahme-Tab) oder via `WHISPER_PROVIDER` Env-Var. Gespeichert in `/opt/tsbot/data/whisper_provider.json` (hat Vorrang vor Env-Var, kein Container-Restart nötig)
- Provider `local`: faster-whisper, kostenlos; Provider `openai`: OpenAI Whisper API (~0,37 €/h Audio, Sekunden statt Minuten)
- CPU-Optimierungen (nur `local`): `beam_size=1` (Greedy Decoding), `cpu_threads=6`, `word_timestamps=False`
- Sprache: Deutsch (`language="de"`), VAD-Filter aktiv, kein Kontext über Segmentgrenzen
- Mehrere Audio-Dateien: Timestamps werden mit Offset zusammengeführt, 2 s Overlap-Toleranz
- Transkript-Format: `[MM:SS - MM:SS] Text` + `VOLLTEXT:` am Ende
- Sprecher-Annotation: Nachträgliche Annotation via `talk_log.json` (dominant speaker pro Zeitfenster)
- **Keine** pyannote.audio / Diarization – Speaker-Tracking läuft über ClientQuery-Events
- `progress_callback(current, total, elapsed_sec, eta_sec)` optional – wird nach jedem fertigen Segment aufgerufen
- **Docker CPU Watchdog** (`/opt/docker-watchdog/watchdog.sh`): tsbot-Limit auf 5500% gesetzt – Whisper-Last löst keinen Auto-Restart aus

## Protokollerstellung (`core/protokoll_erstellen.py`)

- Claude-Modell: aus `CLAUDE_MODEL` Env-Variable (Fallback: `claude-sonnet-4-5-20250929`)
- Max Tokens: 8192, Temperature: 0.3
- Prompt enthält: Datum, Teilnehmer-Block, Agenda, annotiertes Transkript, Kanalwechsel-Events, Extra-Instruktionen
- Claude gibt strukturiertes JSON zurück: `agenda_punkte[]` mit `zusammenfassung`, `details[]`, `beschluesse[]`, `zeitraum`
- **Zwei-Pass** bei Transkripten >80.000 Zeichen: Pass 1 (`ki_segment_timestamps()`) lässt Claude die Zeitstempel der Agenda-Punkte bestimmen; Pass 2 verarbeitet jeden Punkt mit fokussiertem Transkript-Ausschnitt via `_schneide_transkript(transkript, start_ts, end_ts, puffer_min=2)` — spart Tokens, ermöglicht lange Meetings ohne Kürzung
- Timestamp-Regex in `lese_transkript()` und beiden Sprecher-Annotation-Funktionen: `\d+` (nicht `\d{2}`) — Meetings >99 Minuten werden vollständig verarbeitet
- Word-Dokument: Inhaltsverzeichnis (Word TOC-Feld), Metadaten-Tabelle, Teilnehmertabelle, Kanalwechsel-Hinweis, Agenda-Struktur, Protokoll-Abschnitte
- Kanalwechsel im Protokoll: Bullet-Liste vor dem TOC + Zeitangabe (`14:32 Uhr: Kanal A → Kanal B`)
- Windows-Modus: Teilnehmer per Claude Vision aus TS3-Screenshots (`.png` im Skript-Ordner)

---

## Anmeldung am Web-Interface

HTTP Basic Auth aus `API_USER` / `API_SECRET`. Geschützt sind alle Router — **und seit
2026-09-06 auch die Startseite `/`** (`dependencies=[Depends(require_auth)]` in `api/main.py`).

**Warum die Startseite mitgeschützt ist.** Sie war vorher frei abrufbar, die API-Endpunkte
darunter nicht. Damit erschien beim Öffnen nie ein Login-Dialog, und die Zugangsdaten lagen nur
dann im Auth-Cache des Browsers, wenn dort irgendwann einmal einer aufgetaucht war. War der
Cache leer, entstand eine Sackgasse: Die Seite lud, aber jeder `fetch()` auf `/status`,
`/protocols` oder `/agenda` lief in ein 401 — und **`fetch()` löst, anders als eine Navigation,
keinen Login-Dialog aus**. Die Oberfläche stand mit leeren Feldern und „Load failed" da, ohne
jeden Weg zur Anmeldung.

Am 2026-09-06 auf zwei Geräten aufgetreten (15:06 Edge/Windows, 19:25 EdgiOS), bei unverändertem
Code und Image. Im Log steht das Muster unmittelbar nacheinander:

```
"GET /"        200 OK     ← Seite lädt
"GET /status"  401        ← API verweigert
```

**Das Frontend enthält bewusst keine Auth-Logik.** `api()` in `index.html` setzt keinen
`Authorization`-Header, und das ist richtig so: Den hängt der Browser selbst an, sobald er die
Zugangsdaten einmal hat. Wer dort einen eigenen Anmeldeweg einbaut, löst ein Problem, das der
Browser bereits löst — ein Versuch am 2026-09-06, `fetch()` durch `XMLHttpRequest` zu ersetzen,
hätte zusätzlich alle schreibenden Aufrufe zerstört (doppeltes `JSON.stringify`, weil die
Aufrufer den Body bereits serialisiert übergeben).

Gegenprobe nach jeder Änderung an der Anmeldung:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/                    # 401 erwartet
curl -s -o /dev/null -u admin:PASSWORT -w '%{http_code}\n' http://127.0.0.1:8080/  # 200 erwartet
```

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
| `/settings/whisper-provider` | GET / PUT | Aktiven Whisper-Provider laden / speichern (`local` oder `openai`) |
| `/protocols/{id}/retranscribe-status` | GET | Status: `{status, current_segment, total_segments, eta_sec}` — ETA initial aus Dateigröße, danach aus Ist-Geschwindigkeit |
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
| `WHISPER_PROVIDER` | `local` | `local` oder `openai` — Fallback wenn keine `whisper_provider.json` existiert |
| `WHISPER_MODEL` | `medium` | `small` / `medium` / `large` (nur bei `WHISPER_PROVIDER=local`) |
| `OPENAI_API_KEY` | – | Nur bei `WHISPER_PROVIDER=openai` (**Pflicht** dann) |
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
docker logs -f tsbot-tsbot-api-1

# API lokal testen (HTTPS über nginx)
curl -sk -u admin:PASSWORT https://tsbot.devprops.de/status

# Welcher Stand läuft gerade?
docker inspect tsbot-tsbot-api-1 -f '{{.Config.Image}}'
```

Ein `docker pull` allein aktualisiert **nichts** — der Container läuft weiter auf seinem
alten Tag. Zum Ausrollen siehe „Deploy" unten.

---

## Deploy

Push auf `master` → GitHub Actions baut das Image, pusht es nach GHCR und ruft per SSH
`/opt/tsbot/deploy.sh` auf. Das Skript prüft den Sitzungszustand, zieht das Image, trägt den
Tag in `/opt/tsbot/docker-compose.yml` ein und startet den Stack neu.

**Der Zugang ist zweifach eingeschnürt:**

- Der Schlüssel `tsbot-deploy` steht in `/root/.ssh/authorized_keys` mit
  `restrict,command="/opt/tsbot/deploy.sh"` — er kann nichts anderes ausführen. Der Commit-SHA
  kommt als `SSH_ORIGINAL_COMMAND` an und wird gegen `^[0-9a-f]{40}$` geprüft, bevor er in
  irgendeinen Befehl gerät.
- Das GHCR-Token erzeugt GitHub pro Lauf neu und reicht es über **stdin** herein. Auf dem
  Server bleibt keines zurück (`docker logout` im `trap`). Gegenprobe:
  `sudo grep ghcr.io /root/.docker/config.json` darf nichts finden.

**Das Skript bricht ab, wenn eine Sitzung läuft** (`RECORDING`, `TRANSCRIBING`, `GENERATING`) —
ein Deploy würde die Verarbeitung zerreißen. `IDLE` und `DONE` sind unbedenklich.

### Warum nicht mehr über Portainer

Bis 2026-09-07 spielte der Workflow den Stack über die Portainer-API ein. Portainer zieht das
Image dabei selbst und braucht dafür **eigene, dauerhaft hinterlegte** GHCR-Zugangsdaten (ein PAT
in seiner Datenbank). Der lief ab, und der Deploy scheiterte ab dem **2026-08-19** bei jedem Lauf
mit `error from registry: denied` — unbemerkt, weil zwischen dem 19.08. und dem 06.09. niemand
gepusht hat. Der laufende Container blieb dabei wochenlang auf altem Stand, während die Builds
grün aussahen.

Der Kern des Problems war **ein dauerhaftes Geheimnis an einem Ort, den niemand ansieht**:
weder im Repo noch in den GitHub-Secrets, sondern in Portainers interner Datenbank, ohne
vermerktes Ablaufdatum. Der SSH-Weg hat kein solches Geheimnis — er benutzt das Einwegtoken des
Laufs. Damit folgt TSBot demselben Muster wie `hermes`, `garmin-connect-mcp` und `feniska-esphome`,
deren Deploys durchgehend grün sind.

**Ein grüner Build hieß früher nicht, dass etwas ausgerollt wurde.** Diese Gegenprobe bleibt
trotzdem nützlich:

```bash
docker inspect tsbot-tsbot-api-1 -f '{{.Config.Image}}'   # muss den erwarteten Commit-SHA zeigen
```

### Von Hand ausrollen

```bash
echo "$GH_TOKEN" | sudo env SSH_ORIGINAL_COMMAND=<40-stelliger-sha> /opt/tsbot/deploy.sh
```

Derselbe Weg, den auch GitHub geht — nur ohne SSH davor.

---

## Hinweise für Claude

- Ändere `config/config.env` nie direkt – nur `config.example.env` als Template
- Windows-`.bat`-Dateien sind nur für lokalen Betrieb, nicht für den Server relevant
- Der TS3-Client läuft headless unter Xvfb `:99` (kein physisches Display)
- Die FastAPI-App stellt das Web-Dashboard unter `/` aus `api/static/index.html` bereit
- **„docx neu erstellen"** prüft ob Transkript vorhanden ist; fehlt es, erscheint eine Warnmeldung mit „Transkription starten"-Button
- Während Neu-Transkription: Button zeigt „⏳ Transkribiert..." + Fortschritt „Segment X/Y · noch ~N min" (polling alle 5 s)
- Nach Seitenreload: laufende Retranscriptions werden via `/retranscribe-status` wiederhergestellt
- **Kein** pyannote.audio / whisperx / USE_DIARIZATION / HF_TOKEN – Sprecher-Tracking läuft ausschließlich über ClientQuery
- Vor git push immer `/status` prüfen: nur bei `state == IDLE` pushen
