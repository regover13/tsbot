#!/usr/bin/env python3
"""
TSClientControl – Steuert den laufenden TS3 Linux Client via ClientQuery-Plugin.
TSClientMonitor  – Überwacht Client-Events (Kanalwechsel, Kick) via persistenter Verbindung.

Das ClientQuery-Plugin hört auf 127.0.0.1:25639.
"""

import os
import re
import socket
import logging
import time
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_CQ_HOST    = "127.0.0.1"
_CQ_PORT    = 25639
_CQ_TIMEOUT = 3.0


def _ts3_unescape(s: str) -> str:
    """Entfernt TS3-Protokoll-Escaping (\\s → Leerzeichen etc.)."""
    s = s.replace('\\\\', '\x00')
    s = s.replace(r'\s', ' ')
    s = s.replace(r'\p', '|')
    s = s.replace(r'\/', '/')
    s = s.replace(r'\n', '\n')
    s = s.replace('\x00', '\\')
    return s


def _find_api_key() -> str:
    """Liest den ClientQuery API-Key aus ~/.ts3client/clientquery.ini."""
    candidates = [
        Path("/home/tsbot/.ts3client/clientquery.ini"),
        Path.home() / ".ts3client" / "clientquery.ini",
    ]
    for path in candidates:
        if path.exists():
            for line in path.read_text().splitlines():
                if line.startswith("api_key="):
                    return line.split("=", 1)[1].strip()
    return os.environ.get("TS_CLIENT_API_KEY", "")


def _read_response(s: socket.socket, timeout: float = _CQ_TIMEOUT) -> str:
    """Liest vom Socket bis 'error id=' erscheint oder Timeout."""
    s.settimeout(timeout)
    buf = b""
    while True:
        try:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b"error id=" in buf:
                break
        except socket.timeout:
            break
    return buf.decode("utf-8", errors="replace")


def _query(commands: list[str]) -> list[str]:
    """
    Öffnet eine kurze Socket-Verbindung zum ClientQuery-Plugin,
    authentifiziert sich und sendet die angegebenen Befehle.
    Gibt die Antworten als Liste zurück.
    """
    api_key = _find_api_key()
    if not api_key:
        raise RuntimeError("ClientQuery API-Key nicht gefunden.")

    s = socket.create_connection((_CQ_HOST, _CQ_PORT), timeout=_CQ_TIMEOUT)
    try:
        _read_response(s)  # Welcome-Banner
        s.sendall(f"auth apikey={api_key}\n".encode())
        _read_response(s)  # Auth-Antwort

        responses = []
        for cmd in commands:
            s.sendall(f"{cmd}\n".encode())
            responses.append(_read_response(s))

        s.sendall(b"quit\n")
    finally:
        try:
            s.close()
        except Exception:
            pass
    return responses


