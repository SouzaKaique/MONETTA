"""Contas, transferências entre contas próprias e categorias."""
import sqlalchemy as sa
from flask import Blueprint, g, jsonify
from marshmallow import Schema, ValidationError, fields, validate

from ..extensions import db
from ..models import (
    Account, CardPurchase, Category, DebtPayment, InvoicePayment, Recurrence, Transaction,
    Transfer,
)
from .common import error, load_body, login_required
from .finance_common import (
    MoneyField, account_payload, category_payload, check_account, owned, today, transfer_payload,
)

bp = Blueprint("accounts", __name__, url_prefix="/api")

ACCOUNT_TYPES = ["checking", "savings", "cash"]
NEGATIVE_OK = {"places": 2, "validate": validate.Range(min=-999_999_999.99, max=999_999_999.99)}


class AccountSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=80))
    type = fields.String(load_default="checking", validate=validate.OneOf(ACCOUNT_TYPES))
    opening_balance = fields.Decimal(load_default=0, **NEGATIVE_OK)
    opening_date = fields.Date(required=True)


class AccountUpdateSchema(Schema):
    name = fields.String(validate=validate.Length(min=1, max=80))
    type = fields.String(validate=validate.OneOf(ACCOUNT_TYPES))
    opening_balance = fields.Decimal(**NEGATIVE_OK)
    opening_date = fields.Date()
    active = fields.Boolean()
    real_balance = fields.Decimal(allow_none=True, **NEGATIVE_OK)


class TransferSchema(Schema):
    from_account_id = fields.UUID(required=True)
    to_account_id = fields.UUID(required=True)
    amount = MoneyField(required=True)
    date = fields.Date(required=True)
    notes = fields.String(allow_none=True, validate=validate.Length(max=500))


class CategorySchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=60))
    kind = fields.String(required=True, validate=validate.OneOf(["income", "expense"]))
    icon = fields.String(load_default="tag", validate=validate.Regexp(r"^[a-z0-9-]{1,40}$"))
    is_essential = fields.Boolean(load_default=False)


class CategoryUpdateSchema(Schema):
    name = fields.String(validate=validate.Length(min=1, max=60))
    is_essential = fields.Boolean()
    icon = fields.String(validate=validate.Regexp(r"^[a-z0-9-]{1,40}$"))


@bp.get("/accounts")
@login_required
def list_accounts():
    accounts = db.session.scalars(
        sa.select(Account).where(Account.user_id == g.user.id)
        .order_by(Account.active.desc(), Account.created_at)
    ).all()
    return jsonify([account_payload(a) for a in accounts])


@bp.post("/accounts")
@login_required
def create_account():
    account = Account(user_id=g.user.id, **load_body(AccountSchema()))
    account.name = account.name.strip()
    db.session.add(account)
    db.session.commit()
    return jsonify(account_payload(account)), 201


@bp.patch("/accounts/<uuid:account_id>")
@login_required
def update_account(account_id):
    account = owned(Account, account_id)
    for field, value in load_body(AccountUpdateSchema()).items():
        setattr(account, field, value)
        if field == "real_balance":
            account.real_balance_on = None if value is None else today()
    db.session.commit()
    return jsonify(account_payload(account))


@bp.delete("/accounts/<uuid:account_id>")
@login_required
def delete_account(account_id):
    account = owned(Account, account_id)
    used = db.session.scalar(sa.select(
        sa.exists().where(Transaction.account_id == account.id)
        | sa.exists().where(sa.or_(Transfer.from_account_id == account.id,
                                   Transfer.to_account_id == account.id))
        | sa.exists().where(InvoicePayment.account_id == account.id)
        | sa.exists().where(DebtPayment.account_id == account.id)
    ))
    if used:
        return error("Esta conta tem movimentações. Desative-a para preservar o histórico.", 409)
    db.session.delete(account)
    db.session.commit()
    return "", 204


@bp.get("/transfers")
@login_required
def list_transfers():
    transfers = db.session.scalars(
        sa.select(Transfer).where(Transfer.user_id == g.user.id)
        .order_by(Transfer.date.desc(), Transfer.created_at.desc()).limit(50)
    ).all()
    return jsonify([transfer_payload(t) for t in transfers])


@bp.post("/transfers")
@login_required
def create_transfer():
    data = load_body(TransferSchema())
    if data["from_account_id"] == data["to_account_id"]:
        raise ValidationError({"to_account_id": ["Escolha contas diferentes."]})
    check_account(data["from_account_id"], "from_account_id")
    check_account(data["to_account_id"], "to_account_id")
    if data["date"] > today():
        raise ValidationError({"date": ["A transferência não pode estar no futuro."]})
    transfer = Transfer(user_id=g.user.id, **data)
    db.session.add(transfer)
    db.session.commit()
    return jsonify(transfer_payload(transfer)), 201


@bp.delete("/transfers/<uuid:transfer_id>")
@login_required
def delete_transfer(transfer_id):
    db.session.delete(owned(Transfer, transfer_id))
    db.session.commit()
    return "", 204


def _category_taken(kind: str, name: str, ignore=None) -> bool:
    query = sa.select(Category.id).where(
        Category.user_id == g.user.id, Category.kind == kind,
        sa.func.lower(Category.name) == name.lower(),
    )
    if ignore is not None:
        query = query.where(Category.id != ignore)
    return db.session.scalar(query) is not None


@bp.get("/categories")
@login_required
def list_categories():
    categories = db.session.scalars(
        sa.select(Category).where(Category.user_id == g.user.id)
        .order_by(Category.kind, Category.is_default.desc(), Category.name)
    ).all()
    return jsonify([category_payload(c) for c in categories])


@bp.post("/categories")
@login_required
def create_category():
    data = load_body(CategorySchema())
    data["name"] = data["name"].strip()
    if _category_taken(data["kind"], data["name"]):
        return error("Já existe uma categoria com este nome.", 409)
    category = Category(user_id=g.user.id, **data)
    db.session.add(category)
    db.session.commit()
    return jsonify(category_payload(category)), 201


@bp.patch("/categories/<uuid:category_id>")
@login_required
def update_category(category_id):
    category = owned(Category, category_id)
    data = load_body(CategoryUpdateSchema())
    if "name" in data:
        data["name"] = data["name"].strip()
        if _category_taken(category.kind, data["name"], ignore=category.id):
            return error("Já existe uma categoria com este nome.", 409)
    for field, value in data.items():
        setattr(category, field, value)
    db.session.commit()
    return jsonify(category_payload(category))


@bp.delete("/categories/<uuid:category_id>")
@login_required
def delete_category(category_id):
    category = owned(Category, category_id)
    used = db.session.scalar(sa.select(
        sa.exists().where(Transaction.category_id == category.id)
        | sa.exists().where(Recurrence.category_id == category.id)
        | sa.exists().where(CardPurchase.category_id == category.id)
    ))
    if used:
        return error("Esta categoria está em uso e não pode ser excluída.", 409)
    db.session.delete(category)
    db.session.commit()
    return "", 204
