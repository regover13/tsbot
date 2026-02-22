@echo off
echo ================================================
echo  Whisper Setup - Installation
echo ================================================
echo.

REM Python pruefen
python --version >nul 2>&1
if %errorlevel% neq 0 goto :kein_python
goto :python_ok

:kein_python
echo FEHLER: Python ist nicht installiert!
echo Bitte Python von python.org/downloads herunterladen.
echo Wichtig: Bei der Installation "Add Python to PATH" anhaaken!
pause
exit /b 1

:python_ok
echo Python gefunden. Installiere Abhaengigkeiten...
echo.

REM pip aktualisieren
python -m pip install --upgrade pip
echo.

REM Python Scripts-Pfad zu PATH hinzufuegen (verhindert PATH-Warnungen)
for /f "delims=" %%P in ('python -c "import site; print(site.USER_BASE)"') do set PYUSERBASE=%%P
set PYSCRIPTS=%PYUSERBASE%\Scripts
echo %PATH% | find /i "%PYSCRIPTS%" >nul 2>&1
if %errorlevel% neq 0 (
    echo Python Scripts-Pfad wird zu PATH hinzugefuegt: %PYSCRIPTS%
    setx PATH "%PATH%;%PYSCRIPTS%" >nul
    echo Pfad gesetzt - bitte CMD neu starten damit es wirkt.
) else (
    echo Python Scripts-Pfad bereits in PATH.
)
echo.

REM NVIDIA GPU pruefen
echo Pruefe auf NVIDIA GPU...
nvidia-smi >nul 2>&1
if %errorlevel% == 0 goto :nvidia_gefunden
goto :kein_nvidia

:nvidia_gefunden
echo NVIDIA GPU erkannt - installiere PyTorch mit CUDA 12.8...
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
goto :pytorch_fertig

:kein_nvidia
echo Keine NVIDIA GPU gefunden - installiere PyTorch CPU-Version...
pip install torch torchvision torchaudio
goto :pytorch_fertig

:pytorch_fertig
echo.

REM Whisper installieren
echo Installiere OpenAI Whisper...
pip install openai-whisper
echo.

REM ffmpeg pruefen
ffmpeg -version >nul 2>&1
if %errorlevel% == 0 goto :ffmpeg_ok
goto :ffmpeg_fehlt

:ffmpeg_fehlt
echo HINWEIS: ffmpeg nicht gefunden!
echo Whisper benoetigt ffmpeg - Installation via:
echo   winget install ffmpeg
echo Danach dieses Skript erneut ausfuehren.
echo.
goto :weitere_pakete

:ffmpeg_ok
echo ffmpeg gefunden.
echo.

:weitere_pakete
REM python-docx fuer Word-Protokolle
echo Installiere python-docx...
pip install python-docx
echo.

REM Anthropic SDK fuer Claude API
echo Installiere anthropic SDK...
pip install anthropic
echo.

echo ================================================
echo  Installation abgeschlossen!
echo.
echo  GPU-Status pruefen:
python -c "import torch; print('  CUDA verfuegbar:', torch.cuda.is_available()); print('  GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'keine')"
echo.
echo  Naechster Schritt: 2_transkribieren.bat
echo ================================================
pause
