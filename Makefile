.PHONY: install dev help

help:
	@echo "make install - Install poetry and project dependencies"
	@echo "make dev    - Install development dependencies"

install:
	@if ! command -v poetry &> /dev/null; then \
		curl -sSL https://install.python-poetry.org | python3 -; \
	fi
	poetry install --no-dev

dev: install
	poetry install --with dev