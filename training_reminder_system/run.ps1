##############################################################################
# run.ps1 — Setup and run the Training Reminder System (Windows PowerShell)
#
# Usage:
#   .\run.ps1              # Show help
#   .\run.ps1 setup        # Create venv and install dependencies
#   .\run.ps1 cli          # Run a single processing cycle (CLI)
#   .\run.ps1 ui           # Launch the Streamlit web UI
#   .\run.ps1 simulate     # Generate test data and run simulation
#   .\run.ps1 test         # Run the test suite
#
# Note: If you get "cannot be loaded because running scripts is disabled",
# run this once as Administrator:
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
##############################################################################

param(
    [Parameter(Position=0)]
    [string]$Command,

    [Parameter(Position=1, ValueFromRemainingArguments=$true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ScriptDir ".venv"
$Requirements = Join-Path $ScriptDir "requirements.txt"
$Python = Join-Path $VenvDir "Scripts\python.exe"
$Pip = Join-Path $VenvDir "Scripts\pip.exe"
$Streamlit = Join-Path $VenvDir "Scripts\streamlit.exe"

function Write-Header {
    param([string]$Title)
    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host "  Training Reminder System — $Title" -ForegroundColor Cyan
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Show-Help {
    Write-Header "Help"
    Write-Host "  Usage: .\run.ps1 <command>" -ForegroundColor White
    Write-Host ""
    Write-Host "  Commands:" -ForegroundColor White
    Write-Host "    setup       " -NoNewline -ForegroundColor Green
    Write-Host "Create virtual environment and install dependencies"
    Write-Host "    cli         " -NoNewline -ForegroundColor Green
    Write-Host "Run a single processing cycle (command line)"
    Write-Host "    ui          " -NoNewline -ForegroundColor Green
    Write-Host "Launch the Streamlit web UI"
    Write-Host "    simulate    " -NoNewline -ForegroundColor Green
    Write-Host "Generate test data and run multi-cycle simulation"
    Write-Host "    test        " -NoNewline -ForegroundColor Green
    Write-Host "Run the test suite"
    Write-Host ""
    Write-Host "  Examples:" -ForegroundColor White
    Write-Host "    .\run.ps1 setup          # First-time setup"
    Write-Host "    .\run.ps1 ui             # Launch web interface"
    Write-Host "    .\run.ps1 cli            # Run one cycle"
    Write-Host "    .\run.ps1 simulate       # Demo with synthetic data"
    Write-Host ""
}

function Invoke-Setup {
    Write-Header "Setup"

    # Find Python
    $SysPython = $null
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $SysPython = "python"
    } elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
        $SysPython = "python3"
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $SysPython = "py"
    } else {
        Write-Host "  ERROR: Python not found." -ForegroundColor Red
        Write-Host "  Install Python 3.8+ from https://www.python.org/downloads/"
        Write-Host "  Make sure to check 'Add Python to PATH' during installation."
        return
    }

    $PyVersion = & $SysPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    Write-Host "  Python version: $PyVersion" -ForegroundColor Green

    # Create venv
    if (-not (Test-Path $Python)) {
        Write-Host "  Creating virtual environment in .venv\..."
        & $SysPython -m venv $VenvDir
        Write-Host "  Virtual environment created." -ForegroundColor Green
    } else {
        Write-Host "  Virtual environment already exists." -ForegroundColor Green
    }

    # Install dependencies
    Write-Host "  Installing dependencies from requirements.txt..."
    & $Pip install --upgrade pip --quiet
    & $Pip install -r $Requirements --quiet
    & $Pip install pytest --quiet

    Write-Host ""
    Write-Host "  Setup complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Next steps:"
    Write-Host "    .\run.ps1 ui          # Launch the web interface"
    Write-Host "    .\run.ps1 cli         # Run a processing cycle"
    Write-Host "    .\run.ps1 simulate    # Try with synthetic data"
    Write-Host ""
}

function Assert-Venv {
    if (-not (Test-Path $Python)) {
        Write-Host "  Virtual environment not found. Running setup..." -ForegroundColor Yellow
        Invoke-Setup
    }
}

function Invoke-Cli {
    Assert-Venv
    Write-Header "CLI Mode"

    Push-Location $ScriptDir
    try {
        if ($ExtraArgs) {
            & $Python main.py @ExtraArgs
        } else {
            & $Python main.py
        }
    } finally {
        Pop-Location
    }
}

function Invoke-Ui {
    Assert-Venv
    Write-Header "Web UI"

    if (-not (Test-Path $Streamlit)) {
        Write-Host "  Streamlit not found in venv. Installing..." -ForegroundColor Yellow
        & $Pip install streamlit --quiet
    }

    Write-Host "  Launching Streamlit web UI..."
    Write-Host "  The browser should open automatically."
    Write-Host "  If not, open: " -NoNewline
    Write-Host "http://localhost:8501" -ForegroundColor Cyan
    Write-Host ""

    Push-Location $ScriptDir
    try {
        if ($ExtraArgs) {
            & $Streamlit run streamlit_app.py @ExtraArgs
        } else {
            & $Streamlit run streamlit_app.py
        }
    } finally {
        Pop-Location
    }
}

function Invoke-Simulate {
    Assert-Venv
    Write-Header "Simulation"

    Push-Location $ScriptDir
    try {
        Write-Host "  Step 1: Generating synthetic test data..." -ForegroundColor Green
        Write-Host ""
        & $Python generate_test_data.py

        Write-Host ""
        Write-Host "  Step 2: Running multi-cycle simulation..." -ForegroundColor Green
        Write-Host ""
        & $Python run_simulation.py
    } finally {
        Pop-Location
    }
}

function Invoke-Test {
    Assert-Venv
    Write-Header "Tests"

    Push-Location $ScriptDir
    try {
        if ($ExtraArgs) {
            & $Python -m pytest tests/ -v @ExtraArgs
        } else {
            & $Python -m pytest tests/ -v
        }
    } finally {
        Pop-Location
    }
}

# --- Main ---
switch ($Command) {
    "setup"    { Invoke-Setup }
    "cli"      { Invoke-Cli }
    "ui"       { Invoke-Ui }
    "simulate" { Invoke-Simulate }
    "test"     { Invoke-Test }
    default    { Show-Help }
}
