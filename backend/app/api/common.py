"""Utilidades compartilhadas pelas rotas."""
from functools import wraps

from flask import abort, g, jsonify, request
from marshmallow import Schema, ValidationError

from ..models import User
from ..services.security import session_from_request


def current_user() -> User:
    return g.user


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        session = session_from_request(request)
        if session is None:
            abort(401)
        g.session = session
        g.user = session_user(session)
        return view(*args, **kwargs)
    return wrapper


def session_user(session) -> User:
    from ..extensions import db
    return db.session.get_one(User, session.user_id)


def load_body(schema: Schema) -> dict:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError({"_": ["Corpo JSON inválido."]})
    return schema.load(payload)


def user_payload(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "account_name": user.account_name,
        "avatar_url": user.avatar_url,
        "has_password": user.password_hash is not None,
        "providers": sorted(i.provider for i in user.identities),
        "theme": user.settings.theme,
        "created_at": user.created_at.isoformat(),
    }


def error(message: str, status: int, **extra):
    return jsonify({"error": message, **extra}), status
