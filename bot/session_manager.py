#!/usr/bin/env python3
"""
Session Manager – Zustandsmaschine für eine Aufnahme-Session.

States:
    IDLE → RECORDING → TRANSCRIBING → GENERATING → DONE / ERROR
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from enum import Enum
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from bot.audio_capture import AudioCapture
from bot.ts_query import TSQueryTracker
from bot.ts_client_control import TSClientControl, TSClientMonitor

logger = logging.getLogger(__name__)

DATA_DIR    = Path(os.environ.get("DATA_DIR",    "/opt/tsbot/data"))
AGENDA_PATH = Path(os.environ.get("AGENDA_PATH", "/opt/tsbot/data/agenda.txt"))


class State(str, Enum):
    IDLE         = "IDLE"
    RECORDING    = "RECORDING"
    TRANSCRIBING = "TRANSCRIBING"
    GENERATING   = "GENERATING"
    DONE         = "DONE"
    ERROR        = "ERROR"


class SessionManager:
    """
    Koordiniert Aufnahme, Transkription und Protokollerstellung.
    Eine Instanz ist als Singleton im FastAPI-App-Zustand gespeichert.
    """

    def __init__(self):
        self.state:      State    = State.IDLE
        self.session_id: str | None = None
        self.session_dir: Path | None = None
        self.thema:      str      = ""
        self.started_at: datetime | None = None
        self.error_msg:  str | None = None

        self._audio:     AudioCapture | None    = None
        self._tracker:   TSQueryTracker | None  = None
        self._ts_client: TSClientControl | None = None
        self._monitor:   TSClientMonitor | None = None
        self._executor = ThreadPoolExecutor(max_workers=1)

        # Kanalwechsel-Tracking
        self._current_channel_id: int  = 0
        self._channel_events:    list  = []
        self._kicked_triggered:  bool  = False
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── Öffentliche API ───────────────────────────────────────

    async def start_session(self, thema: str, agenda: list | None = None,
                            extra_instruktionen: str | None = None,
                            channel_id: int | None = None) -> str:
        """
        Startet eine neue Sitzung.

        Returns:
            session_id (Zeitstempel-String)
        Raises:
            RuntimeError wenn bereits eine Sitzung läuft
        """
        if self.state not in (State.IDLE, State.DONE, State.ERROR):
            raise RuntimeError(f"Sitzung läuft bereits (State: {self.state})")
        self._reset()

        self.session_id  = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = DATA_DIR / "sessions" / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.thema       = thema
        self.started_at  = datetime.now()
        self.error_msg   = None
        self._loop       = asyncio.get_running_loop()

        cid = channel_id or int(os.environ.get("TS_CHANNEL_ID", "0"))
        self._current_channel_id = cid
        self._channel_events     = []
        self._kicked_triggered   = False

        # Agenda speichern (aus Parameter oder Datei)
        if agenda:
            agenda_file = self.session_dir / "agenda.txt"
            agenda_file.write_text("\n".join(agenda), encoding="utf-8")
            current_agenda = str(agenda_file)
        else:
            current_agenda = str(AGENDA_PATH) if AGENDA_PATH.exists() else None

        # Metadata
        meta = {
            "session_id":          self.session_id,
            "thema":               thema,
            "started_at":          self.started_at.isoformat(),
            "agenda":              agenda or [],
            "agenda_file":         current_agenda,
            "extra_instruktionen": extra_instruktionen or "",
            "channel_id":          cid,
            "channel_events":      [],
        }
        (self.session_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # TS3 Client verbinden
        self._ts_client = TSClientControl()
        try:
            self._ts_client.connect(cid)
            # Monitor nach dem Verbinden starten
            self._monitor = TSClientMonitor(
                on_moved=self._on_channel_moved,
                on_kicked=self._on_kicked,
            )
            self._monitor.start()
        except Exception as e:
            logger.warning("TS3 Client-Verbindung fehlgeschlagen: %s", e)

        # ServerQuery Tracker starten
        self._tracker = TSQueryTracker(channel_id=cid)
        try:
            self._tracker.start()
        except Exception as e:
            logger.warning("ServerQuery nicht verfügbar: %s – Tracker deaktiviert.", e)
            self._tracker = None

        # Audio-Aufnahme starten
        audio_path = self.session_dir / "audio.mp3"
        self._audio = AudioCapture(audio_path)
        self._audio.start()

        self.state = State.RECORDING
        logger.info("Session %s gestartet – State: RECORDING (Kanal %d)", self.session_id, cid)
        return self.session_id

    async def stop_session(self) -> None:
        """
        Stoppt die Aufnahme und startet die Verarbeitung im Hintergrund.
        """
        if self.state != State.RECORDING:
            raise RuntimeError(f"Keine aktive Aufnahme (State: {self.state})")

        # Monitor VOR dem Disconnect stoppen – verhindert dass der Disconnect
        # nochmals einen on_kicked-Callback auslöst
        if self._monitor:
            self._monitor.stop()
            self._monitor = None

        # Audio stoppen
        audio_path = self._audio.stop()

        # Teilnehmer pro Kanal speichern
        participants = []
        participants_by_channel = {}
        if self._tracker:
            # Kanal-ID → Name Mapping aus Channel-Events aufbauen
            channel_names = {}
            for evt in self._channel_events:
                channel_names[evt["from_channel"]] = evt.get("from_channel_name", str(evt["from_channel"]))
                channel_names[evt["to_channel"]]   = evt.get("to_channel_name",   str(evt["to_channel"]))
            # Aktuellen Kanal ebenfalls eintragen
            cid = self._current_channel_id
            if cid not in channel_names:
                channel_names[cid] = str(cid)

            raw = self._tracker.get_participants_by_channel()
            for ch_id, parts in raw.items():
                ch_name = channel_names.get(ch_id, str(ch_id))
                participants_by_channel[ch_name] = parts
                participants.extend(parts)
            # Deduplizieren (gleiche Person in mehreren Kanälen)
            seen = set()
            unique = []
            for p in participants:
                key = p.get("frs") or p.get("name", "")
                if key not in seen:
                    seen.add(key)
                    unique.append(p)
            participants = unique
            self._tracker.stop()

        (self.session_dir / "participants.json").write_text(
            json.dumps(participants, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.session_dir / "participants_by_channel.json").write_text(
            json.dumps(participants_by_channel, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("%d Teilnehmer in %d Kanälen gespeichert.", len(participants), len(participants_by_channel))

        # TS3 Client trennen
        if self._ts_client:
            try:
                self._ts_client.disconnect()
            except Exception as e:
                logger.warning("TS3 Client-Trennung fehlgeschlagen: %s", e)
            self._ts_client = None

        self.state = State.TRANSCRIBING

        # Verarbeitung im Hintergrund
        asyncio.create_task(self._verarbeitungs_pipeline(audio_path, participants))

    async def switch_channel(self, new_channel_id: int) -> None:
        """
        Bewegt den Bot während einer Aufnahme manuell in einen anderen Kanal.
        Schaltet auch das Teilnehmer-Tracking auf den neuen Kanal um.

        Raises:
            RuntimeError wenn keine Aufnahme aktiv
        """
        if self.state != State.RECORDING:
            raise RuntimeError(f"Keine aktive Aufnahme (State: {self.state})")

        if self._ts_client:
            ok = self._ts_client.move_to_channel(new_channel_id)
            if ok:
                # Monitor wird notifyclientmoved empfangen und _handle_channel_move aufrufen
                logger.info("Bot-Kanalwechsel via ClientQuery angefordert → Kanal %d", new_channel_id)
                return
            logger.warning("move_to_channel fehlgeschlagen – direktes Tracking-Update")

        # Fallback: Tracker direkt umschalten ohne Bot-Bewegung
        await self._handle_channel_move(new_channel_id)

    def get_status(self) -> dict:
        """Gibt den aktuellen Status als Dict zurück (für /status Endpoint)."""
        duration_sec = None
        if self.started_at and self.state == State.RECORDING:
            duration_sec = int((datetime.now() - self.started_at).total_seconds())

        participant_count = 0
        if self._tracker:
            participant_count = len(self._tracker.get_participant_list())

        return {
            "state":              self.state,
            "session_id":         self.session_id,
            "thema":              self.thema,
            "started_at":         self.started_at.isoformat() if self.started_at else None,
            "duration_seconds":   duration_sec,
            "participant_count":  participant_count,
            "current_channel_id": self._current_channel_id if self.state == State.RECORDING else 0,
            "channel_events":     list(self._channel_events),
            "error":              self.error_msg,
        }

    # ── Kick / Move Callbacks (aus Monitor-Thread) ─────────────

    def _on_kicked(self):
        """Callback vom Monitor-Thread: Bot wurde vom Server gekickt."""
        if self.state != State.RECORDING:
            return
        if self._kicked_triggered:
            return
        self._kicked_triggered = True
        logger.warning("Bot vom Server gekickt – Session wird automatisch gestoppt.")
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._auto_stop(), self._loop)

    def _on_channel_moved(self, new_channel_id: int):
        """Callback vom Monitor-Thread: Bot wurde in anderen Kanal verschoben."""
        if self.state != State.RECORDING:
            return
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._handle_channel_move(new_channel_id), self._loop
            )

    async def _auto_stop(self):
        """Stoppt die Session automatisch nach einem Kick."""
        try:
            await self.stop_session()
        except RuntimeError:
            pass

    async def _handle_channel_move(self, new_channel_id: int):
        """Verarbeitet einen Kanalwechsel (intern oder extern ausgelöst)."""
        old_id = self._current_channel_id
        if old_id == new_channel_id:
            return  # Kein echter Wechsel

        # Kanalnamen auflösen
        old_name = str(old_id)
        new_name = str(new_channel_id)
        if self._tracker:
            try:
                old_name = await self._loop.run_in_executor(
                    None, self._tracker.get_channel_name, old_id
                )
                new_name = await self._loop.run_in_executor(
                    None, self._tracker.get_channel_name, new_channel_id
                )
            except Exception as e:
                logger.warning("Kanalnamen konnten nicht aufgelöst werden: %s", e)

        self._current_channel_id = new_channel_id
        event = {
            "type":             "channel_change",
            "from_channel":     old_id,
            "from_channel_name": old_name,
            "to_channel":       new_channel_id,
            "to_channel_name":  new_name,
            "timestamp":        datetime.now().isoformat(),
        }
        self._channel_events.append(event)

        # meta.json aktualisieren
        if self.session_dir:
            meta_path = self.session_dir / "meta.json"
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta["channel_events"] = self._channel_events
                meta_path.write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception as e:
                logger.warning("meta.json Kanalwechsel-Update fehlgeschlagen: %s", e)

        # Tracker auf neuen Kanal umschalten (in Thread-Pool, da Netzwerk-I/O)
        if self._tracker:
            try:
                await self._loop.run_in_executor(
                    None, self._tracker.switch_channel, new_channel_id
                )
            except Exception as e:
                logger.warning("Tracker switch_channel fehlgeschlagen: %s", e)

        logger.info("Kanalwechsel: %d → %d – Tracking umgeschaltet.", old_id, new_channel_id)

    # ── Interne Pipeline ──────────────────────────────────────

    async def _verarbeitungs_pipeline(self, audio_path: Path, participants: list):
        """Transkription → Protokollerstellung (läuft als asyncio Task)."""
        loop = asyncio.get_running_loop()

        try:
            # 1. Transkription (CPU-intensiv → ThreadPoolExecutor)
            logger.info("Starte Transkription...")
            self.state = State.TRANSCRIBING
            transcript_path = await loop.run_in_executor(
                self._executor,
                self._transkribiere_sync,
                audio_path,
            )

            # 2. Protokollerstellung
            logger.info("Starte Protokollerstellung...")
            self.state = State.GENERATING

            meta_raw = (self.session_dir / "meta.json").read_text(encoding="utf-8")
            meta = json.loads(meta_raw)
            agenda_file    = meta.get("agenda_file")
            channel_events = meta.get("channel_events", [])

            # participants_by_channel aus Datei laden (wurde von stop_session gespeichert)
            pbc_path = self.session_dir / "participants_by_channel.json"
            participants_by_channel = {}
            if pbc_path.exists():
                participants_by_channel = json.loads(pbc_path.read_text(encoding="utf-8"))

            await loop.run_in_executor(
                self._executor,
                self._erstelle_protokoll_sync,
                transcript_path,
                meta["thema"],
                agenda_file,
                participants,
                meta.get("extra_instruktionen", ""),
                channel_events,
                participants_by_channel,
            )

            self.state = State.DONE
            logger.info("Session %s abgeschlossen.", self.session_id)

        except Exception as e:
            logger.exception("Fehler in der Verarbeitungs-Pipeline:")
            self.error_msg = str(e)
            self.state = State.ERROR

    def _transkribiere_sync(self, audio_path: Path) -> Path:
        """Synchroner Whisper-Aufruf (läuft im ThreadPoolExecutor)."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
        from transkribieren import transkribiere

        result = transkribiere(str(audio_path), str(self.session_dir))
        return Path(result)

    def _erstelle_protokoll_sync(self, transcript_path: Path, thema: str,
                                  agenda_file: str | None, participants: list,
                                  extra_instruktionen: str = "",
                                  channel_events: list = None,
                                  participants_by_channel: dict = None):
        """Synchroner Protokoll-Generator (läuft im ThreadPoolExecutor)."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
        from protokoll_erstellen import erstelle_protokoll

        erstelle_protokoll(
            transkript_pfad         = str(transcript_path),
            thema                   = thema,
            agenda_pfad             = agenda_file,
            teilnehmer_liste        = participants,
            extra_instruktionen     = extra_instruktionen or None,
            kanal_wechsel           = channel_events or [],
            teilnehmer_pro_kanal    = participants_by_channel or {},
        )

    def _reset(self):
        """Setzt den internen Zustand für eine neue Session zurück."""
        self.session_id          = None
        self.session_dir         = None
        self.thema               = ""
        self.started_at          = None
        self.error_msg           = None
        self._audio              = None
        self._tracker            = None
        self._ts_client          = None
        self._monitor            = None
        self._current_channel_id = 0
        self._channel_events     = []
        self._kicked_triggered   = False
        self._loop               = None
