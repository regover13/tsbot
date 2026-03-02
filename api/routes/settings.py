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
- ICAO-Codes: Suche zu genannten Flugplatznamen den ICAO-Code und ergänze ihn (Beispiel: "Bremgarten" → "EDTQ – Flugplatz Bremgarten"). Umgekehrt: Zu genannten ICAO-Codes den Namen heraussuchen.\
"""


class ExtraBody(BaseModel):
    text: str


@router.get("/extra", summary="Zusätzliche Protokoll-Instruktionen laden")
async def get_extra():
    """Gibt die gespeicherten Zusatz-Instruktionen zurück (Default wenn nicht vorhanden oder leer)."""
    if EXTRA_PATH.exists():
        content = EXTRA_PATH.read_text(encoding="utf-8")
        if content.strip():
            return {"text": content}
    return {"text": DEFAULT_INSTRUKTIONEN}


@router.put("/extra", summary="Zusätzliche Protokoll-Instruktionen speichern")
async def put_extra(body: ExtraBody):
    """Speichert die Zusatz-Instruktionen server-seitig (gilt für alle Nutzer)."""
    EXTRA_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXTRA_PATH.write_text(body.text, encoding="utf-8")
    return {"message": "Instruktionen gespeichert.", "text": body.text}
