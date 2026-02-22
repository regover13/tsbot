@echo off
echo ================================================
echo  Protokoll aus Transkript erstellen
echo ================================================
echo.

REM Transkript-Datei
if "%~1"=="" (
    echo Transkript-TXT per Drag ^& Drop auf dieses Skript ziehen,
    echo oder Pfad eingeben:
    set /p TXTFILE="Pfad zur Transkript-Datei: "
) else (
    set TXTFILE=%~1
)

if not exist "%TXTFILE%" (
    echo FEHLER: Datei nicht gefunden: %TXTFILE%
    pause
    exit /b 1
)

echo.
set /p THEMA="Thema/Titel der Sitzung: "

REM Agenda automatisch aus Skript-Ordner laden
set AGENDA=%~dp0agenda.txt
if exist "%AGENDA%" (
    echo Agenda geladen: %AGENDA%
) else (
    echo Hinweis: Keine agenda.txt gefunden.
    set AGENDA=
)

REM Screenshots: alle PNGs im Ordner werden automatisch per OCR ausgewertet
for /f %%F in ('dir /b "%~dp0*.png" 2^>nul') do echo Screenshot gefunden: %%F
echo (Alle PNGs werden per Claude Vision ausgewertet)

echo.
echo Erstelle Word-Protokoll...

python "%~dp0protokoll_erstellen.py" "%TXTFILE%" "%THEMA%" "%AGENDA%"

echo.
pause
