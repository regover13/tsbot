#!/usr/bin/env bash
# =============================================================================
# start_pulseaudio.sh – PulseAudio-Null-Sink für TeamSpeak-Aufnahme einrichten
#
# Wird einmalig beim Server-Start ausgeführt (auch via systemd).
# =============================================================================
set -euo pipefail

SINK_NAME="${PULSE_SINK:-tsbot_sink}"

echo "Starte PulseAudio..."
pulseaudio --start --exit-idle-time=-1 --log-level=warning 2>/dev/null || true
sleep 2

# Prüfen ob Sink bereits existiert
if pactl list sinks short 2>/dev/null | grep -q "$SINK_NAME"; then
    echo "Sink '$SINK_NAME' bereits vorhanden."
else
    echo "Lege Null-Sink '$SINK_NAME' an..."
    pactl load-module module-null-sink \
        sink_name="$SINK_NAME" \
        "sink_properties=device.description='TSBot-Recording-Sink'"
    echo "Null-Sink '$SINK_NAME' angelegt."
fi

echo ""
echo "Verfügbare Sinks:"
pactl list sinks short

echo ""
echo "Monitor-Source für ffmpeg: ${SINK_NAME}.monitor"
echo "Test: ffmpeg -f pulse -i ${SINK_NAME}.monitor -t 5 /tmp/test.mp3"
