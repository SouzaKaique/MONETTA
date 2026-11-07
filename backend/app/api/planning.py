"""Planejamento mensal, calendário, Modo Recuperação e notificações."""
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from flask import Blueprint, g, jsonify, request
from marshmallow import Schema, ValidationError, fields, validate

from ..extensions import db
from ..models import Budget, Category, Notification, RecoveryPlan
from ..models.common import utcnow
from ..services import alerts, budgets, calendar, debts, recovery, spending
from ..services.dashboard import build_dashboard, monthly_capacity
from ..services.periods import month_bounds, parse_month
from ..services.recurrences import generate, generation_horizon
from .common import error, load_body, login_required
from .finance_common import MoneyField, owned, today

bp = Blueprint("planning", __name__, url_prefix="/api")

LIMIT = validate.Range(min=0, max=999_999_999.99)
NOTIFICATIONS_SHOWN = 50


class BudgetSchema(Schema):
    category_id = fields.UUID(required=True)
    amount = fields.Decimal(required=True, places=2, validate=LIMIT)
    month = fields.String(load_default=None, allow_none=True)


class RecoverySchema(Schema):
    monthly_amount = MoneyField(required=True)
    strategy = fields.String(load_default="snowball", validate=validate.OneOf(debts.STRATEGIES))
    priority_debt_ids = fields.List(fields.UUID(), load_default=list)
    non_essential_limit = fields.Decimal(load_default=None, allow_none=True, places=2, validate=LIMIT)
    reserve_minimum = fields.Decimal(load_default=Decimal("0"), places=2, validate=LIMIT)
    spending_goal_pct = fields.Integer(load_default=None, allow_none=True, validate=validate.Range(min=1, max=100))
    target_date = fields.Date(load_default=None, allow_none=True)


class ImpactSchema(Schema):
    amount = MoneyField(required=True)


def _requested_month() -> tuple[int, int]:
    raw = request.args.get("month")
    if raw is None:
        now = today()
        return now.year, now.month
    parsed = parse_month(raw)
    if parsed is None:
        raise ValidationError({"month": ["Use AAAA-MM."]})
    return parsed


@bp.get("/planning")
@login_required
def planning():
    year, month = _requested_month()
    start, end = month_bounds(year, month)
    settings = g.user.settings
    data = build_dashboard(g.user.id, settings, year, month)
    s = data["summary"]

    essential, other = budgets.essential_split(g.user.id, start, end)
    debts_total = s["debt_payments"] + s["debt_due"]
    reserve = settings.planned_reserve
    free = s["income_expected"] - essential - other - s["card_commitment"] - debts_total - reserve
    now = today()
    until = spending.until_salary(g.user.id, settings, now) if data["is_current_month"] else None
    return jsonify({
        "month": data["month"],
        "is_current_month": data["is_current_month"],
        "income_expected": s["income_expected"],
        "income_received": s["income_received"],
        "expenses_paid": s["expenses_paid"],
        "card_commitment": s["card_commitment"],
        "expenses_pending": s["expenses_pending"],
        "future_commitments": spending.future_commitments(g.user.id, end),
        "reserved": reserve,
        "projected_balance": s["projected_balance"],
        "available": until["available"] if until and until["has_salary"] else s["available_to_spend"],
        "commitment_pct": s["income_commitment_pct"],
        "distribution": [
            {"key": "essential", "label": "Essenciais", "amount": essential},
            {"key": "variable", "label": "Variáveis", "amount": other},
            {"key": "cards", "label": "Cartões", "amount": s["card_commitment"]},
            {"key": "debts", "label": "Dívidas", "amount": debts_total},
            {"key": "reserve", "label": "Reserva", "amount": reserve},
            {"key": "wishlist", "label": "Wishlist", "amount": None},
            {"key": "free", "label": "Dinheiro livre", "amount": free},
        ],
        "budgets": budgets.status(g.user.id, year, month),
    })


@bp.get("/planning/until-salary")
@login_required
def until_salary():
    raw = request.args.get("spend", "0")
    try:
        spend = Decimal(raw)
    except ArithmeticError:
        raise ValidationError({"spend": ["Valor inválido."]}) from None
    if not spend.is_finite() or spend < 0:
        raise ValidationError({"spend": ["Valor inválido."]})
    now = today()
    generate(g.user.id, generation_horizon(now))
    return jsonify(spending.until_salary(g.user.id, g.user.settings, now, spend))


