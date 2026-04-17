@echo off
chcp 65001 >nul 2>nul
setlocal enabledelayedexpansion

echo ============================================================
echo   RealtimeTranslator - Cai dat tu dong
echo ============================================================
echo.

set "BASE_DIR=%~dp0"
set "APP_DIR=%BASE_DIR%app"
set "PYTHON_DIR=%BASE_DIR%python"
set "VENV_DIR=%BASE_DIR%venv"
set "PYTHON_VER=3.12.10"
set "PYTHON_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
set "GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py"
set "PYTHON_ZIP=%PYTHON_DIR%\python-embed.zip"
set "GET_PIP=%PYTHON_DIR%\get-pip.py"
set "PTH_FILE=%PYTHON_DIR%\python312._pth"

REM ---- Check app source ----
echo [1/6] Kiem tra source code...
if not exist "%APP_DIR%\main.py" (
    echo [LOI] Khong tim thay %APP_DIR%\main.py
    echo Hay dam bao thu muc "app" chua source code.
    pause
    exit /b 1
)
echo     OK - Tim thay source code

REM ---- Download embedded Python ----
echo.
echo [2/6] Tai Python %PYTHON_VER% embedded...
if not exist "%PYTHON_DIR%" mkdir "%PYTHON_DIR%"
if exist "%PYTHON_DIR%\python.exe" goto :skip_python

echo     Dang tai tu python.org...

REM Try curl first (available on Windows 10+)
where curl >nul 2>nul
if !errorlevel! equ 0 (
    echo     Su dung curl...
    curl -L -o "%PYTHON_ZIP%" "%PYTHON_URL%"
) else (
    echo     Su dung PowerShell...
    powershell -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_ZIP%'"
)

if not exist "%PYTHON_ZIP%" (
    echo [LOI] Khong tai duoc Python.
    echo     - Kiem tra ket noi mang
    echo     - Thu tai thu cong: %PYTHON_URL%
    echo     - Luu vao: %PYTHON_ZIP%
    pause
    exit /b 1
)

echo     Dang giai nen...
powershell -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%PYTHON_ZIP%' -DestinationPath '%PYTHON_DIR%' -Force"
if !errorlevel! neq 0 (
    echo [LOI] Khong giai nen duoc Python.
    pause
    exit /b 1
)
del "%PYTHON_ZIP%" 2>nul

REM Enable pip in embedded Python
if exist "%PTH_FILE%" (
    powershell -ExecutionPolicy Bypass -Command "(Get-Content '%PTH_FILE%') -replace '#import site','import site' | Set-Content '%PTH_FILE%'"
)

REM Verify python.exe exists after extraction
if not exist "%PYTHON_DIR%\python.exe" (
    echo [LOI] python.exe khong tim thay sau khi giai nen.
    echo     Co the file zip bi loi. Thu xoa thu muc python va chay lai.
    pause
    exit /b 1
)

:skip_python
echo     OK - Python %PYTHON_VER%

REM ---- Install pip ----
echo.
echo [3/6] Cai dat pip...
if exist "%PYTHON_DIR%\Scripts\pip.exe" goto :skip_pip

where curl >nul 2>nul
if !errorlevel! equ 0 (
    curl -L -o "%GET_PIP%" "%GET_PIP_URL%"
) else (
    powershell -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%GET_PIP_URL%' -OutFile '%GET_PIP%'"
)

if not exist "%GET_PIP%" (
    echo [LOI] Khong tai duoc get-pip.py
    pause
    exit /b 1
)

"%PYTHON_DIR%\python.exe" "%GET_PIP%" --no-warn-script-location
if !errorlevel! neq 0 (
    echo [LOI] Cai pip that bai.
    pause
    exit /b 1
)
del "%GET_PIP%" 2>nul

if not exist "%PYTHON_DIR%\Scripts\pip.exe" (
    echo [LOI] pip.exe khong tim thay sau khi cai dat.
    pause
    exit /b 1
)

:skip_pip
echo     OK - pip

REM ---- Create virtualenv ----
echo.
echo [4/6] Tao moi truong ao...
if exist "%VENV_DIR%\Scripts\python.exe" goto :skip_venv

"%PYTHON_DIR%\python.exe" -m pip install virtualenv --no-warn-script-location -q
if !errorlevel! neq 0 (
    echo [LOI] Khong cai duoc virtualenv.
    pause
    exit /b 1
)

"%PYTHON_DIR%\python.exe" -m virtualenv "%VENV_DIR%" -q
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [LOI] Khong tao duoc virtualenv.
    pause
    exit /b 1
)

:skip_venv
echo     OK - virtualenv

REM ---- Verify pip in venv ----
if not exist "%VENV_DIR%\Scripts\pip.exe" (
    echo [LOI] pip.exe khong ton tai trong virtualenv.
    echo     Thu xoa thu muc "venv" va chay lai install.bat
    pause
    exit /b 1
)

REM ---- Install dependencies ----
echo.
echo [5/6] Cai dat dependencies (mat 5-15 phut)...

echo     Dang cai PyTorch + CUDA...
"%VENV_DIR%\Scripts\pip.exe" install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 -q
if !errorlevel! neq 0 (
    echo     CANH BAO - CUDA khong duoc, thu CPU version...
    "%VENV_DIR%\Scripts\pip.exe" install torch torchvision torchaudio -q
    if !errorlevel! neq 0 (
        echo     CANH BAO - Khong cai duoc PyTorch. Tiep tuc...
    )
)

echo     Dang cai cac package chinh...
"%VENV_DIR%\Scripts\pip.exe" install sounddevice numpy faster-whisper PyQt6 pyyaml openai huggingface-hub pyaudiowpatch -q
if !errorlevel! neq 0 (
    echo [LOI] Cai dependencies that bai.
    echo     Thu chay lai: "%VENV_DIR%\Scripts\pip.exe" install sounddevice numpy faster-whisper PyQt6 pyyaml openai huggingface-hub pyaudiowpatch
    pause
    exit /b 1
)

echo     Dang cai pyannote.audio...
"%VENV_DIR%\Scripts\pip.exe" install pyannote.audio -q
if !errorlevel! neq 0 (
    echo     CANH BAO - pyannote.audio khong cai duoc. Tinh nang VAD co the bi han che.
)

echo     Dang cai silero-vad (deep-learning VAD, tuy chon)...
"%VENV_DIR%\Scripts\pip.exe" install silero-vad -q
if !errorlevel! neq 0 (
    echo     CANH BAO - silero-vad khong cai duoc. Lop VAD deep-learning se bi tat.
)

echo     OK - Dependencies da cai

REM ---- Setup config ----
echo.
echo [6/6] Thiet lap cau hinh...
if not exist "%APP_DIR%\config\settings.yaml" (
    if exist "%APP_DIR%\config\settings.yaml.example" (
        copy "%APP_DIR%\config\settings.yaml.example" "%APP_DIR%\config\settings.yaml" >nul
        echo     OK - Da tao settings.yaml tu file mau
        echo     CHU Y: Mo file app\config\settings.yaml de dien API keys!
    )
) else (
    echo     OK - settings.yaml da ton tai
)

echo.
echo ============================================================
echo   CAI DAT HOAN TAT!
echo ============================================================
echo.
echo   Cac buoc tiep theo:
echo     1. Mo app\config\settings.yaml bang Notepad
echo     2. Dien API keys (Groq, OpenAI, Ollama, ...)
echo     3. Double-click "run.bat" de chay app
echo.
pause
