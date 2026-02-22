#!/usr/bin/env python3
"""
Protokoll-Generator mit Claude API
- Transkript-Segmente werden per KI den Agenda-Punkten zugeordnet
- Teilnehmer werden per Claude Vision aus allen PNGs im Ordner extrahiert
  (oder direkt als Liste übergeben, z.B. aus ServerQuery im Server-Modus)
"""

import sys
import os
import re
import json
import base64
from datetime import datetime
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn


# ── Konfiguration ─────────────────────────────────────────────
def lese_config(skript_ordner: str) -> dict:
    # Env-Variablen haben Vorrang; config.txt überschreibt nur wenn vorhanden
    config = {
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY"),
        "CLAUDE_MODEL": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929"),
    }
    pfad = os.path.join(skript_ordner, "config.txt")
    if os.path.exists(pfad):
        with open(pfad, "r", encoding="utf-8") as f:
            for zeile in f:
                zeile = zeile.strip()
                if zeile.startswith("#") or "=" not in zeile:
                    continue
                key, _, wert = zeile.partition("=")
                config[key.strip()] = wert.strip()
    return config


# ── Hilfsfunktionen ───────────────────────────────────────────
def setze_seitenraender(doc, oben=2.5, unten=2.5, links=3.0, rechts=2.5):
    for section in doc.sections:
        section.top_margin    = Cm(oben)
        section.bottom_margin = Cm(unten)
        section.left_margin   = Cm(links)
        section.right_margin  = Cm(rechts)


def lese_agenda(pfad: str) -> list:
    if not pfad or not os.path.exists(pfad):
        return []
    with open(pfad, "r", encoding="utf-8") as f:
        return [z.strip() for z in f if z.strip()]


def lese_transkript(pfad: str) -> tuple:
    with open(pfad, "r", encoding="utf-8") as f:
        inhalt = f.read()
    muster = re.compile(r'\[(\d{2}:\d{2}) - (\d{2}:\d{2})\] (.+)')
    segmente = muster.findall(inhalt)
    volltext_match = re.search(r'VOLLTEXT:\s*\n\n(.+)', inhalt, re.DOTALL)
    volltext = volltext_match.group(1).strip() if volltext_match else inhalt
    return volltext, segmente


def finde_alle_pngs(ordner: str) -> list:
    """Alle PNG-Dateien im Ordner, sortiert nach Änderungszeit."""
    pngs = [
        os.path.join(ordner, f)
        for f in os.listdir(ordner)
        if f.lower().endswith(".png")
    ]
    return sorted(pngs, key=os.path.getmtime)


