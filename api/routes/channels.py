"""
Kanal-Endpoint: GET /channels – gibt alle TS3-Kanäle zurück.
Ergebnis wird 30 Sekunden gecacht, um ServerQuery-Rate-Limits zu vermeiden.
"""

import asyncio
import os
import time
import logging
from fastapi import APIRouter, HTTPException

router = APIRouter()
logger = logging.getLogger(__name__)

_cache: dict = {"channels": None, "expires": 0.0}
_lock = asyncio.Lock()
CACHE_TTL = 30  # Sekunden


@router.get("/", summary="TS3-Kanalliste abrufen")
async def get_channels(force: bool = False):
    """
    Verbindet sich per ServerQuery und gibt alle Kanäle zurück.
    Ergebnis wird 30 s gecacht; parallele Anfragen warten auf denselben Fetch.
    force=true umgeht den Cache (für manuellen Reload-Button).
    """
    # Cache noch gültig und kein Force → sofort zurückgeben
    if not force and _cache["channels"] is not None and time.monotonic() < _cache["expires"]:
        return {"channels": _cache["channels"], "cached": True}

    async with _lock:
        # Nach Lock-Erwerb nochmal prüfen (außer bei force)
        if not force and _cache["channels"] is not None and time.monotonic() < _cache["expires"]:
            return {"channels": _cache["channels"], "cached": True}
        # Nochmal prüfen – anderer Request hat inzwischen evtl. schon gefetcht
        if _cache["channels"] is not None and time.monotonic() < _cache["expires"]:
            return {"channels": _cache["channels"], "cached": True}

        try:
            import ts3
        except ImportError:
            raise HTTPException(status_code=500, detail="ts3-Bibliothek nicht installiert.")

        host      = os.environ.get("TS_HOST", "ts3.friesenflieger.de")
        port      = int(os.environ.get("TS_QUERY_PORT", "10011"))
        user      = os.environ.get("TS_QUERY_USER", "serveradmin")
        password  = os.environ.get("TS_QUERY_PASS", "")
        server_id = int(os.environ.get("TS_SERVER_ID", "1"))

        try:
            conn = ts3.query.TS3Connection(host, port)
            conn.login(client_login_name=user, client_login_password=password)
            conn.use(sid=server_id)
            resp = conn.channellist()
            conn.quit()
        except Exception as e:
            logger.error("ServerQuery channellist fehlgeschlagen: %s", e)
            raise HTTPException(status_code=502, detail=f"ServerQuery-Fehler: {e}")

        channels = [
            {
                "id":     int(c.get("cid", 0)),
                "name":   c.get("channel_name", ""),
                "parent": int(c.get("pid", 0)),
                "order":  int(c.get("channel_order", 0)),
            }
            for c in resp.parsed
            if c.get("channel_name")
        ]

        _cache["channels"] = channels
        _cache["expires"]  = time.monotonic() + CACHE_TTL

    return {"channels": channels}
