@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ==========================================
echo  BMS Show Board -- GitHub Setup
echo ==========================================
echo.
echo This runs once to connect your scraper folder to GitHub.
echo You need:
echo   1. A GitHub account (github.com)
echo   2. Git installed (git-scm.com/download/win)
echo   3. A repo named "bms-showboard" created on GitHub (Public, empty)
echo.
echo Press any key when ready, or Ctrl+C to cancel.
pause >nul

where git >nul 2>&1
if errorlevel 1 (
    echo.
    echo [!] Git is not installed.
    echo     Download from: https://git-scm.com/download/win
    echo     Install with all defaults. Then re-run this script.
    pause
    exit /b 1
)
echo [OK] Git found.

echo.
set /p GITHUB_USER=Enter your GitHub username: 
if "%GITHUB_USER%"=="" (
    echo [!] Username cannot be empty.
    pause
    exit /b 1
)

set REPO_URL=https://github.com/%GITHUB_USER%/bms-showboard.git
echo.
echo Repo URL: %REPO_URL%
echo.

if not exist ".git" (
    echo Initialising git repository...
    git init
    git branch -M main
) else (
    echo [OK] Git repo already initialised.
)

git remote remove origin >nul 2>&1
git remote add origin %REPO_URL%
echo [OK] Remote set to %REPO_URL%

echo Creating .gitignore...
(
    echo *
    echo !index.html
    echo !digest_latest.json
    echo !.gitignore
) > .gitignore
echo [OK] .gitignore created.

if exist "showboard.html" (
    copy /Y showboard.html index.html >nul
    echo [OK] Copied showboard.html to index.html.
) else (
    echo [!] showboard.html not found in this folder.
    pause
    exit /b 1
)

echo.
echo Pushing to GitHub...
git add index.html digest_latest.json .gitignore
git commit -m "initial: BMS Show Board setup"
git push -u origin main

if errorlevel 1 (
    echo.
    echo [!] Push failed. Common reasons:
    echo     1. Repo does not exist yet -- create it at github.com/new
    echo        Name: bms-showboard, Public, NO readme, NO gitignore
    echo     2. Authentication needed -- Git will prompt for username
    echo        and a Personal Access Token (not your password).
    echo        Create token at: github.com/settings/tokens
    echo        Select "repo" scope, copy and paste as the password.
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo  Setup complete!
echo  Your Show Board URL:
echo  https://%GITHUB_USER%.github.io/bms-showboard
echo.
echo  Next: enable GitHub Pages at
echo  github.com/%GITHUB_USER%/bms-showboard/settings/pages
echo  Source: Deploy from branch, main, / (root)
echo ==========================================
echo.
echo [i] Also tell Google Drive to ignore the .git folder:
echo     Drive desktop app - Settings - Preferences
echo     Add folder exclusion for .git in this directory.
echo.
pause
