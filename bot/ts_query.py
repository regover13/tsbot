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
        self._participants_by_channel: dict[int, list] = {}  # Abgeschlossene Kanäle
        self._channel_name_cache: dict[int, str] = {}        # cid → Kanalname (beim Start geladen)
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

        # Kanalnamen vorab cachen – vor dem Event-Loop-Start (keine Race Condition)
        self._lade_kanal_namen()

        # Sofort aktuelle Teilnehmer laden (alle auf dem Server)
        self._lade_aktuelle_teilnehmer()

        # Event-Benachrichtigungen aktivieren (server-Events: cliententer/clientleft)
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
        Speichert die Teilnehmer des alten Kanals und lädt die des neuen.
        """
        old = self._channel_id
        # Teilnehmer des alten Kanals sichern
        self._participants_by_channel[old] = self.get_participant_list()
        self._channel_id = channel_id
        with self._lock:
            self._participants.clear()
        logger.info("Tracking gewechselt: Kanal %d → %d – Teilnehmerliste zurückgesetzt.", old, channel_id)
        # Kein _lade_aktuelle_teilnehmer() hier – würde die gemeinsame ServerQuery-Verbindung
        # mit dem Event-Loop-Thread konkurrieren und blockieren. Teilnehmer werden via
        # notifycliententerview-Events und 30s-Polling nachgetragen.

    def get_participants_by_channel(self) -> dict:
        """Gibt alle Teilnehmer gruppiert nach Kanal-ID zurück (inkl. aktuellen Kanal)."""
        result = dict(self._participants_by_channel)
        result[self._channel_id] = self.get_participant_list()
        return result

    def get_channel_name(self, channel_id: int) -> str:
        """Gibt den Kanalnamen für eine gegebene Kanal-ID zurück (aus Cache)."""
        return self._channel_name_cache.get(channel_id, str(channel_id))

    # ── Interne Methoden ──────────────────────────────────────

    def _lade_kanal_namen(self):
        """Lädt alle Kanalnamen einmalig in den Cache (vor dem Event-Loop-Start)."""
        try:
            resp = self._conn.channellist()
            for c in resp.parsed:
                try:
                    cid = int(c.get("cid", -1))
                    name = c.get("channel_name", "")
                    if cid > 0 and name:
                        self._channel_name_cache[cid] = name
                except (ValueError, TypeError):
                    pass
            logger.debug("Kanalnamen gecacht: %d Kanäle", len(self._channel_name_cache))
        except Exception as e:
            logger.warning("Fehler beim Cachen der Kanalnamen: %s", e)

    def _lade_aktuelle_teilnehmer(self):
        """Lädt Clients im aktuell überwachten Kanal (kanalspezifisch)."""
        if not self._running:
            return
        try:
            resp = self._conn.clientlist()
            for c in resp.parsed:
                if c.get("client_type") == "0":  # 0 = normaler Client, 1 = Query
                    try:
                        cid = int(c.get("cid", 0))
                    except (ValueError, TypeError):
                        cid = 0
                    if self._channel_id == 0 or cid == self._channel_id:
                        self._handle_join(c.get("client_nickname", ""))
        except Exception as e:
            logger.warning("Fehler beim Laden aktueller Clients: %s", e)

    def _event_loop(self):
        """Blockierender Event-Loop im Hintergrund-Thread."""
        import ts3
        _poll_zaehler = 0
        while self._running:
            try:
                event = self._conn.wait_for_event(timeout=5.0)
                self._verarbeite_event(event)
            except ts3.query.TS3TimeoutError:
                # Alle 30 Sekunden Clientliste neu einlesen (Fallback für verpasste Events)
                _poll_zaehler += 1
                if _poll_zaehler >= 6:
                    _poll_zaehler = 0
                    self._lade_aktuelle_teilnehmer()
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
            nick = data.get("client_nickname", "")
            client_type = data.get("client_type", "1")
            if client_type == "0":
                try:
                    ctid = int(data.get("ctid", 0))
                except (ValueError, TypeError):
                    ctid = 0
                if self._channel_id == 0 or ctid == self._channel_id:
                    self._handle_join(nick)

        elif event_type == "notifyclientleftview":
            nick = data.get("client_nickname", "")
            logger.debug("Verlassen: %s", nick)

    def _handle_join(self, nickname: str):
        """Fügt einen Teilnehmer zur akkumulierten Liste hinzu."""
        bot_nick = os.environ.get("TS_NICKNAME", "FriesenFliegerBot")
        nick_clean = nickname.strip()
        # Parsing-Artefakte herausfiltern (enthalten '=' oder 'clid=')
        if not nick_clean or '=' in nick_clean:
            return
        if nick_clean == bot_nick or nick_clean.startswith(bot_nick):
            return
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
        Parst TeamSpeak-Nickname. FRS-Nummer kann vor oder nach dem Namen stehen,
        mit beliebigen Trennzeichen (/, |, Leerzeichen) oder direkt angehängt.
        Beispiele:
          "Vorname Nachname/FRS22"     → name="Vorname Nachname", frs="FRS22"
          "Klaus Löfflad | FRS22"      → name="Klaus Löfflad",    frs="FRS22"
          "FRS22/Vorname Nachname"     → name="Vorname Nachname", frs="FRS22"
          "Marco WeißFRS135(MSFS2024)" → name="Marco Weiß",       frs="FRS135"
        """
        nick = nick.strip()
        # FRS-Nummer ohne führende \b suchen (Unicode-Buchstaben wie ß enden nicht auf \b)
        m = re.search(r'FRS(\d+[A-Z]?)', nick, re.IGNORECASE)
        if m:
            frs = m.group(0).upper()
            _sep = '/( |'
            before = nick[:m.start()].strip().strip(_sep)
            # Klammer-Reste nach FRS entfernen (z.B. "(MSFS2024)")
            after_raw = nick[m.end():]
            after = re.sub(r'^\(.*?\)', '', after_raw).strip().strip(_sep + ')')
            # Bevorzuge den Teil der wie ein Vor-/Nachname aussieht (enthält Leerzeichen)
            if ' ' in before:
                name = before
            elif ' ' in after:
                name = after
            else:
                name = before or after
            return {"name": name, "frs": frs}
        return {"name": nick, "frs": ""}
