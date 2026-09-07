#!/bin/bash
# Rollt ein bereits gebautes TSBot-Image aus.
#
# Aufruf ausschliesslich ueber den eingeschraenkten SSH-Schluessel
# 'tsbot-deploy' (command= in /root/.ssh/authorized_keys) -- der Aufrufer
# kann daher kein anderes Kommando waehlen:
#
#   SSH_ORIGINAL_COMMAND = Commit-SHA des auszurollenden Images
#   stdin                = GITHUB_TOKEN des Workflow-Laufs
#
# Der Token wird von GitHub pro Lauf neu erzeugt und hier nur zum Pull
# benutzt; auf dem Server bleibt keiner zurueck. Genau das unterscheidet
# diesen Weg vom frueheren Portainer-Deploy, dessen dauerhaft hinterlegter
# PAT ablief und den Deploy ab dem 2026-08-19 unbemerkt lahmlegte.
set -euo pipefail

SHA="${SSH_ORIGINAL_COMMAND:-}"
if ! [[ "$SHA" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Abbruch: '$SHA' ist kein 40-stelliger Commit-SHA." >&2
    exit 1
fi

cd /opt/tsbot

read -r TOKEN || true
if [ -z "${TOKEN:-}" ]; then
    echo "Abbruch: kein Token auf stdin." >&2
    exit 1
fi

# Eine laufende Aufnahme oder Verarbeitung darf der Neustart nicht zerreissen.
STATE=$(curl -s -u "admin:$(grep -oP '^API_SECRET=\K.*' config/config.env)" \
        http://127.0.0.1:8080/status \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])" 2>/dev/null || echo UNBEKANNT)
case "$STATE" in
    RECORDING|TRANSCRIBING|GENERATING)
        echo "Abbruch: Sitzung im Zustand $STATE -- Deploy wuerde sie abbrechen." >&2
        exit 1
        ;;
esac
echo "Zustand vor dem Deploy: $STATE"

echo "$TOKEN" | docker login ghcr.io -u regover13 --password-stdin
trap 'docker logout ghcr.io >/dev/null 2>&1 || true' EXIT

IMAGE="ghcr.io/regover13/tsbot:$SHA"
docker pull "$IMAGE"

# Genau eine image-Zeile erwartet; bei mehreren waere die Ersetzung mehrdeutig.
TREFFER=$(grep -c '^[[:space:]]*image:' docker-compose.yml)
if [ "$TREFFER" -ne 1 ]; then
    echo "Abbruch: $TREFFER image-Zeilen in docker-compose.yml, erwartet genau eine." >&2
    exit 1
fi
sed -i "s|^\([[:space:]]*image:[[:space:]]*\).*|\1$IMAGE|" docker-compose.yml

docker compose -p tsbot up -d

echo "Ausgerollt: $(docker inspect tsbot-tsbot-api-1 -f '{{.Config.Image}}')"
