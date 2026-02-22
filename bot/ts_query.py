#!/usr/bin/env python3
"""
TeamSpeak 3 ServerQuery – Teilnehmer-Tracking.

Verbindet sich per ServerQuery (Port 10011) und akkumuliert über die
gesamte Sitzung alle Ein- und Austritte im konfigurierten Kanal.
Bibliothek: ts3 (PyPI)
"""

import os
import re
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)


class TSQueryTracker:
    """Verfolgt Teilnehmer in einem TeamSpeak-Kanal über ServerQuery."""

    def __init__(self,
                 host: str = None,
                 port: int = None,
                 user: str = None,
                 password: str = None,
                 server_id: int = None,
                 channel_id: int = None):
        self._host      = host      or os.environ.get("TS_HOST", "127.0.0.1")
        self._port      = port      or int(os.environ.get("TS_QUERY_PORT", "10011"))
        self._user      = user      or os.environ.get("TS_QUERY_USER", "serveradmin")
        self._password  = password  or os.environ.get("TS_QUERY_PASS", "")
        self._server_id = server_id or int(os.environ.get("TS_SERVER_ID", "1"))
        self._channel_id = channel_id or int(os.environ.get("TS_CHANNEL_ID", "0"))

        # Akkumulierte Teilnehmer: key → {"name": str, "frs": str, "joined_at": str}
        self._participants: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._conn = None
        self._running = False

    # ── Öffentliche API ───────────────────────────────────────

    def start(self):
        """Verbindet und beginnt Teilnehmer-Tracking."""
        try:
            import ts3
        except ImportError:
            raise RuntimeError(
                "Paket 'ts3' nicht installiert. Bitte: pip install ts3"
            )

        logger.info("Verbinde mit TS3 ServerQuery %s:%d", self._host, self._port)
        self._conn = ts3.query.TS3Connection(self._host, self._port)
        self._conn.login(
            client_login_name=self._user,
            client_login_password=self._password,
        )
        self._conn.use(sid=self._server_id)

        # Sofort aktuelle Teilnehmer im Kanal laden
        self._lade_aktuelle_teilnehmer()

        # Event-Benachrichtigungen aktivieren
        self._conn.servernotifyregister(event="server")
        self._running = True

        # Hintergrund-Thread für eingehende Events
        self._thread = threading.Thread(target=self._event_loop, daemon=True)
        self._thread.start()
        logger.info("TSQueryTracker gestartet.")

    def stop(self):
        """Beendet das Tracking und schließt die Verbindung."""
        self._running = False
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        logger.info("TSQueryTracker gestoppt.")

    def get_participant_list(self) -> list:
        """Gibt alle akkumulierten Teilnehmer als Liste zurück."""
        with self._lock:
            return sorted(self._participants.values(), key=lambda x: x["name"].lower())

    def get_channel_id(self) -> int:
        """Gibt den aktuell überwachten Kanal zurück."""
        return self._channel_id

    def switch_channel(self, channel_id: int):
        """
        Schaltet das Tracking auf einen neuen Kanal um.
        Lädt sofort alle aktuell im neuen Kanal anwesenden Clients.
        """
        old = self._channel_id
        self._channel_id = channel_id
        logger.info("Tracking gewechselt: Kanal %d → %d", old, channel_id)
        self._lade_aktuelle_teilnehmer()

    # ── Interne Methoden ──────────────────────────────────────

    def _lade_aktuelle_teilnehmer(self):
        """Lädt alle aktuell im konfigurierten Kanal befindlichen Clients."""
        try:
            resp = self._conn.clientlist()
            for c in resp.parsed:
                if c.get("client_type") == "0":  # 0 = normaler Client, 1 = Query
                    cid = int(c.get("cid", 0))
                    if self._channel_id == 0 or cid == self._channel_id:
                        self._handle_join(c.get("client_nickname", ""))
        except Exception as e:
            logger.warning("Fehler beim Laden aktueller Clients: %s", e)

    def _event_loop(self):
        """Blockierender Event-Loop im Hintergrund-Thread."""
        import ts3
        while self._running:
            try:
                event = self._conn.wait_for_event(timeout=5.0)
                self._verarbeite_event(event)
            except ts3.TS3TimeoutError:
                continue
            except Exception as e:
                if self._running:
                    logger.error("Event-Loop-Fehler: %s", e)
                break

    def _verarbeite_event(self, event):
        """Verarbeitet einen eingehenden ServerQuery-Event."""
        if not event:
            return
        event_type = event.event
        data = event.parsed[0] if event.parsed else {}

        if event_type == "notifycliententerview":
            # Nur den aktuell konfigurierten Kanal berücksichtigen
            ctid = int(data.get("ctid", 0))
            if self._channel_id == 0 or ctid == self._channel_id:
                nick = data.get("client_nickname", "")
                client_type = data.get("client_type", "1")
                if client_type == "0":
                    self._handle_join(nick)

        elif event_type == "notifyclientleftview":
            nick = data.get("client_nickname", "")
            logger.debug("Verlassen: %s", nick)

    def _handle_join(self, nickname: str):
        """Fügt einen Teilnehmer zur akkumulierten Liste hinzu."""
        parsed = self._parse_nickname(nickname)
        if not parsed["name"]:
            return

        key = parsed["frs"] if parsed["frs"] else parsed["name"].lower()
        with self._lock:
            if key not in self._participants:
                parsed["joined_at"] = datetime.now().isoformat()
                self._participants[key] = parsed
                logger.info("Teilnehmer beigetreten: %s (%s)",
                            parsed["name"], parsed["frs"])

    def _parse_nickname(self, nick: str) -> dict:
        """
        Parst TeamSpeak-Nickname im Format "Vorname Nachname/FRSxxx".
        Gibt {"name": str, "frs": str} zurück.
        """
        nick = nick.strip()
        m = re.match(r'^(.+?)/(FRS\d+)', nick, re.IGNORECASE)
        if m:
            return {
                "name": m.group(1).strip(),
                "frs":  m.group(2).upper(),
            }
        return {"name": nick, "frs": ""}
