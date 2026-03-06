#!/bin/bash
#
# BananaWiki Update Script
# ========================
# Safely updates BananaWiki to the latest version
#
# This script will:
#   1. Create a backup of the current installation
#   2. Pull the latest code from git
#   3. Update dependencies
#   4. Run database migrations (automatic)
#   5. Restart the service
#   6. Verify the update was successful
#
# Usage:
#   sudo ./update.sh                          # Update current installation
#   sudo ./update.sh --branch <branch>        # Update to specific branch
#   sudo ./update.sh --skip-backup            # Skip backup (not recommended)
#   sudo ./update.sh --no-restart             # Don't restart service after update
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}"
BRANCH=""
SKIP_BACKUP=false
NO_RESTART=false
BACKUP_DIR="${APP_DIR}/backups"
SERVICE_NAME="bananawiki"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --skip-backup)
            SKIP_BACKUP=true
            shift
            ;;
        --no-restart)
            NO_RESTART=true
            shift
            ;;
        --app-dir)
            APP_DIR="$2"
            shift 2
            ;;
        --service-name)
            SERVICE_NAME="$2"
            shift 2
            ;;
        -h|--help)
            echo "BananaWiki Update Script"
            echo ""
            echo "Usage: sudo $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --branch BRANCH      Update to specific git branch (default: current branch)"
            echo "  --skip-backup        Skip creating backup before update (not recommended)"
            echo "  --no-restart         Don't restart the service after update"
            echo "  --app-dir DIR        Application directory (default: script directory)"
            echo "  --service-name NAME  Systemd service name (default: bananawiki)"
            echo "  -h, --help           Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Error: Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ] && [ -z "$SUDO_USER" ]; then
    echo -e "${YELLOW}Warning: This script should typically be run with sudo${NC}"
    echo -e "${YELLOW}Continuing anyway, but some operations may fail...${NC}"
    echo ""
fi

