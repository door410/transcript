@echo off
rem ============================================================
rem  YouTube Transcript Tool - Setup
rem  PURE ASCII ONLY. The system codepage is 950 (Big5) here;
rem  UTF-8 Chinese bytes corrupt this file's line parsing.
rem  That is also why every filename this script touches is ASCII.
rem ============================================================
title YouTube Transcript Tool - Setup
cd /d "%~dp0"
echo.
echo   ============================================
echo    YouTube Transcript Tool - Setup
echo   ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python not found.
    echo   Install from https://www.python.org/downloads/
    echo   and tick "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   Python %%v found

echo.
echo   [1/4] Installing core packages...
python -m pip install --quiet --upgrade youtube-transcript-api yt-dlp
if errorlevel 1 goto failcore
echo         done

echo.
echo   [2/4] Installing AI transcription engine (about 123 MB)...
echo         Takes a few minutes. Please wait.
python -m pip install --quiet --upgrade faster-whisper
if errorlevel 1 (
    echo         [WARN] faster-whisper failed. Videos WITH subtitles
    echo                still work. Retry later with:
    echo                python -m pip install faster-whisper
) else (
    echo         done
)

echo.
echo   [3/4] Checking for NVIDIA graphics card...
where nvidia-smi >nul 2>&1
if errorlevel 1 (
    echo         No NVIDIA GPU detected - CPU will be used.
    goto shortcut
)
echo         NVIDIA GPU found. Installing CUDA libraries...
echo         About 1 GB. Slow, but makes AI transcription ~5x faster.
python -m pip install --quiet nvidia-cublas-cu12 nvidia-cudnn-cu12
if errorlevel 1 (
    echo         [WARN] CUDA libraries failed - will fall back to CPU.
) else (
    echo         done - GPU acceleration enabled
)

:shortcut
echo.
echo   [4/4] Creating desktop shortcut...
cscript //nologo "%~dp0make_shortcut.vbs" >nul 2>&1
if errorlevel 1 (
    echo         [WARN] Could not create shortcut.
    echo                Run start.vbs in this folder instead.
) else (
    echo         done
)

echo.
echo   ============================================
echo    Setup complete.
echo.
echo    Double-click the desktop icon to launch,
echo    or run start.vbs in this folder.
echo   ============================================
echo.
python -c "import ytscript,sys; d,c=ytscript.pick_device(); print('   Compute device: '+d.upper()+' ('+c+')')" 2>nul
echo.
pause
exit /b 0

:failcore
echo.
echo   [ERROR] Could not install required packages.
echo   Check the internet connection and try again.
echo.
pause
exit /b 1
