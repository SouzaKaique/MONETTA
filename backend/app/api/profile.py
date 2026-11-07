"""Perfil simples: nome da conta, tema e senha."""
from flask import Blueprint, g, jsonify
from marshmallow import Schema, fields, validate

from ..extensions import db
from ..services.alerts import KINDS, prefs_for
from ..services.debts import STRATEGIES
from ..services.security import hash_password, revoke_all_sessions, verify_password
from .common import error, load_body, login_required, user_payload

bp = Blueprint("profile", __name__, url_prefix="/api/profile")


class AlertPrefsSchema(Schema):
    budget_pct = fields.Integer(validate=validate.Range(min=10, max=100))
    card_pct = fields.Integer(validate=validate.Range(min=10, max=100))
    commitment_pct = fields.Integer(validate=validate.Range(min=10, max=100))
    due_days = fields.Integer(validate=validate.Range(min=0, max=15))
    muted = fields.List(fields.String(validate=validate.OneOf(KINDS)))


class ProfileSchema(Schema):
    account_name = fields.String(validate=validate.Length(min=2, max=80))
    theme = fields.String(validate=validate.OneOf(["system", "light", "dark"]))
    safety_minimum = fields.Decimal(places=2, validate=validate.Range(min=0, max=999_999_999.99))
    debt_strategy = fields.String(validate=validate.OneOf(STRATEGIES))
    planned_reserve = fields.Decimal(places=2, validate=validate.Range(min=0, max=999_999_999.99))
    alert_prefs = fields.Nested(AlertPrefsSchema)


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
    if "safety_minimum" in data:
        g.user.settings.safety_minimum = data["safety_minimum"]
    if "debt_strategy" in data:
        g.user.settings.debt_strategy = data["debt_strategy"]
    if "planned_reserve" in data:
        g.user.settings.planned_reserve = data["planned_reserve"]
    if "alert_prefs" in data:
        g.user.settings.alert_prefs = {**prefs_for(g.user.settings), **data["alert_prefs"]}
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
