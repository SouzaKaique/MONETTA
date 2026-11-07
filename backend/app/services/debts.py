"""Saldos de dívidas, estratégias de quitação e simulador."""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import sqlalchemy as sa

from ..extensions import db
from ..models import Debt, DebtPayment
from .balances import ZERO
from .periods import shift_month

STRATEGIES = ("snowball", "avalanche", "due_date", "priority", "custom")
# Quantos pagamentos cabem em um mês, para somar o combinado às obrigações do mês.
PAYMENTS_PER_MONTH = {"monthly": 1, "biweekly": 2, "weekly": 4}
MAX_SIMULATED_MONTHS = 600
CENT = Decimal("0.01")


def paid_amount(debt: Debt) -> Decimal:
    return sum((p.amount for p in debt.payments), ZERO)


def balance_of(debt: Debt) -> Decimal:
    return debt.opening_balance - paid_amount(debt)


def status_of(debt: Debt) -> str:
    if balance_of(debt) <= 0:
        return "paid"
    return "in_payment" if debt.payments or debt.opening_balance < debt.original_amount else "pending"


def total_paid(debt: Debt) -> Decimal:
    """Inclui o que já tinha sido pago antes do cadastro."""
    return max(ZERO, debt.original_amount - balance_of(debt))


def paid_pct(debt: Debt) -> int:
    return min(100, round(total_paid(debt) / debt.original_amount * 100))


def user_debts(user_id: UUID) -> list[Debt]:
    return list(db.session.scalars(
        sa.select(Debt).where(Debt.user_id == user_id).order_by(Debt.sort_order, Debt.created_at)
    ).unique())


def order_debts(debts: list[Debt], strategy: str) -> list[Debt]:
    """Ordem de quitação. Dívidas sem o critério escolhido ficam por último, da menor para a maior."""
    def key(debt: Debt) -> tuple:
        balance = balance_of(debt)
        if strategy == "snowball":
            return (balance,)
        if strategy == "avalanche":
            # Maior juro primeiro; sem juros, volta para a menor dívida.
            return (-(debt.interest_rate or ZERO), balance)
        if strategy == "due_date":
            return (debt.due_date or date.max, balance)
        if strategy == "priority":
            return (debt.priority, balance)
        return (debt.sort_order,)

    return sorted(debts, key=key)


def monthly_commitment(debt: Debt) -> Decimal:
    if not debt.agreed_amount:
        return ZERO
    return debt.agreed_amount * PAYMENTS_PER_MONTH.get(debt.frequency, 0)


def paid_between(user_id: UUID, start: date, end: date) -> Decimal:
    return db.session.scalar(
        sa.select(sa.func.sum(DebtPayment.amount))
        .where(DebtPayment.user_id == user_id, DebtPayment.paid_on.between(start, end))
    ) or ZERO


def total_balance(user_id: UUID) -> Decimal:
    return sum((balance_of(d) for d in user_debts(user_id)), ZERO)


def due_in_month(user_id: UUID, start: date, end: date) -> Decimal:
    """Quanto do valor combinado ainda falta pagar no mês, por dívida."""
    total = ZERO
    for debt in user_debts(user_id):
        if debt.start_date > end:
            continue
        paid = sum((p.amount for p in debt.payments if start <= p.paid_on <= end), ZERO)
        missing = max(ZERO, monthly_commitment(debt) - paid)
        total += min(missing, max(ZERO, balance_of(debt)))
    return total


def debt_alerts(user_id: UUID, today: date, due_days: int = 3) -> list[dict]:
    alerts = []
    debts = user_debts(user_id)
    for debt in debts:
        if balance_of(debt) <= 0 or debt.due_date is None:
            continue
        days = (debt.due_date - today).days
        if days < 0:
            alerts.append({
                "kind": "debt", "key": f"debt-late:{debt.id}", "level": "critical",
                "message": f"A dívida {debt.name} está vencida.", "link": "/dividas",
            })
        elif days <= due_days:
            when = "hoje" if days == 0 else f"em {days} dia(s)"
            alerts.append({
                "kind": "debt", "key": f"debt-due:{debt.id}", "level": "warning",
                "message": f"A dívida {debt.name} vence {when}.", "link": "/dividas",
            })

    original = sum((d.original_amount for d in debts), ZERO)
    paid = sum((total_paid(d) for d in debts), ZERO)
    if paid > 0 and original > 0:
        pct = min(100, round(paid / original * 100))
        alerts.append({
            # Uma notificação a cada 10 pontos, para o progresso não virar ruído.
            "kind": "debt", "key": f"debt-progress:{pct // 10}", "level": "info",
            "message": f"Você quitou {pct}% das suas dívidas.", "link": "/dividas",
        })
    return alerts


@dataclass
class SimDebt:
    name: str
    balance: Decimal
    rate: Decimal  # % ao mês
    paid_off_in: int | None = None


def _month_label(start: date, offset: int) -> str:
    year, month = shift_month(start.year, start.month, offset)
    return f"{year:04d}-{month:02d}"


def order_with_priority(debts: list[Debt], strategy: str, first_ids: list[str]) -> list[Debt]:
    """As dívidas prioritárias vêm antes; dentro de cada grupo vale a estratégia."""
    ordered = order_debts(debts, strategy)
    priority = {str(i) for i in first_ids}
    return [d for d in ordered if str(d.id) in priority] + [d for d in ordered if str(d.id) not in priority]


def simulate(
    debts: list[Debt], strategy: str, monthly: Decimal, extra: Decimal, today: date,
    first_ids: list[str] | None = None, added: Decimal = ZERO,
) -> dict:
    """
    Mês a mês, a partir do mês seguinte: aplica os juros estimados e paga na ordem da
    estratégia. O que sobra ao quitar uma dívida passa para a próxima. Extra entra no 1º mês.
    """
    active = [d for d in debts if balance_of(d) > 0]
    pending = order_with_priority(active, strategy, first_ids or [])
    sim = [SimDebt(d.name, balance_of(d), d.interest_rate or ZERO) for d in pending]
    if added > 0:  # valor desviado das dívidas: atrasa a quitação como um saldo a mais
        sim.append(SimDebt("Compra não planejada", added, ZERO))
    timeline = [{"month": _month_label(today, 0), "balance": sum((s.balance for s in sim), ZERO)}]
    interest = ZERO
    months = 0

    while any(s.balance > 0 for s in sim):
        months += 1
        previous = sum((s.balance for s in sim), ZERO)
        for item in sim:
            charge = (item.balance * item.rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
            item.balance += charge
            interest += charge

        budget = monthly + (extra if months == 1 else ZERO)
        for item in sim:
            payment = min(budget, item.balance)
            item.balance -= payment
            budget -= payment
            if item.balance == 0 and item.paid_off_in is None:
                item.paid_off_in = months

        total = sum((s.balance for s in sim), ZERO)
        timeline.append({"month": _month_label(today, months), "balance": total})
        # Se o saldo não cai, o valor não cobre nem os juros: a dívida nunca termina.
        if total >= previous or months >= MAX_SIMULATED_MONTHS:
            return {
                "feasible": False, "months": None, "finish_month": None,
                "total_interest": None, "total_paid": None, "timeline": timeline[:13], "payoff": [],
            }

    return {
        "feasible": True,
        "months": months,
        "finish_month": _month_label(today, months) if months else None,
        "total_interest": interest,
        "total_paid": timeline[0]["balance"] + interest,
        "timeline": timeline,
        "payoff": [
            {"name": s.name, "month": _month_label(today, s.paid_off_in), "months": s.paid_off_in}
            for s in sim
        ],
    }
