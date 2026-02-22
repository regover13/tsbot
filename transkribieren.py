#!/usr/bin/env python3
"""
Whisper Transkriptions-Skript
Transkribiert Audiodateien auf Deutsch und speichert das Ergebnis als TXT-Datei.
"""

import sys
import os
import whisper
from datetime import datetime

def transkribiere(audio_pfad: str, ausgabe_ordner: str = None):
    if not os.path.exists(audio_pfad):
        print(f"FEHLER: Datei nicht gefunden: {audio_pfad}")
        sys.exit(1)

    if ausgabe_ordner is None:
        ausgabe_ordner = os.path.dirname(audio_pfad)

    os.makedirs(ausgabe_ordner, exist_ok=True)

    # Dateiname ohne Erweiterung
    basis_name = os.path.splitext(os.path.basename(audio_pfad))[0]
    zeitstempel = datetime.now().strftime("%Y%m%d_%H%M")
    ausgabe_datei = os.path.join(ausgabe_ordner, f"{basis_name}_transkript_{zeitstempel}.txt")

    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        print(f"GPU erkannt: {torch.cuda.get_device_name(0)} – nutze CUDA")
    else:
        print("Kein CUDA gefunden – nutze CPU (langsamer)")
    print(f"Lade Whisper-Modell (large) in den Arbeitsspeicher...")
    model = whisper.load_model("large", device=device)

    print(f"\nTranskribiere: {os.path.basename(audio_pfad)}")
    print("Bitte warten...")

    result = model.transcribe(
        audio_pfad,
        language="de",
        verbose=False,
        word_timestamps=True
    )

    # Transkript mit Zeitstempeln speichern
    with open(ausgabe_datei, "w", encoding="utf-8") as f:
        f.write(f"TRANSKRIPT\n")
        f.write(f"Datei: {os.path.basename(audio_pfad)}\n")
        f.write(f"Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n")
        f.write("=" * 60 + "\n\n")

        for segment in result["segments"]:
            start = segment["start"]
            end = segment["end"]
            text = segment["text"].strip()

            # Zeitformat mm:ss
            start_str = f"{int(start // 60):02d}:{int(start % 60):02d}"
            end_str   = f"{int(end   // 60):02d}:{int(end   % 60):02d}"

            f.write(f"[{start_str} - {end_str}] {text}\n")

        f.write("\n" + "=" * 60 + "\n")
        f.write("VOLLTEXT:\n\n")
        f.write(result["text"].strip())

    print(f"\nTranskript gespeichert: {ausgabe_datei}")
    return ausgabe_datei


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Verwendung: python transkribieren.py <audiodatei> [ausgabe_ordner]")
        sys.exit(1)

    audio = sys.argv[1]
    ausgabe = sys.argv[2] if len(sys.argv) > 2 else None
    transkribiere(audio, ausgabe)
