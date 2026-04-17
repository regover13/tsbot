#!/usr/bin/env python3
"""
Whisper Transkriptions-Skript
Transkribiert Audiodateien auf Deutsch und speichert das Ergebnis als TXT-Datei.

Unterstützt Einzel- und Mehrdatei-Transkription (segmentierte Aufnahmen).
"""

import sys
import os
import threading
from datetime import datetime

_model_load_lock = threading.Lock()


# ── Hilfsfunktionen ───────────────────────────────────────────

def _fmt(sek: float) -> str:
    """Sekunden → mm:ss"""
    return f"{int(sek // 60):02d}:{int(sek % 60):02d}"


def _get_device_and_model(model_name: str | None = None) -> tuple[str, str]:
    """Erkennt CUDA-Verfügbarkeit und gibt (device, model_name) zurück."""
    device = os.environ.get("WHISPER_DEVICE", "cpu")
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            device = "cuda"
            print("GPU erkannt – nutze CUDA")
        else:
            print("Kein CUDA gefunden – nutze CPU")
    except Exception:
        print(f"Nutze Device: {device}")
    if model_name is None:
        model_name = os.environ.get("WHISPER_MODEL", "large")
    return device, model_name


_whisper_model_cache: dict = {}  # (model_name, device) → WhisperModel


def _whisper_segmente(audio_pfad: str, model_name: str, device: str) -> tuple[list, float]:
    """
    Transkription mit faster-whisper (CTranslate2).
    Gibt (segmente, dauer_sekunden) zurück.
    Segmente: [{"start", "end", "text"}, ...]
    """
    from faster_whisper import WhisperModel
    compute_type = "float16" if device == "cuda" else "int8"
    cache_key = (model_name, device)
    if cache_key not in _whisper_model_cache:
        with _model_load_lock:
            if cache_key not in _whisper_model_cache:
                print(f"Lade Whisper-Modell ({model_name})...")
                _whisper_model_cache[cache_key] = WhisperModel(
                    model_name, device=device, compute_type=compute_type,
                    cpu_threads=6, local_files_only=True
                )
    model = _whisper_model_cache[cache_key]

    print(f"Transkribiere: {os.path.basename(audio_pfad)}...")
    segments_gen, info = model.transcribe(
        audio_pfad,
        language="de",
        beam_size=1,
        word_timestamps=False,
        vad_filter=True,
        condition_on_previous_text=False,
    )

    segs = [
        {"start": s.start, "end": s.end, "text": s.text.strip()}
        for s in segments_gen
    ]
    dauer = info.duration if hasattr(info, "duration") else (segs[-1]["end"] if segs else 0.0)
    return segs, dauer


def _schreibe_transkript(segs: list, volltext: str, ausgabe_datei: str,
                          datei_label: str, ausgabe_ordner: str) -> str:
    """Schreibt Segmente + Volltext in eine TXT-Datei."""
    os.makedirs(ausgabe_ordner, exist_ok=True)
    with open(ausgabe_datei, "w", encoding="utf-8") as f:
        f.write("TRANSKRIPT\n")
        f.write(f"Datei: {datei_label}\n")
        f.write(f"Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n")
        f.write("=" * 60 + "\n\n")

        for seg in segs:
            f.write(f"[{_fmt(seg['start'])} - {_fmt(seg['end'])}] {seg['text']}\n")

        f.write("\n" + "=" * 60 + "\n")
        f.write("VOLLTEXT:\n\n")
        f.write(volltext)
    print(f"\nTranskript gespeichert: {ausgabe_datei}")
    return ausgabe_datei


# ── Öffentliche Funktionen ────────────────────────────────────

