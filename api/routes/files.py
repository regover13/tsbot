"""
Protokoll-Endpoints: GET /protocols, GET /protocols/{session}/{file},
                     DELETE /protocols/{session},
                     POST /protocols/{session}/regenerate,
                     GET /protocols/{session}/regen-status,
                     POST /protocols/{session}/retranscribe,
                     GET /protocols/{session}/retranscribe-status
"""

import asyncio
import functools
import json
import os
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter()

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/tsbot/data"))

_regen_tasks: dict[str, dict] = {}  # {session_id: {"status": "running"|"done"|"error", "error": ""}}
_retranscribe_tasks: dict[str, dict] = {}  # {session_id: {"status": "running"|"done"|"error", "error": ""}}


class RegenerateRequest(BaseModel):
    extra_instruktionen: str = ""


@router.get("/", summary="Alle Protokolle auflisten")
async def list_protocols():
    """
    Gibt eine Liste aller abgeschlossenen Sessions mit ihren Protokoll-Dateien zurück.
    """
    sessions_dir = DATA_DIR / "sessions"
    if not sessions_dir.exists():
        return {"sessions": []}

    result = []
    for session_dir in sorted(sessions_dir.iterdir(), reverse=True):
        if not session_dir.is_dir():
            continue

        meta_file = session_dir / "meta.json"
        meta = {}
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))

        docx_files = sorted(session_dir.glob("Protokoll_*.docx"))
        transcript_files = sorted(session_dir.glob("*_transkript_*.txt"))
        # Segmentierte Aufnahmen (audio_001.mp3, …) + Fallback für alte Sessions (audio.mp3)
        audio_files = sorted(session_dir.glob("audio_*.mp3"))
        if not audio_files:
            audio_files = sorted(session_dir.glob("audio.mp3"))

        result.append({
            "session_id":          session_dir.name,
            "thema":               meta.get("thema", ""),
            "started_at":          meta.get("started_at", ""),
            "protokolle":          [f.name for f in docx_files],
            "transkripte":         [f.name for f in transcript_files],
            "audio":               [f.name for f in audio_files],
            "extra_instruktionen": meta.get("extra_instruktionen", ""),
        })

    return {"sessions": result}


async def _run_regen(session_id: str, session_dir: Path, extra_instruktionen: str):
    """Hintergrundaufgabe: Protokoll neu erstellen."""
    from core.protokoll_erstellen import erstelle_protokoll
    try:
        meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))

        transcript_files = sorted(session_dir.glob("*_transkript_*.txt"))
        if not transcript_files:
            raise ValueError("Kein Transkript gefunden.")
        transcript_path = transcript_files[-1]

        participants: list = []
        p_file = session_dir / "participants.json"
        if p_file.exists():
            participants = json.loads(p_file.read_text(encoding="utf-8"))

        participants_by_channel: dict = {}
        pbc_file = session_dir / "participants_by_channel.json"
        if pbc_file.exists():
            participants_by_channel = json.loads(pbc_file.read_text(encoding="utf-8"))

        agenda_file = meta.get("agenda_file")
        channel_events = meta.get("channel_events", [])

        fn = functools.partial(
            erstelle_protokoll,
            str(transcript_path),
            meta.get("thema", ""),
            agenda_file,
            participants,
            extra_instruktionen,
            channel_events,
            participants_by_channel,
        )
        await asyncio.get_running_loop().run_in_executor(None, fn)
        _regen_tasks[session_id] = {"status": "done", "error": ""}
    except Exception as e:
        _regen_tasks[session_id] = {"status": "error", "error": str(e)}


@router.post("/{session_id}/regenerate", summary="Protokoll neu erstellen")
async def regenerate_protocol(session_id: str, body: RegenerateRequest):
    """
    Erstellt das Word-Protokoll einer bestehenden Session neu (ohne neue Aufnahme).
    Transkript, Teilnehmer und Tagesordnung werden wiederverwendet.
    """
    if ".." in session_id or "/" in session_id:
        raise HTTPException(status_code=400, detail="Ungültige Session-ID.")

    session_dir = DATA_DIR / "sessions" / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="Session nicht gefunden.")

    if not sorted(session_dir.glob("*_transkript_*.txt")):
        raise HTTPException(status_code=422, detail="Kein Transkript vorhanden.")

    if _regen_tasks.get(session_id, {}).get("status") == "running":
        raise HTTPException(status_code=409, detail="Protokollerstellung läuft bereits.")

    # extra_instruktionen in meta.json aktualisieren
    meta_file = session_dir / "meta.json"
    meta: dict = {}
    if meta_file.exists():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    meta["extra_instruktionen"] = body.extra_instruktionen
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    _regen_tasks[session_id] = {"status": "running", "error": ""}
    asyncio.create_task(_run_regen(session_id, session_dir, body.extra_instruktionen))
    return {"message": "Protokollerstellung gestartet."}


@router.get("/{session_id}/regen-status", summary="Regenerierungs-Status abfragen")
async def regen_status(session_id: str):
    """Gibt den aktuellen Status der Protokoll-Neuerstellung zurück."""
    return _regen_tasks.get(session_id, {"status": "idle", "error": ""})