# ── Claude Vision: Teilnehmer aus Screenshots extrahieren ─────
def extrahiere_teilnehmer(png_pfade: list, api_key: str, modell: str) -> list:
    """Sendet alle PNGs an Claude Vision und extrahiert Teilnehmernamen."""
    try:
        import anthropic
    except ImportError:
        print("HINWEIS: anthropic-Paket nicht installiert.")
        return []

    if not png_pfade:
        return []

    print(f"Extrahiere Teilnehmer aus {len(png_pfade)} Screenshot(s)...")
    client = anthropic.Anthropic(api_key=api_key)

    alle_roh = []  # Liste von dicts vor Deduplizierung

    for pfad in png_pfade:
        with open(pfad, "rb") as f:
            bild_data = base64.standard_b64encode(f.read()).decode("utf-8")

        message = client.messages.create(
            model=modell,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": bild_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": """Das ist ein TeamSpeak-Screenshot einer Flugsimulations-Community.

Extrahiere NUR echte Personennamen der eingeloggten Nutzer.
Echte Nutzernamen haben IMMER das Format: "Vorname Nachname/FRSxxx" oder "Vorname Nachname/FRSxxx (Zusatz)".

WICHTIG - folgendes sind KEINE Nutzernamen und dürfen NICHT extrahiert werden:
- Kanal- oder Raumbezeichnungen (z.B. "Fliegen Weltweit", "AFK", "Lobby", "Training", etc.)
- Kanalgruppen oder Kategorien
- Statusmeldungen

Antworte NUR mit einer JSON-Liste. Wenn keine gültigen Nutzernamen gefunden, antworte mit [].
Format:
[
  {"name": "Vorname Nachname", "frs": "FRS49"},
  {"name": "Anderer Name", "frs": "FRS12"}
]"""
                    }
                ],
            }]
        )

        antwort = message.content[0].text.strip()
        json_match = re.search(r'\[.*\]', antwort, re.DOTALL)
        if json_match:
            try:
                teilnehmer = json.loads(json_match.group())
                alle_roh.extend(teilnehmer)
            except json.JSONDecodeError:
                pass

    # Fuzzy-Deduplizierung: gleiche FRS → behalte längeren Namen
    def aehnlichkeit(a: str, b: str) -> float:
        a, b = a.lower(), b.lower()
        if not a or not b:
            return 0.0
        treffer = sum(c in b for c in a)
        return treffer / max(len(a), len(b))

    eindeutig = []
    for eintrag in alle_roh:
        name = eintrag.get("name", "").strip()
        frs  = eintrag.get("frs", "").strip()
        if not name:
            continue
        if frs:
            if any(e["frs"] == frs for e in eindeutig):
                for e in eindeutig:
                    if e["frs"] == frs and len(name) > len(e["name"]):
                        e["name"] = name
                continue
        if any(aehnlichkeit(name, e["name"]) > 0.85 for e in eindeutig):
            continue
        eindeutig.append({"name": name, "frs": frs})

    return sorted(eindeutig, key=lambda x: x["name"].lower())


# ── Hilfsfunktion: Sprecher-IDs aus Segmenten extrahieren ─────
def _erkenne_sprecher(segmente: list) -> list:
    """Gibt sortierte Liste aller SPRECHER_X-IDs aus den Segmenten zurück."""
    sprecher = set()
    for _, _, text in segmente:
        m = re.match(r'^\[(SPRECHER_\d+)\]', text.strip())
        if m:
            sprecher.add(m.group(1))
    return sorted(sprecher)


