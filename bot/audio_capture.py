#!/usr/bin/env python3
"""
Segmentierte Audio-Aufnahme über PulseAudio Null-Sink.

Nimmt in rollierenden Segmenten auf (audio_001.mp3, audio_002.mp3, …).
Ein Watchdog erkennt eingefrorene ffmpeg-Prozesse und rotiert automatisch
auf ein neues Segment.
"""

import os
import time
import asyncio
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Standard-Sink aus Umgebungsvariable oder Fallback
DEFAULT_SINK = os.environ.get("PULSE_SINK", "tsbot_sink")

# Standard-Segment-Dauer in Sekunden (10 Minuten)
DEFAULT_SEGMENT_DURATION = int(os.environ.get("SEGMENT_DURATION", "600"))


class SegmentedAudioCapture:
    """
    Startet und verwaltet eine segmentierte ffmpeg-Aufnahme vom PulseAudio-Monitor.

    Segmente: audio_001.mp3, audio_002.mp3, …
    Rotation:  planmäßig alle `segment_duration` Sekunden + Freeze-Watchdog (60s).
    Overlap:   1,5 s – neues Segment startet vor Stop des alten → kein Gap.
    """

    def __init__(self, session_dir: Path, segment_duration: int = None, sink_name: str = None):
        self._session_dir      = Path(session_dir)
        self._segment_duration = segment_duration or DEFAULT_SEGMENT_DURATION
        self._sink_name        = sink_name or DEFAULT_SINK

        self._segment_index    = 0           # zuletzt gestarteter Index (1-basiert)
        self._current_process: subprocess.Popen | None = None
        self._current_path:    Path | None = None

        self._completed_segments: list[Path] = []

        self._watchdog_task: asyncio.Task | None = None
        self._rotate_task:   asyncio.Task | None = None
        self._freeze_callback = None
        self._rotating        = False        # verhindert gleichzeitige Rotationen
        self._last_segment_start: float = 0.0  # Zeitstempel des letzten Segment-Starts
        self._use_realtime    = self._check_realtime_sched()

    # ── Öffentliche API ───────────────────────────────────────

    async def start(self, freeze_callback=None) -> None:
        """Startet erstes Segment, Watchdog und Rotations-Timer."""
        self._prüfe_sink()
        self._freeze_callback = freeze_callback
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._start_new_segment()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        self._rotate_task   = asyncio.create_task(self._rotation_loop())

    async def stop(self) -> list[Path]:
        """
        Stoppt alle Tasks und finalisiert das laufende Segment.
        Gibt alle abgeschlossenen Segment-Pfade zurück.
        """
        # Tasks abbrechen
        for task in (self._watchdog_task, self._rotate_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._watchdog_task = None
        self._rotate_task   = None

        # Aktuelles Segment finalisieren
        if self._current_process:
            path = self._stop_process(self._current_process, self._current_path)
            if path:
                self._completed_segments.append(path)
                logger.info("Letztes Segment abgeschlossen: %s (%.1f MB)",
                            path.name, path.stat().st_size / 1_048_576)
            self._current_process = None
            self._current_path    = None

        return list(self._completed_segments)

    async def rotate_segment(self, reason: str = "planmäßig") -> None:
        """
        Rotiert auf ein neues Segment mit 1,5 s Überlappung:
        1. Neues ffmpeg starten
        2. 1,5 Sekunden warten (beide Prozesse laufen)
        3. Altes ffmpeg stoppen und als abgeschlossen registrieren
        """
        if self._rotating:
            logger.debug("Rotation bereits aktiv – überspringe.")
            return
        self._rotating = True
        try:
            logger.info("Segment-Rotation (%s): starte audio_%03d.mp3",
                        reason, self._segment_index + 1)

            # Alten Prozess merken
            old_process = self._current_process
            old_path    = self._current_path

            # Neues Segment sofort starten
            self._start_new_segment()

            # 1,5 s Overlap – beide Prozesse laufen gleichzeitig → kein Gap
            await asyncio.sleep(1.5)

            # Altes Segment beenden und speichern
            if old_process:
                path = self._stop_process(old_process, old_path)
                if path:
                    self._completed_segments.append(path)
                    logger.info("Segment %s abgeschlossen (%.1f MB).",
                                path.name, path.stat().st_size / 1_048_576)
        finally:
            self._rotating = False

    # ── Eigenschaften ─────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return (self._current_process is not None
                and self._current_process.poll() is None)

    @property
    def segment_count(self) -> int:
        """Anzahl abgeschlossener Segmente."""
        return len(self._completed_segments)

    @property
    def current_segment_nr(self) -> int:
        """Nummer des aktuell laufenden Segments (1-basiert)."""
        return self._segment_index

    @property
    def current_segment_size_mb(self) -> float:
        """Dateigröße des aktuellen Segments in MB."""
        if self._current_path and self._current_path.exists():
            return self._current_path.stat().st_size / 1_048_576
        return 0.0

    # ── Interne Methoden ──────────────────────────────────────

    @staticmethod
    def _check_realtime_sched() -> bool:
        """Prüft ob chrt -f (SCHED_FIFO) verfügbar ist (CAP_SYS_NICE effektiv)."""
        try:
            result = subprocess.run(
                ["chrt", "-f", "50", "true"],
                capture_output=True,
            )
            if result.returncode == 0:
                logger.info("Echtzeit-Scheduling verfügbar (chrt -f 50).")
                return True
        except FileNotFoundError:
            pass
        logger.warning("chrt -f nicht verfügbar – ffmpeg läuft ohne Echtzeit-Scheduling "
                       "(CAP_SYS_NICE fehlt oder chrt nicht installiert).")
        return False

    def _start_new_segment(self) -> None:
        """Startet einen neuen ffmpeg-Prozess für das nächste Segment."""
        self._segment_index += 1
        path = self._session_dir / f"audio_{self._segment_index:03d}.mp3"

        prefix = ["chrt", "-f", "50"] if self._use_realtime else []
        cmd = prefix + [
            "ffmpeg",
            "-f", "pulse",
            "-i", f"{self._sink_name}.monitor",
            "-acodec", "libmp3lame",
            "-ar", "16000",
            "-ac", "1",
            "-ab", "32k",
            "-fflags", "+flush_packets",   # sofort auf Disk schreiben → Watchdog sieht echten Stand
            "-y",
            str(path),
        ]

        logger.info("Starte Segment %03d → %s", self._segment_index, path.name)
        self._last_segment_start = time.monotonic()

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._current_process = process
        self._current_path    = path
        logger.info("Segment %03d läuft (PID %d)", self._segment_index, process.pid)

    def _stop_process(self, process: subprocess.Popen,
                      path: Path | None) -> Path | None:
        """
        Stoppt einen ffmpeg-Prozess sauber über stdin 'q'.
        Gibt den Pfad zurück wenn die Datei existiert und nicht leer ist.
        """
        try:
            process.stdin.write(b"q\n")
            process.stdin.flush()
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg (PID %d) reagiert nicht – erzwinge Beendigung.",
                           process.pid)
            process.kill()
            process.wait()
        except (BrokenPipeError, OSError):
            pass  # Prozess bereits beendet

        if path and path.exists() and path.stat().st_size > 0:
            return path
        logger.warning("Segment-Datei fehlt oder leer: %s", path)
        return None

    async def _watchdog_loop(self) -> None:
        """
        Alle 30 s Dateigröße des aktuellen Segments prüfen.
        Nach 60 s ohne Wachstum (2 aufeinanderfolgende Prüfungen) → Freeze erkannt
        → Segment rotieren + freeze_callback aufrufen.

        Schonfrist: 90 s nach Segment-Start werden keine Freeze-Checks durchgeführt,
        da ffmpeg erst puffern muss und die Datei anfangs bei 0 Bytes verweilen kann.
        """
        last_size    = -1
        frozen_count = 0

        while True:
            await asyncio.sleep(30)

            if not self._current_path or not self._current_path.exists():
                last_size    = -1
                frozen_count = 0
                continue

            # Schonfrist: nach Segment-Start 90 s nicht prüfen
            age = time.monotonic() - self._last_segment_start
            if age < 90:
                last_size    = -1
                frozen_count = 0
                continue

            size = self._current_path.stat().st_size
            if size == last_size and last_size >= 0:
                frozen_count += 1
                logger.warning(
                    "Watchdog: %s nicht gewachsen (%d/2), Größe=%d B",
                    self._current_path.name, frozen_count, size,
                )
                if frozen_count >= 2:
                    logger.warning("Freeze erkannt – rotiere Segment automatisch.")
                    if self._freeze_callback:
                        asyncio.create_task(self._freeze_callback())
                    await self.rotate_segment("freeze")
                    frozen_count = 0
                    last_size    = -1
            else:
                last_size    = size
                frozen_count = 0

    async def _rotation_loop(self) -> None:
        """Planmäßige Rotation alle segment_duration Sekunden."""
        while True:
            await asyncio.sleep(self._segment_duration)
            await self.rotate_segment("planmäßig")

    def _prüfe_sink(self) -> None:
        """Prüft ob der konfigurierte PulseAudio-Sink existiert."""
        result = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            capture_output=True, text=True,
        )
        if self._sink_name not in result.stdout:
            raise RuntimeError(
                f"PulseAudio-Sink '{self._sink_name}' nicht gefunden.\n"
                f"Bitte 'scripts/start_pulseaudio.sh' ausführen.\n"
                f"Verfügbare Sinks:\n{result.stdout}"
            )
