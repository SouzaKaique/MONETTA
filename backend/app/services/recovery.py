"""
Modo Recuperação Financeira.

Orienta e prioriza, sem bloquear nenhuma decisão: nada aqui impede um lançamento.
"""
from datetime import date, timedelta
from decimal import ROUND_UP, Decimal
from uuid import UUID

import sqlalchemy as sa

from ..extensions import db
from ..models import AppSettings, CardPurchase, Debt, RecoveryPlan
from . import budgets, debts
from .balances import ZERO
from .periods import month_bounds, shift_month

BASELINE_MONTHS = 3
EVOLUTION_MONTHS = 6
RECENT_DAYS = 7


def plan_for(user_id: UUID) -> RecoveryPlan | None:
    return db.session.scalar(sa.select(RecoveryPlan).filter_by(user_id=user_id))


def active_plan(user_id: UUID) -> RecoveryPlan | None:
    plan = plan_for(user_id)
    return plan if plan is not None and plan.active else None


def effective_safety(user_id: UUID, settings: AppSettings) -> Decimal:
    """No Modo Recuperação vale a maior reserva mínima entre as duas configurações."""
    plan = active_plan(user_id)
    return max(settings.safety_minimum, plan.reserve_minimum) if plan else settings.safety_minimum


def debt_due(user_id: UUID, start: date, end: date) -> Decimal:
    """
    Quanto ainda precisa ir para dívidas no mês: o combinado ou, se maior,
    o valor mensal do Modo Recuperação, sem passar do total devido.
    """
    due = debts.due_in_month(user_id, start, end)
    plan = active_plan(user_id)
    if plan is None:
        return due
    missing = max(ZERO, plan.monthly_amount - debts.paid_between(user_id, start, end))
    return min(max(due, missing), max(ZERO, debts.total_balance(user_id)))


def balance_at(all_debts: list[Debt], day: date) -> Decimal:
    total = ZERO
    for debt in all_debts:
        if debt.start_date > day:
            continue
        total += debt.opening_balance - sum(
            (p.amount for p in debt.payments if p.paid_on <= day), ZERO
        )
    return total


def evolution(user_id: UUID, today: date) -> list[dict]:
    all_debts = debts.user_debts(user_id)
    rows = []
    for offset in range(-(EVOLUTION_MONTHS - 1), 1):
        year, month = shift_month(today.year, today.month, offset)
        end = month_bounds(year, month)[1]
        rows.append({"month": f"{year:04d}-{month:02d}", "balance": balance_at(all_debts, min(end, today))})
    return rows


def _baseline(user_id: UUID, today: date) -> Decimal | None:
    """Média dos gastos não essenciais nos meses anteriores ao atual."""
    totals = []
    for offset in range(1, BASELINE_MONTHS + 1):
        total = budgets.non_essential_spent(
            user_id, *month_bounds(*shift_month(today.year, today.month, -offset))
        )
        if total > 0:
            totals.append(total)
    return (sum(totals, ZERO) / len(totals)).quantize(Decimal("0.01")) if totals else None


def _recent_installments(user_id: UUID, today: date) -> int:
    return db.session.scalar(
        sa.select(sa.func.count()).select_from(CardPurchase).where(
            CardPurchase.user_id == user_id, CardPurchase.installment_count > 1,
            CardPurchase.purchase_date >= today - timedelta(days=RECENT_DAYS),
        )
    ) or 0


def _simulate(plan: RecoveryPlan, user_id: UUID, today: date, added: Decimal = ZERO) -> dict:
    return debts.simulate(
        debts.user_debts(user_id), plan.strategy, plan.monthly_amount, ZERO, today,
        first_ids=plan.priority_debt_ids or [], added=added,
    )


def forecast(plan: RecoveryPlan, user_id: UUID, today: date) -> dict:
    return _simulate(plan, user_id, today)


def impact(plan: RecoveryPlan, user_id: UUID, today: date, amount: Decimal) -> dict:
    """Quanto uma compra não planejada, tirada do dinheiro das dívidas, atrasa a quitação."""
    base = _simulate(plan, user_id, today)
    changed = _simulate(plan, user_id, today, added=amount)
    delay = None
    if base["feasible"] and changed["feasible"]:
        delay = changed["months"] - base["months"]
    return {
        "amount": amount, "months_before": base["months"], "months_after": changed["months"],
        "delay_months": delay, "finish_before": base["finish_month"], "finish_after": changed["finish_month"],
    }


def _months_until(today: date, target: date) -> int:
    return max(1, (target.year - today.year) * 12 + target.month - today.month)