# ── Claude API: Transkript den Agenda-Punkten zuordnen ─────────
def ki_zuordnung(volltext: str, segmente: list, agenda: list, api_key: str, modell: str,
                 extra_instruktionen: str = None,
                 teilnehmer_liste: list = None,
                 kanal_wechsel: list = None) -> list:
    try:
        import anthropic
    except ImportError:
        print("HINWEIS: anthropic-Paket nicht installiert.")
        return []

    print("Sende Transkript an Claude API zur Zuordnung...")
    transkript_text = "\n".join([f"[{s} - {e}] {t}" for s, e, t in segmente]) if segmente else volltext
    agenda_text = "\n".join([f"{i+1}. {p}" for i, p in enumerate(agenda)])

    # ── Sprecher-Mapping-Block (nur wenn Diarization-Tags vorhanden) ──
    sprecher_block = ""
    sprecher_ids = _erkenne_sprecher(segmente) if segmente else []
    if sprecher_ids and teilnehmer_liste:
        teilnehmer_text = "\n".join(
            f"  - {t['name']}" + (f" ({t['frs']})" if t.get("frs") else "")
            for t in teilnehmer_liste
        )
        sprecher_block = f"""
SPRECHERIDENTIFIKATION:
Das Transkript enthält automatisch erkannte, anonyme Sprecher ({', '.join(sprecher_ids)}).
Bekannte Teilnehmer laut ServerQuery:
{teilnehmer_text}

Versuche die Sprecher den Teilnehmern zuzuordnen, wo es aus dem Kontext möglich ist
(z.B. wenn jemand mit Namen angesprochen wird, sich vorstellt oder über bekannte Themen spricht).
Verwende in Zusammenfassungen und Beschlüssen die echten Namen statt SPRECHER_X, wenn du dir sicher bist.
Wenn die Zuordnung unklar ist, behalte SPRECHER_X bei.
"""
    elif sprecher_ids:
        sprecher_block = f"""
SPRECHERIDENTIFIKATION:
Das Transkript enthält automatisch erkannte Sprecher ({', '.join(sprecher_ids)}).
Keine Teilnehmerliste verfügbar – behalte SPRECHER_X in Zusammenfassungen bei.
"""

    # ── Kanalwechsel-Block ────────────────────────────────────
    kanal_block = ""
    if kanal_wechsel:
        kanal_block = "\nKANALWECHSEL WÄHREND DER SITZUNG:\n"
        for evt in kanal_wechsel:
            ts      = evt.get("timestamp", "")[:19].replace("T", " ")
            von     = evt.get("from_channel", "?")
            nach    = evt.get("to_channel", "?")
            kanal_block += f"- {ts}: Kanal {von} → Kanal {nach}\n"
        kanal_block += (
            "Erwähne diese Kanalwechsel an passender Stelle im Protokoll "
            "(z.B. als Notiz zwischen den Agenda-Punkten).\n"
        )

    # ── Zusätzliche Instruktionen ─────────────────────────────
    extra_block = ""
    if extra_instruktionen and extra_instruktionen.strip():
        extra_block = f"\nZUSÄTZLICHE INSTRUKTIONEN DES NUTZERS:\n{extra_instruktionen.strip()}\n"

    prompt = f"""Du bist ein professioneller Protokollschreiber. Analysiere das Transkript und weise jeden Abschnitt dem passenden Agenda-Punkt zu.

AGENDA:
{agenda_text}

TRANSKRIPT:
{transkript_text}
{sprecher_block}{kanal_block}{extra_block}
Antworte NUR mit folgendem JSON:
{{
  "agenda_punkte": [
    {{
      "punkt": "Exakter Name des Agenda-Punkts",
      "zusammenfassung": "Kurze sachliche Zusammenfassung (2-4 Sätze)",
      "beschluesse": ["Beschluss oder Aktionspunkt 1"],
      "zeitraum": "00:00 - 08:30",
      "segmente": ["[00:00 - 00:45] Relevanter Text"]
    }}
  ]
}}

Hinweise:
- Jeden Agenda-Punkt aufführen, auch ohne Transkript-Treffer
- Zusammenfassung sachlich und neutral
- Beschlüsse = konkrete Entscheidungen oder Aktionspunkte"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=modell,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )

    antwort = message.content[0].text.strip()
    json_match = re.search(r'\{.*\}', antwort, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())["agenda_punkte"]
        except (json.JSONDecodeError, KeyError):
            pass
    return []


# ── Word-Dokument erstellen ───────────────────────────────────
def erstelle_protokoll(transkript_pfad: str, thema: str,
                       agenda_pfad: str = None,
                       teilnehmer_liste: list = None,
                       extra_instruktionen: str = None,
                       kanal_wechsel: list = None):
    """
    Erstellt ein Word-Protokoll aus einem Transkript.

    Parameter:
        transkript_pfad:     Pfad zur Transkript-TXT-Datei
        thema:               Titel/Thema der Sitzung
        agenda_pfad:         Optionaler Pfad zur agenda.txt
        teilnehmer_liste:    Optionale Liste von Teilnehmern (Server-Modus).
                             Format: [{"name": "...", "frs": "..."}, ...]
                             Wenn übergeben, werden PNGs und Claude Vision übersprungen.
        extra_instruktionen: Freier Text, der zusätzlich an den Claude-Prompt angehängt wird.
    """
    skript_ordner  = os.path.dirname(os.path.abspath(__file__))
    config         = lese_config(skript_ordner)
    volltext, segmente = lese_transkript(transkript_pfad)
    agenda         = lese_agenda(agenda_pfad)
    api_key        = config.get("ANTHROPIC_API_KEY", "")
    modell         = config.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
    hat_api        = bool(api_key and not api_key.startswith("sk-ant-HIER"))

    # Teilnehmer-Ermittlung:
    # Server-Modus: Liste direkt übergeben → Vision entfällt
    # Windows-Modus: PNGs im Skript-Ordner suchen und per Vision auswerten
    if teilnehmer_liste is None:
        pngs = finde_alle_pngs(skript_ordner)
        if pngs and hat_api:
            teilnehmer_liste = extrahiere_teilnehmer(pngs, api_key, modell)
            print(f"{len(teilnehmer_liste)} Teilnehmer gefunden.")
        elif pngs:
            print("HINWEIS: Kein API-Key – Screenshots werden ohne OCR übersprungen.")
            teilnehmer_liste = []
        else:
            teilnehmer_liste = []
    # else: Liste aus Server-Query → direkt verwenden, kein Vision-Call nötig

    # KI-Zuordnung Transkript → Agenda
    ki_punkte = []
    if agenda and hat_api:
        ki_punkte = ki_zuordnung(
            volltext, segmente, agenda, api_key, modell,
            extra_instruktionen=extra_instruktionen,
            teilnehmer_liste=teilnehmer_liste,
            kanal_wechsel=kanal_wechsel or [],
        )
        if ki_punkte:
            print(f"Claude hat {len(ki_punkte)} Agenda-Punkte zugeordnet.")
    elif agenda:
        print("HINWEIS: Kein API-Key – Protokoll ohne KI-Zuordnung.")

    # Ausgabe-Datei
    ausgabe_ordner = os.path.dirname(transkript_pfad)
    zeitstempel    = datetime.now().strftime("%Y%m%d_%H%M")
    ausgabe_datei  = os.path.join(ausgabe_ordner, f"Protokoll_{zeitstempel}.docx")

    doc = Document()
    setze_seitenraender(doc)
    doc.styles['Normal'].font.name = 'Calibri'
    doc.styles['Normal'].font.size = Pt(11)

    # ── Titel ──────────────────────────────────────────────────
    titel = doc.add_heading('Sitzungsprotokoll', level=1)
    titel.alignment = WD_ALIGN_PARAGRAPH.CENTER
    titel.runs[0].font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)
    if thema:
        ut = doc.add_heading(thema, level=2)
        ut.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    # ── Metadaten ──────────────────────────────────────────────
    t = doc.add_table(rows=2, cols=2)
    t.style = 'Table Grid'
    for i, (label, wert) in enumerate([
        ("Datum:",       datetime.now().strftime("%d.%m.%Y")),
        ("Erstellt am:", datetime.now().strftime("%d.%m.%Y %H:%M Uhr")),
    ]):
        t.cell(i, 0).text = label
        t.cell(i, 1).text = wert
        t.cell(i, 0).paragraphs[0].runs[0].bold = True
    doc.add_paragraph()

    # ── Kanalwechsel-Hinweis ──────────────────────────────────
    if kanal_wechsel:
        note = doc.add_paragraph()
        note.add_run("Hinweis – Kanalwechsel während der Sitzung:").bold = True
        for evt in kanal_wechsel:
            ts   = evt.get("timestamp", "")[:19].replace("T", " ")
            von  = evt.get("from_channel", "?")
            nach = evt.get("to_channel", "?")
            item = doc.add_paragraph(style="List Bullet")
            item.add_run(f"{ts}: Kanal {von} → Kanal {nach}")
            item.add_run(" – Teilnehmer-Tracking wurde umgeschaltet.").italic = True
        doc.add_paragraph()

    # ── Inhaltsverzeichnis ─────────────────────────────────────
    doc.add_heading('Inhaltsverzeichnis', level=1)
    from docx.oxml import OxmlElement
    toc_para = doc.add_paragraph()
    fld = OxmlElement('w:fldSimple')
    fld.set(qn('w:instr'), ' TOC \\o "1-3" \\h \\z \\u ')
    run = OxmlElement('w:r')
    rPr = OxmlElement('w:rPr')
    run.append(rPr)
    t = OxmlElement('w:t')
    t.text = '[Inhaltsverzeichnis – bitte in Word mit F9 aktualisieren]'
    run.append(t)
    fld.append(run)
    toc_para._p.append(fld)
    doc.add_paragraph()

    # ── Teilnehmer ─────────────────────────────────────────────
    doc.add_heading('Teilnehmer', level=1)
    if teilnehmer_liste:
        tbl = doc.add_table(rows=1, cols=2)
        tbl.style = 'Table Grid'
        hdr = tbl.rows[0].cells
        hdr[0].text = "Name"
        hdr[1].text = "FRS-Nummer"
        for r in hdr:
            r.paragraphs[0].runs[0].bold = True
        for t in teilnehmer_liste:
            row = tbl.add_row().cells
            row[0].text = t["name"]
            row[1].text = t["frs"]
    else:
        for _ in range(4):
            doc.add_paragraph().add_run("_" * 50)
    doc.add_paragraph()

    # ── Agenda ─────────────────────────────────────────────────
    if agenda:
        doc.add_heading('Agenda', level=1)
        for i, punkt in enumerate(agenda, 1):
            p = doc.add_paragraph()
            p.add_run(f"{i}. {punkt}")
        doc.add_paragraph()

    # ── Protokoll ─────────────────────────────────────────────
    doc.add_heading('Protokoll', level=1)

    if ki_punkte:
        for eintrag in ki_punkte:
            h = doc.add_heading(eintrag.get("punkt", ""), level=2)
            h.runs[0].font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)

            if eintrag.get("zeitraum"):
                p = doc.add_paragraph()
                r = p.add_run(f"Zeitraum: {eintrag['zeitraum']}")
                r.italic = True
                r.font.color.rgb = RGBColor(0x70, 0x70, 0x70)
                r.font.size = Pt(9)

            if eintrag.get("zusammenfassung"):
                doc.add_paragraph(eintrag["zusammenfassung"])

            if eintrag.get("beschluesse"):
                doc.add_paragraph().add_run("Beschlüsse / Aktionspunkte:").bold = True
                for b in eintrag["beschluesse"]:
                    doc.add_paragraph(b, style='List Bullet')

            if eintrag.get("segmente"):
                doc.add_paragraph().add_run("Transkript-Auszüge:").bold = True
                for seg in eintrag["segmente"]:
                    p = doc.add_paragraph()
                    p.paragraph_format.left_indent = Cm(1)
                    r_t = p.add_run(seg[:15] + "  ")
                    r_t.bold = True
                    r_t.font.size = Pt(9)
                    r_t.font.color.rgb = RGBColor(0x70, 0x70, 0x70)
                    p.add_run(seg[15:] if len(seg) > 15 else "")

            doc.add_paragraph()

    elif agenda:
        for punkt in agenda:
            h = doc.add_heading(punkt, level=2)
            h.runs[0].font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)
            for _ in range(3):
                doc.add_paragraph().add_run("_" * 70)
            doc.add_paragraph()
    else:
        for _ in range(6):
            doc.add_paragraph().add_run("_" * 70)

    # ── Vollständiges Transkript ───────────────────────────────
    doc.add_heading('Vollständiges Transkript', level=1)
    if segmente:
        for start, ende, text in segmente:
            p = doc.add_paragraph()
            r = p.add_run(f"[{start}]  ")
            r.bold = True
            r.font.color.rgb = RGBColor(0x70, 0x70, 0x70)
            r.font.size = Pt(9)
            p.add_run(text)
    else:
        doc.add_paragraph(volltext).style.font.size = Pt(10)

    doc.save(ausgabe_datei)
    print(f"\nProtokoll gespeichert: {ausgabe_datei}")
    return ausgabe_datei


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Verwendung: python protokoll_erstellen.py <transkript.txt> [thema] [agenda.txt]")
        sys.exit(1)

    erstelle_protokoll(
        transkript_pfad = sys.argv[1],
        thema           = sys.argv[2] if len(sys.argv) > 2 else "",
        agenda_pfad     = sys.argv[3] if len(sys.argv) > 3 else None,
    )
