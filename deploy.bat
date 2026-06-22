@echo off
setlocal

REM =========================
REM NAILS BOT ONE-CLICK DEPLOY
REM =========================

set "SERVER_USER=root"
set "SERVER_HOST=144.31.239.83"
set "REMOTE_DEPLOY=/opt/deploy-nails-bot.sh"

REM Если передал сообщение коммита:
REM deploy.bat "fixed menu"
set "COMMIT_MSG=%~1"
if "%COMMIT_MSG%"=="" set "COMMIT_MSG=auto deploy"

echo.
echo =========================
echo  NAILS BOT DEPLOY START
echo =========================

echo.
echo === LOCAL: project folder ===
cd /d "%~dp0" || (
    echo ERROR: cannot open project folder
    pause
    exit /b 1
)

cd

echo.
echo === LOCAL: git branch ===
for /f "tokens=*" %%i in ('git branch --show-current') do set "BRANCH=%%i"

if "%BRANCH%"=="" (
    echo ERROR: cannot detect git branch
    pause
    exit /b 1
)

echo Branch: %BRANCH%

echo.
echo === LOCAL: git add ===
git add -A || (
    echo ERROR: git add failed
    pause
    exit /b 1
)

echo.
echo === LOCAL: git commit ===
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
echo === LOCAL: git push ===
git push origin %BRANCH% || (
    echo ERROR: git push failed
    pause
    exit /b 1
)

echo.
echo === VPS: remote deploy ===
ssh %SERVER_USER%@%SERVER_HOST% "bash %REMOTE_DEPLOY%" || (
    echo ERROR: VPS deploy failed
    pause
    exit /b 1
)

echo.
echo =========================
echo  DEPLOY SUCCESS
echo =========================
echo.
pause