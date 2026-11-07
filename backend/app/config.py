"""Configuração carregada do ambiente (.env na raiz do projeto)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "")
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "America/Sao_Paulo")
    PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:4200").rstrip("/")
    SESSION_DAYS = 30
    # Acima das imagens de 2 MB, para caber um backup completo.
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024
    SERVE_FRONTEND = os.environ.get("SERVE_FRONTEND") == "1"

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    APPLE_CLIENT_ID = os.environ.get("APPLE_CLIENT_ID", "")
    APPLE_TEAM_ID = os.environ.get("APPLE_TEAM_ID", "")
    APPLE_KEY_ID = os.environ.get("APPLE_KEY_ID", "")
    APPLE_PRIVATE_KEY_PATH = os.environ.get("APPLE_PRIVATE_KEY_PATH", "")


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "")
    SECRET_KEY = "test"
    GOOGLE_CLIENT_ID = "google-test-client"
    GOOGLE_CLIENT_SECRET = "google-test-secret"
    APPLE_CLIENT_ID = "com.monetta.test"
    APPLE_TEAM_ID = ""
    APPLE_KEY_ID = ""
    APPLE_PRIVATE_KEY_PATH = ""
