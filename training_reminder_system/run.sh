#!/usr/bin/env bash
##############################################################################
# run.sh — Setup and run the Training Reminder System
#
# Usage:
#   ./run.sh              # Show help
#   ./run.sh setup        # Create venv and install dependencies
#   ./run.sh cli           # Run a single processing cycle (CLI)
#   ./run.sh ui            # Launch the Streamlit web UI
#   ./run.sh simulate      # Generate test data and run simulation
#   ./run.sh test          # Run the test suite
#
# The script creates a Python virtual environment in .venv/ on first run
# and installs all dependencies from requirements.txt.
##############################################################################

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
PYTHON="${VENV_DIR}/bin/python"
PIP="${VENV_DIR}/bin/pip"
STREAMLIT="${VENV_DIR}/bin/streamlit"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "\n${BLUE}============================================================${NC}"
    echo -e "${BLUE}  Training Reminder System${NC}"
    echo -e "${BLUE}============================================================${NC}\n"
}

print_usage() {
    print_header
    echo "Usage: ./run.sh <command>"
    echo ""
    echo "Commands:"
    echo -e "  ${GREEN}setup${NC}       Create virtual environment and install dependencies"
    echo -e "  ${GREEN}cli${NC}         Run a single processing cycle (command line)"
    echo -e "  ${GREEN}ui${NC}          Launch the Streamlit web UI"
    echo -e "  ${GREEN}simulate${NC}    Generate test data and run multi-cycle simulation"
    echo -e "  ${GREEN}test${NC}        Run the test suite"
    echo ""
    echo "Examples:"
    echo "  ./run.sh setup          # First-time setup"
    echo "  ./run.sh ui             # Launch web interface"
    echo "  ./run.sh cli            # Run one cycle from command line"
    echo "  ./run.sh simulate       # Demo with synthetic data"
    echo ""
}

# -----------------------------------------------------------------------
# Setup: create venv and install dependencies
# -----------------------------------------------------------------------
do_setup() {
    print_header
    echo -e "${YELLOW}Setting up virtual environment...${NC}"

    # Find Python 3
    if command -v python3 &> /dev/null; then
        SYS_PYTHON="python3"
    elif command -v python &> /dev/null; then
        SYS_PYTHON="python"
    else
        echo -e "${RED}Error: Python 3 not found. Please install Python 3.8+.${NC}"
        exit 1
    fi

    # Check Python version
    PY_VERSION=$($SYS_PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo -e "  Python version: ${GREEN}${PY_VERSION}${NC}"

    # Create venv
    if [ ! -d "$VENV_DIR" ]; then
        echo "  Creating virtual environment in .venv/..."
        $SYS_PYTHON -m venv "$VENV_DIR"
        echo -e "  ${GREEN}Virtual environment created.${NC}"
    else
        echo -e "  ${GREEN}Virtual environment already exists.${NC}"
    fi

    # Install dependencies
    echo "  Installing dependencies from requirements.txt..."
    "$PIP" install --upgrade pip --quiet
    "$PIP" install -r "$REQUIREMENTS" --quiet
    "$PIP" install pytest --quiet

    echo ""
    echo -e "${GREEN}Setup complete!${NC}"
    echo ""
    echo "Next steps:"
    echo "  ./run.sh ui          # Launch the web interface"
    echo "  ./run.sh cli         # Run a processing cycle"
    echo "  ./run.sh simulate    # Try with synthetic data"
}

# -----------------------------------------------------------------------
# Ensure venv exists, or run setup automatically
# -----------------------------------------------------------------------
ensure_venv() {
    if [ ! -f "$PYTHON" ]; then
        echo -e "${YELLOW}Virtual environment not found. Running setup...${NC}"
        do_setup
    fi
}

# -----------------------------------------------------------------------
# CLI: run a single processing cycle
# -----------------------------------------------------------------------
do_cli() {
    ensure_venv
    print_header
    echo -e "${GREEN}Running processing cycle (CLI mode)...${NC}\n"

    cd "$SCRIPT_DIR"
    CONFIG="${1:-config.yaml}"
    "$PYTHON" main.py "$CONFIG"
}

# -----------------------------------------------------------------------
# UI: launch Streamlit web interface
# -----------------------------------------------------------------------
do_ui() {
    ensure_venv
    print_header

    # Check if streamlit is installed
    if [ ! -f "$STREAMLIT" ]; then
        echo -e "${YELLOW}Streamlit not found in venv. Installing...${NC}"
        "$PIP" install streamlit --quiet
    fi

    echo -e "${GREEN}Launching Streamlit web UI...${NC}"
    echo -e "  The browser should open automatically."
    echo -e "  If not, open: ${BLUE}http://localhost:8501${NC}"
    echo ""

    cd "$SCRIPT_DIR"
    "$STREAMLIT" run streamlit_app.py "$@"
}

# -----------------------------------------------------------------------
# Simulate: generate test data and run simulation
# -----------------------------------------------------------------------
do_simulate() {
    ensure_venv
    print_header

    echo -e "${GREEN}Step 1: Generating synthetic test data...${NC}\n"
    cd "$SCRIPT_DIR"
    "$PYTHON" generate_test_data.py

    echo ""
    echo -e "${GREEN}Step 2: Running multi-cycle simulation...${NC}\n"
    "$PYTHON" run_simulation.py
}

# -----------------------------------------------------------------------
# Test: run the test suite
# -----------------------------------------------------------------------
do_test() {
    ensure_venv
    print_header

    echo -e "${GREEN}Running test suite...${NC}\n"
    cd "$SCRIPT_DIR"
    "$PYTHON" -m pytest tests/ -v "$@"
}

# -----------------------------------------------------------------------
# Main entry point
# -----------------------------------------------------------------------
case "${1:-}" in
    setup)
        do_setup
        ;;
    cli)
        shift
        do_cli "$@"
        ;;
    ui)
        shift
        do_ui "$@"
        ;;
    simulate)
        do_simulate
        ;;
    test)
        shift
        do_test "$@"
        ;;
    *)
        print_usage
        ;;
esac
