"""
Settings-Endpoints: GET/PUT /settings/extra, GET/PUT /settings/extra/default

Zweistufiges System:
  extra_instruktionen.txt         → aktuelle Instruktionen (auto-saved aus Textarea)
  extra_instruktionen_default.txt → Standard-Vorlage (editierbar über Modal + Confirm)

Der Factory-Fallback DEFAULT_INSTRUKTIONEN greift nur wenn noch keine Default-Datei existiert.
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

DATA_DIR     = Path(os.environ.get("DATA_DIR", "/opt/tsbot/data"))
EXTRA_PATH   = Path(os.environ.get("EXTRA_INSTRUKTIONEN_PATH",
                                   "/opt/tsbot/data/extra_instruktionen.txt"))
DEFAULT_PATH = Path(os.environ.get("DEFAULT_INSTRUKTIONEN_PATH",
                                   "/opt/tsbot/data/extra_instruktionen_default.txt"))
PROVIDER_FILE = DATA_DIR / "whisper_provider.json"

DEFAULT_INSTRUKTIONEN = """\
VERHALTENSREGELN:
- Verwende Namen und Kennzeichen EXAKT wie in der Teilnehmerliste angegeben
- FRS-Kennzeichen (z.B. FRS49, FRS999N) NIEMALS ausschreiben oder übersetzen – Buchstaben am Ende sind Teil des Kennzeichens, kein NATO-Alphabet
- Namen im Transkript können Whisper-Varianten sein (z.B. "Loffler" für "Löffler", "Weiss" für "Weiß") – gleiche phonetische/orthografische Varianten mit der Teilnehmerliste ab (oe↔ö, ue↔ü, ae↔ä, ss↔ß)
- Das Sprecher-Label [MM:SS - MM:SS] SPRECHER: text ist AUTORITATIV – es zeigt wer gesprochen hat, unabhängig vom Textinhalt
- Wenn ein Sprecher-Label einen Namen anzeigt, hat diese Person gesprochen – auch wenn der Textinhalt einen anderen Namen erwähnt
- Wer sich bei einer Vorstellungsrunde vorstellt, ist die Person laut Sprecher-Label, nicht der im Text genannte Name
- Kanalwechsel begrenzen Inhalte: Segmente NACH einem Wechsel zu einem Sub-Kanal (z.B. Separee) gehören ausschließlich zum Agenda-Punkt des Sub-Kanals – niemals zu Hauptkanal-Punkten
- Erfinde KEINE Informationen die nicht explizit im Transkript stehen – keine Daten, Zahlen oder Alternativen (kein "bzw.", "oder", "ca." wenn nicht im Transkript)
- Bei unklaren Angaben im Transkript: weglassen oder exakt das zitieren was gesagt wurde
- Alle genannten Orte, Personen, Termine und Entscheidungen VOLLSTÄNDIG aufnehmen
- Verabschiedungen, Übergänge und Kanalwechsel-Ankündigungen müssen erwähnt werden

INHALTLICHE VORGABEN:
- Kein Transkript ins Protokoll (weder Auszüge noch Volltext)
- Wenn ein Sprecher dich direkt adressiert ("Claude, bitte..." / "Hinweis fürs Protokoll:"), erfasse diese Aussage EXPLIZIT als Beschluss oder Hinweis im jeweiligen Agenda-Punkt – mit dem Wortlaut der Anweisung
- Wenn ein Sprecher eine direkte Aussage an eine andere Person richtet ("Klaus, bitte..." / "Tobias, was denkst du?"), erfasse diese Interaktion im Detail des Agenda-Punkts
- Wörter aus dem NATO-Alphabet (Alpha, Bravo, Charlie usw.) als Großbuchstaben ohne Leerzeichen übernehmen (Beispiel: "Lima Delta" → "LD")
- ICAO-Codes: Bei JEDEM genannten Ort, Ortsnamen oder Flugplatznamen prüfen ob es dort einen Flugplatz gibt – falls ja, ICAO-Code ermitteln und ergänzen (Beispiel: "Herzogenaurach" → "EDQH – Flugplatz Herzogenaurach", "Bremgarten" → "EDTQ – Flugplatz Bremgarten"). Der Ort muss nicht explizit als Flugplatz bezeichnet werden. Umgekehrt: Zu genannten ICAO-Codes den Flugplatz- und Ortsnamen heraussuchen.\
"""


class ExtraBody(BaseModel):
    text: str


def _get_default_text() -> str:
    """Gibt die gespeicherte Standard-Vorlage zurück, oder den Factory-Default."""
    if DEFAULT_PATH.exists():
        content = DEFAULT_PATH.read_text(encoding="utf-8")
        if content.strip():
            return content
    return DEFAULT_INSTRUKTIONEN


# ── Aktuelle Instruktionen ─────────────────────────────────

@router.get("/extra", summary="Aktuelle Protokoll-Instruktionen laden")
async def get_extra():
    """Gibt die aktuellen Instruktionen zurück.
    Liefert den Standard wenn Datei fehlt, leer ist oder noch alten Inhalt hat
    (erkennbar am fehlenden 'VERHALTENSREGELN:'-Block)."""
    if EXTRA_PATH.exists():
        content = EXTRA_PATH.read_text(encoding="utf-8")
        if content.strip() and "VERHALTENSREGELN:" in content:
            return {"text": content}
    return {"text": _get_default_text()}


@router.put("/extra", summary="Aktuelle Protokoll-Instruktionen speichern")
async def put_extra(body: ExtraBody):
    """Speichert die aktuellen Instruktionen (gilt für alle neuen Sessions)."""
    EXTRA_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXTRA_PATH.write_text(body.text, encoding="utf-8")
    return {"message": "Instruktionen gespeichert.", "text": body.text}


# ── Standard-Vorlage ──────────────────────────────────────

@router.get("/extra/default", summary="Standard-Vorlage laden")
async def get_extra_default():
    """Gibt die Standard-Vorlage zurück (für ↺-Reset und Modal)."""
    return {"text": _get_default_text()}


@router.put("/extra/default", summary="Standard-Vorlage speichern")
async def put_extra_default(body: ExtraBody):
    """Überschreibt die Standard-Vorlage (geschützte Operation)."""
    DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_PATH.write_text(body.text, encoding="utf-8")
    return {"message": "Standard-Vorlage gespeichert.", "text": body.text}


# ── Whisper-Provider ──────────────────────────────────────

class ProviderBody(BaseModel):
    provider: str  # "local" | "openai"


@router.get("/whisper-provider", summary="Whisper-Provider laden")
async def get_whisper_provider():
    if PROVIDER_FILE.exists():
        return json.loads(PROVIDER_FILE.read_text(encoding="utf-8"))
    return {"provider": os.environ.get("WHISPER_PROVIDER", "local")}


@router.put("/whisper-provider", summary="Whisper-Provider speichern")
async def put_whisper_provider(body: ProviderBody):
    if body.provider not in ("local", "openai"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Provider muss 'local' oder 'openai' sein.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROVIDER_FILE.write_text(json.dumps({"provider": body.provider}), encoding="utf-8")
    return {"provider": body.provider}