def status(plan: RecoveryPlan, user_id: UUID, today: date, capacity: Decimal | None) -> dict:
    all_debts = debts.user_debts(user_id)
    active = [d for d in all_debts if debts.balance_of(d) > 0]
    current = sum((debts.balance_of(d) for d in active), ZERO)
    start, end = month_bounds(today.year, today.month)

    prediction = forecast(plan, user_id, today)
    spent = budgets.non_essential_spent(user_id, start, end)
    baseline = _baseline(user_id, today)
    goal_amount = None
    if baseline is not None and plan.spending_goal_pct:
        goal_amount = (baseline * (100 - plan.spending_goal_pct) / 100).quantize(Decimal("0.01"))

    ordered = debts.order_with_priority(active, plan.strategy, plan.priority_debt_ids or [])
    paid = max(ZERO, plan.initial_debt - current)
    recommendations = _recommendations(
        plan, user_id, today, spent, goal_amount, capacity, prediction, current,
        start, end,
    )
    return {
        "initial_debt": plan.initial_debt,
        "current_debt": current,
        "paid": paid,
        "reduction_pct": min(100, round(paid / plan.initial_debt * 100)) if plan.initial_debt > 0 else 0,
        "available_for_payments": capacity,
        "paid_this_month": debts.paid_between(user_id, start, end),
        "next_debt": ordered[0].name if ordered else None,
        "forecast": {
            "feasible": prediction["feasible"], "months": prediction["months"],
            "finish_month": prediction["finish_month"], "total_interest": prediction["total_interest"],
        },
        "on_target": (
            None if plan.target_date is None or not prediction["finish_month"]
            else prediction["finish_month"] <= plan.target_date.strftime("%Y-%m")
        ),
        "evolution": evolution(user_id, today),
        "non_essential": {
            "spent": spent, "limit": plan.non_essential_limit, "baseline": baseline,
            "goal_amount": goal_amount,
        },
        "recommendations": recommendations,
    }


def _recommendations(
    plan, user_id, today, spent, goal_amount, capacity, prediction, current, start, end,
) -> list[str]:
    tips = []
    limit = plan.non_essential_limit
    if limit is not None and spent > limit:
        top = budgets.top_non_essential(user_id, start, end)
        extra = f" O maior gasto está em {top.lower()}." if top else ""
        tips.append(f"Os gastos não essenciais passaram do limite do mês.{extra}")
    elif goal_amount is not None and spent > goal_amount:
        tips.append("Os gastos não essenciais estão acima da sua meta de redução.")
    if capacity is not None and plan.monthly_amount > capacity:
        tips.append(
            "O valor mensal passa do que sobra neste mês. Priorize as despesas essenciais "
            "e pague o que couber."
        )
    if not prediction["feasible"]:
        tips.append("O valor mensal não cobre os juros: aumente o valor ou renegocie.")
    elif plan.target_date and prediction["finish_month"] and (
        prediction["finish_month"] > plan.target_date.strftime("%Y-%m")
    ):
        months = _months_until(today, plan.target_date)
        needed = (current / months).quantize(Decimal("1"), rounding=ROUND_UP)
        tips.append(
            f"Para terminar na data desejada, seriam necessários cerca de R$ {needed} por mês, "
            "sem contar juros."
        )
    recent = _recent_installments(user_id, today)
    if recent:
        tips.append(
            f"Você fez {recent} compra(s) parcelada(s) nos últimos {RECENT_DAYS} dias. "
            "Parcelas comprometem os meses em que você quer quitar dívidas."
        )
    return tips


def recovery_alerts(plan: RecoveryPlan, user_id: UUID, today: date) -> list[dict]:
    start, end = month_bounds(today.year, today.month)
    alerts = []
    tag = today.strftime("%Y-%m")
    if plan.non_essential_limit is not None:
        spent = budgets.non_essential_spent(user_id, start, end)
        if spent > plan.non_essential_limit:
            alerts.append({
                "kind": "recovery", "key": f"recovery-limit:{tag}", "level": "warning",
                "message": "Modo Recuperação: gastos não essenciais acima do limite.",
                "link": "/recuperacao",
            })
    recent = _recent_installments(user_id, today)
    if recent:
        week = today.isocalendar()
        alerts.append({
            "kind": "recovery", "key": f"recovery-installment:{week.year}-{week.week}",
            "level": "warning",
            "message": "Modo Recuperação: você fez uma nova compra parcelada.",
            "link": "/recuperacao",
        })
    return alerts
