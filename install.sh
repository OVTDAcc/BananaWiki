#!/bin/bash
#
# BananaWiki Production Installation Script
# ==========================================
# Automated setup for production deployment on Ubuntu/Debian VPS
#
# This script will:
#   1. Install system dependencies (Python, nginx, etc.)
#   2. Set up the application directory and virtual environment
#   3. Install Python dependencies
#   4. Create and configure systemd service
#   5. Configure nginx reverse proxy (optional)
#   6. Set up SSL with Let's Encrypt (optional)
#
# Usage:
#   sudo ./install.sh                          # Interactive setup
#   sudo ./install.sh --non-interactive        # Use defaults
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default configuration values
APP_NAME="bananawiki"
APP_DIR="/opt/BananaWiki"
APP_USER="www-data"
APP_GROUP="www-data"
VENV_PATH="$APP_DIR/venv"
PORT=5001
WORKERS=4
NON_INTERACTIVE=false
SETUP_NGINX=true
SETUP_SSL=false
DOMAIN=""
EMAIL=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --non-interactive)
            NON_INTERACTIVE=true
            shift
            ;;
        --app-name)
            APP_NAME="$2"
            shift 2
            ;;
        --app-dir)
            APP_DIR="$2"
            VENV_PATH="$APP_DIR/venv"
            shift 2
            ;;
        --user)
            APP_USER="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --workers)
            WORKERS="$2"
            shift 2
            ;;
        --domain)
            DOMAIN="$2"
            SETUP_NGINX=true
            shift 2
            ;;
        --email)
            EMAIL="$2"
            shift 2
            ;;
        --ssl)
            SETUP_SSL=true
            shift
            ;;
        --no-nginx)
            SETUP_NGINX=false
            shift
            ;;
        -h|--help)
            echo "BananaWiki Production Installation Script"
            echo ""
            echo "Usage: sudo $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --non-interactive    Skip all prompts, use defaults"
            echo "  --app-name NAME      Service name (default: bananawiki)"
            echo "  --app-dir DIR        Installation directory (default: /opt/BananaWiki)"
            echo "  --user USER          System user to run as (default: www-data)"
            echo "  --port PORT          Port to bind to (default: 5001)"
            echo "  --workers N          Number of Gunicorn workers (default: 4)"
            echo "  --domain DOMAIN      Domain name for nginx/SSL setup"
            echo "  --email EMAIL        Email for Let's Encrypt notifications"
            echo "  --ssl                Set up SSL with Let's Encrypt"
            echo "  --no-nginx           Skip nginx configuration"
            echo "  -h, --help           Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Error: Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    echo "Please run: sudo $0"
    exit 1
fi

