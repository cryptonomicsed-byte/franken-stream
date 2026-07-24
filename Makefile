.PHONY: install dev test lint clean update help

PYTHON := python3
PIP    := $(PYTHON) -m pip

help:
	@echo "franken-stream development commands"
	@echo ""
	@echo "  make install   Install for regular use (pip install -e .)"
	@echo "  make dev       Install with dev dependencies"
	@echo "  make test      Run all tests"
	@echo "  make lint      Run linters"
	@echo "  make clean     Remove build artifacts"
	@echo "  make update    Refresh streaming providers"
	@echo "  make rust      Build Rust server (requires cargo)"
	@echo "  make native    Build native Rust scraper (requires maturin)"

install:
	$(PIP) install -e .

dev:
	$(PIP) install -e ".[dev]"

test:
	$(PYTHON) -m pytest tests/ -v

lint:
	$(PYTHON) -m black --check franken_stream/ tests/
	$(PYTHON) -m isort --check franken_stream/ tests/
	$(PYTHON) -m flake8 franken_stream/ tests/

clean:
	rm -rf build/ dist/ *.egg-info franken_stream/_version.py
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

update:
	$(PYTHON) -m franken_stream.main update

rust:
	cargo build --release -p franken-server

native:
	cd crates/py-scraper && maturin develop
