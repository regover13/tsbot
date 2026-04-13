#!/usr/bin/env python3
"""
Audio-Aufnahme über PulseAudio Null-Sink.

Nutzt ffmpeg mit PulseAudio-Backend, um den tsbot_sink.monitor
(Loopback der TeamSpeak-Audioausgabe) als MP3 aufzuzeichnen.
"""

import os
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Standard-Sink aus Umgebungsvariable oder Fallback
DEFAULT_SINK = os.environ.get("PULSE_SINK", "tsbot_sink")


class AudioCapture:
    """Startet und stoppt eine ffmpeg-Aufnahme vom PulseAudio-Monitor."""

    def __init__(self, output_path: Path, sink_name: str = None):
        self._output_path = Path(output_path)
        self._sink_name   = sink_name or DEFAULT_SINK
        self._process: subprocess.Popen | None = None

    # ── Öffentliche API ───────────────────────────────────────

    def start(self):
        """Startet die Aufnahme. Wirft RuntimeError, wenn ffmpeg fehlt oder der Sink nicht existiert."""
        self._prüfe_sink()

        cmd = [
            "ffmpeg",
            "-f", "pulse",
            "-i", f"{self._sink_name}.monitor",
            "-acodec", "libmp3lame",
            "-ab", "64k",
            "-y",                          # Ausgabedatei überschreiben
            str(self._output_path),
        ]
        logger.info("Starte Aufnahme: %s", " ".join(cmd))

        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,  # PIPE würde den 64KB-Buffer in ~21 min füllen (ffmpeg 7.x)
        )
        logger.info("Aufnahme läuft (PID %d) → %s", self._process.pid, self._output_path)

    def stop(self) -> Path:
        """
        Stoppt die Aufnahme sauber über ffmpeg's 'q'-Befehl.
        Gibt den Pfad zur erzeugten MP3-Datei zurück.
        """
        if self._process is None:
            raise RuntimeError("Aufnahme läuft nicht.")

        logger.info("Stoppe Aufnahme (sende 'q' an ffmpeg)...")
        try:
            self._process.stdin.write(b"q\n")
            self._process.stdin.flush()
            self._process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg reagiert nicht – erzwinge Beendigung.")
            self._process.kill()
            self._process.wait()
        except BrokenPipeError:
            # ffmpeg kann bereits beendet sein
            pass
        finally:
            self._process = None

        if not self._output_path.exists():
            raise RuntimeError(f"Ausgabedatei nicht erzeugt: {self._output_path}")

        logger.info("Aufnahme beendet → %s (%.1f MB)",
                    self._output_path,
                    self._output_path.stat().st_size / 1_048_576)
        return self._output_path

    @property
    def is_recording(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # ── Interne Methoden ──────────────────────────────────────

    def _prüfe_sink(self):
        """Prüft, ob der konfigurierte PulseAudio-Sink existiert."""
        result = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            capture_output=True, text=True
        )
        if self._sink_name not in result.stdout:
            raise RuntimeError(
                f"PulseAudio-Sink '{self._sink_name}' nicht gefunden.\n"
                f"Bitte 'scripts/start_pulseaudio.sh' ausführen.\n"
                f"Verfügbare Sinks:\n{result.stdout}"
            )
