"""Cadastro, login e sessão com e-mail e senha."""
import secrets
from datetime import timedelta

from flask import Blueprint, current_app, g, jsonify, make_response, request
from marshmallow import Schema, fields, validate

from ..extensions import db
from ..models import PasswordReset, User
from ..models.common import utcnow
from ..services import mail, oauth, ratelimit
from ..services.accounts import create_user, registration_open
from ..services.security import (
    end_session_cookie, hash_password, revoke_all_sessions,
    session_from_request, sha256, start_session, verify_password,
)
from .common import error, load_body, login_required, user_payload

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

MAX_FAILED_LOGINS = 5
LOGIN_PER_MINUTE = 20
REGISTER_PER_MINUTE = 10
LOCK_MINUTES = 15
FORGOT_PER_MINUTE = 5
RESET_PER_MINUTE = 10
RESET_MINUTES = 30
PasswordField = fields.String(required=True, validate=validate.Length(min=10, max=128))


class RegisterSchema(Schema):
    account_name = fields.String(required=True, validate=validate.Length(min=2, max=80))
    email = fields.Email(required=True, validate=validate.Length(max=254))
    password = PasswordField


class LoginSchema(Schema):
    email = fields.Email(required=True)
    password = fields.String(required=True, validate=validate.Length(max=128))


class ForgotSchema(Schema):
    email = fields.Email(required=True, validate=validate.Length(max=254))


class ResetSchema(Schema):
    token = fields.String(required=True, validate=validate.Length(min=20, max=200))
    password = PasswordField


@bp.get("/providers")
def providers():
    enabled = {name: oauth.is_enabled(name) for name in oauth.PROVIDERS}
    return jsonify(enabled | {"registration": registration_open()})


@bp.post("/register")
def register():
    if not ratelimit.allow(f"register:{request.remote_addr}", REGISTER_PER_MINUTE):
        return error("Muitas tentativas. Aguarde um minuto.", 429)
    if not registration_open():
        return error("O cadastro de novas contas está fechado.", 403)
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


@bp.post("/password/forgot")
def forgot_password():
    if not ratelimit.allow(f"forgot:{request.remote_addr}", FORGOT_PER_MINUTE):
        return error("Muitas tentativas. Aguarde um minuto.", 429)
    data = load_body(ForgotSchema())
    email = data["email"].strip().lower()
    # Mesma resposta exista ou não a conta: não revela quem está cadastrado.
    answer = jsonify({"message": "Se houver uma conta com este e-mail, enviamos um link "
                                 "para criar uma nova senha. Ele vale por 30 minutos."})
    if not ratelimit.allow(f"forgot-email:{email}", 3, window=900):
        return answer
    user = db.session.scalar(db.select(User).filter_by(email=email))
    if user is None:
        return answer

    db.session.execute(db.delete(PasswordReset).where(
        (PasswordReset.user_id == user.id) | (PasswordReset.expires_at < utcnow())
    ))
    token = secrets.token_urlsafe(32)
    db.session.add(PasswordReset(token_hash=sha256(token), user_id=user.id,
                                 expires_at=utcnow() + timedelta(minutes=RESET_MINUTES)))
    db.session.commit()
    link = f"{current_app.config['PUBLIC_URL']}/redefinir-senha#{token}"
    mail.send(user.email, "MONETTA: criar uma nova senha", (
        f"Olá, {user.account_name}.\n\n"
        f"Para criar uma nova senha no MONETTA, abra o link abaixo em até {RESET_MINUTES} minutos:\n\n"
        f"{link}\n\n"
        "Se você não pediu, ignore este e-mail: sua senha continua a mesma."
    ))
    return answer


@bp.post("/password/reset")
def reset_password():
    if not ratelimit.allow(f"reset:{request.remote_addr}", RESET_PER_MINUTE):
        return error("Muitas tentativas. Aguarde um minuto.", 429)
    data = load_body(ResetSchema())
    pending = db.session.get(PasswordReset, sha256(data["token"]), with_for_update=True)
    if pending is None or pending.expires_at <= utcnow():
        return error("Este link expirou ou já foi usado. Peça um novo.", 400)

    user = db.session.get(User, pending.user_id)
    db.session.execute(db.delete(PasswordReset).where(PasswordReset.user_id == user.id))
    user.password_hash = hash_password(data["password"])
    # Quem abriu o link recebido no e-mail provou que o e-mail é seu.
    user.email_verified = True
    user.failed_logins = 0
    user.locked_until = None
    revoke_all_sessions(user)
    db.session.commit()
    return jsonify({"message": "Senha criada. Entre com a nova senha."})
