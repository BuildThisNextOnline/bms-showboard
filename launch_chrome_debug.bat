@echo off
setlocal

REM ── BMS Scraper: Launch Chrome with remote debugging ──────────────────────
REM Uses a dedicated scraper-only profile. Does NOT affect Opera or any
REM other browser. Google sign-in is NOT required.

set PORT=9222
set PROFILE_DIR=%~dp0.chrome_bms_profile

REM ── Find Chrome ───────────────────────────────────────────────────────────
set CHROME=

if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe
    goto :found
)
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
    goto :found
)
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe
    goto :found
)

echo ERROR: Could not find Chrome.
echo Install Chrome from https://www.google.com/chrome/
pause
exit /b 1

:found
echo Found Chrome: %CHROME%
echo Debug port  : %PORT%
echo Profile     : %PROFILE_DIR%
echo.

REM Kill any existing Chrome on this debug port first (clean start)
taskkill /F /FI "WindowTitle eq BMS Scraper Chrome*" >nul 2>&1

echo Starting Chrome for BMS scraper...
echo You can minimise this window. Keep it open while scraping.
echo.

start "BMS Scraper Chrome" "%CHROME%" ^
  --remote-debugging-port=%PORT% ^
  --user-data-dir="%PROFILE_DIR%" ^
  --disable-ipv6 ^
  --no-first-run ^
  --no-default-browser-check ^
  --new-window ^
  about:blank

timeout /t 3 /nobreak >nul

REM Verify Chrome is listening
powershell -Command "try { $r = Invoke-WebRequest http://localhost:%PORT%/json/version -UseBasicParsing -TimeoutSec 3; Write-Host 'Chrome ready on port %PORT%'; Write-Host $r.Content } catch { Write-Host 'WARNING: Chrome not responding on port %PORT% yet. Wait a few seconds and try running the scraper.' }"

echo.
echo Run the scraper now:
echo   python bms_scraper.py --playwright --save
echo.
pause
endlocal
