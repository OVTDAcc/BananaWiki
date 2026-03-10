.PHONY: help dev start install update test clean

# Default target
help:
	@echo ""
	@echo "🍌 BananaWiki - Make Commands"
	@echo "=============================="
	@echo ""
	@echo "Development:"
	@echo "  make dev          Start development server (auto-setup)"
	@echo "  make test         Run test suite"
	@echo ""
	@echo "Production:"
	@echo "  make start        Start production server with Gunicorn"
	@echo "  make install      Run automated production installation (requires sudo)"
	@echo "  make update       Update BananaWiki to latest version (requires sudo)"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean        Remove venv, cache, and temporary files"
	@echo ""

# Development server
dev:
	@./dev.sh

# Production server
start:
	@./start.sh

# Automated production installation
install:
	@sudo ./install.sh

# Update to latest version
update:
	@sudo ./update.sh

# Run tests
test:
	@if [ ! -d "venv" ]; then \
		echo "Setting up virtual environment..."; \
		python3 -m venv venv; \
	fi
	@. venv/bin/activate && pip install -q -r requirements.txt pytest
	@. venv/bin/activate && python -m pytest tests/ -v

# Clean up
clean:
	@echo "Cleaning up..."
	@rm -rf venv __pycache__ .pytest_cache
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✓ Cleanup complete"
