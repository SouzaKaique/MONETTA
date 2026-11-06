"""Cartões, faturas, compras e pagamentos."""
from datetime import date

import sqlalchemy as sa
from flask import Blueprint, g, jsonify, request
from marshmallow import Schema, ValidationError, fields, validate, validates_schema
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import CardPurchase, CreditCard, Installment, Invoice, InvoicePayment
from ..services import cards as service
from ..services.periods import month_bounds, parse_month
from .common import error, load_body, login_required
from .finance_common import (
    MoneyField, check_account, check_category, find_by_key, owned, save_once, today,
)

bp = Blueprint("cards", __name__, url_prefix="/api")

COLORS = ["forest", "graphite", "wine", "navy", "ochre", "plum"]
DAY = validate.Range(min=1, max=31)
LIMIT = validate.Range(min=0, max=999_999_999.99)
NOTES = {"allow_none": True, "validate": validate.Length(max=2000)}


class CardSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=80))
    institution = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=80))
    credit_limit = fields.Decimal(required=True, places=2, validate=LIMIT)
    closing_day = fields.Integer(required=True, validate=DAY)
    due_day = fields.Integer(required=True, validate=DAY)
    color = fields.String(load_default="forest", validate=validate.OneOf(COLORS))

    @validates_schema
    def check_days(self, data, **kwargs):
        if data["closing_day"] == data["due_day"]:
            raise ValidationError({"due_day": ["O vencimento precisa ser diferente do fechamento."]})


class CardUpdateSchema(Schema):
    name = fields.String(validate=validate.Length(min=1, max=80))
    institution = fields.String(allow_none=True, validate=validate.Length(max=80))
    credit_limit = fields.Decimal(places=2, validate=LIMIT)
    closing_day = fields.Integer(validate=DAY)
    due_day = fields.Integer(validate=DAY)
    color = fields.String(validate=validate.OneOf(COLORS))
    active = fields.Boolean()


class PurchaseSchema(Schema):
    description = fields.String(required=True, validate=validate.Length(min=1, max=160))
    total_amount = MoneyField(required=True)
    purchase_date = fields.Date(required=True)
    installment_count = fields.Integer(load_default=1, validate=validate.Range(min=1, max=48))
    # Compras antigas: parcelas quitadas antes de a compra entrar no sistema.
    already_paid = fields.Integer(load_default=0, validate=validate.Range(min=0, max=47))
    # Permite corrigir a fatura quando a regra do banco diferir do cálculo automático.
    first_month = fields.String(load_default=None, allow_none=True)
    category_id = fields.UUID(load_default=None, allow_none=True)
    notes = fields.String(load_default=None, **NOTES)

    @validates_schema
    def check_paid(self, data, **kwargs):
        if data["already_paid"] >= data["installment_count"]:
            raise ValidationError({"already_paid": ["Deve restar ao menos uma parcela."]})


class PurchaseUpdateSchema(Schema):
    description = fields.String(validate=validate.Length(min=1, max=160))
    category_id = fields.UUID(allow_none=True)
    notes = fields.String(**NOTES)


class PaymentSchema(Schema):
    amount = MoneyField(required=True)
    paid_on = fields.Date(required=True)
    account_id = fields.UUID(required=True)
    notes = fields.String(load_default=None, **NOTES)


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def card_payload(card: CreditCard) -> dict:
    return {
        "id": str(card.id), "name": card.name, "institution": card.institution,
        "credit_limit": card.credit_limit, "closing_day": card.closing_day,
        "due_day": card.due_day, "color": card.color, "active": card.active,
        **service.card_summary(card, today()),
    }


def invoice_payload(invoice: Invoice) -> dict:
    total, paid = service.invoice_total(invoice), service.invoice_paid(invoice)
    return {
        "id": str(invoice.id), "card_id": str(invoice.card_id),
        "card_name": invoice.card.name,
        "month": invoice.reference_month.strftime("%Y-%m"),
        "closing_date": invoice.closing_date.isoformat(),
        "due_date": invoice.due_date.isoformat(),
        "total": total, "paid": paid, "remaining": total - paid,
        "status": service.invoice_status(invoice, today()),
    }


def installment_payload(item: Installment) -> dict:
    purchase = item.purchase
    return {
        "id": str(item.id), "purchase_id": str(purchase.id), "description": purchase.description,
        "number": item.number, "count": purchase.installment_count, "amount": item.amount,
        "purchase_date": purchase.purchase_date.isoformat(),
        "category_name": purchase.category.name if purchase.category else None,
        "card_name": purchase.card.name,
        "due_date": _iso(item.invoice.due_date if item.invoice else None),
    }


