@echo off
rem Pure ASCII only - the system codepage here is 950 (Big5) and
rem UTF-8 Chinese bytes would corrupt this file's line parsing.
title YouTube Transcript Tool - Diagnostics
cd /d "%~dp0"
echo.
echo   Running with a visible console so you can read any error.
echo   Close this window to stop the program.
echo.
python ytscript.py
echo.
echo   Program exited.
pause
