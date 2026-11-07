"""Dívidas pessoais, pagamentos, ordem de quitação e simulador."""
from decimal import Decimal

from flask import Blueprint, g, jsonify, request
from marshmallow import Schema, ValidationError, fields, validate, validates_schema
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Debt, DebtPayment
from ..services import debts as service
from ..services.balances import ZERO
from ..services.dashboard import monthly_capacity
from .common import error, load_body, login_required
from .finance_common import MoneyField, check_account, find_by_key, owned, today

bp = Blueprint("debts", __name__, url_prefix="/api")

NAME = validate.Length(min=1, max=120)
FREQUENCY = validate.OneOf(["none", "weekly", "biweekly", "monthly"])
PRIORITY = validate.Range(min=1, max=3)
RATE = validate.Range(min=0, max=100)
BALANCE = validate.Range(min=0, max=999_999_999.99)
NOTES = {"allow_none": True, "validate": validate.Length(max=2000)}
MAX_SCENARIOS = 4


class DebtSchema(Schema):
    name = fields.String(required=True, validate=NAME)
    creditor = fields.String(required=True, validate=NAME)
    original_amount = MoneyField(required=True)
    # Saldo de hoje, se parte da dívida já foi paga antes do cadastro.
    current_balance = fields.Decimal(load_default=None, allow_none=True, places=2, validate=BALANCE)
    start_date = fields.Date(required=True)
    due_date = fields.Date(load_default=None, allow_none=True)
    agreed_amount = MoneyField(load_default=None, allow_none=True)
    frequency = fields.String(load_default="none", validate=FREQUENCY)
    interest_rate = fields.Decimal(load_default=None, allow_none=True, places=3, validate=RATE)
    priority = fields.Integer(load_default=2, validate=PRIORITY)
    notes = fields.String(load_default=None, **NOTES)

    @validates_schema
    def check_agreement(self, data, **kwargs):
        if data["frequency"] != "none" and not data.get("agreed_amount"):
            raise ValidationError({"agreed_amount": ["Informe o valor combinado."]})


class DebtUpdateSchema(Schema):
    name = fields.String(validate=NAME)
    creditor = fields.String(validate=NAME)
    original_amount = MoneyField()
    opening_balance = fields.Decimal(places=2, validate=BALANCE)
    start_date = fields.Date()
    due_date = fields.Date(allow_none=True)
    agreed_amount = MoneyField(allow_none=True)
    frequency = fields.String(validate=FREQUENCY)
    interest_rate = fields.Decimal(allow_none=True, places=3, validate=RATE)
    priority = fields.Integer(validate=PRIORITY)
    notes = fields.String(**NOTES)


class PaymentSchema(Schema):
    amount = MoneyField(required=True)
    paid_on = fields.Date(required=True)
    account_id = fields.UUID(load_default=None, allow_none=True)
    description = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=160))
    notes = fields.String(load_default=None, **NOTES)


class OrderSchema(Schema):
    ids = fields.List(fields.UUID(), required=True)


class SimulationSchema(Schema):
    amounts = fields.List(
        MoneyField(), required=True, validate=validate.Length(min=1, max=MAX_SCENARIOS)
    )
    extra = fields.Decimal(load_default=Decimal("0"), places=2, validate=BALANCE)
    strategy = fields.String(load_default=None, allow_none=True, validate=validate.OneOf(service.STRATEGIES))


def payment_payload(payment: DebtPayment) -> dict:
    return {
        "id": str(payment.id), "amount": payment.amount, "paid_on": payment.paid_on.isoformat(),
        "description": payment.description, "notes": payment.notes,
        "account_name": payment.account.name if payment.account else None,
    }


def debt_payload(debt: Debt) -> dict:
    return {
        "id": str(debt.id), "name": debt.name, "creditor": debt.creditor,
        "original_amount": debt.original_amount, "opening_balance": debt.opening_balance,
        "balance": service.balance_of(debt), "total_paid": service.total_paid(debt),
        "paid_pct": service.paid_pct(debt), "status": service.status_of(debt),
        "start_date": debt.start_date.isoformat(),
        "due_date": debt.due_date.isoformat() if debt.due_date else None,
        "agreed_amount": debt.agreed_amount, "frequency": debt.frequency,
        "interest_rate": debt.interest_rate, "priority": debt.priority, "notes": debt.notes,
        "payments": [payment_payload(p) for p in debt.payments],
    }


