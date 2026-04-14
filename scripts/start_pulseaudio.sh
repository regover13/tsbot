#!/usr/bin/env bash
# =============================================================================
# start_pulseaudio.sh – PulseAudio-Null-Sink für TeamSpeak-Aufnahme einrichten
#
# Wird einmalig beim Server-Start ausgeführt (auch via systemd).
# =============================================================================
set -euo pipefail

SINK_NAME="${PULSE_SINK:-tsbot_sink}"

PULSE_SOCKET="${XDG_RUNTIME_DIR:-/run/user/1000}/pulse/native"

# PulseAudio starten oder sicherstellen dass es erreichbar ist
if pactl info >/dev/null 2>&1; then
    echo "PulseAudio läuft bereits und ist erreichbar."
else
    echo "PulseAudio nicht erreichbar – neu starten..."
    pulseaudio --kill 2>/dev/null || true
    rm -f "$PULSE_SOCKET" 2>/dev/null || true
    sleep 1
    pulseaudio --start --exit-idle-time=-1 --log-level=warning
    sleep 2
    if ! pactl info >/dev/null 2>&1; then
        echo "FEHLER: PulseAudio konnte nicht gestartet werden!" >&2
        exit 1
    fi
    echo "PulseAudio gestartet."
fi

# Prüfen ob Sink bereits existiert
if pactl list sinks short 2>/dev/null | grep -q "$SINK_NAME"; then
    echo "Sink '$SINK_NAME' bereits vorhanden."
else
    echo "Lege Null-Sink '$SINK_NAME' an..."
    pactl load-module module-null-sink \
        sink_name="$SINK_NAME" \
        rate=44100 \
        "sink_properties=device.description='TSBot-Recording-Sink'"
    echo "Null-Sink '$SINK_NAME' angelegt."
fi

pactl set-default-sink "$SINK_NAME"
echo "Standard-Sink gesetzt: $SINK_NAME"

# Null-Source für Bot-Mikrofon (verhindert Echo-Feedback)
if ! pactl list sources short 2>/dev/null | grep -q "tsbot_null_mic"; then
    pactl load-module module-null-sink sink_name=tsbot_null_mic \
        "sink_properties=device.description='TSBot-Null-Mic'"
fi
pactl set-default-source tsbot_null_mic.monitor
echo "Standard-Source (Mikrofon) auf Stille gesetzt: tsbot_null_mic.monitor"

echo ""
echo "Verfügbare Sinks:"
pactl list sinks short

echo ""
echo "Monitor-Source für ffmpeg: ${SINK_NAME}.monitor"
echo "Test: ffmpeg -f pulse -i ${SINK_NAME}.monitor -t 5 /tmp/test.mp3"
