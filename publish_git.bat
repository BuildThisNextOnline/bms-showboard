@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ==========================================
echo  BMS Show Board -- Publish to GitHub
echo ==========================================
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo [!] Git not found. Run setup_github.bat first.
    pause
    exit /b 1
)
if not exist ".git" (
    echo [!] Git not initialised. Run setup_github.bat first.
    pause
    exit /b 1
)
if exist ".git\rebase-merge" (
    echo [!] Git is in a broken rebase state. Run: git rebase --abort
    pause
    exit /b 1
)
if exist ".git\MERGE_HEAD" (
    echo [!] Git is in a broken merge state. Run: git merge --abort
    pause
    exit /b 1
)

if exist "showboard.html" (
    copy /Y showboard.html index.html >nul
    echo [OK] Synced showboard.html to index.html.
)

REM --- Push to bms-showboard (live tool repo) ---
git add index.html digest_latest.json README.md .gitignore
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "publish: %DATE%"
    git checkout -- index.html
    git pull
    git push
    if errorlevel 1 (
        echo ERROR: Push to bms-showboard failed. Check your internet connection.
        pause
        exit /b 1
    )
    echo [OK] Published to bms-showboard.
    echo      https://buildthisnextonline.github.io/bms-showboard
) else (
    echo [i] bms-showboard -- nothing has changed.
)

REM --- Push all source files to bms-showboard-code ---
git remote get-url code >nul 2>&1
if errorlevel 1 (
    echo [i] No 'code' remote found -- skipping code repo push.
    goto :end_publish
)
git add -f README_code.md requirements.txt ^
        bms_scraper.py bms_curator.py category_area_map.json ^
        run_bms.bat run_bms_scheduled.bat remap.bat publish_git.bat ^
        launch_chrome_debug.bat setup_github.bat setup_schedule.bat ^
        "BMS Show Board Weekly Scrape.xml"
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "publish: %DATE%"
    git pull code main --no-rebase
    git push code main
    if errorlevel 1 (
        echo WARNING: Push to bms-showboard-code failed.
    ) else (
        echo [OK] Published to bms-showboard-code.
    )
) else (
    echo [i] bms-showboard-code -- nothing has changed.
)
:end_publish

echo.
pause