def payment_payload(payment: InvoicePayment) -> dict:
    return {
        "id": str(payment.id), "amount": payment.amount,
        "paid_on": payment.paid_on.isoformat(), "account_name": payment.account.name,
    }


def purchase_payload(purchase: CardPurchase) -> dict:
    open_items = [i for i in purchase.installments if i.invoice_id]
    return {
        "id": str(purchase.id), "card_id": str(purchase.card_id),
        "description": purchase.description, "total_amount": purchase.total_amount,
        "purchase_date": purchase.purchase_date.isoformat(),
        "installment_count": purchase.installment_count,
        "category_id": str(purchase.category_id) if purchase.category_id else None,
        "category_name": purchase.category.name if purchase.category else None,
        "notes": purchase.notes,
        "first_due_date": _iso(open_items[0].invoice.due_date if open_items else None),
        "last_due_date": _iso(open_items[-1].invoice.due_date if open_items else None),
    }


def _idempotency_key() -> str | None:
    key = request.headers.get("Idempotency-Key")
    if key and len(key) > 64:
        raise ValidationError({"_": ["Idempotency-Key inválida."]})
    return key


# Cartões

@bp.get("/cards")
@login_required
def list_cards():
    cards = db.session.scalars(
        sa.select(CreditCard).where(CreditCard.user_id == g.user.id)
        .order_by(CreditCard.active.desc(), CreditCard.created_at)
    ).all()
    return jsonify([card_payload(c) for c in cards])


@bp.post("/cards")
@login_required
def create_card():
    data = load_body(CardSchema())
    data["name"] = data["name"].strip()
    card = CreditCard(user_id=g.user.id, **data)
    db.session.add(card)
    db.session.commit()
    return jsonify(card_payload(card)), 201


@bp.get("/cards/<uuid:card_id>")
@login_required
def get_card(card_id):
    card = owned(CreditCard, card_id)
    return jsonify({
        **card_payload(card),
        "invoices": [invoice_payload(i) for i in service.card_invoices(card)],
        "spending": service.spending_by_month(card, today()),
    })


@bp.patch("/cards/<uuid:card_id>")
@login_required
def update_card(card_id):
    card = owned(CreditCard, card_id)
    data = load_body(CardUpdateSchema())
    for field, value in data.items():
        setattr(card, field, value)
    if card.closing_day == card.due_day:
        raise ValidationError({"due_day": ["O vencimento precisa ser diferente do fechamento."]})
    if "closing_day" in data or "due_day" in data:
        # Só faturas ainda não fechadas acompanham os novos dias; as passadas são histórico.
        for invoice in service.card_invoices(card):
            if invoice.closing_date >= today():
                invoice.closing_date, invoice.due_date = service.invoice_dates(
                    card, invoice.reference_month
                )
    db.session.commit()
    return jsonify(card_payload(card))


@bp.delete("/cards/<uuid:card_id>")
@login_required
def delete_card(card_id):
    card = owned(CreditCard, card_id)
    used = db.session.scalar(sa.select(sa.exists().where(CardPurchase.card_id == card.id)))
    if used:
        return error("Este cartão tem compras. Desative-o para preservar o histórico.", 409)
    db.session.delete(card)
    db.session.commit()
    return "", 204


# Faturas

@bp.get("/invoices/<uuid:invoice_id>")
@login_required
def get_invoice(invoice_id):
    invoice = owned(Invoice, invoice_id)
    return jsonify({
        **invoice_payload(invoice),
        "installments": [installment_payload(i) for i in invoice.installments],
        "payments": [payment_payload(p) for p in invoice.payments],
    })


@bp.post("/invoices/<uuid:invoice_id>/payments")
@login_required
def pay_invoice(invoice_id):
    invoice = owned(Invoice, invoice_id)
    key = _idempotency_key()
    existing = find_by_key(InvoicePayment, key)
    if existing:
        return jsonify(invoice_payload(existing.invoice)), 200

    data = load_body(PaymentSchema())
    check_account(data["account_id"])
    if data["paid_on"] > today():
        raise ValidationError({"paid_on": ["O pagamento não pode estar no futuro."]})
    remaining = service.invoice_total(invoice) - service.invoice_paid(invoice)
    if data["amount"] > remaining:
        raise ValidationError({"amount": ["O valor é maior do que o restante da fatura."]})

    invoice.payments.append(InvoicePayment(user_id=g.user.id, idempotency_key=key, **data))
    duplicate = save_once(InvoicePayment, key)
    if duplicate:
        return jsonify(invoice_payload(duplicate.invoice)), 200
    return jsonify(invoice_payload(invoice)), 201


