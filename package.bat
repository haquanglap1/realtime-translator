@echo off
chcp 65001 >nul 2>nul
echo ============================================================
echo   RealtimeTranslator - Dong goi bo cai dat
echo ============================================================
echo.
echo Script nay tao thu muc "RealtimeTranslator-Setup" chua:
echo   - install.bat  (script cai dat tu dong)
echo   - run.bat      (launcher)
echo   - app\          (source code, KHONG co API keys)
echo.
echo Nguoi nhan chi can:
echo   1. Chay install.bat (cai Python + deps tu dong)
echo   2. Chinh sua app\config\settings.yaml (dien API keys)
echo   3. Chay run.bat
echo.

set "SRC_DIR=%~dp0"
set "OUT_DIR=%SRC_DIR%RealtimeTranslator-Setup"

REM Clean old output
if exist "%OUT_DIR%" (
    echo Dang xoa ban dong goi cu...
    rmdir /S /Q "%OUT_DIR%"
)

echo Dang tao cau truc thu muc...
mkdir "%OUT_DIR%"
mkdir "%OUT_DIR%\app"
mkdir "%OUT_DIR%\app\core"
mkdir "%OUT_DIR%\app\ui"
mkdir "%OUT_DIR%\app\utils"
mkdir "%OUT_DIR%\app\config"

REM Copy installer scripts
echo Dang copy installer scripts...
copy "%SRC_DIR%installer\install.bat" "%OUT_DIR%\install.bat" >nul
copy "%SRC_DIR%installer\run.bat" "%OUT_DIR%\run.bat" >nul

REM Copy source code (no __pycache__, no .git, no secrets)
echo Dang copy source code...
copy "%SRC_DIR%main.py" "%OUT_DIR%\app\main.py" >nul
copy "%SRC_DIR%pyproject.toml" "%OUT_DIR%\app\pyproject.toml" >nul

REM Core
for %%f in ("%SRC_DIR%core\*.py") do copy "%%f" "%OUT_DIR%\app\core\" >nul

REM UI
for %%f in ("%SRC_DIR%ui\*.py") do copy "%%f" "%OUT_DIR%\app\ui\" >nul

REM Utils
for %%f in ("%SRC_DIR%utils\*.py") do copy "%%f" "%OUT_DIR%\app\utils\" >nul

REM Config (example only, NOT the real settings.yaml with API keys)
copy "%SRC_DIR%config\settings.yaml.example" "%OUT_DIR%\app\config\settings.yaml.example" >nul
copy "%SRC_DIR%config\prompts.yaml" "%OUT_DIR%\app\config\prompts.yaml" >nul

echo.
echo ============================================================
echo   DONG GOI HOAN TAT!
echo ============================================================
echo.
echo   Thu muc: %OUT_DIR%
echo.
echo   Nen zip thu muc nay va gui cho nguoi dung.
echo   KHONG co API keys trong ban dong goi.
echo.
echo   Huong dan nguoi nhan:
echo     1. Giai nen
echo     2. Chay install.bat (doi 5-15 phut cai dat)
echo     3. Sua app\config\settings.yaml
echo     4. Chay run.bat
echo.
pause
