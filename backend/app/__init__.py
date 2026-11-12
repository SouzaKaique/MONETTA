from decimal import Decimal
from pathlib import Path

import re

from flask import Flask, abort, jsonify, request, send_from_directory
from flask.json.provider import DefaultJSONProvider
from marshmallow import ValidationError
from werkzeug.exceptions import HTTPException

from .api import register_blueprints
from .cli import register_commands
from .config import Config
from .extensions import db, migrate
from .services.messages import translate_all
from .services.ratelimit import RateLimiter

CLIENT_HEADER = "X-Monetta-Client"
HTTP_MESSAGES = {
    400: "Requisição inválida.",
    401: "Entre na sua conta para continuar.",
    403: "Acesso não autorizado.",
    404: "Não encontrado.",
    405: "Operação não permitida.",
    413: "O arquivo é grande demais.",
}
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "frontend" / "browser"
# O nome muda a cada versão, então o arquivo nunca envelhece no cache.
HASHED_ASSET = re.compile(r"-[A-Z0-9]{8}\.\w+$")
ONE_YEAR = 31536000
# Imagens externas da wishlist exigem https:. Sem scripts inline nem de terceiros.
CONTENT_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' https: data:; font-src 'self'; connect-src 'self'; manifest-src 'self'; "
    "worker-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)


class MoneyJSONProvider(DefaultJSONProvider):
    """Decimal vai como string ("1234.50"): JSON number perderia precisão."""

    @staticmethod
    def default(o):
        if isinstance(o, Decimal):
            return f"{o:.2f}"
        return DefaultJSONProvider.default(o)


def create_app(config: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)
    if not app.config["SQLALCHEMY_DATABASE_URI"] or not app.config["SECRET_KEY"]:
        raise RuntimeError("Defina DATABASE_URL e SECRET_KEY no .env (scripts/db.ps1 init).")
    app.json = MoneyJSONProvider(app)
    app.extensions["rate_limiter"] = RateLimiter()

    db.init_app(app)
    migrate.init_app(app, db)
    from . import models  # noqa: F401  (registra as tabelas para o Alembic)

    register_blueprints(app)
    register_commands(app)

    @app.before_request
    def require_client_header():
        """
        Proteção contra CSRF: outro site não consegue enviar este header sem
        autorização de CORS, que a API não concede. O retorno da Apple é a exceção,
        pois é protegido por state, nonce e cookie de navegador.
        """
        if (request.method in ("POST", "PUT", "PATCH", "DELETE")
                and request.path.startswith("/api/")
                and not request.path.endswith("/callback")
                and not request.path.startswith("/api/integrations/")
                and request.headers.get(CLIENT_HEADER) != "web"):
            return jsonify({"error": "Requisição não autorizada."}), 403

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if app.config["PUBLIC_URL"].startswith("https://"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        else:
            response.headers.setdefault("Content-Security-Policy", CONTENT_POLICY)
        return response

    @app.get("/api/health")
    def health():
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"status": "ok"})

    if app.config["SERVE_FRONTEND"]:
        @app.get("/")
        @app.get("/<path:path>")
        def frontend(path: str = "index.html"):
            if path.startswith("api/"):
                abort(404)
            target = FRONTEND_DIR / path
            if not target.resolve().is_relative_to(FRONTEND_DIR) or not target.is_file():
                path = "index.html"  # rota do Angular
            response = send_from_directory(FRONTEND_DIR, path)
            if HASHED_ASSET.search(path):
                response.headers["Cache-Control"] = f"public, max-age={ONE_YEAR}, immutable"
            else:
                response.headers["Cache-Control"] = "no-cache"
            return response

    @app.errorhandler(ValidationError)
    def validation_error(exc: ValidationError):
        return jsonify({"error": "Dados inválidos.", "fields": translate_all(exc.messages)}), 422

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        return jsonify({"error": HTTP_MESSAGES.get(exc.code, "Não foi possível concluir.")}), exc.code

    return app
