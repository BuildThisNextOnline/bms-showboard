@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ==========================================
echo  BMS Show Board -- Scheduled Run
echo ==========================================
echo.

REM Launch Chrome with debug port if not already running
powershell -NoProfile -Command "try{[Net.Sockets.TcpClient]::new('127.0.0.1',9222).Close();exit 0}catch{exit 1}" 2>nul
if errorlevel 1 (
    echo [i] Chrome not running -- launching now...
    call launch_chrome_debug.bat
    REM Wait 8 seconds for Chrome to fully start
    timeout /t 8 /nobreak >nul
)

REM Verify Chrome is ready
powershell -NoProfile -Command "try{[Net.Sockets.TcpClient]::new('127.0.0.1',9222).Close();exit 0}catch{exit 1}" 2>nul
if errorlevel 1 (
    echo ERROR: Chrome failed to start on port 9222. Aborting.
    exit /b 1
)
echo [OK] Chrome ready on port 9222.
echo.

echo [1/2] Scraping BookMyShow...
python bms_scraper.py --playwright
if errorlevel 1 (
    echo ERROR: Scraping failed.
    exit /b 1
)

echo.
echo [2/2] Curating with Claude...
python bms_curator.py
if errorlevel 1 (
    echo ERROR: Curation failed. Run bms_curator.py manually to retry.
    exit /b 1
)

call :publish
exit /b 0

:publish
where git >nul 2>&1
if errorlevel 1 exit /b 0
if not exist ".git" exit /b 0
echo.
echo [3/3] Publishing to GitHub Pages...
if exist "showboard.html" copy /Y showboard.html index.html >nul
git add index.html digest_latest.json
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "digest: %DATE%"
    git push
    if errorlevel 1 (
        echo WARNING: Git push failed.
    ) else (
        echo [OK] Published to GitHub Pages.
    )
) else (
    echo [i] No changes to publish.
)
exit /b 0