# Print banner
clear
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}           🍌 BananaWiki Production Installation${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Interactive prompts if not in non-interactive mode
if [ "$NON_INTERACTIVE" = false ]; then
    echo -e "${CYAN}Installation Configuration${NC}"
    echo ""

    read -p "Installation directory [$APP_DIR]: " input
    APP_DIR="${input:-$APP_DIR}"
    VENV_PATH="$APP_DIR/venv"

    read -p "System user to run as [$APP_USER]: " input
    APP_USER="${input:-$APP_USER}"
    APP_GROUP="${input:-$APP_USER}"

    read -p "Port to bind to [$PORT]: " input
    PORT="${input:-$PORT}"

    read -p "Number of Gunicorn workers [$WORKERS]: " input
    WORKERS="${input:-$WORKERS}"

    echo ""
    read -p "Set up nginx reverse proxy? [Y/n]: " input
    if [[ "$input" =~ ^[Nn]$ ]]; then
        SETUP_NGINX=false
    else
        SETUP_NGINX=true
        read -p "Domain name (leave empty for IP-only access): " DOMAIN

        if [ -n "$DOMAIN" ]; then
            read -p "Set up SSL with Let's Encrypt? [y/N]: " input
            if [[ "$input" =~ ^[Yy]$ ]]; then
                SETUP_SSL=true
                read -p "Email for Let's Encrypt notifications: " EMAIL
            fi
        fi
    fi

    echo ""
    echo -e "${YELLOW}Review your configuration:${NC}"
    echo "  Installation directory: $APP_DIR"
    echo "  System user: $APP_USER"
    echo "  Port: $PORT"
    echo "  Workers: $WORKERS"
    echo "  Nginx: $SETUP_NGINX"
    if [ "$SETUP_NGINX" = true ] && [ -n "$DOMAIN" ]; then
        echo "  Domain: $DOMAIN"
        echo "  SSL: $SETUP_SSL"
    fi
    echo ""
    read -p "Continue with installation? [Y/n]: " input
    if [[ "$input" =~ ^[Nn]$ ]]; then
        echo -e "${YELLOW}Installation cancelled${NC}"
        exit 0
    fi
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}Starting installation...${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Step 1: Install system dependencies
echo -e "${BLUE}[1/6]${NC} Installing system dependencies..."
apt-get update -qq
PACKAGES="python3 python3-venv python3-pip git"
if [ "$SETUP_NGINX" = true ]; then
    PACKAGES="$PACKAGES nginx"
fi
if [ "$SETUP_SSL" = true ]; then
    PACKAGES="$PACKAGES certbot python3-certbot-nginx"
fi
apt-get install -y $PACKAGES > /dev/null 2>&1
echo -e "${GREEN}✓${NC} System dependencies installed"

# Step 2: Create application directory and set permissions
echo -e "${BLUE}[2/6]${NC} Setting up application directory..."
mkdir -p "$APP_DIR"

# Check if running in a git repository (for development)
if [ -d ".git" ]; then
    # Copy current directory contents to APP_DIR
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ "$SCRIPT_DIR" != "$APP_DIR" ]; then
        echo "   Copying files from current directory to $APP_DIR..."
        rsync -a --exclude=venv --exclude=instance --exclude=logs --exclude=.git \
              --exclude='__pycache__' --exclude='*.pyc' \
              "$SCRIPT_DIR/" "$APP_DIR/"
    fi
else
    # Clone from GitHub if not already present
    if [ ! -f "$APP_DIR/app.py" ]; then
        echo "   Cloning BananaWiki from GitHub..."
        git clone -q https://github.com/ovtdadt/BananaWiki.git "$APP_DIR"
    fi
fi

chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"
echo -e "${GREEN}✓${NC} Application directory ready"

# Step 3: Set up Python virtual environment
echo -e "${BLUE}[3/6]${NC} Creating Python virtual environment..."
if [ ! -d "$VENV_PATH" ]; then
    sudo -u "$APP_USER" python3 -m venv "$VENV_PATH"
fi
echo -e "${GREEN}✓${NC} Virtual environment created"

# Step 4: Install Python dependencies
echo -e "${BLUE}[4/6]${NC} Installing Python dependencies..."
sudo -u "$APP_USER" "$VENV_PATH/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$VENV_PATH/bin/pip" install -q -r "$APP_DIR/requirements.txt"
echo -e "${GREEN}✓${NC} Python dependencies installed"

# Step 5: Create and configure systemd service
echo -e "${BLUE}[5/6]${NC} Configuring systemd service..."

# Create systemd service file
cat > "/etc/systemd/system/$APP_NAME.service" <<EOF
[Unit]
Description=BananaWiki
After=network.target

[Service]
Type=notify
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV_PATH/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
ExecStart=$VENV_PATH/bin/gunicorn wsgi:app -c gunicorn.conf.py
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Update config.py for production
if [ "$SETUP_NGINX" = true ]; then
    # Running behind nginx
    cat >> "$APP_DIR/config.py.prod" <<EOF

# Production overrides (added by install.sh)
PORT = $PORT
HOST = "127.0.0.1"  # Behind nginx
PROXY_MODE = True
EOF
else
    # Direct access
    cat >> "$APP_DIR/config.py.prod" <<EOF