@bp.get("/debts")
@login_required
def list_debts():
    strategy = request.args.get("strategy") or g.user.settings.debt_strategy
    if strategy not in service.STRATEGIES:
        return error("Estratégia inválida.", 400)
    debts = service.user_debts(g.user.id)
    active = [d for d in debts if service.balance_of(d) > 0]
    ordered = service.order_debts(active, strategy) + [d for d in debts if d not in active]
    original = sum((d.original_amount for d in debts), ZERO)
    paid = sum((service.total_paid(d) for d in debts), ZERO)
    return jsonify({
        "strategy": strategy,
        "items": [debt_payload(d) for d in ordered],
        "summary": {
            "original": original,
            "paid": paid,
            "balance": sum((service.balance_of(d) for d in debts), ZERO),
            "paid_pct": min(100, round(paid / original * 100)) if original > 0 else 0,
            "monthly_commitment": sum((service.monthly_commitment(d) for d in active), ZERO),
            "next_debt": ordered[0].name if active else None,
        },
    })


@bp.post("/debts")
@login_required
def create_debt():
    data = load_body(DebtSchema())
    current = data.pop("current_balance")
    last = max((d.sort_order for d in service.user_debts(g.user.id)), default=0)
    debt = Debt(
        user_id=g.user.id, sort_order=last + 1,
        opening_balance=data["original_amount"] if current is None else current, **data,
    )
    db.session.add(debt)
    db.session.commit()
    return jsonify(debt_payload(debt)), 201


@bp.patch("/debts/<uuid:debt_id>")
@login_required
def update_debt(debt_id):
    debt = owned(Debt, debt_id)
    for field, value in load_body(DebtUpdateSchema()).items():
        setattr(debt, field, value)
    if service.balance_of(debt) < 0:
        raise ValidationError({"opening_balance": ["O saldo não pode ficar abaixo do que já foi pago."]})
    db.session.commit()
    return jsonify(debt_payload(debt))


@bp.delete("/debts/<uuid:debt_id>")
@login_required
def delete_debt(debt_id):
    debt = owned(Debt, debt_id)
    if debt.payments:
        return error("Esta dívida tem pagamentos. Remova-os antes de excluir.", 409)
    db.session.delete(debt)
    db.session.commit()
    return "", 204


@bp.post("/debts/order")
@login_required
def reorder_debts():
    ids = load_body(OrderSchema())["ids"]
    debts = {d.id: d for d in service.user_debts(g.user.id)}
    if len(ids) != len(set(ids)) or set(ids) - set(debts):
        raise ValidationError({"ids": ["Lista de dívidas inválida."]})
    for position, debt_id in enumerate(ids, start=1):
        debts[debt_id].sort_order = position
    g.user.settings.debt_strategy = "custom"
    db.session.commit()
    return "", 204


@bp.post("/debts/<uuid:debt_id>/payments")
@login_required
def pay_debt(debt_id):
    debt = owned(Debt, debt_id)
    key = request.headers.get("Idempotency-Key")
    if key and len(key) > 64:
        return error("Idempotency-Key inválida.", 400)
    existing = find_by_key(DebtPayment, key)
    if existing:
        return jsonify(debt_payload(existing.debt)), 200

    data = load_body(PaymentSchema())
    check_account(data["account_id"])
    if data["paid_on"] > today():
        raise ValidationError({"paid_on": ["O pagamento não pode estar no futuro."]})
    if data["amount"] > service.balance_of(debt):
        raise ValidationError({"amount": ["O valor é maior do que o saldo da dívida."]})

    debt.payments.append(DebtPayment(user_id=g.user.id, idempotency_key=key, **data))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(debt_payload(find_by_key(DebtPayment, key).debt)), 200
    db.session.refresh(debt)
    return jsonify(debt_payload(debt)), 201


@bp.delete("/debt-payments/<uuid:payment_id>")
@login_required
def delete_debt_payment(payment_id):
    db.session.delete(owned(DebtPayment, payment_id))
    db.session.commit()
    return "", 204


@bp.post("/debts/simulate")
@login_required
def simulate_debts():
    data = load_body(SimulationSchema())
    strategy = data["strategy"] or g.user.settings.debt_strategy
    debts = service.user_debts(g.user.id)
    capacity = monthly_capacity(g.user.id, g.user.settings, today())

    scenarios = []
    for amount in data["amounts"]:
        result = service.simulate(debts, strategy, amount, data["extra"], today())
        scenarios.append({
            "monthly": amount,
            "above_capacity": capacity is not None and amount > capacity,
            **result,
        })

    base = scenarios[0]
    for scenario in scenarios:
        comparable = base["feasible"] and scenario["feasible"]
        scenario["months_saved"] = base["months"] - scenario["months"] if comparable else None
        scenario["interest_saved"] = (
            base["total_interest"] - scenario["total_interest"] if comparable else None
        )
    return jsonify({"strategy": strategy, "capacity": capacity, "scenarios": scenarios})