class TSClientMonitor:
    """
    Überwacht den TS3-Client via persistenter ClientQuery-Verbindung.

    Erkennt:
    - notifyclientmoved  → Bot wurde in anderen Kanal verschoben → on_moved(new_channel_id)
    - notifyclientkicked → Bot vom Server gekickt               → on_kicked()
    - notifyconnectstatuschange status=disconnected              → on_kicked()
    """

    def __init__(self,
                 on_moved:  "Callable[[int], None] | None" = None,
                 on_kicked: "Callable[[], None] | None"    = None,
                 recording_start: float = None):
        self._on_moved  = on_moved   # callback(new_channel_id: int)
        self._on_kicked = on_kicked  # callback()
        self._running   = False
        self._thread: threading.Thread | None = None
        self._own_clid: int | None = None

        # Talk-Status-Tracking
        self._recording_start  = recording_start or time.time()
        self._talk_log:        list = []   # [{clid, name, start_sec, end_sec}]
        self._current_talkers: dict = {}   # clid → abs_start_time
        self._clid_names:      dict = {}   # clid → display name (Cache)

    def start(self):
        """Startet den Monitor-Thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="ts-monitor"
        )
        self._thread.start()
        logger.info("TSClientMonitor gestartet.")

    def stop(self):
        """Beendet den Monitor-Thread (nicht-blockierend)."""
        self._running = False
        logger.info("TSClientMonitor gestoppt.")

    # ── Interner Monitor-Loop ──────────────────────────────────

    def _monitor_loop(self):
        api_key = _find_api_key()
        if not api_key:
            logger.error("TSClientMonitor: API-Key nicht gefunden – Monitoring deaktiviert.")
            return

        try:
            s = socket.create_connection((_CQ_HOST, _CQ_PORT), timeout=10)
        except Exception as e:
            logger.error("TSClientMonitor: Verbindung zu ClientQuery fehlgeschlagen: %s", e)
            return

        try:
            _read_response(s)  # Banner
            s.sendall(f"auth apikey={api_key}\n".encode())
            _read_response(s)

            # Kurz warten bis TS3-Client vollständig mit Server verbunden ist
            time.sleep(3)
            if not self._running:
                return  # Session bereits gestoppt während dem Sleep

            # Eigene Client-ID ermitteln
            s.sendall(b"whoami\n")
            resp = _read_response(s)
            m = re.search(r'\bclid=(\d+)', resp)
            if m:
                self._own_clid = int(m.group(1))
                logger.info("TSClientMonitor: Eigene Client-ID: %d", self._own_clid)
            else:
                logger.warning(
                    "TSClientMonitor: Client-ID nicht ermittelbar (%s) – alle Move-Events werden verarbeitet.",
                    resp[:80]
                )

            # Events für alle Aktionen auf Server-Verbindung 1 registrieren
            s.sendall(b"clientnotifyregister schandlerid=1 event=any\n")
            _read_response(s)
            logger.info("TSClientMonitor: Event-Monitoring aktiv (clid=%s).", self._own_clid)

            # Clientnamen vorab cachen (für Talk-Status-Zuordnung)
            s.sendall(b"clientlist\n")
            cl_resp = _read_response(s)
            for part in cl_resp.split("|"):
                m_cl = re.search(r'\bclid=(\d+)', part)
                m_nn = re.search(r'\bclient_nickname=(\S+)', part)
                if m_cl and m_nn:
                    self._clid_names[int(m_cl.group(1))] = _ts3_unescape(m_nn.group(1))
            logger.debug("TSClientMonitor: %d Clientnamen gecacht.", len(self._clid_names))

            # Event-Loop: kurzer Timeout damit _running-Flag zeitnah geprüft wird
            s.settimeout(2.0)
            buf = ""
            _last_keepalive = time.time()
            while self._running:
                try:
                    chunk = s.recv(4096).decode("utf-8", errors="replace")
                    if not chunk:
                        logger.warning("TSClientMonitor: Verbindung unerwartet geschlossen.")
                        self._fire_kicked()
                        break
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.rstrip("\r").strip()
                        if line:
                            self._process_event(line)
                except socket.timeout:
                    # Keepalive alle 60s senden damit ClientQuery-Timeout (600s) nicht greift
                    if time.time() - _last_keepalive >= 60:
                        s.sendall(b"whoami\n")
                        _last_keepalive = time.time()
                    continue
                except Exception as e:
                    if self._running:
                        logger.error("TSClientMonitor: Fehler im Event-Loop: %s", e)
                        self._fire_kicked()
                    break
        finally:
            try:
                s.close()
            except Exception:
                pass

    def _process_event(self, line: str):
        if not self._running:
            return
        logger.debug("CQ-Event: %s", line[:140])

        if line.startswith("notifyclientmoved"):
            m_clid = re.search(r'\bclid=(\d+)', line)
            m_ctid = re.search(r'\bctid=(\d+)', line)
            if m_clid and m_ctid:
                clid = int(m_clid.group(1))
                ctid = int(m_ctid.group(1))
                if self._own_clid is None or clid == self._own_clid:
                    logger.info("TSClientMonitor: Bot in Kanal %d verschoben.", ctid)
                    if self._on_moved:
                        self._on_moved(ctid)

        elif line.startswith("notifyclientkicked"):
            m_clid = re.search(r'\bclid=(\d+)', line)
            if m_clid:
                clid = int(m_clid.group(1))
                if self._own_clid is None or clid == self._own_clid:
                    logger.info("TSClientMonitor: Bot vom Server gekickt (notifyclientkicked).")
                    self._fire_kicked()

        elif line.startswith("notifytalkstatuschange"):
            m_clid   = re.search(r'\bclid=(\d+)', line)
            m_status = re.search(r'\bstatus=(\d+)', line)
            if m_clid and m_status:
                clid   = int(m_clid.group(1))
                status = int(m_status.group(1))
                if clid == self._own_clid:
                    return  # Bot selbst ignorieren
                if status == 1:
                    self._current_talkers[clid] = time.time()
                elif status == 0:
                    start_abs = self._current_talkers.pop(clid, None)
                    if start_abs is not None:
                        rel_start = start_abs - self._recording_start
                        rel_end   = time.time() - self._recording_start
                        if rel_start >= 0:
                            self._talk_log.append({
                                "clid":      clid,
                                "name":      self._get_client_name(clid),
                                "start_sec": round(rel_start, 1),
                                "end_sec":   round(rel_end, 1),
                            })

        elif "notifyconnectstatuschange" in line and "status=disconnected" in line:
            logger.info("TSClientMonitor: Verbindungsstatus = disconnected.")
            self._fire_kicked()

    def _get_client_name(self, clid: int) -> str:
        """Gibt den Anzeigenamen für eine Client-ID zurück (gecacht oder per Query)."""
        if clid in self._clid_names:
            return self._clid_names[clid]
        try:
            resp = _query([f"clientinfo clid={clid}"])
            if resp:
                m = re.search(r'\bclient_nickname=(\S+)', resp[0])
                if m:
                    name = _ts3_unescape(m.group(1))
                    self._clid_names[clid] = name
                    return name
        except Exception:
            pass
        return f"clid{clid}"

    def get_talk_log(self) -> list:
        """Gibt den Talk-Log zurück; laufende Gespräche werden mit aktuellem Zeitpunkt abgeschlossen."""
        now = time.time()
        result = list(self._talk_log)
        for clid, start_abs in self._current_talkers.items():
            rel_start = start_abs - self._recording_start
            rel_end   = now - self._recording_start
            if rel_start >= 0:
                result.append({
                    "clid":      clid,
                    "name":      self._get_client_name(clid),
                    "start_sec": round(rel_start, 1),
                    "end_sec":   round(rel_end, 1),
                })
        return sorted(result, key=lambda x: x["start_sec"])

    def _fire_kicked(self):
        """Ruft on_kicked genau einmal auf (auch bei mehreren Trigger-Events)."""
        if not self._running:
            return
        self._running = False  # Verhindert Doppel-Trigger
        if self._on_kicked:
            self._on_kicked()


class TSClientControl:
    """Verbindet und trennt den TS3 Client über das ClientQuery-Plugin."""

    def __init__(self):
        self._server_addr = os.environ.get("TS_HOST", "ts3.friesenflieger.de")
        self._server_port = int(os.environ.get("TS_PORT", "9987"))
        self._server_pass = os.environ.get("TS_SERVER_PASS", "")
        self._nickname    = os.environ.get("TS_NICKNAME", "FriesenFliegerBot")
        self._own_clid: str | None = None  # gecacht nach erstem whoami

    def connect(self, channel_id: int = 0) -> bool:
        """
        Verbindet den TS3 Client mit dem konfigurierten Server und Kanal.
        Trennt zuerst eine bestehende Verbindung (falls vorhanden).
        """
        try:
            try:
                _query(["disconnect"])
                time.sleep(1.5)
            except Exception:
                pass

            cmd = (
                f"connect address={self._server_addr} port={self._server_port} "
                f"nickname={self._nickname}"
            )
            if self._server_pass:
                cmd += f" password={self._server_pass}"

            resp = _query([cmd])
            ok = resp and "error id=0" in resp[0]
            if not ok:
                logger.warning("TS3 Client connect Antwort: %s", resp)
                return False

            logger.info(
                "TS3 Client verbunden: %s:%d",
                self._server_addr, self._server_port,
            )

            # Kanal per clientmove ansteuern (connect channel= erwartet Namen, nicht ID)
            if channel_id:
                time.sleep(3)  # Warten bis Client vollständig verbunden ist
                moved = self.move_to_channel(channel_id)
                if moved:
                    logger.info("Bot in Zielkanal %d verschoben.", channel_id)
                else:
                    logger.warning("Kanalwechsel zu %d fehlgeschlagen – Bot bleibt im Standard-Kanal.", channel_id)

            return True
        except Exception as e:
            logger.error("TS3 Client connect fehlgeschlagen: %s", e)
            return False

    def disconnect(self) -> bool:
        """Trennt den TS3 Client vom Server."""
        try:
            resp = _query(["disconnect"])
            ok = resp and "error id=0" in resp[0]
            if ok:
                logger.info("TS3 Client getrennt.")
            return ok
        except Exception as e:
            logger.error("TS3 Client disconnect fehlgeschlagen: %s", e)
            return False

    def move_to_channel(self, channel_id: int) -> bool:
        """
        Bewegt den Bot in einen anderen Kanal (ohne Server-Reconnect).
        Gibt True zurück wenn die ClientQuery-Anfrage erfolgreich war.
        Eigene clid wird nach dem ersten Aufruf gecacht → nur 1 Socket-Verbindung nötig.
        """
        try:
            if not self._own_clid:
                # clid noch unbekannt → einmalig per whoami ermitteln und cachen
                resp = _query(["whoami"])
                m = re.search(r'\bclid=(\d+)', resp[0] if resp else "")
                if not m:
                    logger.warning("move_to_channel: Eigene Client-ID nicht ermittelbar.")
                    return False
                self._own_clid = m.group(1)

            # clid bekannt → direkt verschieben (1 Verbindung statt 2)
            resp = _query([f"clientmove clid={self._own_clid} cid={channel_id}"])
            ok = bool(resp and "error id=0" in resp[0])

            if ok:
                logger.info("Bot in Kanal %d verschoben.", channel_id)
            else:
                logger.warning("clientmove Antwort: %s", resp)
            return ok
        except Exception as e:
            logger.error("move_to_channel fehlgeschlagen: %s", e)
            return False

    def is_connected(self) -> bool:
        """Gibt True zurück wenn der Client mit einem Server verbunden ist."""
        try:
            resp = _query(["channellist"])
            return bool(resp and "error id=0" in resp[0] and "cid=" in resp[0])
        except Exception:
            return False
