#!/bin/bash
# MeManga setup script for Linux (Debian/Ubuntu/Raspberry Pi)

set -e

# Navigate to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

echo "📖 Setting up MeManga..."
echo "   Project: $PROJECT_DIR"
echo ""

# Check for system dependencies
echo "Checking system dependencies..."
if ! command -v xvfb-run &> /dev/null; then
    echo "Installing xvfb (needed for headless browser)..."
    sudo apt-get update && sudo apt-get install -y xvfb
fi

# Create venv if not exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Install Playwright browsers
echo "Installing Playwright browsers (this may take a while)..."
playwright install chromium firefox

# Create config directory
mkdir -p ~/.config/memanga/downloads

echo ""
echo "✅ Setup complete!"
echo ""
echo "Quick start:"
echo "  ./scripts/run.sh              # Launch interactive TUI"
echo "  ./scripts/run.sh add -i       # Add manga to track"
echo "  ./scripts/run.sh check        # Check for new chapters"
echo "  ./scripts/run.sh --help       # See all commands"