async def _run_retranscribe(session_id: str, session_dir: Path):
    """Hintergrundaufgabe: Transkription aus Audio-Segmenten neu starten."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core"))
    from transkribieren import transkribiere_mehrere
    try:
        audio_paths = sorted(session_dir.glob("audio_*.mp3"))
        if not audio_paths:
            audio_paths = sorted(session_dir.glob("audio.mp3"))
        if not audio_paths:
            raise ValueError("Keine Audio-Dateien gefunden.")

        total_segments = len(audio_paths)
        # Vorab-Schätzung: 32 kbps mono → 4000 Bytes/s Audiodauer → ~1.3× Echtzeit auf CPU
        total_bytes = sum(p.stat().st_size for p in audio_paths)
        estimated_eta = round(total_bytes / 4000 * 1.3)
        _retranscribe_tasks[session_id].update({
            "current_segment": 0,
            "total_segments": total_segments,
            "eta_sec": estimated_eta,
        })

        def _progress(current, total, elapsed, eta):
            _retranscribe_tasks[session_id].update({
                "current_segment": current,
                "total_segments": total,
                "eta_sec": round(eta),
            })

        fn = functools.partial(
            transkribiere_mehrere,
            [str(p) for p in audio_paths],
            str(session_dir),
            progress_callback=_progress,
        )
        transcript_path = Path(await asyncio.get_running_loop().run_in_executor(None, fn))

        # Sprecher-Annotation falls Talk-Log vorhanden
        talk_log_path = session_dir / "talk_log.json"
        if talk_log_path.exists():
            talk_log = json.loads(talk_log_path.read_text(encoding="utf-8"))
            if talk_log:
                def _annotate():
                    def dominant_speaker(start_sec, end_sec):
                        overlaps: dict = {}
                        for entry in talk_log:
                            overlap = min(end_sec, entry["end_sec"]) - max(start_sec, entry["start_sec"])
                            if overlap > 0:
                                raw = entry["name"].split("/")[0].strip()
                                raw = re.sub(r'\s*\(.*?\)', '', raw).strip()
                                raw = re.sub(r'\s+FRS\w+.*$', '', raw).strip()
                                overlaps[raw] = overlaps.get(raw, 0) + overlap
                        return max(overlaps, key=overlaps.get) if overlaps else ""

                    seg_re = re.compile(r'\[(\d{2}):(\d{2}) - (\d{2}):(\d{2})\] (.+)')
                    lines = transcript_path.read_text(encoding="utf-8").splitlines()
                    annotated = []
                    for line in lines:
                        m = seg_re.match(line)
                        if m:
                            m1, s1, m2, s2, text = m.groups()
                            spk = dominant_speaker(int(m1)*60+int(s1), int(m2)*60+int(s2))
                            annotated.append(f"[{m1}:{s1} - {m2}:{s2}] {spk+': ' if spk else ''}{text}")
                        else:
                            annotated.append(line)
                    transcript_path.write_text("\n".join(annotated), encoding="utf-8")

                await asyncio.get_running_loop().run_in_executor(None, _annotate)

        _retranscribe_tasks[session_id] = {"status": "done", "error": ""}
    except Exception as e:
        _retranscribe_tasks[session_id] = {"status": "error", "error": str(e)}


@router.post("/{session_id}/retranscribe", summary="Transkription neu starten")
async def retranscribe(session_id: str):
    """Transkribiert die vorhandenen Audio-Segmente einer Session neu."""
    if ".." in session_id or "/" in session_id:
        raise HTTPException(status_code=400, detail="Ungültige Session-ID.")

    session_dir = DATA_DIR / "sessions" / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="Session nicht gefunden.")

    if not sorted(session_dir.glob("audio_*.mp3")) and not sorted(session_dir.glob("audio.mp3")):
        raise HTTPException(status_code=422, detail="Keine Audio-Dateien vorhanden.")

    if _retranscribe_tasks.get(session_id, {}).get("status") == "running":
        raise HTTPException(status_code=409, detail="Transkription läuft bereits.")

    _retranscribe_tasks[session_id] = {"status": "running", "error": ""}
    asyncio.create_task(_run_retranscribe(session_id, session_dir))
    return {"message": "Transkription gestartet."}


@router.get("/{session_id}/retranscribe-status", summary="Transkriptions-Status abfragen")
async def retranscribe_status(session_id: str):
    """Gibt den aktuellen Status der Neu-Transkription zurück."""
    return _retranscribe_tasks.get(session_id, {"status": "idle", "error": ""})


@router.get("/{session_id}/{filename}", summary="Protokoll, Transkript oder Audio herunterladen")
async def download_file(session_id: str, filename: str):
    """
    Lädt eine Datei aus einer Session herunter.
    """
    if ".." in session_id or ".." in filename:
        raise HTTPException(status_code=400, detail="Ungültiger Pfad.")

    file_path = DATA_DIR / "sessions" / session_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")

    suffix = file_path.suffix.lower()
    if suffix not in {".docx", ".txt", ".json", ".mp3"}:
        raise HTTPException(status_code=403, detail="Dateityp nicht erlaubt.")

    media_types = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt":  "text/plain; charset=utf-8",
        ".json": "application/json",
        ".mp3":  "audio/mpeg",
    }

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type=media_types[suffix],
    )


@router.delete("/{session_id}", summary="Session vollständig löschen")
async def delete_session(session_id: str):
    """
    Löscht eine komplette Session (Audio, Transkript, Protokoll, Metadaten).
    """
    if ".." in session_id or "/" in session_id:
        raise HTTPException(status_code=400, detail="Ungültiger Session-ID.")

    session_dir = DATA_DIR / "sessions" / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="Session nicht gefunden.")

    shutil.rmtree(session_dir)
    return {"message": f"Session {session_id} gelöscht."}
