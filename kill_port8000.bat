@echo off
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do taskkill /f /pid %%a
timeout /t 2 /nobreak >nul
echo Puerto 8000 liberado.
exit