# Print banner
clear
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}           🍌 BananaWiki Update${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Change to app directory
cd "$APP_DIR"

# Verify we're in a git repository
if [ ! -d ".git" ]; then
    echo -e "${RED}Error: Not a git repository${NC}"
    echo "This script must be run from a BananaWiki installation that was installed via git."
    exit 1
fi

# Get current branch and commit
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
CURRENT_COMMIT=$(git rev-parse --short HEAD)

if [ -z "$BRANCH" ]; then
    BRANCH="$CURRENT_BRANCH"
fi

echo -e "${CYAN}Update Information${NC}"
echo "  Application directory: $APP_DIR"
echo "  Current branch: $CURRENT_BRANCH"
echo "  Current commit: $CURRENT_COMMIT"
echo "  Target branch: $BRANCH"
echo "  Service name: $SERVICE_NAME"
echo ""

# Check if service exists
SERVICE_EXISTS=false
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    SERVICE_EXISTS=true
    SERVICE_STATUS=$(systemctl is-active "$SERVICE_NAME" || echo "inactive")
    echo -e "  Service status: ${YELLOW}${SERVICE_STATUS}${NC}"
else
    echo -e "  ${YELLOW}Service not found (running in development mode?)${NC}"
fi
echo ""

# Confirm before proceeding
read -p "Continue with update? [Y/n]: " input
if [[ "$input" =~ ^[Nn]$ ]]; then
    echo -e "${YELLOW}Update cancelled${NC}"
    exit 0
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}Starting update...${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Step 1: Create backup
if [ "$SKIP_BACKUP" = false ]; then
    echo -e "${BLUE}[1/7]${NC} Creating backup..."

    # Create backup directory if it doesn't exist
    mkdir -p "$BACKUP_DIR"

    # Generate backup filename with timestamp
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="${BACKUP_DIR}/bananawiki_backup_${TIMESTAMP}.tar.gz"

    # Create backup excluding venv, .git, and backups directory
    tar -czf "$BACKUP_FILE" \
        --exclude='venv' \
        --exclude='.git' \
        --exclude='backups' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.pytest_cache' \
        -C "$APP_DIR" . > /dev/null 2>&1

    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo -e "${GREEN}✓${NC} Backup created: $BACKUP_FILE (${BACKUP_SIZE})"

    # Keep only last 5 backups
    cd "$BACKUP_DIR"
    ls -t bananawiki_backup_*.tar.gz 2>/dev/null | tail -n +6 | xargs -r rm
    BACKUP_COUNT=$(ls -1 bananawiki_backup_*.tar.gz 2>/dev/null | wc -l)
    echo "   Backup retention: keeping last ${BACKUP_COUNT} backups"
    cd "$APP_DIR"
else
    echo -e "${BLUE}[1/7]${NC} ${YELLOW}Skipping backup${NC}"
fi
echo ""

# Step 2: Check for uncommitted changes
echo -e "${BLUE}[2/7]${NC} Checking for local changes..."
if git diff-index --quiet HEAD --; then
    echo -e "${GREEN}✓${NC} No uncommitted changes"
else
    echo -e "${YELLOW}Warning: You have uncommitted changes${NC}"
    git status --short
    echo ""
    read -p "Stash changes and continue? [Y/n]: " input
    if [[ "$input" =~ ^[Nn]$ ]]; then
        echo -e "${YELLOW}Update cancelled${NC}"
        exit 0
    fi
    git stash save "Automatic stash before update at $(date)"
    echo -e "${GREEN}✓${NC} Changes stashed"
fi
echo ""

# Step 3: Fetch and pull latest changes
echo -e "${BLUE}[3/7]${NC} Pulling latest changes from git..."

# Fetch all branches
git fetch --all > /dev/null 2>&1

# Get remote commit before pull
REMOTE_COMMIT=$(git rev-parse --short "origin/${BRANCH}")

# Checkout target branch if different
if [ "$BRANCH" != "$CURRENT_BRANCH" ]; then
    echo "   Switching from $CURRENT_BRANCH to $BRANCH..."
    git checkout "$BRANCH" > /dev/null 2>&1
fi

# Check if there are updates
if [ "$CURRENT_COMMIT" = "$REMOTE_COMMIT" ]; then
    echo -e "${YELLOW}   Already up to date (commit $CURRENT_COMMIT)${NC}"
else
    # Pull changes
    git pull origin "$BRANCH" > /dev/null 2>&1
    NEW_COMMIT=$(git rev-parse --short HEAD)
    echo -e "${GREEN}✓${NC} Updated from $CURRENT_COMMIT to $NEW_COMMIT"

    # Show commit log
    echo ""
    echo "   Recent changes:"
    git log --oneline --no-merges "$CURRENT_COMMIT..HEAD" | head -5 | sed 's/^/     /'
fi
echo ""

# Step 4: Update Python dependencies
echo -e "${BLUE}[4/7]${NC} Updating Python dependencies..."

VENV_PATH="${APP_DIR}/venv"
if [ ! -d "$VENV_PATH" ]; then
    echo -e "${YELLOW}   Virtual environment not found, creating...${NC}"
    python3 -m venv "$VENV_PATH"
fi

# Activate virtual environment and update dependencies
"${VENV_PATH}/bin/pip" install -q --upgrade pip > /dev/null 2>&1
OUTDATED_COUNT=$("${VENV_PATH}/bin/pip" list --outdated 2>/dev/null | wc -l)
"${VENV_PATH}/bin/pip" install -q -r requirements.txt > /dev/null 2>&1

if [ "$OUTDATED_COUNT" -gt 2 ]; then
    echo -e "${GREEN}✓${NC} Dependencies updated (${OUTDATED_COUNT} packages)"
else
    echo -e "${GREEN}✓${NC} Dependencies up to date"
fi
echo ""

# Step 5: Run database migrations
echo -e "${BLUE}[5/7]${NC} Running database migrations..."
echo "   Database migrations run automatically on app startup"
echo -e "${GREEN}✓${NC} Migrations will be applied when service starts"
echo ""

# Step 6: Restart service
if [ "$NO_RESTART" = false ] && [ "$SERVICE_EXISTS" = true ]; then
    echo -e "${BLUE}[6/7]${NC} Restarting service..."

    # Restart the service
    systemctl restart "$SERVICE_NAME"

    # Wait a moment for service to start
    sleep 2

    # Check if service started successfully
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo -e "${GREEN}✓${NC} Service restarted successfully"
    else
        echo -e "${RED}✗ Service failed to start${NC}"
        echo ""
        echo "   Recent logs:"
        journalctl -u "$SERVICE_NAME" -n 20 --no-pager
        echo ""
        echo -e "${YELLOW}Attempting to restore from backup...${NC}"

        if [ -f "$BACKUP_FILE" ]; then
            systemctl stop "$SERVICE_NAME"
            tar -xzf "$BACKUP_FILE" -C "$APP_DIR"
            systemctl start "$SERVICE_NAME"

            if systemctl is-active --quiet "$SERVICE_NAME"; then
                echo -e "${GREEN}✓${NC} Service restored from backup"
            else
                echo -e "${RED}✗ Failed to restore service${NC}"
                echo "   Manual intervention required"
            fi
        fi
        exit 1
    fi
elif [ "$NO_RESTART" = true ]; then
    echo -e "${BLUE}[6/7]${NC} ${YELLOW}Skipping service restart${NC}"
    echo "   Remember to restart the service manually:"
    echo "   ${CYAN}sudo systemctl restart $SERVICE_NAME${NC}"
else
    echo -e "${BLUE}[6/7]${NC} ${YELLOW}Service not found - running in development mode${NC}"
    echo "   If running manually, restart the application to apply changes"
fi
echo ""

# Step 7: Verify update
echo -e "${BLUE}[7/7]${NC} Verifying update..."

FINAL_COMMIT=$(git rev-parse --short HEAD)
FINAL_BRANCH=$(git rev-parse --abbrev-ref HEAD)

echo "   Current branch: $FINAL_BRANCH"
echo "   Current commit: $FINAL_COMMIT"

if [ "$SERVICE_EXISTS" = true ]; then
    SERVICE_STATUS=$(systemctl is-active "$SERVICE_NAME")
    if [ "$SERVICE_STATUS" = "active" ]; then
        echo -e "   Service status: ${GREEN}${SERVICE_STATUS}${NC}"
    else
        echo -e "   Service status: ${RED}${SERVICE_STATUS}${NC}"
    fi
fi

echo -e "${GREEN}✓${NC} Verification complete"
echo ""

# Installation complete
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Update completed successfully!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [ "$SKIP_BACKUP" = false ]; then
    echo -e "${CYAN}Backup Information:${NC}"
    echo "  Backup file: $BACKUP_FILE"
    echo "  Backup size: $BACKUP_SIZE"
    echo ""
    echo -e "${YELLOW}To restore from backup if needed:${NC}"
    echo "  1. Stop the service: ${CYAN}sudo systemctl stop $SERVICE_NAME${NC}"
    echo "  2. Extract backup: ${CYAN}sudo tar -xzf $BACKUP_FILE -C $APP_DIR${NC}"
    echo "  3. Start the service: ${CYAN}sudo systemctl start $SERVICE_NAME${NC}"
    echo ""
fi

if [ "$SERVICE_EXISTS" = true ]; then
    echo -e "${CYAN}Useful commands:${NC}"
    echo -e "  View logs:        ${YELLOW}sudo journalctl -u $SERVICE_NAME -f${NC}"
    echo -e "  Check status:     ${YELLOW}sudo systemctl status $SERVICE_NAME${NC}"
    echo -e "  Restart service:  ${YELLOW}sudo systemctl restart $SERVICE_NAME${NC}"
    echo ""
fi

echo -e "${GREEN}Update complete! Your BananaWiki is now running the latest version.${NC}"
echo ""