# Production overrides (added by install.sh)
PORT = $PORT
HOST = "0.0.0.0"  # Direct access
PROXY_MODE = False
EOF
fi

# If prod config exists, append it to config.py
if [ -f "$APP_DIR/config.py.prod" ]; then
    cat "$APP_DIR/config.py.prod" >> "$APP_DIR/config.py"
    rm "$APP_DIR/config.py.prod"
fi

# Reload systemd and enable service
systemctl daemon-reload
systemctl enable "$APP_NAME" > /dev/null 2>&1
systemctl start "$APP_NAME"
echo -e "${GREEN}✓${NC} Systemd service configured and started"

# Step 6: Configure nginx (if requested)
if [ "$SETUP_NGINX" = true ]; then
    echo -e "${BLUE}[6/6]${NC} Configuring nginx reverse proxy..."

    NGINX_CONF="/etc/nginx/sites-available/$APP_NAME"

    if [ -n "$DOMAIN" ]; then
        # Domain-based configuration
        cat > "$NGINX_CONF" <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_redirect off;
        proxy_buffering off;
    }
}
EOF
    else
        # IP-only configuration
        cat > "$NGINX_CONF" <<EOF
server {
    listen 80 default_server;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_redirect off;
        proxy_buffering off;
    }
}
EOF
    fi

    # Enable site
    ln -sf "$NGINX_CONF" "/etc/nginx/sites-enabled/$APP_NAME"

    # Remove default nginx site if it exists
    if [ -f "/etc/nginx/sites-enabled/default" ]; then
        rm -f "/etc/nginx/sites-enabled/default"
    fi

    # Test and reload nginx
    nginx -t > /dev/null 2>&1
    systemctl reload nginx

    echo -e "${GREEN}✓${NC} Nginx configured"

    # Set up SSL with Let's Encrypt (if requested)
    if [ "$SETUP_SSL" = true ] && [ -n "$DOMAIN" ]; then
        echo "   Setting up SSL certificate..."
        if [ -n "$EMAIL" ]; then
            certbot --nginx -n --agree-tos --email "$EMAIL" -d "$DOMAIN" > /dev/null 2>&1
        else
            certbot --nginx -n --agree-tos --register-unsafely-without-email -d "$DOMAIN" > /dev/null 2>&1
        fi
        echo -e "${GREEN}✓${NC} SSL certificate obtained"
    fi
else
    echo -e "${BLUE}[6/6]${NC} Skipping nginx configuration"
fi

# Get server IP
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")

# Installation complete
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Installation completed successfully!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${CYAN}Access your BananaWiki at:${NC}"
if [ "$SETUP_SSL" = true ] && [ -n "$DOMAIN" ]; then
    echo -e "  ${BLUE}https://$DOMAIN${NC}"
elif [ -n "$DOMAIN" ]; then
    echo -e "  ${BLUE}http://$DOMAIN${NC}"
elif [ "$SETUP_NGINX" = true ]; then
    echo -e "  ${BLUE}http://$SERVER_IP${NC}"
else
    echo -e "  ${BLUE}http://$SERVER_IP:$PORT${NC}"
fi
echo ""
echo -e "${CYAN}Useful commands:${NC}"
echo -e "  View logs:        ${YELLOW}sudo journalctl -u $APP_NAME -f${NC}"
echo -e "  Restart service:  ${YELLOW}sudo systemctl restart $APP_NAME${NC}"
echo -e "  Stop service:     ${YELLOW}sudo systemctl stop $APP_NAME${NC}"
echo -e "  Check status:     ${YELLOW}sudo systemctl status $APP_NAME${NC}"
if [ "$SETUP_NGINX" = true ]; then
    echo -e "  Reload nginx:     ${YELLOW}sudo systemctl reload nginx${NC}"
fi
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Visit the URL above to complete first-time setup"
echo "  2. Create your admin account"
echo "  3. Configure settings in $APP_DIR/config.py"
echo "  4. Set up backups (see docs/configuration.md for Telegram sync)"
echo ""
