#!/usr/bin/env python3
"""
TSClientControl – Steuert den laufenden TS3 Linux Client via ClientQuery-Plugin.

Das ClientQuery-Plugin hört auf 127.0.0.1:25639 und akzeptiert Befehle über
eine telnet-ähnliche Verbindung.
"""

import os
import socket
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_CQ_HOST    = "127.0.0.1"
_CQ_PORT    = 25639
_CQ_TIMEOUT = 8.0


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
    s.settimeout(_CQ_TIMEOUT)

    def recv_until_error() -> str:
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

    try:
        recv_until_error()  # Welcome-Banner
        s.sendall(f"auth apikey={api_key}\n".encode())
        recv_until_error()  # auth response

        responses = []
        for cmd in commands:
            s.sendall(f"{cmd}\n".encode())
            responses.append(recv_until_error())

        s.sendall(b"quit\n")
    finally:
        try:
            s.close()
        except Exception:
            pass

    return responses


class TSClientControl:
    """Verbindet und trennt den TS3 Client über das ClientQuery-Plugin."""

    def __init__(self):
        self._server_addr = os.environ.get("TS_HOST", "ts3.friesenflieger.de")
        self._server_port = int(os.environ.get("TS_PORT", "9987"))
        self._server_pass = os.environ.get("TS_SERVER_PASS", "")
        self._nickname    = os.environ.get("TS_NICKNAME", "FriesenFliegerBot")

    def connect(self, channel_id: int = 0) -> bool:
        """
        Verbindet den TS3 Client mit dem konfigurierten Server und Kanal.
        Trennt zuerst eine bestehende Verbindung (falls vorhanden).
        """
        try:
            # Bestehende Verbindung trennen
            try:
                _query(["disconnect"])
                time.sleep(1.5)
            except Exception:
                pass

            # Verbinden
            cmd = (
                f"connect address={self._server_addr} port={self._server_port} "
                f"nickname={self._nickname}"
            )
            if self._server_pass:
                cmd += f" password={self._server_pass}"
            if channel_id:
                cmd += f" channel={channel_id}"

            resp = _query([cmd])
            ok = resp and "error id=0" in resp[0]
            if ok:
                logger.info(
                    "TS3 Client verbunden: %s:%d Kanal %d",
                    self._server_addr, self._server_port, channel_id,
                )
            else:
                logger.warning("TS3 Client connect Antwort: %s", resp)
            return ok
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

    def is_connected(self) -> bool:
        """Gibt True zurück wenn der Client mit einem Server verbunden ist."""
        try:
            resp = _query(["channellist"])
            return bool(resp and "error id=0" in resp[0] and "cid=" in resp[0])
        except Exception:
            return False
