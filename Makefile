.PHONY: dev help

help:
	@echo "make dev     - Install development dependencies"
	@echo "make setup   - Dev setup"

setup:
	python3 -m venv .venv
	.venv/bin/python3 -m pip install --upgrade pip
	.venv/bin/python3 -m pip install poetry
	.venv/bin/poetry update

install: setup
	.venv/bin/poetry install --without dev
	.venv/bin/playwright install --with-deps --only-shell chromium

dev: setup
	.venv/bin/poetry install --with dev
	.venv/bin/playwright install --with-deps --only-shell chromium

clean:
	rm -rf .venv
	rm -rf lexoid.egg-info
	rm -rf dist

build:
	.venv/bin/poetry update && .venv/bin/poetry build

build-debian:
	.venv/bin/poetry update --without qt5 && .venv/bin/poetry build
