FROM python:3.11-slim

# System-Abhängigkeiten
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    pulseaudio-utils \
    && rm -rf /var/lib/apt/lists/*

# Nicht-Root-User mit UID 1000 (passend zum Host-tsbot-User)
RUN useradd -u 1000 -m -s /bin/bash tsbot
USER tsbot
WORKDIR /opt/tsbot

# Python-Abhängigkeiten (Layer-Cache-freundlich)
COPY --chown=tsbot:tsbot requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Whisper-Modell vorab herunterladen (wird im Image gecacht → kein Download beim ersten Start)
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

# App-Code
COPY --chown=tsbot:tsbot . .

ENV PATH="/home/tsbot/.local/bin:$PATH"
ENV DATA_DIR=/opt/tsbot/data
ENV AGENDA_PATH=/opt/tsbot/data/agenda.txt

EXPOSE 8080
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]
