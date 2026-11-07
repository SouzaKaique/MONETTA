"""Tokens revogáveis e lançamentos externos, como o app Atalhos do iOS."""
import hashlib
import secrets
import time
from decimal import Decimal, InvalidOperation
from functools import wraps

import sqlalchemy as sa
from flask import Blueprint, g, jsonify, request
from marshmallow import Schema, ValidationError, fields, validate

from ..extensions import db
from ..models import Account, ApiToken, CardPurchase, Category, CreditCard, Transaction, User
from ..models.common import utcnow
from ..services import cards, ratelimit, spending
from ..services.periods import format_brl, today_for
from ..services.recurrences import generate, generation_horizon
from ..services.security import sha256
from .common import error, load_body, login_required
from .finance_common import find_by_key, owned

bp = Blueprint("integrations", __name__, url_prefix="/api")

TOKEN_PREFIX = "mt_"
MAX_TOKENS = 10
REQUESTS_PER_MINUTE = 30
# Sem chave do cliente, dois envios iguais neste intervalo contam como repetição.
DUPLICATE_WINDOW_SECONDS = 120


class TokenSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=60))


class AmountField(fields.Field):
    """Atalhos pode enviar número, "12.50" ou "12,50"."""

    def _deserialize(self, value, attr, data, **kwargs):
        text = str(value).strip().replace("R$", "").strip()
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            amount = Decimal(text).quantize(Decimal("0.01"))
        except InvalidOperation as exc:
            raise ValidationError("Valor inválido.") from exc
        if not amount.is_finite() or amount <= 0 or amount > Decimal("999999999.99"):
            raise ValidationError("Valor inválido.")
        return amount


class ExpenseSchema(Schema):
    amount = AmountField(required=True)
    description = fields.String(required=True, validate=validate.Length(min=1, max=160))
    category = fields.String(load_default=None, allow_none=True)
    account = fields.String(load_default=None, allow_none=True)
    card = fields.String(load_default=None, allow_none=True)
    installments = fields.Integer(load_default=1, validate=validate.Range(min=1, max=48))
    payment_method = fields.String(
        load_default=None, allow_none=True,
        validate=validate.OneOf(["pix", "debit", "cash", "boleto", "transfer", "other"]),
    )
    request_id = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=64))


def token_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "bearer" or not value.startswith(TOKEN_PREFIX):
            return error("Token ausente.", 401)
        token = db.session.scalar(sa.select(ApiToken).filter_by(token_hash=sha256(value)))
        if token is None or token.revoked_at is not None:
            return error("Token inválido ou revogado.", 401)
        if not ratelimit.allow(f"token:{token.id}", REQUESTS_PER_MINUTE):
            return error("Muitas requisições. Aguarde um minuto.", 429)
        g.user = db.session.get_one(User, token.user_id)
        token.last_used_at = utcnow()
        db.session.commit()
        return view(*args, **kwargs)
    return wrapper


def _by_name(model, name: str | None, *filters):
    if not name:
        return None
    return db.session.scalar(
        sa.select(model).where(
            model.user_id == g.user.id, sa.func.lower(model.name) == name.strip().lower(), *filters
        )
    )


def _active_accounts() -> list[Account]:
    return list(db.session.scalars(
        sa.select(Account).where(Account.user_id == g.user.id, Account.active).order_by(Account.created_at)
    ))


