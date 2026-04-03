@echo off
REM ##########################################################################
REM  run.bat — Setup and run the Training Reminder System (Windows)
REM
REM  Usage:
REM    run.bat              Show help
REM    run.bat setup        Create venv and install dependencies
REM    run.bat cli          Run a single processing cycle (CLI)
REM    run.bat ui           Launch the Streamlit web UI
REM    run.bat simulate     Generate test data and run simulation
REM    run.bat test         Run the test suite
REM
REM  The script creates a Python virtual environment in .venv\ on first run
REM  and installs all dependencies from requirements.txt.
REM ##########################################################################

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "REQUIREMENTS=%SCRIPT_DIR%requirements.txt"
set "PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PIP=%VENV_DIR%\Scripts\pip.exe"
set "STREAMLIT=%VENV_DIR%\Scripts\streamlit.exe"

if "%~1"=="" goto :help
if "%~1"=="setup" goto :setup
if "%~1"=="cli" goto :cli
if "%~1"=="ui" goto :ui
if "%~1"=="simulate" goto :simulate
if "%~1"=="test" goto :test
if "%~1"=="help" goto :help
if "%~1"=="-h" goto :help
if "%~1"=="--help" goto :help

echo Unknown command: %~1
echo.
goto :help

REM -----------------------------------------------------------------------
REM  Help
REM -----------------------------------------------------------------------
:help
echo.
echo  ============================================================
echo   Training Reminder System
echo  ============================================================
echo.
echo  Usage: run.bat ^<command^>
echo.
echo  Commands:
echo    setup       Create virtual environment and install dependencies
echo    cli         Run a single processing cycle (command line)
echo    ui          Launch the Streamlit web UI
echo    simulate    Generate test data and run multi-cycle simulation
echo    test        Run the test suite
echo.
echo  Examples:
echo    run.bat setup          First-time setup
echo    run.bat ui             Launch web interface
echo    run.bat cli            Run one cycle from command line
echo    run.bat simulate       Demo with synthetic data
echo.
goto :eof

REM -----------------------------------------------------------------------
REM  Setup: create venv and install dependencies
REM -----------------------------------------------------------------------
:setup
echo.
echo  ============================================================
echo   Training Reminder System — Setup
echo  ============================================================
echo.

REM Find Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    where python3 >nul 2>nul
    if %errorlevel% neq 0 (
        echo  ERROR: Python not found. Please install Python 3.8+ from python.org
        echo  Make sure to check "Add Python to PATH" during installation.
        goto :eof
    )
    set "SYS_PYTHON=python3"
) else (
    set "SYS_PYTHON=python"
)

REM Check Python version
for /f "tokens=*" %%i in ('%SYS_PYTHON% -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set PY_VERSION=%%i
echo  Python version: %PY_VERSION%

REM Create venv
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo  Creating virtual environment in .venv\...
    %SYS_PYTHON% -m venv "%VENV_DIR%"
    echo  Virtual environment created.
) else (
    echo  Virtual environment already exists.
)

REM Install dependencies
echo  Installing dependencies from requirements.txt...
"%PIP%" install --upgrade pip --quiet
"%PIP%" install -r "%REQUIREMENTS%" --quiet
"%PIP%" install pytest --quiet

echo.
echo  Setup complete!
echo.
echo  Next steps:
echo    run.bat ui          Launch the web interface
echo    run.bat cli         Run a processing cycle
echo    run.bat simulate    Try with synthetic data
echo.
goto :eof

REM -----------------------------------------------------------------------
REM  Ensure venv exists
REM -----------------------------------------------------------------------
:ensure_venv
if not exist "%PYTHON%" (
    echo  Virtual environment not found. Running setup...
    call :setup
)
goto :eof

REM -----------------------------------------------------------------------
REM  CLI: run a single processing cycle
REM -----------------------------------------------------------------------
:cli
call :ensure_venv
echo.
echo  ============================================================
echo   Training Reminder System — CLI Mode
echo  ============================================================
echo.

cd /d "%SCRIPT_DIR%"
if "%~2"=="" (
    "%PYTHON%" main.py
) else (
    "%PYTHON%" main.py %~2
)
goto :eof

REM -----------------------------------------------------------------------
REM  UI: launch Streamlit web interface
REM -----------------------------------------------------------------------
:ui
call :ensure_venv
echo.
echo  ============================================================
echo   Training Reminder System — Web UI
echo  ============================================================
echo.

if not exist "%STREAMLIT%" (
    echo  Streamlit not found in venv. Installing...
    "%PIP%" install streamlit --quiet
)

echo  Launching Streamlit web UI...
echo  The browser should open automatically.
echo  If not, open: http://localhost:8501
echo.

cd /d "%SCRIPT_DIR%"
"%STREAMLIT%" run streamlit_app.py %2 %3 %4 %5
goto :eof

REM -----------------------------------------------------------------------
REM  Simulate: generate test data and run simulation
REM -----------------------------------------------------------------------
:simulate
call :ensure_venv
echo.
echo  ============================================================
echo   Training Reminder System — Simulation
echo  ============================================================
echo.

cd /d "%SCRIPT_DIR%"

echo  Step 1: Generating synthetic test data...
echo.
"%PYTHON%" generate_test_data.py

echo.
echo  Step 2: Running multi-cycle simulation...
echo.
"%PYTHON%" run_simulation.py
goto :eof

REM -----------------------------------------------------------------------
REM  Test: run the test suite
REM -----------------------------------------------------------------------
:test
call :ensure_venv
echo.
echo  ============================================================
echo   Training Reminder System — Tests
echo  ============================================================
echo.

cd /d "%SCRIPT_DIR%"
"%PYTHON%" -m pytest tests/ -v %2 %3 %4 %5
goto :eof
