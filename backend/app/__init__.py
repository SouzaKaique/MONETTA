from decimal import Decimal

from flask import Flask, jsonify, request
from flask.json.provider import DefaultJSONProvider
from marshmallow import ValidationError
from werkzeug.exceptions import HTTPException

from .api import register_blueprints
from .config import Config
from .extensions import db, migrate

CLIENT_HEADER = "X-Monetta-Client"


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

    db.init_app(app)
    migrate.init_app(app, db)
    from . import models  # noqa: F401  (registra as tabelas para o Alembic)

    register_blueprints(app)

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
                and request.headers.get(CLIENT_HEADER) != "web"):
            return jsonify({"error": "Requisição não autorizada."}), 403

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/api/health")
    def health():
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"status": "ok"})

    @app.errorhandler(ValidationError)
    def validation_error(exc: ValidationError):
        return jsonify({"error": "Dados inválidos.", "fields": exc.messages}), 422

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        return jsonify({"error": exc.description}), exc.code

    return app
