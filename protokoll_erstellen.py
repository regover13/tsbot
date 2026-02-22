#!/usr/bin/env python3
"""
Windows-Wrapper – delegiert an core/protokoll_erstellen.py.
Die .bat-Dateien rufen dieses Skript auf; die Logik liegt in core/.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "core"))
from protokoll_erstellen import erstelle_protokoll  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Verwendung: python protokoll_erstellen.py <transkript.txt> [thema] [agenda.txt]")
        sys.exit(1)

    erstelle_protokoll(
        transkript_pfad = sys.argv[1],
        thema           = sys.argv[2] if len(sys.argv) > 2 else "",
        agenda_pfad     = sys.argv[3] if len(sys.argv) > 3 else None,
    )
