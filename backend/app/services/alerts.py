"""Alertas do dashboard e notificações: mesma origem, sem repetir o mesmo aviso."""
from datetime import date
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from ..extensions import db
from ..models import AppSettings, Notification
from . import budgets, cards, debts, recovery, spending, wishlist

KINDS = ("budget", "card", "debt", "balance", "insight", "recovery", "wishlist")
DEFAULT_PREFS = {"budget_pct": 80, "card_pct": 80, "commitment_pct": 80, "due_days": 3, "muted": []}
CAN_PAY_MORE = Decimal("100.00")


def prefs_for(settings: AppSettings) -> dict:
    return {**DEFAULT_PREFS, **(settings.alert_prefs or {})}


def _summary_alerts(summary: dict, tag: str, is_current: bool, threshold: int) -> list[dict]:
    alerts = []
    pct = summary["income_commitment_pct"]
    if pct is not None and pct >= threshold:
        alerts.append({
            "kind": "balance", "key": f"commitment:{tag}", "level": "warning",
            "message": f"Você já comprometeu {pct}% da sua renda.", "link": "/planejamento",
        })
    if is_current and summary["projected_balance"] < 0:
        alerts.append({
            "kind": "balance", "key": f"negative:{tag}", "level": "critical",
            "message": "Seu saldo projetado está negativo.", "link": "/planejamento",
        })
    if is_current and summary["overdue_expenses"] > 0:
        alerts.append({
            "kind": "balance", "key": f"overdue:{tag}", "level": "warning",
            "message": "Você tem despesas atrasadas.", "link": "/despesas",
        })
    return alerts


def collect(
    user_id: UUID, settings: AppSettings, summary: dict, today: date,
    year: int, month: int, is_current: bool,
) -> list[dict]:
    prefs = prefs_for(settings)
    tag = f"{year:04d}-{month:02d}"
    alerts = _summary_alerts(summary, tag, is_current, prefs["commitment_pct"])
    if is_current:
        alerts += cards.card_alerts(user_id, today, prefs["card_pct"], prefs["due_days"])
        alerts += debts.debt_alerts(user_id, today, prefs["due_days"])
        alerts += budgets.budget_alerts(user_id, year, month, prefs["budget_pct"])
        alerts += budgets.spending_increases(user_id, year, month)
        alerts += spending.daily_alert(user_id, spending.until_salary(user_id, settings, today), today)
        if summary["pending_debts"] > 0 and summary["free_money"] >= CAN_PAY_MORE:
            alerts.append({
                "kind": "insight", "key": f"can-pay-more:{tag}", "level": "info",
                "message": "Sobrou dinheiro neste mês: você pode aumentar o pagamento de uma dívida.",
                "link": "/dividas",
            })
        plan = recovery.active_plan(user_id)
        if plan:
            alerts += recovery.recovery_alerts(plan, user_id, today)
    return [a for a in alerts if a["kind"] not in prefs["muted"]]


def _achievements(user_id: UUID) -> list[dict]:
    """Conquistas ficam só nas notificações: no dashboard perderiam o sentido depois de um dia."""
    paid = [
        {"kind": "debt", "key": f"debt-paid:{debt.id}", "level": "info",
         "message": f"Você quitou a dívida {debt.name}.", "link": "/dividas"}
        for debt in debts.user_debts(user_id)
        if debts.balance_of(debt) <= 0 and debt.payments
    ]
    goals = [
        {"kind": "wishlist", "key": f"goal-reached:{item.goal.id}", "level": "info",
         "message": f"Você atingiu a meta de {item.name}.", "link": "/wishlist"}
        for item in wishlist.reached_goals(user_id)
    ]
    return paid + goals


def sync(user_id: UUID, settings: AppSettings, alerts: list[dict]) -> None:
    """Grava o que ainda não virou notificação; a chave impede repetir o mesmo aviso."""
    muted = prefs_for(settings)["muted"]
    entries = alerts + [a for a in _achievements(user_id) if a["kind"] not in muted]
    for alert in entries:
        db.session.execute(
            insert(Notification).values(
                id=db.func.gen_random_uuid(), user_id=user_id, created_at=db.func.now(),
                **{k: alert.get(k) for k in ("key", "kind", "level", "message", "link")},
            ).on_conflict_do_nothing(index_elements=["user_id", "key"])
        )
    db.session.commit()


def unread_count(user_id: UUID) -> int:
    return db.session.scalar(
        sa.select(sa.func.count()).select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
    ) or 0

