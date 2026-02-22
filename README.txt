================================================
 WHISPER SETUP - Sitzungstranskription
 TeamSpeak -> Transkript -> Word-Protokoll
================================================

VORAUSSETZUNGEN
---------------
- Python 3.9+       winget install Python.Python.3
  (Bei Installation: "Add Python to PATH" anhaaken!)
- ffmpeg            winget install ffmpeg
- VB-Cable          https://vb-audio.com/Cable/
  (einmalig installieren, kostenlos)
- Anthropic API-Key
  Benoetigt fuer: Teilnehmer-OCR und Protokoll-Zuordnung per KI
  Holen unter:    https://console.anthropic.com/settings/keys
    1. Einloggen / Konto erstellen
    2. "Create Key" klicken, Namen vergeben
    3. Key kopieren (wird nur einmal angezeigt!)
    4. In config.txt eintragen: ANTHROPIC_API_KEY=sk-ant-...
  Kosten: wenige Cent pro Sitzung (Nutzungsabhaengig)
  Hinweis: config.txt ist in .gitignore - wird nie ins Repo committed!


EINRICHTUNG (einmalig)
-----------------------
1. install.bat als Administrator ausfuehren
   Erkennt automatisch ob NVIDIA GPU vorhanden ist und
   installiert PyTorch mit CUDA (GPU) oder CPU-Version.
   Installiert: Whisper, python-docx, anthropic SDK

2. Windows Soundeinstellungen (einmalig nach VB-Cable-Installation):
   Rechtsklick Lautsprecher-Symbol → "Soundeinstellungen" →
   "Weitere Soundeinstellungen"

   Tab "Wiedergabe":
   - "Lautsprecher (VB-Audio Virtual Cable)" → Rechtsklick →
     "Als Standardgeraet festlegen"
     (alle System-Sounds laufen nun durch VB-Cable)

   Tab "Aufnahme":
   - "CABLE Output (VB-Audio Virtual Cable)" → Rechtsklick →
     "Als Standardgeraet festlegen"
   - "CABLE Output" → Rechtsklick → "Eigenschaften" →
     Tab "Abhoeren" →
     "Dieses Geraet abhoeren" aktivieren →
     "Wiedergabe ueber: [dein Kopfhoerer/Lautsprecher,
      z.B. Lautsprecher (2- Jabra Link 380)]"
     → OK
     (du hoerst alles weiterhin normal ueber dein Geraet)

3. config.txt oeffnen → API-Key eintragen

4. agenda.txt vor jeder Sitzung anpassen (ein Punkt pro Zeile)


WORKFLOW PRO SITZUNG
---------------------

SCHRITT 1: AUFNAHME
→ 1_aufnahme_starten.bat doppelklicken
  Nimmt auf: Jabra-Mikrofon + alles was durch VB-Cable laeuft
  (TeamSpeak-Ausgabe, alle System-Sounds)
  Stoppen: Q druecken
  Ergebnis: aufnahme_YYYYMMDD_HHMM.mp3

SCHRITT 2: TEAMSPEAK-SCREENSHOTS FUER TEILNEHMERLISTE
  Screenshots von TS3 machen wenn Teilnehmer beitreten oder gehen
  (Win+Shift+S oder Druck-Taste) und alle PNGs in diesen Ordner legen.
  Dateiname egal – es werden ALLE PNGs im Ordner ausgewertet.
  Claude Vision extrahiert automatisch alle Nutzernamen im Format
  "Vorname Nachname/FRSxxx", filtert Kanalbezeichnungen heraus
  und entfernt Duplikate. Ergebnis: Tabelle im Protokoll.

SCHRITT 3: TRANSKRIBIEREN
→ 2_transkribieren.bat ausfuehren
  MP3 per Drag & Drop auf das Skript ziehen.
  Laeuft auf NVIDIA GPU (z.B. RTX 5080) oder CPU (Whisper large-Modell).
  Ergebnis: aufnahme_..._transkript_YYYYMMDD_HHMM.txt

SCHRITT 4: PROTOKOLL ERSTELLEN
→ 3_protokoll_erstellen.bat ausfuehren
  Transkript-TXT per Drag & Drop auf das Skript ziehen.
  Thema eingeben – Rest laeuft automatisch:
  - Agenda aus agenda.txt
  - Teilnehmer per OCR aus allen PNGs
  - Claude API ordnet Transkript den Agenda-Punkten zu
  Ergebnis: Protokoll_YYYYMMDD_HHMM.docx
  (mit Inhaltsverzeichnis, Teilnehmertabelle, Zusammenfassungen)
  Inhaltsverzeichnis in Word mit F9 aktualisieren!


DATEIEN IM ORDNER
------------------
install.bat              Einmalige Installation
1_aufnahme_starten.bat   Aufnahme starten/stoppen
2_transkribieren.bat     MP3 -> Transkript (TXT)
3_protokoll_erstellen.bat Transkript -> Word-Protokoll
transkribieren.py        Whisper-Skript (large, GPU)
protokoll_erstellen.py   Protokoll-Generator mit Claude API
agenda.txt               Agenda bearbeiten vor jeder Sitzung
config.txt               API-Key (NICHT ins Git committen!)
config.example.txt       Vorlage fuer config.txt
.gitignore               Schuetzt API-Key und Aufnahmen vor Git


WHISPER-MODELLE
---------------
  large   – Standard, beste Qualitaet  (~2.9 GB, GPU empfohlen)
  medium  – schneller, etwas ungenauer (~1.5 GB)
  small   – CPU-tauglich               (~460 MB)
  Modell aendern in: transkribieren.py → whisper.load_model("...")


SUPPORT
-------
Bei Fragen einfach Claude in Cowork fragen!

================================================
