#!/usr/bin/env python3
"""
Whisper Transkriptions-Skript
Transkribiert Audiodateien auf Deutsch und speichert das Ergebnis als TXT-Datei.
"""

import sys
import os
from datetime import datetime


# ── Hilfsfunktionen ───────────────────────────────────────────

def _fmt(sek: float) -> str:
    """Sekunden → mm:ss"""
    return f"{int(sek // 60):02d}:{int(sek % 60):02d}"


def _whisper_segmente(audio_pfad: str, model_name: str, device: str) -> tuple:
    """
    Transkription mit openai-whisper.
    Gibt (segmente, volltext) zurück.
    Segmente: [{"start", "end", "text"}, ...]
    """
    import whisper
    print(f"Lade Whisper-Modell ({model_name})...")
    model = whisper.load_model(model_name, device=device)

    print("Transkribiere...")
    result = model.transcribe(audio_pfad, language="de", verbose=False, word_timestamps=True)

    segs = [
        {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
        for s in result["segments"]
    ]
    return segs, result["text"].strip()


# ── Haupt-Funktion ─────────────────────────────────────────────

def transkribiere(audio_pfad: str, ausgabe_ordner: str = None, model_name: str = None):
    if not os.path.exists(audio_pfad):
        print(f"FEHLER: Datei nicht gefunden: {audio_pfad}")
        sys.exit(1)

    if ausgabe_ordner is None:
        ausgabe_ordner = os.path.dirname(audio_pfad)
    os.makedirs(ausgabe_ordner, exist_ok=True)

    basis_name    = os.path.splitext(os.path.basename(audio_pfad))[0]
    zeitstempel   = datetime.now().strftime("%Y%m%d_%H%M")
    ausgabe_datei = os.path.join(ausgabe_ordner, f"{basis_name}_transkript_{zeitstempel}.txt")

    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        print(f"GPU erkannt: {torch.cuda.get_device_name(0)} – nutze CUDA")
    else:
        print("Kein CUDA gefunden – nutze CPU (langsamer)")

    if model_name is None:
        model_name = os.environ.get("WHISPER_MODEL", "large")

    print(f"\nTranskribiere: {os.path.basename(audio_pfad)}")

    segs, volltext = _whisper_segmente(audio_pfad, model_name, device)

    # ── Datei schreiben ───────────────────────────────────────
    # Ordner nochmals anlegen – könnte während der langen Transkription gelöscht worden sein
    os.makedirs(ausgabe_ordner, exist_ok=True)
    with open(ausgabe_datei, "w", encoding="utf-8") as f:
        f.write("TRANSKRIPT\n")
        f.write(f"Datei: {os.path.basename(audio_pfad)}\n")
        f.write(f"Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n")
        f.write("=" * 60 + "\n\n")

        for seg in segs:
            start_str = _fmt(seg["start"])
            end_str   = _fmt(seg["end"])
            f.write(f"[{start_str} - {end_str}] {seg['text']}\n")

        f.write("\n" + "=" * 60 + "\n")
        f.write("VOLLTEXT:\n\n")
        f.write(volltext)

    print(f"\nTranskript gespeichert: {ausgabe_datei}")
    return ausgabe_datei


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Verwendung: python transkribieren.py <audiodatei> [ausgabe_ordner]")
        sys.exit(1)

    transkribiere(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
