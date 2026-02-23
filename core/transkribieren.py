#!/usr/bin/env python3
"""
Whisper Transkriptions-Skript
Transkribiert Audiodateien auf Deutsch und speichert das Ergebnis als TXT-Datei.

Optionale Sprechertrennung (Diarization) via whisperx + pyannote.audio:
    USE_DIARIZATION=true   (Env-Variable, default: false)
    HF_TOKEN=hf_...        (HuggingFace-Token, kostenlos unter huggingface.co)

Ohne Diarization: plain openai-whisper, kein HF-Token nötig.
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
    Transkription mit plain openai-whisper.
    Gibt (segmente, volltext, n_sprecher=0) zurück.
    Segmente: [{"start", "end", "text", "speaker": None}, ...]
    """
    import whisper
    print(f"Lade Whisper-Modell ({model_name})...")
    model = whisper.load_model(model_name, device=device)

    print(f"Transkribiere (plain Whisper)...")
    result = model.transcribe(audio_pfad, language="de", verbose=False, word_timestamps=True)

    segs = [
        {"start": s["start"], "end": s["end"], "text": s["text"].strip(), "speaker": None}
        for s in result["segments"]
    ]
    return segs, result["text"].strip(), 0


def _whisperx_segmente(audio_pfad: str, model_name: str, device: str, hf_token: str) -> tuple:
    """
    Transkription mit whisperx: Whisper + Wort-Alignment + Sprechertrennung.
    Gibt (segmente, volltext, n_sprecher) zurück.
    Segmente: [{"start", "end", "text", "speaker": "SPRECHER_0"|None}, ...]
    """
    try:
        import whisperx
    except ImportError:
        raise RuntimeError(
            "whisperx nicht installiert. Bitte:\n"
            "  pip install whisperx\n"
            "oder USE_DIARIZATION=false setzen."
        )
    import gc

    compute_type = "float16" if device == "cuda" else "int8"
    batch_size   = 8 if device == "cuda" else 4

    # ── 1. Transkription ─────────────────────────────────────
    print(f"Lade whisperx-Modell ({model_name}, compute={compute_type})...")
    model = whisperx.load_model(model_name, device, compute_type=compute_type)
    audio = whisperx.load_audio(audio_pfad)

    print("Transkribiere...")
    result = model.transcribe(audio, batch_size=batch_size, language="de")
    del model
    gc.collect()
    if device == "cuda":
        import torch; torch.cuda.empty_cache()

    # ── 2. Wort-genaues Alignment ─────────────────────────────
    print("Wort-Alignment läuft...")
    try:
        model_a, metadata = whisperx.load_align_model(language_code="de", device=device)
        result = whisperx.align(
            result["segments"], model_a, metadata, audio, device,
            return_char_alignments=False
        )
        del model_a
        gc.collect()
    except Exception as e:
        print(f"  Alignment fehlgeschlagen ({e}) – überspringe.")

    # ── 3. Sprechertrennung ───────────────────────────────────
    print("Sprechertrennung läuft (pyannote)...")
    try:
        import torch
        from whisperx.diarize import DiarizationPipeline
        diarize_model = DiarizationPipeline(
            token=hf_token, device=device
        )
        # Audio als vorgeladenes Tensor übergeben – umgeht torchcodec-Fehler
        waveform = {"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": 16000}
        diarize_segments = diarize_model(waveform)
        result = whisperx.assign_word_speakers(diarize_segments, result)
    except Exception as e:
        print(f"  Sprechertrennung fehlgeschlagen ({e}) – Sprecher-Tags entfallen.")

    # ── Normalisierung ────────────────────────────────────────
    # Sprecher-IDs kompaktieren: SPEAKER_00 → SPRECHER_0, SPEAKER_01 → SPRECHER_1, ...
    rohids = sorted({s.get("speaker") for s in result["segments"] if s.get("speaker")})
    id_map  = {roh: f"SPRECHER_{i}" for i, roh in enumerate(rohids)}

    segs = []
    for s in result["segments"]:
        roh_speaker = s.get("speaker")
        speaker = id_map.get(roh_speaker) if roh_speaker else None
        segs.append({
            "start":   s["start"],
            "end":     s["end"],
            "text":    s["text"].strip(),
            "speaker": speaker,
        })

    # Volltext mit Sprecher-Tags
    volltext_parts = []
    letzter_sprecher = None
    for s in segs:
        if s["speaker"] and s["speaker"] != letzter_sprecher:
            volltext_parts.append(f"\n[{s['speaker']}] {s['text']}")
            letzter_sprecher = s["speaker"]
        elif s["speaker"]:
            volltext_parts.append(s["text"])
        else:
            volltext_parts.append(s["text"])
    volltext = " ".join(volltext_parts).strip()

    return segs, volltext, len(rohids)


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

    use_diarization = os.environ.get("USE_DIARIZATION", "false").lower() == "true"
    hf_token        = os.environ.get("HF_TOKEN", "").strip()

    if use_diarization and not hf_token:
        print("WARNUNG: USE_DIARIZATION=true, aber kein HF_TOKEN gesetzt.")
        print("         → Falle zurück auf Standard-Whisper ohne Sprechertrennung.")
        print("         → HF_TOKEN in config.env eintragen und neu starten.")
        use_diarization = False

    print(f"\nTranskribiere: {os.path.basename(audio_pfad)}")

    if use_diarization:
        print("Modus: whisperx + Sprechertrennung (pyannote)")
        segs, volltext, n_sprecher = _whisperx_segmente(audio_pfad, model_name, device, hf_token)
    else:
        segs, volltext, n_sprecher = _whisper_segmente(audio_pfad, model_name, device)

    # ── Datei schreiben ───────────────────────────────────────
    with open(ausgabe_datei, "w", encoding="utf-8") as f:
        f.write("TRANSKRIPT\n")
        f.write(f"Datei: {os.path.basename(audio_pfad)}\n")
        f.write(f"Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n")
        if use_diarization and n_sprecher > 0:
            f.write(f"Sprechertrennung: Aktiviert ({n_sprecher} Sprecher erkannt)\n")
        elif use_diarization:
            f.write("Sprechertrennung: Aktiviert (keine Sprecher zugewiesen)\n")
        f.write("=" * 60 + "\n\n")

        for seg in segs:
            start_str   = _fmt(seg["start"])
            end_str     = _fmt(seg["end"])
            speaker_tag = f"[{seg['speaker']}] " if seg.get("speaker") else ""
            f.write(f"[{start_str} - {end_str}] {speaker_tag}{seg['text']}\n")

        f.write("\n" + "=" * 60 + "\n")
        f.write("VOLLTEXT:\n\n")
        f.write(volltext)

    print(f"\nTranskript gespeichert: {ausgabe_datei}")
    if n_sprecher > 0:
        sprecher_ids = sorted({seg["speaker"] for seg in segs if seg.get("speaker")})
        print(f"Erkannte Sprecher: {', '.join(sprecher_ids)}")
        print("Tipp: Claude versucht die Sprecher beim Protokollieren den Teilnehmern zuzuordnen.")
    return ausgabe_datei


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Verwendung: python transkribieren.py <audiodatei> [ausgabe_ordner]")
        sys.exit(1)

    audio = sys.argv[1]
    ausgabe = sys.argv[2] if len(sys.argv) > 2 else None
    transkribiere(audio, ausgabe)