def _dedupe_key(data: dict) -> str:
    if data["request_id"]:
        return f"ext:{data['request_id']}"[:64]
    window = int(time.time() // DUPLICATE_WINDOW_SECONDS)
    raw = f"{data['amount']}|{data['description'].strip().lower()}|{data['card']}|{window}"
    return "auto:" + hashlib.sha256(raw.encode()).hexdigest()[:40]


def _confirmation(amount: Decimal) -> dict:
    today = today_for(g.user.settings)
    generate(g.user.id, generation_horizon(today))
    until = spending.until_salary(g.user.id, g.user.settings, today)
    message = f"Registrado: {format_brl(amount)}."
    if until["has_salary"]:
        message += f" Disponível até o salário: {format_brl(until['available'])}."
    return {"ok": True, "message": message}


@bp.get("/tokens")
@login_required
def list_tokens():
    rows = db.session.scalars(
        sa.select(ApiToken).where(ApiToken.user_id == g.user.id, ApiToken.revoked_at.is_(None))
        .order_by(ApiToken.created_at.desc())
    ).all()
    return jsonify([{
        "id": str(t.id), "name": t.name, "prefix": t.prefix, "created_at": t.created_at.isoformat(),
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
    } for t in rows])


@bp.post("/tokens")
@login_required
def create_token():
    data = load_body(TokenSchema())
    active = db.session.scalar(
        sa.select(sa.func.count()).select_from(ApiToken)
        .where(ApiToken.user_id == g.user.id, ApiToken.revoked_at.is_(None))
    )
    if active >= MAX_TOKENS:
        return error("Revogue um token antes de criar outro.", 409)
    value = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = ApiToken(
        user_id=g.user.id, name=data["name"].strip(), token_hash=sha256(value), prefix=value[:10],
    )
    db.session.add(token)
    db.session.commit()
    return jsonify({"id": str(token.id), "name": token.name, "token": value}), 201


@bp.delete("/tokens/<uuid:token_id>")
@login_required
def revoke_token(token_id):
    owned(ApiToken, token_id).revoked_at = utcnow()
    db.session.commit()
    return "", 204


@bp.get("/integrations/options")
@token_required
def options():
    """Listas para os menus do atalho."""
    categories = db.session.scalars(
        sa.select(Category.name).where(Category.user_id == g.user.id, Category.kind == "expense")
        .order_by(Category.name)
    ).all()
    card_names = db.session.scalars(
        sa.select(CreditCard.name).where(CreditCard.user_id == g.user.id, CreditCard.active)
    ).all()
    return jsonify({
        "categories": list(categories), "accounts": [a.name for a in _active_accounts()],
        "cards": list(card_names),
    })


@bp.post("/integrations/expenses")
@token_required
def create_expense():
    data = load_body(ExpenseSchema())
    today = today_for(g.user.settings)
    key = _dedupe_key(data)
    category = _by_name(Category, data["category"], Category.kind == "expense")

    if data["card"]:
        if find_by_key(CardPurchase, key):
            return jsonify({"ok": True, "duplicate": True, "message": "Este lançamento já foi registrado."})
        card = _by_name(CreditCard, data["card"], CreditCard.active)
        if card is None:
            return error("Cartão não encontrado.", 422)
        purchase = CardPurchase(
            user_id=g.user.id, card=card, category_id=category.id if category else None,
            description=data["description"].strip(), total_amount=data["amount"],
            purchase_date=today, installment_count=data["installments"], idempotency_key=key,
        )
        db.session.add(purchase)
        db.session.flush()
        cards.create_installments(purchase, cards.invoice_month_for(card, today), 0)
    else:
        if find_by_key(Transaction, key):
            return jsonify({"ok": True, "duplicate": True, "message": "Este lançamento já foi registrado."})
        accounts = _active_accounts()
        account = _by_name(Account, data["account"], Account.active)
        if data["account"] and account is None:
            return error("Conta não encontrada.", 422)
        if account is None and len(accounts) == 1:
            account = accounts[0]
        # Sem conta definida fica pendente: registrar é melhor do que perder o gasto.
        db.session.add(Transaction(
            user_id=g.user.id, kind="expense", amount=data["amount"],
            description=data["description"].strip(), competence_date=today,
            category_id=category.id if category else None,
            account_id=account.id if account else None,
            status="confirmed" if account else "pending",
            paid_on=today if account else None,
            payment_method=data["payment_method"], idempotency_key=key,
        ))
    db.session.commit()
    return jsonify(_confirmation(data["amount"])), 201
