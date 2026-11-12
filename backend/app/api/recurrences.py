"""Regras recorrentes: salário, contas fixas e assinaturas."""
from datetime import date, timedelta
from decimal import Decimal

import sqlalchemy as sa
from flask import Blueprint, g, jsonify, request
from marshmallow import Schema, ValidationError, fields, validate, validates_schema

from ..extensions import db
from ..models import CreditCard, Recurrence, RecurrenceAmount
from ..services import recurrences as service
from ..services.periods import parse_month
from .common import error, load_body, login_required
from .finance_common import (
    MoneyField, PaymentField, check_account, check_category, owned, recurrence_payload, today,
)

bp = Blueprint("recurrences", __name__, url_prefix="/api/recurrences")

NAME = validate.Length(min=1, max=160)
DAY = validate.Range(min=1, max=31)
NOTES = {"allow_none": True, "validate": validate.Length(max=2000)}


def OTHERS(**kwargs):
    """Parte de outras pessoas em cada cobrança no cartão."""
    return fields.Decimal(places=2, validate=validate.Range(min=0, max=999_999_999.99), **kwargs)


class RecurrenceSchema(Schema):
    kind = fields.String(required=True, validate=validate.OneOf(["income", "expense"]))
    name = fields.String(required=True, validate=NAME)
    amount = MoneyField(required=True)
    frequency = fields.String(
        load_default="monthly", validate=validate.OneOf(["weekly", "biweekly", "monthly", "yearly"])
    )
    day_of_month = fields.Integer(load_default=None, allow_none=True, validate=DAY)
    start_date = fields.Date(required=True)
    end_date = fields.Date(load_default=None, allow_none=True)
    is_salary = fields.Boolean(load_default=False)
    category_id = fields.UUID(load_default=None, allow_none=True)
    account_id = fields.UUID(load_default=None, allow_none=True)
    card_id = fields.UUID(load_default=None, allow_none=True)
    others_amount = OTHERS(load_default=Decimal("0.00"))
    payment_method = PaymentField(load_default=None)
    notes = fields.String(load_default=None, **NOTES)

    @validates_schema
    def check_rules(self, data, **kwargs):
        if data.get("card_id") and data["kind"] != "expense":
            raise ValidationError({"card_id": ["Apenas despesas podem ir para o cartão."]})
        if data["others_amount"] > data["amount"]:
            raise ValidationError({"others_amount": ["Não pode passar do valor."]})
        if data["frequency"] == "monthly" and data.get("day_of_month") is None:
            raise ValidationError({"day_of_month": ["Informe o dia."]})
        if data.get("end_date") and data["end_date"] < data["start_date"]:
            raise ValidationError({"end_date": ["O fim não pode ser antes do início."]})
        if data["is_salary"] and data["kind"] != "income":
            raise ValidationError({"is_salary": ["Apenas receitas podem ser salário."]})


class RecurrenceUpdateSchema(Schema):
    name = fields.String(validate=NAME)
    amount = MoneyField()
    # Mês em que o novo valor começa; meses anteriores nunca são alterados.
    effective_from = fields.String()
    day_of_month = fields.Integer(validate=DAY)
    end_date = fields.Date(allow_none=True)
    active = fields.Boolean()
    category_id = fields.UUID(allow_none=True)
    account_id = fields.UUID(allow_none=True)
    card_id = fields.UUID(allow_none=True)
    others_amount = OTHERS()
    payment_method = PaymentField()
    notes = fields.String(**NOTES)


def _check_card(card_id) -> CreditCard | None:
    if card_id is None:
        return None
    card = owned(CreditCard, card_id)
    if not card.active:
        raise ValidationError({"card_id": ["Este cartão está desativado."]})
    return card


@bp.get("")
@login_required
def list_recurrences():
    query = sa.select(Recurrence).where(Recurrence.user_id == g.user.id)
    if request.args.get("kind"):
        query = query.where(Recurrence.kind == request.args["kind"])
    rules = db.session.scalars(
        query.order_by(Recurrence.active.desc(), Recurrence.is_salary.desc(), Recurrence.name)
    ).all()
    return jsonify([recurrence_payload(r) for r in rules])


@bp.post("")
@login_required
def create_recurrence():
    data = load_body(RecurrenceSchema())
    check_account(data["account_id"])
    check_category(data["category_id"], data["kind"])
    if _check_card(data["card_id"]):
        data["account_id"] = None  # a saída da conta é o pagamento da fatura
    amount = data.pop("amount")
    data["name"] = data["name"].strip()
    data["day_of_month"] = data["day_of_month"] or data["start_date"].day

    rec = Recurrence(user_id=g.user.id, generate_from=data["start_date"], **data)
    rec.amounts.append(RecurrenceAmount(
        amount=amount, effective_from=data["start_date"].replace(day=1)
    ))
    db.session.add(rec)
    db.session.commit()
    service.generate(g.user.id, service.generation_horizon(today()))
    return jsonify(recurrence_payload(rec)), 201


def _effective_month(raw: str | None):
    current = today().replace(day=1)
    if raw is None:
        return current
    parsed = parse_month(raw)
    if parsed is None:
        raise ValidationError({"effective_from": ["Use AAAA-MM."]})
    effective = date(parsed[0], parsed[1], 1)
    if effective < current:
        raise ValidationError({"effective_from": ["Meses anteriores não podem ser alterados."]})
    return effective


@bp.patch("/<uuid:rec_id>")
@login_required
def update_recurrence(rec_id):
    rec = owned(Recurrence, rec_id)
    data = load_body(RecurrenceUpdateSchema())
    effective = _effective_month(data.pop("effective_from", None))
    if "account_id" in data:
        check_account(data["account_id"])
    if "category_id" in data:
        check_category(data["category_id"], rec.kind)
    if data.get("card_id"):
        if rec.kind != "expense":
            return error("Apenas despesas podem ir para o cartão.", 422)
        if data["card_id"] != rec.card_id:
            _check_card(data["card_id"])
        data["account_id"] = None  # a saída da conta é o pagamento da fatura

    amount = data.pop("amount", None)
    active = data.pop("active", None)
    if data.get("others_amount", 0) > (amount or service.amount_for(rec, effective)):
        raise ValidationError({"others_amount": ["Não pode passar do valor."]})
    for field, value in data.items():
        setattr(rec, field, value)
    if amount is not None:
        service.set_amount(rec, amount, effective)
    db.session.flush()
    service.sync_pending(rec, effective)

    if rec.end_date:
        service.remove_pending(rec, rec.end_date + timedelta(days=1))
    if active is False and rec.active:
        rec.active = False
        service.remove_pending(rec, today())
    elif active is True and not rec.active:
        rec.active = True
        rec.generate_from = today()  # os meses da pausa não são criados
    db.session.commit()
    service.generate(g.user.id, service.generation_horizon(today()))
    return jsonify(recurrence_payload(rec))


@bp.delete("/<uuid:rec_id>")
@login_required
def delete_recurrence(rec_id):
    """Apaga a regra e o que estava pendente; o que já foi confirmado continua no histórico."""
    rec = owned(Recurrence, rec_id)
    service.remove_pending(rec, date.min)
    db.session.delete(rec)
    db.session.commit()
    return "", 204
