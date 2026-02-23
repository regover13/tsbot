#!/usr/bin/env bash
# =============================================================================
# backup_onedrive.sh – TSBot-Daten nach OneDrive sichern
#
# Sichert nach: onedrive:/TSBot-Backup/
#   - data/sessions/   (Audio-MP3, Transkripte, Protokolle)
#   - data/agenda.txt
#
# Läuft täglich per Cron. Protokoll: /opt/tsbot/logs/backup.log
# =============================================================================
set -euo pipefail

LOG=/opt/tsbot/logs/backup.log
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$TIMESTAMP] Backup gestartet" >> "$LOG"

# Sessions (Audio, Transkripte, Protokolle)
rclone sync /opt/tsbot/data/sessions/ onedrive:/TSBot-Backup/sessions/ \
    --log-file="$LOG" --log-level INFO

# Agenda
rclone copy /opt/tsbot/data/agenda.txt onedrive:/TSBot-Backup/ \
    --log-file="$LOG" --log-level INFO

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup abgeschlossen" >> "$LOG"
