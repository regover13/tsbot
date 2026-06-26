#!/usr/bin/env bash
# =============================================================================
# start_pulseaudio.sh – PulseAudio-Null-Sink für TeamSpeak-Aufnahme einrichten
#
# Wird einmalig beim Server-Start ausgeführt (auch via systemd).
# =============================================================================
# Kein -e: die Retry-Schleife toleriert fehlgeschlagene Einzelversuche.
set -uo pipefail

SINK_NAME="${PULSE_SINK:-tsbot_sink}"

PULSE_SOCKET="${XDG_RUNTIME_DIR:-/run/user/1000}/pulse/native"

# PulseAudio race-fest starten: bis zu 6 Versuche; ein bereits laufendes
# PulseAudio (z.B. aus der tsbot-User-Session) wird bevorzugt. Vermeidet den
# Boot-Race "bind(): Address already in use" durch konkurrierende Instanzen.
start_pulse() {
    for attempt in 1 2 3 4 5 6; do
        if pactl info >/dev/null 2>&1; then
            echo "PulseAudio erreichbar (Versuch $attempt)."
            return 0
        fi
        pulseaudio --kill 2>/dev/null || true
        rm -f "$PULSE_SOCKET" 2>/dev/null || true
        sleep 1
        pulseaudio --start --exit-idle-time=-1 --log-level=warning 2>/dev/null || true
        sleep 2
    done
    pactl info >/dev/null 2>&1
}
if ! start_pulse; then
    echo "FEHLER: PulseAudio konnte nicht gestartet werden!" >&2
    exit 1
fi

# Existierenden Sink entladen falls vorhanden (stellt sicheren Rate-Reset sicher)
EXISTING_MODULE=$(pactl list modules short 2>/dev/null | awk -v name="$SINK_NAME" '$0 ~ name {print $1}' | head -1)
if [ -n "$EXISTING_MODULE" ]; then
    echo "Entlade vorhandenen Sink '$SINK_NAME' (Modul $EXISTING_MODULE)..."
    pactl unload-module "$EXISTING_MODULE" 2>/dev/null || true
fi

echo "Lege Null-Sink '$SINK_NAME' an (rate=44100, mono)..."
pactl load-module module-null-sink \
    sink_name="$SINK_NAME" \
    rate=44100 \
    channels=1 \
    "sink_properties=device.description='TSBot-Recording-Sink'"
echo "Null-Sink '$SINK_NAME' angelegt."

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
