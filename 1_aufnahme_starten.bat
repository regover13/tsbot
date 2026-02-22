@echo off
echo ================================================
echo  Sitzungsaufnahme - Jabra + Desktop-Audio
echo ================================================
echo.

REM Ausgabe-Ordner und Dateiname mit Zeitstempel
set OUTDIR=%~dp0
set TAG=%date:~6,4%%date:~3,2%%date:~0,2%
set UHRZEIT=%time:~0,2%%time:~3,2%
set UHRZEIT=%UHRZEIT: =0%
set AUSGABE=%OUTDIR%aufnahme_%TAG%_%UHRZEIT%.mp3

echo Mikrofon : Jabra Link 380
echo Desktop  : CABLE Output (VB-Audio Virtual Cable)
echo Ausgabe  : %AUSGABE%
echo.
echo Aufnahme laeuft... zum Stoppen Q druecken (im Fenster)
echo.

ffmpeg -f dshow -i audio="CABLE Output (VB-Audio Virtual Cable)" ^
       -f dshow -i audio="Mikrofon (2- Jabra Link 380)" ^
       -filter_complex "[0:a][1:a]amix=inputs=2:duration=longest:normalize=0" ^
       -acodec libmp3lame -ab 64k ^
       "%AUSGABE%"

echo.
echo ================================================
echo  Aufnahme gespeichert:
echo  %AUSGABE%
echo.
echo  Naechster Schritt: 2_transkribieren.bat
echo ================================================
pause
