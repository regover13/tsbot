# TSBot – TeamSpeak Aufnahme & Protokoll-Generator

TSBot nimmt TeamSpeak-Sitzungen automatisch auf, transkribiert sie mit faster-whisper und
erstellt daraus per Claude API ein fertiges Word-Protokoll – inklusive Teilnehmerliste,
Agenda-Zuordnung, Sprecherzuweisung und Beschlüssen.

**Entwickelt für Communities, die regelmäßige TeamSpeak-Meetings abhalten und professionelle
Protokolle benötigen, ohne manuell mitschreiben zu müssen.**

## Features

- **Automatische Aufnahme** – PulseAudio Null-Sink (Linux) oder VB-Cable (Windows), headless im Hintergrund
- **Transkription mit [faster-whisper](https://github.com/SYSTRAN/faster-whisper)** (Systran) – 3–5× schneller als das OpenAI-Original, CPU-optimiert (int8), Modell `medium` als Standard; Modell-Gewichte stammen von OpenAI (Open Source), kein API-Call
- **Sprechererkennung** – Der Bot erfasst per TS3 ClientQuery Events (`notifytalkstatuschange`), wer wann spricht.
  Whisper-Segmente werden automatisch mit Sprechernamen annotiert: `[00:45 - 01:30] Max Mustermann: Text`.
  Die ClientQuery-Verbindung bleibt durch einen Keepalive (alle 60s) dauerhaft aktiv – auch bei langen Sitzungen ohne Aktivität.
- **KI-Protokollerstellung** – Claude ordnet Transkript-Abschnitte automatisch den Agenda-Punkten zu,
  schreibt Zusammenfassungen, erkennt Beschlüsse und gibt strukturierte Aufzählungen (Events, Termine,
  Programmpunkte) als Bullet-Liste aus
- **Teilnehmer-Tracking** – Automatisch per TS3 ServerQuery; pro Kanal separate Teilnehmerliste im Protokoll
- **Kanalwechsel** – Bot folgt dem Moderator in andere Kanäle, Kanalwechsel werden im Protokoll vermerkt
- **Zusätzliche Instruktionen** – Freier Text direkt an Claude, z.B. *„ICAO-Codes ausschreiben"* oder
  *„Sprecher-Labels sind autoritativ"* — wird **server-seitig** gespeichert und beim ersten Öffnen
  mit sinnvollen Verhaltensregeln vorbelegt (editierbar im Browser)
- **Protokoll neu erstellen** – Im Tab „Protokolle" kann jede Session per **🔄 Neu erstellen**-Button
  erneut durch Claude geschickt werden, ohne neue Aufnahme oder Transkription. Die Instruktionen
  lassen sich dabei sitzungsspezifisch anpassen; die geänderte Version überschreibt das alte `.docx`
- **Web-Interface** – FastAPI-Dashboard zum Starten/Stoppen, Kanalauswahl, Agenda-Verwaltung, Protokoll-Download
- **Docker + CI/CD** – Automatisches Deployment via GitHub Actions + Portainer bei jedem Push auf `master`
- **Word-Protokoll (.docx)** – Mit Inhaltsverzeichnis, Metadaten, Teilnehmertabelle, Zeitangaben und
  optionalem Volltranskript

## Datenschutz & Datensicherheit

### Wo bleiben die Daten?

Alle Aufnahmen, Transkripte und Protokolle liegen ausschließlich auf **deinem eigenen Server**
unter `/opt/tsbot/data/sessions/`. Es gibt keine automatische Weitergabe an Dritte –
mit einer Ausnahme (siehe unten).

### Was wird extern gesendet?

| Daten | Ziel | Hinweis |
|-------|------|---------|
| **Audio (.mp3)** | Nirgends – bleibt auf dem Server | faster-whisper läuft lokal |
| **Transkript (Text)** | Claude API (Anthropic) | Für die Protokollerstellung |
| **Screenshots** | Claude API (Anthropic) | Nur im Windows-Modus für Teilnehmererkennung |

Das Transkript (reiner Text, kein Audio) wird zur Protokollerstellung an die **Anthropic Claude API**
gesendet. Anthropic verarbeitet API-Anfragen gemäß ihrer
[Datenschutzrichtlinie](https://www.anthropic.com/privacy) und nutzt API-Daten nicht für das
Training ihrer Modelle. Für API-Kunden steht ein
[Data Processing Addendum (DPA)](https://www.anthropic.com/legal/data-processing-addendum)
mit Standard Contractual Clauses (SCCs) bereit – die rechtliche Grundlage für DSGVO-konforme
Übertragung in die USA. Eine EU-Datenhaltung bietet Anthropic standardmäßig nicht an.

### Zugriffssicherheit

- Web-Interface ist per **HTTP Basic Auth** geschützt (Zugangsdaten über HTTPS verschlüsselt)
- Produktionsbetrieb läuft ausschließlich über **HTTPS** (Let's Encrypt)
- **Brute-Force-Schutz** via nginx `limit_req`: max. 60 Requests/Minute pro IP (burst 30), bei Überschreitung HTTP 429
- Server-Zugang nur per **SSH-Key** (kein Passwort-Login)
- `config.env` mit allen Secrets ist in `.gitignore` und wird nie ins Repository committet

### Rechtlicher Hinweis

Das Aufnehmen von Gesprächen ohne Einwilligung der Teilnehmer kann in vielen Ländern
(z.B. Deutschland, §201 StGB) strafbar sein.
**Informiere alle Teilnehmer vor Beginn der Aufnahme.**

---

Zwei Betriebsmodi:

| Modus | Aufnahme | Teilnehmer | Steuerung |
|-------|----------|------------|-----------|
| **Windows** (lokal) | VB-Cable + ffmpeg, manuell starten | Screenshot → Claude Vision | `.bat`-Dateien |
| **Linux-Server** (Bot) | PulseAudio Null-Sink, automatisch | TS3 ServerQuery API | Web-Interface |

---

## Inhaltsverzeichnis

1. [Features](#features)
2. [Datenschutz & Datensicherheit](#datenschutz--datensicherheit)
3. [Windows-Setup (lokal)](#1-windows-setup-lokal)
4. [Linux-Server-Setup (Bot)](#2-linux-server-setup-bot)
5. [Docker-Deployment & CI/CD](#3-docker-deployment--cicd)
6. [Konfiguration](#4-konfiguration)
7. [Web-Interface bedienen](#5-web-interface-bedienen)
8. [Projektstruktur](#6-projektstruktur)
9. [Zugriff und Sicherheit](#7-zugriff-und-sicherheit)
10. [Backup nach OneDrive](#8-backup-nach-onedrive)
11. [Troubleshooting](#9-troubleshooting)

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

| Schritt | Pflicht? |
|---------|----------|
| 1 – Repo klonen | ✅ Pflicht |
| 2 – Systempakete | ✅ Pflicht |
| 3 – User anlegen | ✅ Pflicht |
| 4 – Verzeichnisse | ✅ Pflicht |
| 5 – Python venv | ⚪ Optional (nur für Tests ohne Docker) |
| 6 – config.env | ✅ Pflicht |
| 7 – TS3-Client + Lizenz | ✅ Pflicht (einmalig) |
| 8 – systemd (`tsbot-pulseaudio`) | ✅ Pflicht |
| 9 – Erreichbarkeit testen | ✅ Pflicht |

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
    python3.12 python3.12-venv python3-pip \
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

> **Hinweis:** Der Server-Betrieb läuft seit der Docker-Migration (Abschnitt 3) nicht mehr über eine lokale venv. Dieser Schritt ist nur noch für manuelle Tests ohne Docker relevant.

```bash
sudo -u tsbot python3.12 -m venv /opt/tsbot/venv
sudo -u tsbot /opt/tsbot/venv/bin/pip install --upgrade pip
sudo -u tsbot /opt/tsbot/venv/bin/pip install -r /opt/tsbot/requirements.txt
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

> **Hinweis:** Nach der Service-Installation läuft Xvfb `:99` bereits automatisch –
> nicht nochmal starten. Nur x11vnc muss für den VNC-Zugriff gestartet werden.

```bash
# Schritt 1 – x11vnc als tsbot-User starten (Xvfb läuft bereits via systemd)
runuser -u tsbot -- env DISPLAY=:99 x11vnc -display :99 -forever -nopw -localhost -bg

# Schritt 2 – SSH-Tunnel auf dem lokalen Rechner öffnen (neues Terminal)
ssh -L 5900:localhost:5900 tsbot@DEINE_SERVER_IP
```

Dann mit einem VNC-Viewer auf `localhost:5900` verbinden (z.B. [RealVNC Viewer](https://www.realvnc.com/de/connect/download/viewer/), kostenlos).
Im TS3-Fenster den Lizenzdialog bestätigen → fertig. Danach läuft der Client headless.

Nach der Lizenz-Akzeptanz x11vnc wieder beenden:
```bash
pkill x11vnc
```

### Schritt 8 – systemd Service installieren

> **Hinweis:** `tsbot-api.service` wird seit der Docker-Migration nicht mehr benötigt.
> Die FastAPI-App läuft im Docker-Container (verwaltet via Portainer, Abschnitt 3).
> Nur `tsbot-pulseaudio.service` muss auf dem Host laufen.

```bash
# Zurück als root
exit

cp /opt/tsbot/systemd/tsbot-pulseaudio.service /etc/systemd/system/

# start_pulseaudio.sh nach /usr/local/bin/ installieren (bleibt bei Cleanups erhalten):
cp /opt/tsbot/scripts/start_pulseaudio.sh /usr/local/bin/start_tsbot_pulseaudio.sh
chmod +x /usr/local/bin/start_tsbot_pulseaudio.sh

# Pfad in der Service-Datei anpassen:
sed -i 's|ExecStart=/opt/tsbot/scripts/start_pulseaudio.sh|ExecStart=/usr/local/bin/start_tsbot_pulseaudio.sh|' \
    /etc/systemd/system/tsbot-pulseaudio.service

systemctl daemon-reload
systemctl enable tsbot-pulseaudio
systemctl start  tsbot-pulseaudio
```

**Status prüfen:**

```bash
systemctl status tsbot-pulseaudio
journalctl -u tsbot-pulseaudio -f
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

## 3. Docker-Deployment & CI/CD

Der Server-Betrieb läuft via **Docker + GitHub Actions**.
Bei jedem Push auf `master` wird automatisch ein neues Image gebaut und deployed – kein manuelles `git pull` mehr.

| Schritt | Pflicht? |
|---------|----------|
| Portainer installieren + Stack einrichten | ✅ Pflicht |
| GHCR-Registry in Portainer konfigurieren | ✅ Pflicht |
| GitHub Actions CI/CD (Auto-Deploy) | ⚪ Optional – wer kein automatisches Deployment braucht, kann den Container manuell mit `docker compose up -d` starten |

### Architektur

```
git push master
  → GitHub Actions: Docker build + push → ghcr.io/regover13/tsbot:latest
  → Portainer Webhook: Pull neues Image + Container neu starten
```

**Was wird dockerisiert:** Nur die Python-App (FastAPI + Whisper + Claude).
**Nicht im Container:** PulseAudio, Xvfb und der TS3 Linux Client – diese laufen stabil als
systemd-Service (`tsbot-pulseaudio`) auf dem Host. Der Container bekommt Zugriff über:
- `network_mode: host` → localhost:25639 (ClientQuery) und localhost:10011 (ServerQuery) direkt erreichbar
- Volume-Mount für PulseAudio-Socket (`/run/user/1000/pulse`)
- Volume-Mount für TS3 ClientQuery-API-Key (`~/.ts3client`)

### Einmaliger Server-Setup

**1. tsbot-api systemd-Service stoppen (Docker übernimmt)**
```bash
systemctl stop tsbot-api
systemctl disable tsbot-api
```

**2. Portainer mit Config-Mount starten**

Portainer muss `/opt/tsbot/config` eingebunden haben, damit es `env_file` lesen kann:

```bash
docker run -d \
  --name portainer \
  --restart=always \
  -p 8000:8000 \
  -p 9443:9443 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  -v /opt/tsbot/config:/opt/tsbot/config \
  portainer/portainer-ce:latest
```

> Falls Portainer bereits läuft: `docker stop portainer && docker rm portainer` – dann obigen Befehl ausführen.

**3. Portainer: GHCR-Registry konfigurieren**

Portainer → Registries → Add registry → Custom registry:

| Feld | Wert |
|------|------|
| Name | `ghcr.io` |
| URL | `ghcr.io` |
| Username | `regover13` |
| Password | GitHub PAT mit `read:packages`-Scope |

**3. Portainer: Stack erstellen**

Stacks → Add stack → Repository:

| Feld | Wert |
|------|------|
| Repository URL | `https://github.com/regover13/tsbot` |
| Compose path | `docker-compose.yml` |
| Reference | `refs/heads/master` |
| Authentication | ✅ Username + GitHub PAT (Scope: `repo`) |

→ **Deploy the stack** → Webhook-URL aus Portainer kopieren

**4. Webhook-URL als GitHub Secret speichern**

GitHub → Repository → Settings → Secrets → Actions → New secret:
- Name: `PORTAINER_WEBHOOK_URL`
- Value: (URL aus Portainer)

Nach dem Setup wird bei jedem Push auf `master` automatisch:
1. Das Docker-Image gebaut und auf GHCR gepusht
2. Portainer benachrichtigt → Container wird mit dem neuen Image neu gestartet

### Lokaler Docker-Test

```bash
# Image bauen:
docker build -t tsbot:local .

# Container starten (ohne PulseAudio-Socket, nur zum API-Test):
docker run --rm -p 8080:8080 \
    --env-file config/config.env \
    -v $(pwd)/data:/opt/tsbot/data \
    tsbot:local

# Auf dem Server (mit allen Mounts):
docker compose up -d
docker compose logs -f
```

---

## 4. Konfiguration

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
| `API_PORT` | Web-UI Port | `8080` |
| `API_USER` | Web-UI Benutzername | `admin` |
| `API_SECRET` | Web-UI Passwort | `geheim` |

**faster-whisper-Modelle nach Hardware** (Systran-Implementierung, int8 auf CPU, Modell-Gewichte von OpenAI):

| Modell | Größe | CPU-Zeit/h Audio | Empfehlung |
|--------|-------|-----------------|------------|
| `small` | 460 MB | ~15–20 Min | Kleiner VPS, schnellste Option |
| `medium` | 1,5 GB | ~30–40 Min | **Standard** – gutes Qualitäts-/Zeitverhältnis |
| `large` | 2,9 GB | ~60–90 Min | Starker Server oder GPU |

---

## 5. Web-Interface bedienen

Erreichbar unter `https://tsbot.devprops.de` (Login mit `API_USER` / `API_SECRET`).

### Tab „Aufnahme"

1. **Thema** eingeben (Pflichtfeld)
2. **TeamSpeak-Kanal** aus Dropdown wählen — der Bot tritt genau diesem Kanal bei.
   Das Dropdown lädt alle Kanäle live vom Server. Der zuletzt verwendete Kanal wird
   automatisch vorausgewählt (im Browser-LocalStorage gespeichert).
3. **Agenda** leer lassen = Server-Agenda wird verwendet; oder für diese Sitzung überschreiben
4. **Zusätzliche Instruktionen** optional — freier Text, der direkt an Claude angehängt wird.
   Wird server-seitig in `data/extra_instruktionen.txt` gespeichert und erscheint bei allen Nutzern gleich.
   Beispiele: *„Schreibe Beschlüsse besonders hervor."* / *„Ignoriere Small Talk."*
5. **▶ Aufnahme starten** → Bot verbindet sich mit TS3, tritt dem Kanal bei,
   Aufnahme und Teilnehmer-Tracking starten automatisch
6. **Kanalwechsel** — über das Dropdown während der Aufnahme möglich. Der Bot wechselt
   den Kanal, Teilnehmer-Tracking wird umgeschaltet. Jeder Kanal bekommt eine eigene
   Teilnehmerliste im Protokoll.
7. **■ Aufnahme stoppen** → Bot verlässt den Kanal, MP3 wird gespeichert.
   Automatische Pipeline: Transkription → **Sprecher-Annotation** → Protokollerstellung
8. **Protokoll-Struktur** — Claude gibt pro Agenda-Punkt optional ein `details`-Array zurück.
   Inhalte mit Listencharakter (Events, Programmpunkte, Termine, Stichpunkte) werden
   als Bullet-Liste ins Word-Dokument eingefügt (zwischen Zusammenfassung und Beschlüssen).
   Fließtext ohne Listencharakter erscheint als normaler Absatz.
9. **Sprecher-Annotation** — Der Bot erfasst während der Aufnahme per ClientQuery-Event
   `notifytalkstatuschange`, wer wann spricht. Nach der Transkription werden die
   Whisper-Segmente automatisch mit Sprechernamen versehen:
   `[00:45 - 01:30] Max Mustermann: Hier der gesprochene Text`
   Claude kann damit Aussagen direkt Personen zuordnen (zuverlässiger als Diarization).
9. **Neue Aufnahme während TRANSCRIBING/GENERATING** → möglich. Die laufende Verarbeitung
   läuft im Hintergrund weiter und schreibt ihr Protokoll in den eigenen Session-Ordner.
   Nur während `RECORDING` ist ein Neustart blockiert (Audio-Hardware belegt).
   Laufende Hintergrund-Pipelines werden im Status-Bereich separat angezeigt
   (Session-ID + TRANSCRIBING/GENERATING-Badge).

Der Status-Badge zeigt den Fortschritt:
`IDLE` → `RECORDING` → `TRANSCRIBING` → `GENERATING` → `DONE`

### Tab „Agenda"

Dauerhafte Server-Agenda bearbeiten (wird für alle zukünftigen Sitzungen verwendet):
- Punkte per Drag & Drop sortieren
- Einzelne Punkte hinzufügen / entfernen
- **💾 Agenda speichern** schreibt auf den Server

### Tab „Protokolle"

Liste aller abgeschlossenen Sitzungen mit Download-Links für:
- `Protokoll_YYYYMMDD_HHMM.docx` — Word-Protokoll (Dateiname basiert auf Session-Startzeit, nicht auf Generierungszeit)
- `*_transkript_*.txt` — Volltranskript mit Zeitstempeln
- `audio.mp3` — Original-Aufnahme

**🔄 Neu erstellen** öffnet ein Modal mit den gespeicherten Instruktionen dieser Session.
Nach Anpassung und Bestätigung wird Claude das Protokoll neu generieren – ohne neue Aufnahme
oder Transkription. Transkript, Teilnehmer und Agenda bleiben erhalten; das bestehende `.docx`
wird überschrieben. Der Button wechselt zu „⏳ Läuft..." bis der Vorgang abgeschlossen ist.

Über den **🗑 Löschen**-Button wird eine komplette Session unwiderruflich entfernt
(Audio, Transkript, Protokoll und Metadaten).

---

## 6. Projektstruktur

```
/opt/tsbot/  (Linux-Server) bzw. tsbot/ (Windows-Repo)
├── core/
│   ├── transkribieren.py        Whisper-Transkription
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
├── Dockerfile                  Docker-Image Definition
├── docker-compose.yml          Portainer Stack (Server-Deployment)
├── .dockerignore               Build-Context Filter
├── .github/
│   └── workflows/deploy.yml    CI/CD Pipeline (Build + Deploy)
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
Host server
    HostName DEINE_SERVER_IP
    User root
    IdentityFile ~/.ssh/tsbot_server

# Verbinden:
ssh server
```

### HTTPS + nginx

Das Web-Interface läuft unter **https://tsbot.devprops.de** mit einem
Let's Encrypt-Zertifikat (automatische Erneuerung via certbot).

Für eine Neuinstallation:

```bash
# 1. Pakete installieren
apt install nginx certbot

# 2. nginx-Konfiguration (liegt im Repo unter nginx/tsbot.conf)
cp /opt/tsbot/nginx/tsbot.conf /etc/nginx/sites-available/tsbot
ln -s /etc/nginx/sites-available/tsbot /etc/nginx/sites-enabled/
mkdir -p /var/www/html
nginx -t && systemctl reload nginx

# 3. DNS-A-Record setzen: tsbot.devprops.de → SERVER_IP

# 4. Zertifikat ausstellen (webroot-Methode, funktioniert auch headless)
certbot certonly --webroot -w /var/www/html -d tsbot.devprops.de \
    --non-interactive --agree-tos -m admin@devprops.de

# 5. nginx mit SSL neu laden
systemctl reload nginx
```

Das Zertifikat wird automatisch erneuert (certbot-Timer läuft als systemd-Service).

Die nginx-Konfiguration enthält außerdem **Brute-Force-Schutz** via `limit_req`:
max. 60 Requests/Minute pro IP (burst 30), bei Überschreitung wird HTTP 429 zurückgegeben.
Die Konfiguration liegt im Repo unter `nginx/tsbot.conf`.

### WireGuard VPN (alternative zu HTTPS)

Wenn das Web-Interface gar nicht öffentlich erreichbar sein soll:

```bash
apt install wireguard
# wg0-Interface einrichten, Peer (lokalen Rechner) hinzufügen
# Web-Interface dann erreichbar unter http://10.x.x.x:8080
# Port 8080 aus der öffentlichen Firewall entfernen
```

---

## 8. Backup nach OneDrive

Sitzungsdaten (Audio, Transkripte, Protokolle) werden täglich automatisch nach OneDrive gesichert.
Verwendet wird **rclone** mit `sync` – OneDrive spiegelt immer den aktuellen Server-Stand.
Gelöschte Sessions verschwinden beim nächsten Backup auch aus OneDrive.

Das Backup-Skript und die systemd-Unit-Dateien liegen im separaten Repository
[**server-backup**](https://github.com/DEIN_USER/server-backup).
Dort findet sich auch die vollständige Einrichtungsanleitung (rclone, OneDrive-Auth, Timer-Aktivierung).

**Gesicherter Inhalt:**
```
OneDrive:/Server-Backup/
├── agenda.txt
└── sessions/
    └── YYYYMMDD_HHMMSS/
        ├── audio.mp3
        ├── Protokoll_*.docx
        ├── *_transkript_*.txt
        └── meta.json
```

### Manuell ausführen / Log prüfen

```bash
# Backup manuell starten:
systemctl start onedrive-backup.service

# Log einsehen:
tail -20 /opt/backup/logs/backup.log
journalctl -u onedrive-backup -f
```

---

## 9. Troubleshooting

### Services starten nach Neustart nicht

```bash
# Status prüfen:
systemctl status tsbot-pulseaudio
docker ps   # Container läuft?

# tsbot-pulseaudio manuell starten:
systemctl start tsbot-pulseaudio

# Docker-Container neu starten (falls PulseAudio-Socket neu erstellt wurde):
docker restart tsbot-tsbot-api-1

# Live-Log beobachten:
journalctl -u tsbot-pulseaudio -f
docker logs tsbot-tsbot-api-1 -f
```

### start_tsbot_pulseaudio.sh fehlt (nach Server-Cleanup)

Das Script liegt unter `/usr/local/bin/start_tsbot_pulseaudio.sh` – nicht in `/opt/tsbot/scripts/`.
Falls es fehlt, aus dem Git-Repo wiederherstellen:

```bash
git show HEAD:scripts/start_pulseaudio.sh > /usr/local/bin/start_tsbot_pulseaudio.sh
chmod +x /usr/local/bin/start_tsbot_pulseaudio.sh
systemctl restart tsbot-pulseaudio
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
WHISPER_MODEL=small   # statt medium – halbiert die Transkriptionszeit
```

### Web-UI zeigt 401 Unauthorized

`API_USER` und `API_SECRET` in `config.env` prüfen. Browser-Cache leeren.

### API startet nicht

```bash
journalctl -u tsbot-api -n 50 --no-pager
# Häufig: config.env fehlt oder Python-Pakete nicht installiert
```

### Docker: Container startet nicht

```bash
# Container-Logs prüfen:
docker compose logs tsbot-api

# Image manuell pullen (falls Portainer-Webhook fehlschlug):
docker compose pull && docker compose up -d

# PulseAudio-Socket erreichbar?
ls -la /run/user/1000/pulse/native
# Fehlt er → tsbot-pulseaudio Service neu starten:
systemctl restart tsbot-pulseaudio
```

### GitHub Actions: Build schlägt fehl

```bash
# Im GitHub Actions Tab (Repository → Actions) den fehlgeschlagenen Job öffnen.
# Häufige Ursachen:
# - PORTAINER_WEBHOOK_URL Secret fehlt oder ist abgelaufen
# - Docker Buildx Cache kaputt → Cache löschen: Actions → Caches → Delete
# - requirements.txt enthält fehlerhafte Paketnamen
```

### Docker: Portainer zieht kein neues Image

```bash
# Webhook manuell testen (URL aus Portainer kopieren):
curl -X POST "https://portainer.example.com/api/webhooks/..."

# Im Portainer Stack: "Pull and redeploy" manuell auslösen
# Dann prüfen ob das Image-Tag "latest" wirklich aktuell ist:
docker inspect ghcr.io/regover13/tsbot:latest | grep Created
```

---

## Support

Bei Fragen und Fehlern: Fehlermeldung + `journalctl -u tsbot-api -n 100` in den Chat.
