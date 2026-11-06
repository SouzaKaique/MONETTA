"""Perfil simples: nome da conta, tema e senha."""
from flask import Blueprint, g, jsonify
from marshmallow import Schema, fields, validate

from ..extensions import db
from ..services.security import hash_password, revoke_all_sessions, verify_password
from .common import error, load_body, login_required, user_payload

bp = Blueprint("profile", __name__, url_prefix="/api/profile")


class ProfileSchema(Schema):
    account_name = fields.String(validate=validate.Length(min=2, max=80))
    theme = fields.String(validate=validate.OneOf(["system", "light", "dark"]))


class PasswordSchema(Schema):
    current_password = fields.String(load_default=None, validate=validate.Length(max=128))
    new_password = fields.String(required=True, validate=validate.Length(min=10, max=128))


@bp.patch("")
@login_required
def update_profile():
    data = load_body(ProfileSchema())
    if "account_name" in data:
        g.user.account_name = data["account_name"].strip()
    if "theme" in data:
        g.user.settings.theme = data["theme"]
    db.session.commit()
    return jsonify(user_payload(g.user))


@bp.post("/password")
@login_required
def change_password():
    data = load_body(PasswordSchema())
    has_password = g.user.password_hash is not None
    # Contas só com Google/Apple podem definir a primeira senha.
    if has_password and not verify_password(g.user.password_hash, data["current_password"] or ""):
        return error("Senha atual incorreta.", 403)
    g.user.password_hash = hash_password(data["new_password"])
    # Uma troca de senha derruba as outras sessões abertas.
    revoke_all_sessions(g.user, keep=g.session)
    db.session.commit()
    return jsonify(user_payload(g.user))
