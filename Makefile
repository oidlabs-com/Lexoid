.PHONY: install dev help

help:
	@echo "make install - Install poetry and project dependencies"
	@echo "make dev     - Install development dependencies"
	@echo "make setup   - Dev setup"

setup: install
	python3 -m venv .venv
	.venv/bin/python3 -m pip install --upgrade pip

install:
	@if ! command -v poetry &> /dev/null; then \
		curl -sSL https://install.python-poetry.org | python3 -; \
	fi
	poetry install --only main

dev: install
	poetry install --with dev