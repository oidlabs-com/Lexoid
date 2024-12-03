.PHONY: dev help

help:
	@echo "make dev     - Install development dependencies"
	@echo "make setup   - Dev setup"

setup:
	python3 -m venv .venv
	.venv/bin/python3 -m pip install --upgrade pip
	.venv/bin/python3 -m pip install poetry
	.venv/bin/poetry update

dev: setup
	.venv/bin/poetry install --with dev

clean:
	rm -rf .venv

build:
	.venv/bin/poetry update && .venv/bin/poetry build

build-debian:
	.venv/bin/poetry update --without qt5 && .venv/bin/poetry build
