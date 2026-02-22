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

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/tsbot/data"))
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

        self._audio:   AudioCapture | None   = None
        self._tracker: TSQueryTracker | None = None
        self._executor = ThreadPoolExecutor(max_workers=1)

    # ── Öffentliche API ───────────────────────────────────────

    async def start_session(self, thema: str, agenda: list | None = None,
                            extra_instruktionen: str | None = None) -> str:
        """
        Startet eine neue Sitzung.

        Returns:
            session_id (Zeitstempel-String)
        Raises:
            RuntimeError wenn bereits eine Sitzung läuft
        """
        if self.state not in (State.IDLE, State.DONE, State.ERROR):
            raise RuntimeError(f"Sitzung läuft bereits (State: {self.state})")
        # Nach DONE/ERROR automatisch zurücksetzen
        self._reset()

        self.session_id  = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = DATA_DIR / "sessions" / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.thema       = thema
        self.started_at  = datetime.now()
        self.error_msg   = None

        # Agenda speichern (aus Parameter oder Datei)
        if agenda:
            agenda_file = self.session_dir / "agenda.txt"
            agenda_file.write_text("\n".join(agenda), encoding="utf-8")
            current_agenda = str(agenda_file)
        else:
            current_agenda = str(AGENDA_PATH) if AGENDA_PATH.exists() else None

        # Metadata
        meta = {
            "session_id":         self.session_id,
            "thema":              thema,
            "started_at":         self.started_at.isoformat(),
            "agenda":             agenda or [],
            "agenda_file":        current_agenda,
            "extra_instruktionen": extra_instruktionen or "",
        }
        (self.session_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # ServerQuery Tracker starten
        self._tracker = TSQueryTracker()
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
        logger.info("Session %s gestartet – State: RECORDING", self.session_id)
        return self.session_id

    async def stop_session(self) -> None:
        """
        Stoppt die Aufnahme und startet die Verarbeitung im Hintergrund.
        Der State wechselt sofort zu TRANSCRIBING; die Pipeline läuft async.
        """
        if self.state != State.RECORDING:
            raise RuntimeError(f"Keine aktive Aufnahme (State: {self.state})")

        # Audio stoppen
        audio_path = self._audio.stop()

        # Teilnehmer speichern
        participants = []
        if self._tracker:
            participants = self._tracker.get_participant_list()
            self._tracker.stop()
        (self.session_dir / "participants.json").write_text(
            json.dumps(participants, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("%d Teilnehmer gespeichert.", len(participants))

        self.state = State.TRANSCRIBING

        # Verarbeitung im Hintergrund
        asyncio.create_task(self._verarbeitungs_pipeline(audio_path, participants))

    def get_status(self) -> dict:
        """Gibt den aktuellen Status als Dict zurück (für /status Endpoint)."""
        duration_sec = None
        if self.started_at and self.state == State.RECORDING:
            duration_sec = int((datetime.now() - self.started_at).total_seconds())

        participant_count = 0
        if self._tracker:
            participant_count = len(self._tracker.get_participant_list())

        return {
            "state":             self.state,
            "session_id":        self.session_id,
            "thema":             self.thema,
            "started_at":        self.started_at.isoformat() if self.started_at else None,
            "duration_seconds":  duration_sec,
            "participant_count": participant_count,
            "error":             self.error_msg,
        }

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

            # Agenda-Datei ermitteln
            meta_raw = (self.session_dir / "meta.json").read_text(encoding="utf-8")
            meta = json.loads(meta_raw)
            agenda_file = meta.get("agenda_file")

            await loop.run_in_executor(
                self._executor,
                self._erstelle_protokoll_sync,
                transcript_path,
                meta["thema"],
                agenda_file,
                participants,
                meta.get("extra_instruktionen", ""),
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
                                  extra_instruktionen: str = ""):
        """Synchroner Protokoll-Generator (läuft im ThreadPoolExecutor)."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
        from protokoll_erstellen import erstelle_protokoll

        erstelle_protokoll(
            transkript_pfad     = str(transcript_path),
            thema               = thema,
            agenda_pfad         = agenda_file,
            teilnehmer_liste    = participants,
            extra_instruktionen = extra_instruktionen or None,
        )

    def _reset(self):
        """Setzt den internen Zustand für eine neue Session zurück."""
        self.session_id  = None
        self.session_dir = None
        self.thema       = ""
        self.started_at  = None
        self.error_msg   = None
        self._audio      = None
        self._tracker    = None
