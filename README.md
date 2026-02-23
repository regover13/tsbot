# TSBot – TeamSpeak Aufnahme & Protokoll-Generator

Automatische Transkription und Protokollerstellung von TeamSpeak-Sitzungen.
Zwei Betriebsmodi:

| Modus | Aufnahme | Teilnehmer | Steuerung |
|-------|----------|------------|-----------|
| **Windows** (lokal) | VB-Cable + ffmpeg, manuell starten | Screenshot → Claude Vision | `.bat`-Dateien |
| **Linux-Server** (Bot) | PulseAudio Null-Sink, automatisch | TS3 ServerQuery API | Web-Interface |

---

## Inhaltsverzeichnis

1. [Windows-Setup (lokal)](#1-windows-setup-lokal)
2. [Linux-Server-Setup (Bot)](#2-linux-server-setup-bot)
3. [Konfiguration](#3-konfiguration)
4. [Optionale Sprechertrennung](#4-optionale-sprechertrennung-diarization)
5. [Web-Interface bedienen](#5-web-interface-bedienen)
6. [Projektstruktur](#6-projektstruktur)
7. [Zugriff und Sicherheit](#7-zugriff-und-sicherheit)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Windows-Setup (lokal)

### Voraussetzungen

```
Python 3.9+    winget install Python.Python.3
               (bei Installation: "Add Python to PATH" anhaken!)
ffmpeg         winget install ffmpeg
VB-Cable       https://vb-audio.com/Cable/  (kostenlos)
NVIDIA GPU     optional, beschleunigt Whisper erheblich
```

### Einrichtung (einmalig)

**1. `install.bat` als Administrator ausführen**
Erkennt automatisch NVIDIA GPU und installiert PyTorch mit CUDA oder CPU-Version.

**2. VB-Cable konfigurieren**
`Rechtsklick Lautsprecher → Soundeinstellungen → Weitere Soundeinstellungen`

- Tab **Wiedergabe**: „CABLE Input (VB-Audio Virtual Cable)" → Als Standardgerät
- Tab **Aufnahme**: „CABLE Output (VB-Audio Virtual Cable)" → Als Standardgerät
  → Eigenschaften → Abhören → „Dieses Gerät abhören" → Wiedergabe über: *dein Kopfhörer*

**3. `config.txt` anlegen**

```
cp config.example.txt config.txt
```

API-Key eintragen: `ANTHROPIC_API_KEY=sk-ant-...`
→ Holen unter: https://console.anthropic.com/settings/keys

**4. `agenda.txt` vor jeder Sitzung anpassen** (ein Punkt pro Zeile)

### Workflow pro Sitzung

```
1_aufnahme_starten.bat    → Aufnahme läuft, Q zum Stoppen
                            → aufnahme_YYYYMMDD_HHMM.mp3

[Screenshots machen]      → Alle PNGs in diesen Ordner legen
                            Claude Vision erkennt Teilnehmer automatisch

2_transkribieren.bat      → MP3 per Drag & Drop
                            → ..._transkript_YYYYMMDD_HHMM.txt

3_protokoll_erstellen.bat → Transkript per Drag & Drop, Thema eingeben
                            → Protokoll_YYYYMMDD_HHMM.docx
```

> **Hinweis:** Das Inhaltsverzeichnis im Word-Dokument nach dem Öffnen mit **F9** aktualisieren.

---

## 2. Linux-Server-Setup (Bot)

Getestet auf **Ubuntu 22.04 / 24.04 LTS**.
Voraussetzung: Root-Zugang, ca. 6 GB freier Speicher (für Python-Umgebung + Whisper-Modell).

### Schritt 1 – Als root einloggen und Repo klonen

```bash
ssh root@DEINE_SERVER_IP

git clone https://github.com/DEIN_USER/tsbot.git /opt/tsbot
cd /opt/tsbot
```

### Schritt 2 – Systempakete installieren

```bash
apt-get update
apt-get install -y \
    python3.11 python3.11-venv python3-pip \
    ffmpeg \
    pulseaudio pulseaudio-utils \
    xvfb x11vnc \
    wget curl git build-essential
```

### Schritt 3 – Dedicated User anlegen

```bash
useradd -m -s /bin/bash tsbot
loginctl enable-linger tsbot   # PulseAudio auch ohne aktive Session
```

### Schritt 4 – Verzeichnisse und Berechtigungen

```bash
mkdir -p /opt/tsbot/data/sessions /opt/tsbot/config /opt/tsbot/logs
chown -R tsbot:tsbot /opt/tsbot
```

### Schritt 5 – Python-Umgebung aufbauen

> **Hinweis:** `torch` (CPU-only) ist ~2,5 GB Download. Einmalig, danach gecacht.

```bash
sudo -u tsbot python3.11 -m venv /opt/tsbot/venv
sudo -u tsbot /opt/tsbot/venv/bin/pip install --upgrade pip

# CPU-only PyTorch + alle Abhängigkeiten
sudo -u tsbot /opt/tsbot/venv/bin/pip install \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r /opt/tsbot/requirements.txt
```

### Schritt 6 – Konfiguration anlegen

```bash
cp /opt/tsbot/config/config.example.env /opt/tsbot/config/config.env
nano /opt/tsbot/config/config.env
```

Mindestens diese Werte eintragen:

```ini
ANTHROPIC_API_KEY=sk-ant-...
TS_HOST=127.0.0.1          # oder IP des TS3-Servers
TS_QUERY_PASS=...           # ServerAdmin-Passwort (in ts3server.ini oder Startlog)
TS_CHANNEL_ID=42            # ID des Konferenz-Kanals
API_SECRET=sicheres_passwort
```

> **TS3 ServerQuery-Passwort finden:**
> Beim ersten Start des TS3-Servers wird es ins Log geschrieben:
> `grep "serveradmin" /path/to/ts3server.log`
> Oder in der `ts3server.ini`: `serveradmin_password=...`

### Schritt 7 – TeamSpeak 3 Linux Client installieren

```bash
# Als tsbot-User
sudo -u tsbot bash

cd ~
wget https://files.teamspeak-services.com/releases/client/3.6.2/TeamSpeak3-Client-linux_amd64-3.6.2.run
chmod +x TeamSpeak3-Client-linux_amd64-3.6.2.run
./TeamSpeak3-Client-linux_amd64-3.6.2.run -- --target ~/TeamSpeak3
```

**Einmalige Lizenz-Akzeptanz (muss einmalig mit GUI gemacht werden):**

```bash
# Terminal 1 – Xvfb + TS3 starten
export DISPLAY=:99
Xvfb :99 -screen 0 1024x768x24 &
sleep 1
x11vnc -display :99 -forever -nopw -localhost &
~/TeamSpeak3/ts3client_linux_amd64 &

# Terminal 2 – VNC-Tunnel auf deinem lokalen Rechner (nicht Server)
ssh -L 5900:localhost:5900 tsbot@DEINE_SERVER_IP
```

Dann mit einem VNC-Viewer auf `localhost:5900` verbinden (z.B. [RealVNC Viewer](https://www.realvnc.com/de/connect/download/viewer/), kostenlos).
Im TS3-Fenster den Lizenzdialog bestätigen → fertig. Danach läuft der Client headless.

### Schritt 8 – systemd Services installieren

```bash
# Zurück als root
exit

cp /opt/tsbot/systemd/tsbot-pulseaudio.service /etc/systemd/system/
cp /opt/tsbot/systemd/tsbot-api.service        /etc/systemd/system/

systemctl daemon-reload
systemctl enable tsbot-pulseaudio tsbot-api
systemctl start  tsbot-pulseaudio
systemctl start  tsbot-api
```

**Status prüfen:**

```bash
systemctl status tsbot-pulseaudio tsbot-api
journalctl -u tsbot-api -f      # Live-Log
```

### Schritt 9 – Erreichbarkeit testen

```bash
# Auf dem Server:
curl -u admin:DEIN_API_SECRET http://localhost:8080/status
# Erwartete Antwort: {"state":"IDLE","session_id":null,...}

# Aus dem Browser (wenn Port 8080 in der Firewall freigegeben):
http://DEINE_SERVER_IP:8080
```

**Firewall (falls ufw aktiv):**

```bash
ufw allow 8080/tcp
```

> **Sicherheitshinweis:** Für den Produktionsbetrieb empfiehlt sich ein nginx-Reverse-Proxy mit HTTPS (Let's Encrypt). Ohne HTTPS wird das Basic-Auth-Passwort im Klartext übertragen.

---

## 3. Konfiguration

Alle Einstellungen in `/opt/tsbot/config/config.env` (Linux) bzw. `config.txt` (Windows).

| Variable | Beschreibung | Beispiel |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Claude API-Key | `sk-ant-...` |
| `CLAUDE_MODEL` | Claude-Modell | `claude-sonnet-4-5-20250929` |
| `TS_HOST` | TS3-Server IP | `127.0.0.1` |
| `TS_QUERY_PORT` | ServerQuery Port | `10011` |
| `TS_QUERY_USER` | ServerQuery User | `serveradmin` |
| `TS_QUERY_PASS` | ServerQuery Passwort | `geheim` |
| `TS_SERVER_ID` | Virtual Server ID | `1` |
| `TS_CHANNEL_ID` | Kanal-ID für Aufnahme | `42` |
| `WHISPER_MODEL` | Modellgröße | `medium` |
| `USE_DIARIZATION` | Sprechertrennung | `false` |
| `HF_TOKEN` | HuggingFace Token | `hf_...` |
| `API_PORT` | Web-UI Port | `8080` |
| `API_USER` | Web-UI Benutzername | `admin` |
| `API_SECRET` | Web-UI Passwort | `geheim` |

**Whisper-Modelle nach Hardware:**

| Modell | Größe | CPU-Zeit/h Audio | Empfehlung |
|--------|-------|-----------------|------------|
| `small` | 460 MB | ~5 Min | Sehr schwache VPS |
| `medium` | 1,5 GB | ~10 Min | Standard-VPS (2–4 Kerne) |
| `large` | 2,9 GB | ~20 Min | Starker Server oder GPU |

---

## 4. Optionale Sprechertrennung (Diarization)

Jeder Sprecher bekommt ein Tag (`[SPRECHER_0]`, `[SPRECHER_1]`, …).
Claude versucht beim Protokollieren die Sprecher den Teilnehmern aus dem ServerQuery zuzuordnen.

**Einrichtung (einmalig):**

```bash
# 1. HuggingFace-Account erstellen: https://huggingface.co
# 2. Token generieren: https://huggingface.co/settings/tokens (Read-Rechte reichen)
# 3. Lizenzen akzeptieren (einmalig im Browser, mit dem HF-Account eingeloggt):
#    https://huggingface.co/pyannote/speaker-diarization-3.1
#    https://huggingface.co/pyannote/segmentation-3.0
# 4. whisperx installieren:
/opt/tsbot/venv/bin/pip install whisperx
# 5. In config.env eintragen:
USE_DIARIZATION=true
HF_TOKEN=hf_dein_token
```

**Mehraufwand:**
- +~30–50 % Rechenzeit gegenüber plain Whisper
- Beim ersten Start werden die pyannote-Modelle (~1 GB) heruntergeladen und gecacht

**Deaktivieren:**

```ini
USE_DIARIZATION=false
```

Plain Whisper läuft dann ohne HF-Token.

---

## 5. Web-Interface bedienen

Erreichbar unter `http://SERVER_IP:8080` (Login mit `API_USER` / `API_SECRET`).

### Tab „Aufnahme"

1. **Thema** eingeben (Pflichtfeld)
2. **TeamSpeak-Kanal** aus Dropdown wählen — der Bot tritt genau diesem Kanal bei.
   Das Dropdown lädt alle Kanäle live vom Server. Der zuletzt verwendete Kanal wird
   automatisch vorausgewählt (im Browser-LocalStorage gespeichert).
3. **Agenda** leer lassen = Server-Agenda wird verwendet; oder für diese Sitzung überschreiben
4. **Zusätzliche Instruktionen** optional — freier Text, der direkt an Claude angehängt wird
   Beispiele: *„Schreibe Beschlüsse besonders hervor."* / *„Ignoriere Small Talk."*
5. **▶ Aufnahme starten** → Bot verbindet sich mit TS3, tritt dem Kanal bei,
   Aufnahme und Teilnehmer-Tracking starten automatisch
6. **Kanalwechsel** — über das Dropdown während der Aufnahme möglich. Der Bot wechselt
   den Kanal, Teilnehmer-Tracking wird umgeschaltet. Jeder Kanal bekommt eine eigene
   Teilnehmerliste im Protokoll.
7. **■ Aufnahme stoppen** → Bot verlässt den Kanal, MP3 wird gespeichert,
   Transkription + Protokollerstellung laufen im Hintergrund

Der Status-Badge zeigt den Fortschritt:
`IDLE` → `RECORDING` → `TRANSCRIBING` → `GENERATING` → `DONE`

### Tab „Agenda"

Dauerhafte Server-Agenda bearbeiten (wird für alle zukünftigen Sitzungen verwendet):
- Punkte per Drag & Drop sortieren
- Einzelne Punkte hinzufügen / entfernen
- **💾 Agenda speichern** schreibt auf den Server

### Tab „Protokolle"

Liste aller abgeschlossenen Sitzungen mit Download-Links für:
- `Protokoll_YYYYMMDD_HHMM.docx` — Word-Protokoll
- `*_transkript_*.txt` — Volltranskript mit Zeitstempeln
- `audio.mp3` — Original-Aufnahme

Über den **🗑 Löschen**-Button wird eine komplette Session unwiderruflich entfernt
(Audio, Transkript, Protokoll und Metadaten).

---

## 6. Projektstruktur

```
/opt/tsbot/  (Linux-Server) bzw. tsbot/ (Windows-Repo)
├── core/
│   ├── transkribieren.py        Whisper-Transkription (plain + whisperx)
│   └── protokoll_erstellen.py  Protokoll-Generator (Claude API)
├── bot/
│   ├── ts_query.py             TS3 ServerQuery Teilnehmer-Tracking
│   ├── ts_client_control.py    TS3 Client verbinden/trennen per ClientQuery
│   ├── audio_capture.py        PulseAudio + ffmpeg Aufnahme
│   └── session_manager.py      Zustandsmaschine (IDLE→RECORDING→…→DONE)
├── api/
│   ├── main.py                 FastAPI App + HTTP Basic Auth
│   ├── routes/
│   │   ├── session.py          POST /session/start, /session/stop
│   │   ├── status.py           GET /status
│   │   ├── files.py            GET /protocols, Download, DELETE
│   │   ├── channels.py         GET /channels (TS3 Kanalliste)
│   │   └── agenda.py           GET/PUT /agenda
│   └── static/index.html       Web-Dashboard
├── scripts/
│   ├── setup_server.sh         Vollständige Server-Einrichtung
│   ├── start_pulseaudio.sh     PulseAudio-Null-Sink anlegen
│   └── start_ts_client.sh      TS3-Client headless starten
├── systemd/
│   ├── tsbot-api.service       systemd für FastAPI (Port 8080)
│   └── tsbot-pulseaudio.service systemd für PulseAudio + Xvfb + TS3-Client
├── config/
│   ├── config.env              Secrets (in .gitignore, nie committen!)
│   └── config.example.env      Template
├── data/
│   ├── agenda.txt              Server-Agenda
│   └── sessions/YYYYMMDD_HHMMSS/
│       ├── audio.mp3
│       ├── meta.json
│       ├── participants.json
│       ├── participants_by_channel.json
│       ├── *_transkript_*.txt
│       └── Protokoll_*.docx
├── requirements.txt            Python-Abhängigkeiten (Linux)
│
│   ── Windows-Dateien (nur lokal) ──────────────────────────
├── transkribieren.py           Windows-Wrapper → core/
├── protokoll_erstellen.py      Windows-Wrapper → core/
├── 1_aufnahme_starten.bat
├── 2_transkribieren.bat
├── 3_protokoll_erstellen.bat
├── install.bat
└── agenda.txt                  Windows-Agenda (lokal)
```

---

## 7. Zugriff und Sicherheit

### Web-Interface

Das Web-Interface (Port 8080) ist per **HTTP Basic Auth** geschützt
(Benutzername + Passwort aus `config.env`).

> **Hinweis:** HTTP Basic Auth überträgt Zugangsdaten Base64-kodiert, nicht verschlüsselt.
> Für internen Betrieb (LAN, VPN) ist das akzeptabel.
> Für öffentlichen Zugriff über das Internet: nginx mit HTTPS vorschalten (siehe unten).

### SSH-Zugang

Der Server-Zugang erfolgt ausschließlich per **SSH-Schlüssel** (kein Passwort-Login).

```bash
# SSH-Config (~/.ssh/config) auf dem lokalen Rechner:
Host tsbot
    HostName DEINE_SERVER_IP
    User tsbot
    IdentityFile ~/.ssh/tsbot_server

# Verbinden:
ssh tsbot
```

### Empfehlung: HTTPS + nginx (optional)

Für den Betrieb über das öffentliche Internet empfiehlt sich ein Reverse Proxy:

```bash
apt install nginx certbot python3-certbot-nginx

# /etc/nginx/sites-available/tsbot:
server {
    server_name tsbot.example.com;
    location / {
        proxy_pass http://127.0.0.1:8080;
    }
}

certbot --nginx -d tsbot.example.com
```

Damit läuft das Web-Interface unter `https://tsbot.example.com` mit gültigem SSL-Zertifikat,
und Port 8080 muss **nicht** mehr in der Firewall freigegeben sein.

### Empfehlung: WireGuard VPN (optional)

Alternativ zu HTTPS kann das Web-Interface nur über ein VPN zugänglich gemacht werden.
Dann ist Port 8080 nicht im Internet – nur Peers im VPN-Netz können zugreifen.

```bash
apt install wireguard
# wg0-Interface einrichten, Peer (lokalen Rechner) hinzufügen
# Web-Interface dann erreichbar unter http://10.x.x.x:8080
# Port 8080 aus der öffentlichen Firewall entfernen
```

---

## 8. Troubleshooting

### Services starten nach Neustart nicht

```bash
# Status beider Services prüfen:
systemctl status tsbot-pulseaudio tsbot-api

# Falls tsbot-api "dependency failed" zeigt:
# → tsbot-pulseaudio zuerst starten, dann api:
systemctl start tsbot-pulseaudio
systemctl start tsbot-api

# Live-Log beobachten:
journalctl -u tsbot-pulseaudio -u tsbot-api -f
```

### PulseAudio-Sink fehlt nach Neustart

```bash
systemctl restart tsbot-pulseaudio
# Prüfen ob Sinks und Null-Mic angelegt sind:
runuser -u tsbot -- env XDG_RUNTIME_DIR=/run/user/1000 pactl list sinks short
```

### TS3-Client startet nicht / kein Audio

```bash
# Prüfen ob Xvfb läuft (virtuelles Display):
pgrep Xvfb || Xvfb :99 -screen 0 1024x768x24 &

# Prüfen ob TS3-Client läuft:
pgrep -a ts3client

# ALSA → PulseAudio Routing prüfen:
cat /home/tsbot/.asoundrc   # muss pcm.!default { type asym ... } enthalten

# TS3-Client manuell starten (als root, da runuser root-Rechte braucht):
runuser -u tsbot -- env XDG_RUNTIME_DIR=/run/user/1000 DISPLAY=:99 \
    /home/tsbot/TeamSpeak3/ts3client_runscript.sh

# Log ansehen:
tail -f /home/tsbot/ts3client.log
journalctl -u tsbot-pulseaudio --since "5 min ago"
```

### ServerQuery-Verbindung schlägt fehl

```bash
# Test direkt per Telnet:
telnet DEINE_SERVER_IP 10011
# Erwartete Antwort: TS3
# Dann: login serveradmin PASSWORT
```

Häufige Ursachen:
- `TS_QUERY_PASS` falsch → im TS3-Server-Log nachschauen (`grep serveradmin`)
- ServerQuery-Port 10011 nicht erreichbar → Firewall oder TS3-Konfiguration prüfen
- `TS_CHANNEL_ID` falsch → Kanal-ID im TS3-Client unter „Erweitert" anzeigen lassen

### Whisper-Transkription sehr langsam

```ini
# In config.env kleineres Modell wählen:
WHISPER_MODEL=small
```

### Web-UI zeigt 401 Unauthorized

`API_USER` und `API_SECRET` in `config.env` prüfen. Browser-Cache leeren.

### API startet nicht

```bash
journalctl -u tsbot-api -n 50 --no-pager
# Häufig: config.env fehlt oder Python-Pakete nicht installiert
```

### Diarization-Fehler: „Access token is required"

HF_TOKEN in `config.env` fehlt oder ist ungültig. Lizenzen auf HuggingFace akzeptiert?
Prüfen: https://huggingface.co/pyannote/speaker-diarization-3.1

---

## Support

Bei Fragen und Fehlern: Fehlermeldung + `journalctl -u tsbot-api -n 100` in den Chat.
