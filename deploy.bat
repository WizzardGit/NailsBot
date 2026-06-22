@echo off
setlocal

REM =========================
REM WIZZARD NAILS BOT DEPLOY
REM =========================

REM VPS
set "SERVER_USER=root"
set "SERVER_HOST=144.31.239.83"

REM Скрипт на VPS
set "REMOTE_DEPLOY=/opt/deploy-nails-bot.sh"

REM Сообщение коммита. Можно запускать так:
REM deploy.bat "added new buttons"
set "COMMIT_MSG=%~1"
if "%COMMIT_MSG%"=="" set "COMMIT_MSG=auto deploy"

echo.
echo === LOCAL: go to project folder ===
cd /d "%~dp0" || (
    echo ERROR: cannot open project folder
    pause
    exit /b 1
)

echo.
echo === LOCAL: current folder ===
cd

echo.
echo === LOCAL: current branch ===
for /f "tokens=*" %%i in ('git branch --show-current') do set "BRANCH=%%i"
if "%BRANCH%"=="" (
    echo ERROR: cannot detect git branch
    pause
    exit /b 1
)
echo Branch: %BRANCH%

echo.
echo === LOCAL: git status ===
git status || (
    echo ERROR: git status failed
    pause
    exit /b 1
)

echo.
echo === LOCAL: add all changes ===
git add -A || (
    echo ERROR: git add failed
    pause
    exit /b 1
)

echo.
echo === LOCAL: commit if changed ===
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "%COMMIT_MSG%" || (
        echo ERROR: git commit failed
        pause
        exit /b 1
    )
) else (
    echo No changes to commit.
)

echo.
echo === LOCAL: push ===
git push origin %BRANCH% || (
    echo ERROR: git push failed
    pause
    exit /b 1
)

echo.
echo === REMOTE: deploy on VPS ===
ssh %SERVER_USER%@%SERVER_HOST% "bash %REMOTE_DEPLOY%" || (
    echo ERROR: remote deploy failed
    pause
    exit /b 1
)

echo.
echo === DONE ===
pause