FROM python:3.11-slim

# System-Abhängigkeiten
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    pulseaudio-utils \
    libcap2-bin \
    && rm -rf /var/lib/apt/lists/* \
    && setcap 'cap_sys_nice+eip' /usr/bin/chrt

# Nicht-Root-User mit UID 1000 (passend zum Host-tsbot-User)
RUN useradd -u 1000 -m -s /bin/bash tsbot
USER tsbot
WORKDIR /opt/tsbot

# Python-Abhängigkeiten (Layer-Cache-freundlich)
COPY --chown=tsbot:tsbot requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Whisper-Modell vorab herunterladen (wird im Image gecacht → kein Download beim ersten Start)
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('medium', device='cpu', compute_type='int8')"

# App-Code
COPY --chown=tsbot:tsbot . .

ENV PATH="/home/tsbot/.local/bin:$PATH"
ENV DATA_DIR=/opt/tsbot/data
ENV AGENDA_PATH=/opt/tsbot/data/agenda.txt

EXPOSE 8080
# --host 127.0.0.1 seit 2026-08-19 (Security-Audit).
#
# Der Container laeuft mit network_mode: host und teilt sich damit den
# Netzwerk-Namensraum der Maschine. Mit 0.0.0.0 lauschte die API auf ALLEN
# Adressen -- von aussen unerreichbar allein deshalb, weil ufw Port 8080
# nicht freigibt. Eine einzige zusaetzliche Firewall-Regel haette die
# unverschluesselte API mit ihrer Basic-Auth ins Internet gestellt.
#
# Auf Loopback bleibt der einzige Weg der ueber nginx: mit TLS, HSTS,
# Ratenbegrenzung und dem fail2ban-Jail [tsbot]. nginx laeuft ebenfalls auf
# dem Host und erreicht 127.0.0.1:8080 unveraendert.
CMD ["uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8080", "--log-level", "info"]
