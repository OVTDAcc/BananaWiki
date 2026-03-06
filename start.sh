#!/bin/bash
#
# BananaWiki Production Start Script
# ===================================
# Simple script to start BananaWiki with Gunicorn for production use
#
# Usage:
#   ./start.sh                    # Start with gunicorn.conf.py settings
#   ./start.sh --port 8080        # Override port
#   ./start.sh --workers 8        # Override worker count
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values (can be overridden by command line)
PORT=""
HOST=""
WORKERS=""
BIND=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --port)
            PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --workers)
            WORKERS="$2"
            shift 2
            ;;
        --bind)
            BIND="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --port PORT       Override port from config.py"
            echo "  --host HOST       Override host from config.py"
            echo "  --bind ADDR       Bind to address (e.g., 0.0.0.0:8080)"
            echo "  --workers N       Override worker count"
            echo "  -h, --help        Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                        # Use gunicorn.conf.py settings"
            echo "  $0 --port 8080            # Start on port 8080"
            echo "  $0 --bind 0.0.0.0:5001    # Bind to all interfaces on port 5001"
            echo "  $0 --workers 8            # Use 8 workers"
            exit 0
            ;;
        *)
            echo -e "${RED}Error: Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}🍌 BananaWiki Production Server${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check if venv exists
if [ ! -d "venv" ]; then
    echo -e "${RED}Error: Virtual environment not found${NC}"
    echo "Please run './dev.sh' first to set up the environment or run './install.sh' for production setup"
    exit 1
fi

# Activate venv
source venv/bin/activate

# Check if gunicorn is installed
if ! command -v gunicorn &> /dev/null; then
    echo -e "${RED}Error: Gunicorn is not installed${NC}"
    echo "Installing gunicorn..."
    pip install gunicorn
fi

echo -e "${GREEN}✓${NC} Starting Gunicorn production server..."
echo ""

# Build gunicorn command
GUNICORN_CMD="gunicorn wsgi:app -c gunicorn.conf.py"

# Add overrides if provided
if [ -n "$BIND" ]; then
    GUNICORN_CMD="$GUNICORN_CMD --bind $BIND"
    echo -e "  Bind address: ${BLUE}$BIND${NC}"
else
    if [ -n "$HOST" ] || [ -n "$PORT" ]; then
        # Use config.py defaults if not both specified
        if [ -z "$HOST" ]; then
            HOST=$(python3 -c "import config; print(config.HOST)" 2>/dev/null || echo "127.0.0.1")
        fi
        if [ -z "$PORT" ]; then
            PORT=$(python3 -c "import config; print(config.PORT)" 2>/dev/null || echo "5001")
        fi
        GUNICORN_CMD="$GUNICORN_CMD --bind $HOST:$PORT"
        echo -e "  Bind address: ${BLUE}$HOST:$PORT${NC}"
    else
        # Show config.py values
        HOST=$(python3 -c "import config; print(config.HOST)" 2>/dev/null || echo "127.0.0.1")
        PORT=$(python3 -c "import config; print(config.PORT)" 2>/dev/null || echo "5001")
        echo -e "  Bind address: ${BLUE}$HOST:$PORT${NC} (from config.py)"
    fi
fi

if [ -n "$WORKERS" ]; then
    GUNICORN_CMD="$GUNICORN_CMD --workers $WORKERS"
    echo -e "  Workers:      ${BLUE}$WORKERS${NC}"
else
    # Show configured workers from gunicorn.conf.py
    WORKERS=$(python3 -c "import gunicorn.conf as gc; print(getattr(gc, 'workers', 'auto'))" 2>/dev/null || echo "auto")
    echo -e "  Workers:      ${BLUE}$WORKERS${NC} (from gunicorn.conf.py)"
fi

echo ""
echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
echo ""

# Run gunicorn
exec $GUNICORN_CMD
