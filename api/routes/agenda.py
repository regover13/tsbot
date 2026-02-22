"""
Agenda-Endpoints: GET /agenda, PUT /agenda
"""

import os
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter()

AGENDA_PATH = Path(os.environ.get("AGENDA_PATH", "/opt/tsbot/data/agenda.txt"))


class AgendaBody(BaseModel):
    punkte: list[str]


@router.get("/agenda", summary="Agenda vom Server laden")
async def get_agenda():
    """Gibt die aktuelle agenda.txt als Liste zurück."""
    if not AGENDA_PATH.exists():
        return {"punkte": []}
    lines = [l.strip() for l in AGENDA_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {"punkte": lines}


@router.put("/agenda", summary="Agenda auf dem Server speichern")
async def put_agenda(body: AgendaBody):
    """Überschreibt agenda.txt mit der übergebenen Liste."""
    AGENDA_PATH.parent.mkdir(parents=True, exist_ok=True)
    AGENDA_PATH.write_text("\n".join(body.punkte), encoding="utf-8")
    return {"message": f"Agenda gespeichert ({len(body.punkte)} Punkte).", "punkte": body.punkte}
