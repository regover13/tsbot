"""
Session-Endpoints: POST /session/start, POST /session/stop, POST /session/channel
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter()


class StartRequest(BaseModel):
    thema:               str
    agenda:              list[str] | None = None
    extra_instruktionen: str | None = None
    channel_id:          int | None = None


class ChannelSwitchRequest(BaseModel):
    channel_id: int


@router.post("/start", summary="Sitzungsaufnahme starten")
async def start_session(body: StartRequest, request: Request):
    """
    Startet eine neue Aufnahme-Session.

    - **thema**: Titel der Sitzung
    - **agenda**: Optionale Liste von Agenda-Punkten (überschreibt agenda.txt)
    - **extra_instruktionen**: Freitext-Zusatzanweisungen für die Claude-Protokollerstellung
    """
    manager = request.app.state.manager
    try:
        session_id = await manager.start_session(
            thema=body.thema,
            agenda=body.agenda,
            extra_instruktionen=body.extra_instruktionen,
            channel_id=body.channel_id,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {"session_id": session_id, "message": "Aufnahme gestartet."}


@router.post("/stop", summary="Sitzungsaufnahme stoppen und Protokoll erstellen")
async def stop_session(request: Request):
    """
    Stoppt die laufende Aufnahme und startet Transkription + Protokollerstellung
    asynchron im Hintergrund.
    """
    manager = request.app.state.manager
    try:
        await manager.stop_session()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {
        "session_id": manager.session_id,
        "message":    "Aufnahme gestoppt – Verarbeitung läuft im Hintergrund.",
    }


@router.post("/channel", summary="Kanal während der Aufnahme wechseln")
async def switch_channel(body: ChannelSwitchRequest, request: Request):
    """
    Bewegt den Bot in einen anderen TS3-Kanal und schaltet das
    Teilnehmer-Tracking um. Nur während einer aktiven Aufnahme möglich.
    Der Kanalwechsel wird im Protokoll vermerkt.
    """
    manager = request.app.state.manager
    try:
        await manager.switch_channel(body.channel_id)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {
        "channel_id": body.channel_id,
        "message":    f"Bot in Kanal {body.channel_id} verschoben – Tracking umgeschaltet.",
    }
