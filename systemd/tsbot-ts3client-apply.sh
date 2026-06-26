#!/bin/bash
# Wendet die TS3-Client-Anforderung aus der Flag-Datei an (vom .path-Watcher getriggert).
# Installation: nach /usr/local/sbin/tsbot-ts3client-apply.sh kopieren, chmod +x.
REQ=/opt/tsbot/data/.ts3client.request
state=$(tr -d '[:space:]' < "$REQ" 2>/dev/null)
case "$state" in
  up)   systemctl start tsbot-ts3client.service ;;
  down) systemctl stop  tsbot-ts3client.service ;;
  *)    logger -t tsbot-ts3client "unbekannte Anforderung: '$state'" ;;
esac
