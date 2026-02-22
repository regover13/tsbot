"""
Status-Endpoint: GET /status
"""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/status", summary="Aktuellen Bot-Status abfragen")
async def get_status(request: Request):
    """
    Gibt den aktuellen Zustand zurück.

    States: IDLE | RECORDING | TRANSCRIBING | GENERATING | DONE | ERROR
    """
    manager = request.app.state.manager
    return manager.get_status()
