@echo off
chcp 65001 >nul 2>nul
setlocal

set "BASE_DIR=%~dp0"
set "VENV_DIR=%BASE_DIR%venv"
set "APP_DIR=%BASE_DIR%app"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [LOI] Chua cai dat. Hay chay install.bat truoc!
    pause
    exit /b 1
)

if not exist "%APP_DIR%\main.py" (
    echo [LOI] Khong tim thay app\main.py
    pause
    exit /b 1
)

if not exist "%APP_DIR%\config\settings.yaml" (
    if exist "%APP_DIR%\config\settings.yaml.example" (
        copy "%APP_DIR%\config\settings.yaml.example" "%APP_DIR%\config\settings.yaml" >nul
        echo CHU Y: Mo app\config\settings.yaml de dien API keys!
    )
)

echo Dang khoi dong RealtimeTranslator...
cd /d "%APP_DIR%"
"%VENV_DIR%\Scripts\python.exe" main.py %*
