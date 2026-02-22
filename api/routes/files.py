"""
Protokoll-Endpoints: GET /protocols, GET /protocols/{session}/{file},
                     DELETE /protocols/{session}
"""

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/tsbot/data"))


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
            import json
            meta = json.loads(meta_file.read_text(encoding="utf-8"))

        docx_files = sorted(session_dir.glob("Protokoll_*.docx"))
        transcript_files = sorted(session_dir.glob("*_transkript_*.txt"))
        audio_files = sorted(session_dir.glob("audio.*"))

        result.append({
            "session_id":  session_dir.name,
            "thema":       meta.get("thema", ""),
            "started_at":  meta.get("started_at", ""),
            "protokolle":  [f.name for f in docx_files],
            "transkripte": [f.name for f in transcript_files],
            "audio":       [f.name for f in audio_files],
        })

    return {"sessions": result}


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