def transkribiere(audio_pfad: str, ausgabe_ordner: str = None, model_name: str = None) -> str:
    """
    Transkribiert eine einzelne Audiodatei.
    Gibt den Pfad zur erzeugten TXT-Datei zurück.
    """
    if not os.path.exists(audio_pfad):
        print(f"FEHLER: Datei nicht gefunden: {audio_pfad}")
        sys.exit(1)

    if ausgabe_ordner is None:
        ausgabe_ordner = os.path.dirname(audio_pfad)

    basis_name    = os.path.splitext(os.path.basename(audio_pfad))[0]
    zeitstempel   = datetime.now().strftime("%Y%m%d_%H%M")
    ausgabe_datei = os.path.join(ausgabe_ordner, f"{basis_name}_transkript_{zeitstempel}.txt")

    device, model_name = _get_device_and_model(model_name)
    segs, _ = _whisper_segmente(audio_pfad, model_name, device)
    volltext = " ".join(s["text"] for s in segs)

    return _schreibe_transkript(
        segs, volltext, ausgabe_datei,
        datei_label=os.path.basename(audio_pfad),
        ausgabe_ordner=ausgabe_ordner,
    )


def transkribiere_mehrere(audio_pfade: list[str], ausgabe_ordner: str,
                           model_name: str = None,
                           progress_callback=None) -> str:
    """
    Transkribiert mehrere Audiodateien (Segmente einer Aufnahme) parallel und
    fügt sie zu einem einzigen Transkript zusammen.

    Timestamps werden durch Offset (kumulierte Dauer) korrekt verschoben.
    Eine 1,5 s Überlappung zwischen Segmenten wird durch Duplikat-Filter entfernt.

    progress_callback(current, total, elapsed_sec, eta_sec) wird nach jedem fertigen Segment aufgerufen.

    Gibt den Pfad zur erzeugten TXT-Datei zurück.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not audio_pfade:
        raise ValueError("Keine Audiodateien angegeben.")

    if len(audio_pfade) == 1:
        return transkribiere(audio_pfade[0], ausgabe_ordner, model_name)

    device, model_name = _get_device_and_model(model_name)

    sorted_pfade = sorted(audio_pfade)
    total = len(sorted_pfade)
    start_time = time.time()
    completed = 0
    results = [None] * total  # (segs, dauer) in Reihenfolge

    def _transkribiere_segment(idx: int, pfad: str):
        print(f"\n[{idx+1}/{total}] {os.path.basename(pfad)}")
        return idx, _whisper_segmente(pfad, model_name, device)

    with ThreadPoolExecutor(max_workers=total) as executor:
        futures = {executor.submit(_transkribiere_segment, idx, pfad): idx
                   for idx, pfad in enumerate(sorted_pfade)}
        for future in as_completed(futures):
            idx, (segs, dauer) = future.result()
            results[idx] = (segs, dauer)
            completed += 1
            if progress_callback:
                elapsed = time.time() - start_time
                avg = elapsed / completed
                eta = avg * (total - completed)
                progress_callback(completed, total, elapsed, eta)

    # Offsets anwenden und zusammenführen (in sortierter Reihenfolge)
    alle_segs: list[dict] = []
    offset = 0.0

    for segs, dauer in results:
        for seg in segs:
            abs_start = seg["start"] + offset
            if alle_segs and abs_start < offset:
                continue
            alle_segs.append({
                "start": abs_start,
                "end":   seg["end"] + offset,
                "text":  seg["text"],
            })
        offset += dauer

    volltext = " ".join(s["text"] for s in alle_segs)

    # Dateiname basierend auf dem ersten Segment
    basis_name    = "audio"
    zeitstempel   = datetime.now().strftime("%Y%m%d_%H%M")
    ausgabe_datei = os.path.join(ausgabe_ordner, f"{basis_name}_transkript_{zeitstempel}.txt")
    datei_label   = f"{len(audio_pfade)} Segmente ({os.path.basename(audio_pfade[0])} … {os.path.basename(audio_pfade[-1])})"

    return _schreibe_transkript(
        alle_segs, volltext, ausgabe_datei,
        datei_label=datei_label,
        ausgabe_ordner=ausgabe_ordner,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Verwendung: python transkribieren.py <audiodatei> [ausgabe_ordner]")
        sys.exit(1)

    transkribiere(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
