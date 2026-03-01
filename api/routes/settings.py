"""
Settings-Endpoints: GET /settings/extra, PUT /settings/extra

Speichert server-seitige Einstellungen, die für alle Nutzer gleich gelten.
"""

import os
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

EXTRA_PATH = Path(os.environ.get("EXTRA_INSTRUKTIONEN_PATH", "/opt/tsbot/data/extra_instruktionen.txt"))


class ExtraBody(BaseModel):
    text: str


@router.get("/extra", summary="Zusätzliche Protokoll-Instruktionen laden")
async def get_extra():
    """Gibt die gespeicherten Zusatz-Instruktionen zurück (leer wenn nicht vorhanden)."""
    if not EXTRA_PATH.exists():
        return {"text": ""}
    return {"text": EXTRA_PATH.read_text(encoding="utf-8")}


@router.put("/extra", summary="Zusätzliche Protokoll-Instruktionen speichern")
async def put_extra(body: ExtraBody):
    """Speichert die Zusatz-Instruktionen server-seitig (gilt für alle Nutzer)."""
    EXTRA_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXTRA_PATH.write_text(body.text, encoding="utf-8")
    return {"message": "Instruktionen gespeichert.", "text": body.text}
