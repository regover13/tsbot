#!/usr/bin/env python3
"""
Windows-Wrapper – delegiert an core/transkribieren.py.
Die .bat-Dateien rufen dieses Skript auf; die Logik liegt in core/.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "core"))
from transkribieren import transkribiere  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Verwendung: python transkribieren.py <audiodatei> [ausgabe_ordner]")
        sys.exit(1)

    audio = sys.argv[1]
    ausgabe = sys.argv[2] if len(sys.argv) > 2 else None
    transkribiere(audio, ausgabe)
