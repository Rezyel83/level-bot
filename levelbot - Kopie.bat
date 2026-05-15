@echo off
title verify bot Desktop -> Dropbox Sync
echo Level Bot Sync gestartet
echo Main: Dropbox\Level Bot
echo Backup: Desktop\Level Bot 1
echo Druecke STRG+C zum Beenden
echo.

set "SOURCE=C:\Users\Rafan\Desktop\Level Bot1"
set "TARGET=C:\Users\Rafan\Dropbox\Level Bot"
set INTERVAL=15

:loop
robocopy "%SOURCE%" "%TARGET%" /E /XO /R:1 /W:1 /NFL /NDL /NP
echo [%date% %time%] Sync gelaufen
timeout /t %INTERVAL% /nobreak >nul
goto loop