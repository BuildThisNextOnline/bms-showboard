@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ==========================================
echo  BMS Show Board -- Remap Categories/Areas
echo ==========================================
echo.
echo Re-applying category and area normalisation to cached events.
echo No API calls, no scraping. Uses category_area_map.json.
echo.

python bms_curator.py --remap
if errorlevel 1 (
    echo.
    echo ERROR: Remap failed.
    pause
    exit /b 1
)

echo.
echo [Publish] Pushing updated digest to GitHub...
if exist "showboard.html" copy /Y showboard.html index.html >nul
where git >nul 2>&1
if errorlevel 1 goto :done
if not exist ".git" goto :done
if exist ".git\rebase-merge" (
    echo [!] Git is in a broken rebase state. Run: git rebase --abort
    goto :done
)
REM --- Push to bms-showboard (live tool repo) ---
git add index.html digest_latest.json README.md .gitignore
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "remap: %DATE%"
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
        git commit -m "remap: %DATE%"
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

:done
echo.
echo ==========================================
echo  Done.
echo ==========================================
echo.
pause
