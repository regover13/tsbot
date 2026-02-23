#!/usr/bin/env bash
# =============================================================================
# setup_server.sh – Einmalige Server-Einrichtung für TSBot
#
# Voraussetzung: Repo bereits nach /opt/tsbot geklont.
# Ausführen als root:
#   sudo bash /opt/tsbot/scripts/setup_server.sh
# =============================================================================
set -euo pipefail

TSBOT_DIR="/opt/tsbot"
TSBOT_USER="tsbot"
VENV="$TSBOT_DIR/venv"

echo "=== TSBot Server Setup ==="
echo ""

# ── 1. Systempakete ──────────────────────────────────────────
echo "[1/7] Installiere Systempakete..."
apt-get update -qq
apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    ffmpeg \
    pulseaudio \
    pulseaudio-utils \
    libasound2-plugins \
    xvfb \
    x11vnc \
    nginx \
    certbot \
    wget \
    curl \
    git \
    build-essential

# ── 2. Dedicated User ────────────────────────────────────────
echo "[2/7] Erstelle tsbot-Benutzer..."
if ! id "$TSBOT_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$TSBOT_USER"
fi
# PulseAudio auch ohne aktive Login-Session erlauben
loginctl enable-linger "$TSBOT_USER" 2>/dev/null || true

# ── 3. Verzeichnisstruktur ───────────────────────────────────
echo "[3/7] Richte Verzeichnisse ein..."
mkdir -p "$TSBOT_DIR"/{data/sessions,config,logs}
mkdir -p /run/user/1000
chown tsbot:tsbot /run/user/1000
chmod 700 /run/user/1000
chown -R "$TSBOT_USER":"$TSBOT_USER" "$TSBOT_DIR"

# ── 4. ALSA → PulseAudio Routing ─────────────────────────────
echo "[4/7] Konfiguriere ALSA-Routing..."
# TS3 Linux Client hat nur ALSA-Backend – wird über diese Datei
# an PulseAudio weitergeleitet. Capture auf null → kein Echo.
cat > /home/$TSBOT_USER/.asoundrc << 'EOF'
pcm.!default {
    type asym
    playback.pcm { type plug; slave.pcm "pulse" }
    capture.pcm  { type plug; slave.pcm "null"  }
}
pcm.null { type null }
ctl.!default { type pulse }
EOF
chown $TSBOT_USER:$TSBOT_USER /home/$TSBOT_USER/.asoundrc

# ── 5. Python-Umgebung ───────────────────────────────────────
echo "[5/7] Erstelle Python venv und installiere Abhängigkeiten..."
echo "  → Hinweis: torch (CPU-only) benötigt ~2,5 GB Download."
sudo -u "$TSBOT_USER" python3.11 -m venv "$VENV"
sudo -u "$TSBOT_USER" "$VENV/bin/pip" install --upgrade pip --quiet
sudo -u "$TSBOT_USER" "$VENV/bin/pip" install \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r "$TSBOT_DIR/requirements.txt"

# whisperx separat (für Sprechertrennung, optional aber empfohlen)
echo "  → Installiere whisperx (Sprechertrennung)..."
sudo -u "$TSBOT_USER" "$VENV/bin/pip" install whisperx --quiet

# ── 6. TeamSpeak 3 Linux Client ─────────────────────────────
echo "[6/7] TeamSpeak 3 Client..."
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
    echo ""
    echo "  → WICHTIG: Lizenz einmalig per VNC akzeptieren (nach Setup-Abschluss):"
    echo "     1. runuser -u tsbot -- env DISPLAY=:99 x11vnc -display :99 -forever -nopw -localhost -bg"
    echo "     2. SSH-Tunnel: ssh -L 5900:localhost:5900 <server>"
    echo "     3. VNC-Viewer auf localhost:5900 verbinden, Lizenz klicken"
    echo "     4. pkill x11vnc"
else
    echo "  → TS3-Client bereits installiert."
fi

# ── 7. systemd Services ──────────────────────────────────────
echo "[7/7] Installiere systemd-Services..."
cp "$TSBOT_DIR/systemd/tsbot-pulseaudio.service" /etc/systemd/system/
cp "$TSBOT_DIR/systemd/tsbot-api.service"        /etc/systemd/system/
systemctl daemon-reload
systemctl enable tsbot-pulseaudio tsbot-api
systemctl start  tsbot-pulseaudio

# ── nginx ─────────────────────────────────────────────────────
if [ -f "$TSBOT_DIR/nginx/tsbot.conf" ]; then
    mkdir -p /var/www/html
    cp "$TSBOT_DIR/nginx/tsbot.conf" /etc/nginx/sites-available/tsbot
    ln -sf /etc/nginx/sites-available/tsbot /etc/nginx/sites-enabled/tsbot
    nginx -t && systemctl enable nginx && systemctl reload nginx
    echo "  → nginx konfiguriert."
fi

echo ""
echo "=== Setup abgeschlossen ==="
echo ""
echo "Nächste Schritte:"
echo "  1. cp $TSBOT_DIR/config/config.example.env $TSBOT_DIR/config/config.env"
echo "  2. Secrets in config/config.env eintragen (API-Keys, TS3-Passwort)"
echo "  3. systemctl start tsbot-api"
echo "  4. SSL-Zertifikat ausstellen (nach DNS-Eintrag für die Domain):"
echo "     certbot certonly --webroot -w /var/www/html -d tsbot.DEINE-DOMAIN.de \\"
echo "         --non-interactive --agree-tos -m admin@DEINE-DOMAIN.de"
echo "     systemctl reload nginx"
echo "  5. TS3-Lizenz einmalig per VNC akzeptieren (siehe Schritt 6 oben)"
echo "  6. Web-UI: https://tsbot.DEINE-DOMAIN.de"
