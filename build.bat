@echo off
echo ============================================
echo  RealtimeTranslator - Build Executable
echo ============================================
echo.

REM Check if uv is available
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] uv not found. Install from https://docs.astral.sh/uv/
    pause
    exit /b 1
)

REM Sync dependencies
echo [1/3] Installing dependencies...
uv sync
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)

REM Install PyInstaller if not present
echo [2/3] Ensuring PyInstaller is installed...
uv run pip install pyinstaller
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install PyInstaller
    pause
    exit /b 1
)

REM Build
echo [3/3] Building executable...
uv run pyinstaller main.spec --noconfirm
if %errorlevel% neq 0 (
    echo [ERROR] Build failed. Check errors above.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Build completed!
echo  Output: dist\RealtimeTranslator\
echo ============================================
echo.
echo Next steps:
echo   1. Copy config\settings.yaml.example to dist\RealtimeTranslator\config\settings.yaml
echo   2. Edit settings.yaml with your API keys
echo   3. Run dist\RealtimeTranslator\RealtimeTranslator.exe
echo.
pause
