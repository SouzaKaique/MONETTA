"""Configuração carregada do ambiente (.env na raiz do projeto)."""
import os
from pathlib import Path
from urllib.parse import urlsplit

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
    # Fechado, o sistema só aceita a primeira conta; depois, apenas login.
    REGISTRATION_OPEN = os.environ.get("REGISTRATION_OPEN", "1") == "1"
    # Testa a conexão antes de usar: o banco pode ter reiniciado.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    APPLE_CLIENT_ID = os.environ.get("APPLE_CLIENT_ID", "")
    APPLE_TEAM_ID = os.environ.get("APPLE_TEAM_ID", "")
    APPLE_KEY_ID = os.environ.get("APPLE_KEY_ID", "")
    APPLE_PRIVATE_KEY_PATH = os.environ.get("APPLE_PRIVATE_KEY_PATH", "")


MIN_SECRET_LENGTH = 32
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")


def production_problems(config: type, allow_local: bool = False) -> list[str]:
    """O que torna a configuração insegura para um endereço público."""
    problems = []
    url = config.PUBLIC_URL
    if not url.startswith("https://"):
        problems.append("PUBLIC_URL precisa começar com https://")
    host = urlsplit(url).hostname or ""
    if host in LOCAL_HOSTS and not allow_local:
        problems.append("PUBLIC_URL precisa ser um endereço público")
    secret = config.SECRET_KEY
    if len(secret) < MIN_SECRET_LENGTH or "troque" in secret.lower():
        problems.append(f"SECRET_KEY precisa ser aleatória, com {MIN_SECRET_LENGTH} caracteres ou mais")
    if not config.SQLALCHEMY_DATABASE_URI:
        problems.append("DATABASE_URL não foi definida")
    return problems


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "")
    REGISTRATION_OPEN = True
    SERVE_FRONTEND = False
    SECRET_KEY = "test"
    GOOGLE_CLIENT_ID = "google-test-client"
    GOOGLE_CLIENT_SECRET = "google-test-secret"
    APPLE_CLIENT_ID = "com.monetta.test"
    APPLE_TEAM_ID = ""
    APPLE_KEY_ID = ""
    APPLE_PRIVATE_KEY_PATH = ""