@bp.put("/budgets")
@login_required
def save_budget():
    data = load_body(BudgetSchema())
    category = owned(Category, data["category_id"])
    if category.kind != "expense":
        raise ValidationError({"category_id": ["Use uma categoria de despesa."]})
    current = today().replace(day=1)
    month = current
    if data["month"]:
        parsed = parse_month(data["month"])
        if parsed is None:
            raise ValidationError({"month": ["Use AAAA-MM."]})
        month = date(parsed[0], parsed[1], 1)
    if month < current:
        raise ValidationError({"month": ["Meses anteriores não podem ser alterados."]})

    budget = db.session.scalar(
        sa.select(Budget).filter_by(user_id=g.user.id, category_id=category.id, month=month)
    )
    if budget:
        budget.amount = data["amount"]
    else:
        db.session.add(Budget(
            user_id=g.user.id, category_id=category.id, month=month, amount=data["amount"],
        ))
    db.session.commit()
    return "", 204


@bp.get("/calendar")
@login_required
def month_calendar():
    year, month = _requested_month()
    now = today()
    generate(g.user.id, generation_horizon(now, month_bounds(year, month)[1]))
    return jsonify({
        "month": f"{year:04d}-{month:02d}",
        "events": calendar.month_events(g.user.id, year, month, now),
    })


# Modo Recuperação

def _plan_config(plan: RecoveryPlan) -> dict:
    return {
        "active": plan.active, "monthly_amount": plan.monthly_amount, "strategy": plan.strategy,
        "priority_debt_ids": plan.priority_debt_ids or [],
        "non_essential_limit": plan.non_essential_limit, "reserve_minimum": plan.reserve_minimum,
        "spending_goal_pct": plan.spending_goal_pct,
        "target_date": plan.target_date.isoformat() if plan.target_date else None,
        "started_on": plan.started_on.isoformat(),
        "ended_on": plan.ended_on.isoformat() if plan.ended_on else None,
    }


def _recovery_payload(plan: RecoveryPlan | None) -> dict:
    if plan is None:
        return {"configured": False, "active": False}
    capacity = monthly_capacity(g.user.id, g.user.settings, today())
    return {
        "configured": True,
        "config": _plan_config(plan),
        "active": plan.active,
        "status": recovery.status(plan, g.user.id, today(), capacity),
    }


@bp.get("/recovery")
@login_required
def get_recovery():
    return jsonify(_recovery_payload(recovery.plan_for(g.user.id)))


@bp.put("/recovery")
@login_required
def save_recovery():
    """Salva a configuração e ativa o modo."""
    data = load_body(RecoverySchema())
    known = {d.id for d in debts.user_debts(g.user.id)}
    if set(data["priority_debt_ids"]) - known:
        raise ValidationError({"priority_debt_ids": ["Dívida não encontrada."]})
    data["priority_debt_ids"] = [str(i) for i in data["priority_debt_ids"]]

    plan = recovery.plan_for(g.user.id)
    if plan is None:
        plan = RecoveryPlan(
            user_id=g.user.id, initial_debt=debts.total_balance(g.user.id), started_on=today(),
            **data,
        )
        db.session.add(plan)
    else:
        for field, value in data.items():
            setattr(plan, field, value)
    plan.active = True
    plan.ended_on = None
    db.session.commit()
    return jsonify(_recovery_payload(plan))


@bp.post("/recovery/deactivate")
@login_required
def deactivate_recovery():
    plan = recovery.plan_for(g.user.id)
    if plan is None:
        return error("O Modo Recuperação ainda não foi configurado.", 404)
    plan.active = False
    plan.ended_on = today()
    db.session.commit()
    return jsonify(_recovery_payload(plan))


@bp.post("/recovery/impact")
@login_required
def purchase_impact():
    plan = recovery.plan_for(g.user.id)
    if plan is None:
        return error("O Modo Recuperação ainda não foi configurado.", 404)
    return jsonify(recovery.impact(plan, g.user.id, today(), load_body(ImpactSchema())["amount"]))


# Notificações

@bp.get("/notifications")
@login_required
def list_notifications():
    now = today()
    build_dashboard(g.user.id, g.user.settings, now.year, now.month, sync_alerts=True)
    rows = db.session.scalars(
        sa.select(Notification).where(Notification.user_id == g.user.id)
        .order_by(Notification.created_at.desc()).limit(NOTIFICATIONS_SHOWN)
    ).all()
    return jsonify({
        "unread": alerts.unread_count(g.user.id),
        "items": [{
            "id": str(n.id), "kind": n.kind, "level": n.level, "message": n.message,
            "link": n.link, "created_at": n.created_at.isoformat(), "read": n.read_at is not None,
        } for n in rows],
    })


@bp.post("/notifications/<uuid:notification_id>/read")
@login_required
def read_notification(notification_id):
    notification = owned(Notification, notification_id)
    notification.read_at = notification.read_at or utcnow()
    db.session.commit()
    return "", 204


@bp.post("/notifications/read-all")
@login_required
def read_all_notifications():
    db.session.execute(
        sa.update(Notification)
        .where(Notification.user_id == g.user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.session.commit()
    return "", 204

