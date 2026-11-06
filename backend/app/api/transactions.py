"""Lançamentos de receitas e despesas."""
from datetime import date
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from flask import Blueprint, g, jsonify, request
from marshmallow import Schema, ValidationError, fields, validate
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import Transaction
from ..services.periods import month_bounds, parse_month
from ..services.recurrences import generate, generation_horizon, skip_occurrence
from .common import error, load_body, login_required
from .finance_common import (
    MoneyField, PaymentField, check_account, check_category, find_by_key, owned, save_once, today,
    transaction_payload,
)

bp = Blueprint("transactions", __name__, url_prefix="/api/transactions")

PER_PAGE = 50
NOTES = {"allow_none": True, "validate": validate.Length(max=2000)}


class TransactionSchema(Schema):
    kind = fields.String(required=True, validate=validate.OneOf(["income", "expense"]))
    description = fields.String(required=True, validate=validate.Length(min=1, max=160))
    amount = MoneyField(required=True)
    competence_date = fields.Date(required=True)
    status = fields.String(load_default="confirmed", validate=validate.OneOf(["pending", "confirmed"]))
    paid_on = fields.Date(load_default=None, allow_none=True)
    account_id = fields.UUID(load_default=None, allow_none=True)
    category_id = fields.UUID(load_default=None, allow_none=True)
    payment_method = PaymentField(load_default=None)
    notes = fields.String(load_default=None, **NOTES)


class TransactionUpdateSchema(Schema):
    description = fields.String(validate=validate.Length(min=1, max=160))
    amount = MoneyField()
    competence_date = fields.Date()
    paid_on = fields.Date(allow_none=True)
    account_id = fields.UUID(allow_none=True)
    category_id = fields.UUID(allow_none=True)
    payment_method = PaymentField()
    notes = fields.String(**NOTES)


class ConfirmSchema(Schema):
    paid_on = fields.Date(required=True)
    account_id = fields.UUID(required=True)
    amount = MoneyField()  # o valor real pode diferir do previsto


def _check_paid(paid_on: date | None, account_id) -> None:
    if paid_on is None:
        raise ValidationError({"paid_on": ["Informe a data do pagamento."]})
    if paid_on > today():
        raise ValidationError({"paid_on": ["Para uma data futura, registre como pendente."]})
    if account_id is None:
        raise ValidationError({"account_id": ["Escolha a conta."]})


def _filtered_query():
    args = request.args
    query = sa.select(Transaction).where(Transaction.user_id == g.user.id)

    if args.get("month"):
        parsed = parse_month(args["month"])
        if parsed is None:
            raise ValidationError({"month": ["Use AAAA-MM."]})
        start, end = month_bounds(*parsed)
        query = query.where(Transaction.competence_date.between(start, end))

    for name, column in (("kind", Transaction.kind), ("status", Transaction.status)):
        if args.get(name):
            query = query.where(column == args[name])
    for name, column in (("category_id", Transaction.category_id),
                         ("account_id", Transaction.account_id)):
        if args.get(name):
            query = query.where(column == _uuid_arg(name))

    if args.get("fixed") in ("true", "false"):
        query = query.where(Transaction.is_fixed.is_(args["fixed"] == "true"))
    if args.get("q"):
        escaped = args["q"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Transaction.description.ilike(f"%{escaped}%", escape="\\"))
    for name, compare in (("min_amount", Transaction.amount.__ge__),
                          ("max_amount", Transaction.amount.__le__)):
        if args.get(name):
            try:
                query = query.where(compare(Decimal(args[name])))
            except InvalidOperation as exc:
                raise ValidationError({name: ["Valor inválido."]}) from exc
    return query


def _uuid_arg(name: str):
    try:
        return fields.UUID().deserialize(request.args[name])
    except ValidationError as exc:
        raise ValidationError({name: ["Identificador inválido."]}) from exc


@bp.get("")
@login_required
def list_transactions():
    requested = None
    if parsed := parse_month(request.args.get("month")):
        requested = month_bounds(*parsed)[1]
    generate(g.user.id, generation_horizon(today(), requested))

    query = _filtered_query()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    filtered = query.subquery()
    count, total = db.session.execute(
        sa.select(sa.func.count(), sa.func.coalesce(sa.func.sum(filtered.c.amount), 0))
        .select_from(filtered)
    ).one()
    rows = db.session.scalars(
        query.options(joinedload(Transaction.category), joinedload(Transaction.account))
        .order_by(Transaction.competence_date.desc(), Transaction.created_at.desc())
        .limit(PER_PAGE).offset((page - 1) * PER_PAGE)
    ).all()
    return jsonify({
        "items": [transaction_payload(t) for t in rows],
        "count": count, "total": Decimal(total), "page": page, "per_page": PER_PAGE,
    })


@bp.post("")
@login_required
def create_transaction():
    key = request.headers.get("Idempotency-Key")
    if key:
        if len(key) > 64:
            return error("Idempotency-Key inválida.", 400)
        existing = find_by_key(Transaction, key)
        if existing:
            return jsonify(transaction_payload(existing)), 200

    data = load_body(TransactionSchema())
    check_account(data["account_id"])
    check_category(data["category_id"], data["kind"])
    if data["status"] == "confirmed":
        data["paid_on"] = data["paid_on"] or data["competence_date"]
        _check_paid(data["paid_on"], data["account_id"])
    else:
        data["paid_on"] = None

    data["description"] = data["description"].strip()
    tx = Transaction(user_id=g.user.id, idempotency_key=key, **data)
    db.session.add(tx)
    duplicate = save_once(Transaction, key)
    if duplicate:
        return jsonify(transaction_payload(duplicate)), 200
    return jsonify(transaction_payload(tx)), 201


@bp.patch("/<uuid:tx_id>")
@login_required
def update_transaction(tx_id):
    tx = owned(Transaction, tx_id)
    data = load_body(TransactionUpdateSchema())
    if "account_id" in data:
        check_account(data["account_id"])
    if "category_id" in data:
        check_category(data["category_id"], tx.kind)
    if tx.status == "confirmed":
        _check_paid(data.get("paid_on", tx.paid_on), data.get("account_id", tx.account_id))
    else:
        data.pop("paid_on", None)

    for field in ("amount", "description"):
        if field in data and data[field] != getattr(tx, field):
            tx.amount_overridden = True
    for field, value in data.items():
        setattr(tx, field, value)
    db.session.commit()
    return jsonify(transaction_payload(tx))


@bp.post("/<uuid:tx_id>/confirm")
@login_required
def confirm_transaction(tx_id):
    tx = owned(Transaction, tx_id)
    if tx.status == "confirmed":
        return error("Este lançamento já está confirmado.", 409)
    data = load_body(ConfirmSchema())
    check_account(data["account_id"])
    _check_paid(data["paid_on"], data["account_id"])

    tx.status, tx.paid_on, tx.account_id = "confirmed", data["paid_on"], data["account_id"]
    if "amount" in data and data["amount"] != tx.amount:
        tx.amount = data["amount"]
        tx.amount_overridden = True
    db.session.commit()
    return jsonify(transaction_payload(tx))


@bp.post("/<uuid:tx_id>/unconfirm")
@login_required
def unconfirm_transaction(tx_id):
    tx = owned(Transaction, tx_id)
    tx.status, tx.paid_on = "pending", None
    db.session.commit()
    return jsonify(transaction_payload(tx))


@bp.delete("/<uuid:tx_id>")
@login_required
def delete_transaction(tx_id):
    tx = owned(Transaction, tx_id)
    skip_occurrence(tx)
    db.session.delete(tx)
    db.session.commit()
    return "", 204
