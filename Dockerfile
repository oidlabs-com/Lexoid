# Base image
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies required for:
# - building Python packages
# - Playwright
RUN apt-get update && apt-get install -y \
    curl \
    git \
    make \
    build-essential \
    qtbase5-dev \
    qtchooser \
    qt5-qmake \
    qtbase5-dev-tools \
    qttools5-dev \
    qttools5-dev-tools \
    libqt5svg5-dev \
    libgl1-mesa-dev \
    python3-dev \
    libnss3 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libgbm-dev \
    libasound2 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libxss1 \
    libxtst6 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project
COPY . /app

# Create virtual environment
RUN python3 -m venv .venv

# Upgrade pip
RUN .venv/bin/pip install --upgrade pip setuptools wheel

# Install poetry inside venv
RUN .venv/bin/pip install poetry

# Run make build
RUN make build

# Install built wheel into same venv
RUN .venv/bin/pip install dist/*.whl

# Install Playwright Chromium
RUN .venv/bin/playwright install --with-deps --only-shell chromium

# Add venv to PATH so we don't need activation
ENV PATH="/app/.venv/bin:$PATH"