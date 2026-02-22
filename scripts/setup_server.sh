#!/usr/bin/env bash
# =============================================================================
# setup_server.sh – Einmalige Server-Einrichtung für /opt/tsbot
#
# Führe dieses Skript als root auf einem Debian/Ubuntu-Server aus:
#   sudo bash scripts/setup_server.sh
# =============================================================================
set -euo pipefail

TSBOT_DIR="/opt/tsbot"
TSBOT_USER="tsbot"
VENV="$TSBOT_DIR/venv"

echo "=== TSBot Server Setup ==="
echo ""

# ── 1. Systempakete ──────────────────────────────────────────
echo "[1/6] Installiere Systempakete..."
apt-get update -qq
apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    ffmpeg \
    pulseaudio \
    pulseaudio-utils \
    xvfb \
    x11vnc \
    wget \
    curl \
    git \
    build-essential

# ── 2. Dedicated User ────────────────────────────────────────
echo "[2/6] Erstelle tsbot-Benutzer..."
if ! id "$TSBOT_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$TSBOT_USER"
fi
# PulseAudio auch ohne aktive Login-Session erlauben
loginctl enable-linger "$TSBOT_USER" 2>/dev/null || true

# ── 3. Verzeichnisstruktur ───────────────────────────────────
echo "[3/6] Richte Verzeichnisse ein..."
mkdir -p "$TSBOT_DIR"/{data/sessions,config,logs}
chown -R "$TSBOT_USER":"$TSBOT_USER" "$TSBOT_DIR"

# Repo ins Verzeichnis klonen / aktualisieren
if [ -d "$TSBOT_DIR/.git" ]; then
    echo "  → Repo bereits vorhanden, aktualisiere..."
    git -C "$TSBOT_DIR" pull
else
    echo "  → HINWEIS: Klone das Repo manuell nach $TSBOT_DIR"
    echo "     git clone <repo-url> $TSBOT_DIR"
fi

# ── 4. Python-Umgebung ───────────────────────────────────────
echo "[4/6] Erstelle Python venv und installiere Abhängigkeiten..."
echo "  → Hinweis: torch (CPU-only) benötigt ~2,5 GB Download."
sudo -u "$TSBOT_USER" python3.11 -m venv "$VENV"
sudo -u "$TSBOT_USER" "$VENV/bin/pip" install --upgrade pip --quiet
sudo -u "$TSBOT_USER" "$VENV/bin/pip" install \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r "$TSBOT_DIR/requirements.txt"

# ── 5. TeamSpeak 3 Linux Client ─────────────────────────────
echo "[5/6] TeamSpeak 3 Client..."
TS_DIR="/home/$TSBOT_USER/TeamSpeak3"
if [ ! -d "$TS_DIR" ]; then
    echo "  → Lade TS3-Client herunter (Version 3.6.2)..."
    TS_URL="https://files.teamspeak-services.com/releases/client/3.6.2/TeamSpeak3-Client-linux_amd64-3.6.2.run"
    wget -q -O /tmp/ts3client.run "$TS_URL"
    chmod +x /tmp/ts3client.run
    sudo -u "$TSBOT_USER" bash -c "
        cd ~
        /tmp/ts3client.run -- --target ~/TeamSpeak3
    "
    rm /tmp/ts3client.run
    echo "  → WICHTIG: Starte den TS3-Client einmalig per VNC, um die Lizenz zu akzeptieren!"
    echo "     1. x11vnc -display :99 -forever &"
    echo "     2. Mit VNC-Viewer verbinden und Lizenz klicken"
fi

# ── 6. systemd Services ──────────────────────────────────────
echo "[6/6] Installiere systemd-Services..."
cp "$TSBOT_DIR/systemd/tsbot-pulseaudio.service" /etc/systemd/system/
cp "$TSBOT_DIR/systemd/tsbot-api.service"        /etc/systemd/system/
systemctl daemon-reload
systemctl enable tsbot-pulseaudio tsbot-api
systemctl start  tsbot-pulseaudio

echo ""
echo "=== Setup abgeschlossen ==="
echo ""
echo "Nächste Schritte:"
echo "  1. cp $TSBOT_DIR/config/config.example.env $TSBOT_DIR/config/config.env"
echo "  2. Secrets in config/config.env eintragen"
echo "  3. TS3-Client einmalig per VNC starten und Lizenz akzeptieren"
echo "  4. systemctl start tsbot-api"
echo "  5. Web-UI: http://<server-ip>:8080"
