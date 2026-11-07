"""Cadastro, login e sessão com e-mail e senha."""
from datetime import timedelta

from flask import Blueprint, g, jsonify, make_response, request
from marshmallow import Schema, fields, validate

from ..extensions import db
from ..models import User
from ..models.common import utcnow
from ..services import oauth, ratelimit
from ..services.accounts import create_user
from ..services.security import (
    end_session_cookie, hash_password, revoke_all_sessions,
    session_from_request, start_session, verify_password,
)
from .common import error, load_body, login_required, user_payload

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

MAX_FAILED_LOGINS = 5
LOGIN_PER_MINUTE = 20
REGISTER_PER_MINUTE = 10
LOCK_MINUTES = 15
PasswordField = fields.String(required=True, validate=validate.Length(min=10, max=128))


class RegisterSchema(Schema):
    account_name = fields.String(required=True, validate=validate.Length(min=2, max=80))
    email = fields.Email(required=True, validate=validate.Length(max=254))
    password = PasswordField


class LoginSchema(Schema):
    email = fields.Email(required=True)
    password = fields.String(required=True, validate=validate.Length(max=128))


@bp.get("/providers")
def providers():
    return jsonify({name: oauth.is_enabled(name) for name in oauth.PROVIDERS})


@bp.post("/register")
def register():
    if not ratelimit.allow(f"register:{request.remote_addr}", REGISTER_PER_MINUTE):
        return error("Muitas tentativas. Aguarde um minuto.", 429)
    data = load_body(RegisterSchema())
    email = data["email"].strip().lower()
    if db.session.scalar(db.select(User.id).filter_by(email=email)):
        return error("Já existe uma conta com este e-mail.", 409)
    user = create_user(
        email=email, account_name=data["account_name"],
        password_hash=hash_password(data["password"]),
    )
    response = make_response(jsonify(user_payload(user)), 201)
    start_session(user, request, response)
    db.session.commit()
    return response


@bp.post("/login")
def login():
    if not ratelimit.allow(f"login:{request.remote_addr}", LOGIN_PER_MINUTE):
        return error("Muitas tentativas. Aguarde um minuto.", 429)
    data = load_body(LoginSchema())
    user = db.session.scalar(db.select(User).filter_by(email=data["email"].strip().lower()))
    invalid = error("E-mail ou senha incorretos.", 401)

    if user is not None and user.locked_until and user.locked_until > utcnow():
        return error("Muitas tentativas. Tente de novo em alguns minutos.", 429)

    if not verify_password(user.password_hash if user else None, data["password"]):
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
                user.failed_logins = 0
            db.session.commit()
        return invalid

    user.failed_logins = 0
    user.locked_until = None
    response = make_response(jsonify(user_payload(user)))
    start_session(user, request, response)
    db.session.commit()
    return response


@bp.post("/logout")
def logout():
    session = session_from_request(request)
    if session is not None:
        session.revoked_at = utcnow()
        db.session.commit()
    response = make_response("", 204)
    end_session_cookie(response)
    return response


@bp.post("/logout-all")
@login_required
def logout_all():
    revoke_all_sessions(g.user)
    db.session.commit()
    response = make_response("", 204)
    end_session_cookie(response)
    return response


@bp.get("/me")
@login_required
def me():
    return jsonify(user_payload(g.user))