@bp.delete("/invoice-payments/<uuid:payment_id>")
@login_required
def delete_payment(payment_id):
    db.session.delete(owned(InvoicePayment, payment_id))
    db.session.commit()
    return "", 204


# Compras

def _first_month(card: CreditCard, data: dict) -> date:
    raw = data["first_month"]
    if not raw:
        return service.invoice_month_for(card, data["purchase_date"])
    parsed = parse_month(raw)
    if parsed is None:
        raise ValidationError({"first_month": ["Use AAAA-MM."]})
    return date(parsed[0], parsed[1], 1)


@bp.get("/cards/<uuid:card_id>/purchases")
@login_required
def list_purchases(card_id):
    card = owned(CreditCard, card_id)
    purchases = db.session.scalars(
        sa.select(CardPurchase).where(CardPurchase.card_id == card.id)
        .order_by(CardPurchase.purchase_date.desc(), CardPurchase.created_at.desc()).limit(100)
    ).all()
    return jsonify([purchase_payload(p) for p in purchases])


@bp.post("/cards/<uuid:card_id>/purchases")
@login_required
def create_purchase(card_id):
    card = owned(CreditCard, card_id)
    key = _idempotency_key()
    existing = find_by_key(CardPurchase, key)
    if existing:
        return jsonify(purchase_payload(existing)), 200

    if not card.active:
        return error("Este cartão está desativado.", 409)
    data = load_body(PurchaseSchema())
    check_category(data["category_id"], "expense")
    if data["purchase_date"] > today():
        raise ValidationError({"purchase_date": ["A compra não pode estar no futuro."]})

    first = _first_month(card, data)
    already_paid = data.pop("already_paid")
    data.pop("first_month")
    data["description"] = data["description"].strip()
    purchase = CardPurchase(user_id=g.user.id, card=card, idempotency_key=key, **data)
    db.session.add(purchase)
    try:
        db.session.flush()  # aqui a constraint da chave barra um envio simultâneo
    except IntegrityError:
        db.session.rollback()
        return jsonify(purchase_payload(find_by_key(CardPurchase, key))), 200
    service.create_installments(purchase, first, already_paid)
    db.session.commit()
    return jsonify(purchase_payload(purchase)), 201


@bp.patch("/purchases/<uuid:purchase_id>")
@login_required
def update_purchase(purchase_id):
    """Valor e parcelas não mudam: para corrigi-los, exclua a compra e registre de novo."""
    purchase = owned(CardPurchase, purchase_id)
    data = load_body(PurchaseUpdateSchema())
    if "category_id" in data:
        check_category(data["category_id"], "expense")
    for field, value in data.items():
        setattr(purchase, field, value)
    db.session.commit()
    return jsonify(purchase_payload(purchase))


@bp.delete("/purchases/<uuid:purchase_id>")
@login_required
def delete_purchase(purchase_id):
    purchase = owned(CardPurchase, purchase_id)
    paid = db.session.scalar(sa.select(sa.exists().where(
        InvoicePayment.invoice_id.in_(
            sa.select(Installment.invoice_id).where(Installment.purchase_id == purchase.id)
        )
    )))
    if paid:
        return error("Há pagamento em uma fatura desta compra. Remova o pagamento antes.", 409)
    card_id = purchase.card_id
    db.session.delete(purchase)
    db.session.flush()
    service.remove_empty_invoices(card_id)
    db.session.commit()
    return "", 204


@bp.get("/installments")
@login_required
def list_installments():
    """Parcelas que pesam no mês, de todos os cartões."""
    parsed = parse_month(request.args.get("month"))
    if parsed is None:
        raise ValidationError({"month": ["Use AAAA-MM."]})
    start, end = month_bounds(*parsed)
    items = db.session.scalars(
        sa.select(Installment).join(Invoice)
        .options(joinedload(Installment.purchase).joinedload(CardPurchase.category),
                 joinedload(Installment.purchase).joinedload(CardPurchase.card))
        .where(Installment.user_id == g.user.id, Invoice.due_date.between(start, end))
        .order_by(Invoice.due_date, Installment.number)
    ).all()
    return jsonify({
        "items": [installment_payload(i) for i in items],
        "total": service.installments_total(g.user.id, start, end),
    })
