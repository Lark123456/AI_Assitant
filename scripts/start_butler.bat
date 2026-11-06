@echo off
title Butler Assistant
echo [Butler] Waking WSL and Docker, starting containers...
start "Butler-KeepAlive" /min wsl.exe -d Ubuntu -u root -- bash -c "sleep infinity"
wsl -d Ubuntu -u root -- bash -c "cd '/mnt/e/F&J/FJ v1' && (docker info >/dev/null 2>&1 || service docker start) && for i in 1 2 3 4 5 6 7 8 9 10; do docker info >/dev/null 2>&1 && break; echo '  waiting for docker daemon...'; sleep 2; done; docker compose up -d && sleep 8 && docker compose ps --format 'table {{.Name}}\t{{.Status}}' && (docker compose logs feishu --since 90s 2>&1 | grep -i connected | tail -1; true) && echo READY: send message to the bot in Feishu."
rem Open the database dashboard (adminer 绑定 127.0.0.1，经 WSL localhost 转发访问)
start "" "http://localhost:8080/"
echo.
echo [Butler] Assistant is RUNNING.
echo Database dashboard: http://localhost:8080/  (PostgreSQL / server=db / user=butler / pass=butler)
echo A minimized window "Butler-KeepAlive" in the taskbar keeps it alive.
echo Close that window to shut the assistant down.
echo.
pause
