================================================
 WHISPER SETUP - Sitzungstranskription
 TeamSpeak / Audioaufnahmen -> Word-Protokoll
================================================

VORAUSSETZUNGEN
---------------
- Python 3.9 oder neuer  →  https://www.python.org/downloads/
  (Bei Installation: "Add Python to PATH" anhaaken!)
- ffmpeg                 →  winget install ffmpeg
  (oder https://ffmpeg.org/download.html)


SCHRITT 1: EINMALIGE INSTALLATION
----------------------------------
→ 1_install.bat ausfuehren
   Installiert Whisper und alle Abhaengigkeiten automatisch.
   Beim ersten Transkript wird das KI-Modell (~1.5 GB) heruntergeladen.


SCHRITT 2: TEAMSPEAK-AUFNAHME
------------------------------
Option A – TeamSpeak eingebaut:
  Tools → Options → Capture → "Start recording" aktivieren
  Aufnahmen landen unter: %AppData%\TS3Client\

Option B – OBS Studio (kostenlos):
  Audio-Quelle: "Desktop-Audio" oder Mikrofon
  Format: MP3 oder WAV


SCHRITT 3: TRANSKRIBIEREN
--------------------------
→ 2_transkribieren.bat ausfuehren
   Audiodatei per Drag & Drop auf das Skript ziehen
   ODER beim Start den Pfad eingeben.

   Ergebnis: <dateiname>_transkript_YYYYMMDD_HHMM.txt
   (mit Zeitstempeln, z.B. [00:35 - 00:42] "Dann fangen wir an...")


SCHRITT 4: WORD-PROTOKOLL ERSTELLEN
-------------------------------------
→ 3_protokoll_erstellen.bat ausfuehren
   Transkript-TXT per Drag & Drop auf das Skript ziehen.
   Thema und Teilnehmer eingeben.

   Ergebnis: Protokoll_YYYYMMDD_HHMM.docx
   (fertiges Word-Dokument mit Zeitstempeln, Metadaten, Notizfeld)


WHISPER-MODELLE (optional anpassen in transkribieren.py)
---------------------------------------------------------
  tiny    – sehr schnell, weniger genau      (~75 MB)
  base    – schnell, OK fuer klare Sprache   (~145 MB)
  small   – guter Kompromiss                 (~460 MB)
  medium  – EMPFOHLEN fuer Deutsch           (~1.5 GB)  ← Standard
  large   – maximale Genauigkeit             (~3.1 GB)


SUPPORT
-------
Bei Fragen einfach Claude in Cowork fragen!

================================================
