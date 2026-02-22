@echo off
echo ================================================
echo  Whisper - Transkription
echo ================================================
echo.

REM Audiodatei per Drag & Drop oder Eingabe
if "%~1"=="" (
    echo Audiodatei per Drag ^& Drop auf dieses Skript ziehen,
    echo oder Pfad eingeben:
    set /p AUDIOFILE="Pfad zur Audiodatei: "
) else (
    set AUDIOFILE=%~1
)

if not exist "%AUDIOFILE%" (
    echo FEHLER: Datei nicht gefunden: %AUDIOFILE%
    pause
    exit /b 1
)

echo.
echo Datei: %AUDIOFILE%
echo Sprache: Deutsch
echo Modell: large (beste Qualitaet, ca. 2.9 GB, nutzt RTX 5080 GPU)
echo.
echo Starte Transkription... (kann einige Minuten dauern)
echo.

REM Ausgabe-Ordner = gleicher Ordner wie Audiodatei
set OUTDIR=%~dp1
if "%OUTDIR%"=="" set OUTDIR=%~dp0

REM Trailing-Backslash entfernen (verhindert Pfad-Fehler in Python)
if "%OUTDIR:~-1%"=="\" set OUTDIR=%OUTDIR:~0,-1%

python "%~dp0transkribieren.py" "%AUDIOFILE%" "%OUTDIR%"

echo.
echo Fertig! Transkript wurde gespeichert in:
echo %OUTDIR%
echo.
echo Naechster Schritt: 3_protokoll_erstellen.bat ausfuehren
pause
