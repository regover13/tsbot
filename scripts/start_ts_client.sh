#!/usr/bin/env bash
# =============================================================================
# start_ts_client.sh – TeamSpeak 3 Linux Client headless starten
#
# Nutzt Xvfb als virtuelles Display und leitet Audio an den PulseAudio-Sink.
# Voraussetzung: start_pulseaudio.sh wurde bereits ausgeführt.
# =============================================================================
set -euo pipefail

DISPLAY_NUM=":99"
SINK_NAME="${PULSE_SINK:-tsbot_sink}"
TS_DIR="${TS_CLIENT_DIR:-$HOME/TeamSpeak3}"
TS_BIN="$TS_DIR/ts3client_linux_amd64"
TS_SERVER="${TS_HOST:-127.0.0.1}"
TS_PORT="${TS_PORT:-9987}"
TS_CHANNEL="${TS_CHANNEL_ID:-0}"

# ── Xvfb starten ─────────────────────────────────────────────
if ! pgrep -x Xvfb &>/dev/null; then
    echo "Starte Xvfb auf Display $DISPLAY_NUM..."
    Xvfb "$DISPLAY_NUM" -screen 0 1024x768x24 &
    sleep 1
fi

# ── TS3-Client starten ────────────────────────────────────────
if [ ! -x "$TS_BIN" ]; then
    echo "FEHLER: TS3-Client nicht gefunden: $TS_BIN"
    echo "Bitte setup_server.sh ausführen oder TS3-Pfad in TS_CLIENT_DIR setzen."
    exit 1
fi

export DISPLAY="$DISPLAY_NUM"
export PULSE_SINK="$SINK_NAME"

TS_URL="ts3server://${TS_SERVER}?port=${TS_PORT}"
if [ "$TS_CHANNEL" != "0" ]; then
    TS_URL="${TS_URL}&channel=${TS_CHANNEL}"
fi

echo "Starte TS3-Client:"
echo "  URL:     $TS_URL"
echo "  Audio:   $SINK_NAME"
echo "  Display: $DISPLAY_NUM"
echo ""

"$TS_BIN" "$TS_URL" &
TS_PID=$!
echo "TS3-Client PID: $TS_PID"

# PID für späteres Beenden speichern
echo "$TS_PID" > /tmp/tsbot_tsclient.pid

echo ""
echo "VNC-Zugriff (für einmalige Lizenz-Akzeptanz):"
echo "  x11vnc -display $DISPLAY_NUM -forever -nopw -localhost &"
echo "  ssh -L 5900:localhost:5900 user@server"
