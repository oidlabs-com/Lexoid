"""Shared pytest setup: load .env once for every test module under tests/."""

from dotenv import load_dotenv

load_dotenv()
