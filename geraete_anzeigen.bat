@echo off
echo ================================================
echo  Verfuegbare Audio-Aufnahmegeraete (dshow)
echo ================================================
echo.
ffmpeg -list_devices true -f dshow -i dummy 2>&1
echo.
pause
