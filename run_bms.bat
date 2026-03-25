@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ==========================================
echo  BMS Show Board
echo ==========================================
echo.

powershell -NoProfile -Command "try{[Net.Sockets.TcpClient]::new('127.0.0.1',9222).Close();exit 0}catch{exit 1}" 2>nul
if errorlevel 1 (
    echo [!] Chrome is not running on port 9222.
    echo     Please run launch_chrome_debug.bat first, then re-run this file.
    echo.
    pause
    exit /b 1
)
echo [OK] Chrome ready on port 9222.
echo.

echo [1/2] Scraping BookMyShow...
python bms_scraper.py --playwright
if errorlevel 1 (
    echo.
    echo ERROR: Scraping failed. Fix the issue and re-run.
    pause
    exit /b 1
)

echo.
echo [2/2] Curating with Claude...
python bms_curator.py
if errorlevel 1 (
    echo.
    echo ERROR: Curation failed. Scrape data saved in scrape_latest.json.
    echo To retry without re-scraping: python bms_curator.py
    pause
    exit /b 1
)

call :publish
goto :done

:publish
where git >nul 2>&1
if errorlevel 1 exit /b 0
if not exist ".git" exit /b 0
echo.
echo [3/3] Publishing to GitHub Pages...
REM Safety check -- abort if git is in a broken state (rebase/merge in progress)
if exist ".git\rebase-merge" (
    echo [!] Git is in a broken rebase state. Run: git rebase --abort
    exit /b 0
)
if exist ".git\MERGE_HEAD" (
    echo [!] Git is in a broken merge state. Run: git merge --abort
    exit /b 0
)
if exist "showboard.html" copy /Y showboard.html index.html >nul

REM --- Push to bms-showboard (live tool repo) ---
git add index.html digest_latest.json README.md .gitignore
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "digest: %DATE%"
    git checkout -- index.html
    git pull
    git push
    if errorlevel 1 (
        echo WARNING: Push to bms-showboard failed.
    ) else (
        echo [OK] Published to bms-showboard.
    )
) else (
    echo [i] bms-showboard -- no changes.
)

REM --- Push source files to bms-showboard-code ---
git remote get-url code >nul 2>&1
if not errorlevel 1 (
    git add -f README_code.md requirements.txt ^
        bms_scraper.py bms_curator.py category_area_map.json ^
        run_bms.bat run_bms_scheduled.bat remap.bat publish_git.bat ^
        launch_chrome_debug.bat setup_github.bat setup_schedule.bat ^
        "BMS Show Board Weekly Scrape.xml"
    git diff --cached --quiet
    if errorlevel 1 (
        git commit -m "digest: %DATE%"
        git push code main --force
        if errorlevel 1 (
            echo WARNING: Push to bms-showboard-code failed.
        ) else (
            echo [OK] Published to bms-showboard-code.
        )
    ) else (
        echo [i] bms-showboard-code -- no changes.
    )
)
exit /b 0

:done
echo.
echo ==========================================
echo  Done. Your Show Board is live at:
echo  https://buildthisnextonline.github.io/bms-showboard
echo ==========================================
echo.
pause
