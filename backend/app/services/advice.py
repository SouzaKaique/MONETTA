"""
"Posso comprar?"

Cada critério vira um item explicado. O resultado é o pior deles; no Modo Recuperação
a quitação das dívidas pesa mais. É uma recomendação: nada aqui impede a compra.
"""
from datetime import date
from decimal import Decimal
from uuid import UUID

from ..models import AppSettings, CreditCard, WishlistItem
from . import budgets, cards, debts, recovery, spending, wishlist
from .balances import ZERO
from .dashboard import build_dashboard
from .periods import format_brl as brl
from .periods import month_bounds

OK, WARN, BAD = "ok", "warning", "bad"
VERDICTS = {
    OK: ("buy", "Compra dentro do planejamento"),
    WARN: ("attention", "Compra possível, mas exige atenção"),
    BAD: ("postpone", "Melhor adiar"),
}
COMFORT_SHARE = Decimal("0.5")  # usar até metade do disponível é confortável
HIGH_COMMITMENT = 80
LONG_INSTALLMENTS = 6
CARD_HIGH_USAGE = 80


def _check(label: str, status: str, detail: str) -> dict:
    return {"label": label, "status": status, "detail": detail}


def _funds(need: Decimal, available: Decimal, saved: Decimal) -> dict:
    if need == 0:
        return _check("Saldo disponível", OK, f"Você já guardou {brl(saved)} para esta compra.")
    detail = f"Precisa de {brl(need)} e há {brl(available)} disponíveis."
    if need > available:
        return _check("Saldo disponível", BAD, detail)
    if need > available * COMFORT_SHARE:
        return _check("Saldo disponível", WARN, f"{detail} Vai usar boa parte do que resta.")
    return _check("Saldo disponível", OK, detail)


def _obligations(summary: dict) -> dict:
    late = summary["overdue_expenses"] + summary["overdue_invoices"]
    if late > 0:
        return _check("Despesas comprometidas", BAD, f"Há {brl(late)} em contas e faturas atrasadas.")
    return _check("Despesas comprometidas", OK, "Nenhuma conta ou fatura atrasada.")


def _commitment(summary: dict, monthly: Decimal) -> dict | None:
    income = summary["income_expected"]
    if income <= 0:
        return _check("Orçamento mensal", WARN, "Sem renda prevista para comparar.")
    used = income - summary["free_money"] + monthly
    pct = round(used / income * 100)
    detail = f"Sua renda ficaria {pct}% comprometida."
    if pct >= 100:
        return _check("Orçamento mensal", BAD, detail)
    return _check("Orçamento mensal", WARN if pct >= HIGH_COMMITMENT else OK, detail)


def _card(card: CreditCard, amount: Decimal, installments: int, summary: dict, today: date) -> list[dict]:
    state = cards.card_summary(card, today)
    checks = []
    if amount > state["available"]:
        checks.append(_check("Limite do cartão", BAD, f"Há {brl(state['available'])} de limite disponível."))
    else:
        after = round((state["used"] + amount) / card.credit_limit * 100) if card.credit_limit > 0 else 100
        status = WARN if after >= CARD_HIGH_USAGE else OK
        checks.append(_check("Limite do cartão", status, f"O uso do limite iria para {after}%."))
    if installments > 1:
        monthly = (amount / installments).quantize(Decimal("0.01"))
        free_after = summary["free_money"] - monthly
        status = BAD if free_after < 0 else WARN if installments >= LONG_INSTALLMENTS else OK
        checks.append(_check(
            "Faturas futuras", status,
            f"{installments} parcelas de {brl(monthly)} comprometem os próximos meses.",
        ))
    return checks


def _debts(user_id: UUID, today: date, need: Decimal) -> dict:
    all_debts = debts.user_debts(user_id)
    balance = sum((debts.balance_of(d) for d in all_debts), ZERO)
    late = any(d.due_date and d.due_date < today and debts.balance_of(d) > 0 for d in all_debts)
    if balance <= 0:
        return _check("Dívidas pendentes", OK, "Você não tem dívidas pendentes.")
    detail = f"Você deve {brl(balance)}."
    if late:
        return _check("Dívidas pendentes", BAD, f"{detail} Há dívida vencida.")
    return _check("Dívidas pendentes", WARN if need > 0 else OK, detail)


def _reserve(available: Decimal, need: Decimal, safety: Decimal) -> dict:
    if safety <= 0:
        return _check("Reserva financeira", WARN, "Você não definiu um mínimo de segurança.")
    if need > available:
        return _check("Reserva financeira", BAD, f"A compra usaria o mínimo de {brl(safety)}.")
    return _check("Reserva financeira", OK, f"O mínimo de {brl(safety)} continua guardado.")


def _budget(user_id: UUID, category_id: UUID | None, amount: Decimal, today: date) -> dict | None:
    if category_id is None:
        return None
    start, end = month_bounds(today.year, today.month)
    limit = budgets.limits_for(user_id, start).get(category_id)
    if limit is None:
        return None
    left = limit - budgets.spent_by_category(user_id, start, end).get(category_id, ZERO)
    status = OK if amount <= left else WARN
    return _check("Limite da categoria", status, f"Restam {brl(max(ZERO, left))} nesta categoria.")


def _recovery(user_id: UUID, need: Decimal, amount: Decimal, today: date) -> dict | None:
    plan = recovery.active_plan(user_id)
    if plan is None:
        return None
    if need == 0:
        return _check("Modo Recuperação", WARN, "Valor já guardado, mas ele também poderia reduzir dívidas.")
    delay = recovery.impact(plan, user_id, today, amount)["delay_months"]
    if delay:
        unit = "mês" if delay == 1 else "meses"
        detail = f"Esta compra atrasaria a quitação em {delay} {unit}."
    else:
        detail = "Durante a recuperação, a prioridade é quitar as dívidas."
    return _check("Modo Recuperação", BAD, detail)


def analyze(
    user_id: UUID, settings: AppSettings, today: date, amount: Decimal,
    item: WishlistItem | None = None, card: CreditCard | None = None, installments: int = 1,
) -> dict:
    summary = build_dashboard(user_id, settings, today.year, today.month)["summary"]
    until = spending.until_salary(user_id, settings, today)
    available = until["available"] if until["has_salary"] else summary["available_to_spend"]
    saved = wishlist.saved_of(item) if item else ZERO
    safety = recovery.effective_safety(user_id, settings)

    # O guardado para este item volta a ser usável: é para isso que ele existe.
    usable = available + saved
    monthly = (amount / installments).quantize(Decimal("0.01")) if card else max(ZERO, amount - saved)
    need = monthly if card else max(ZERO, amount - saved)

    checks = [
        _funds(need, usable if saved else available, saved),
        _obligations(summary),
        _commitment(summary, monthly),
        *(_card(card, amount, installments, summary, today) if card else []),
        _debts(user_id, today, need),
        _reserve(usable if saved else available, need, safety),
    ]
    category_id = item.category_id if item else None
    for extra in (_budget(user_id, category_id, amount, today), _recovery(user_id, need, amount, today)):
        if extra:
            checks.append(extra)

    statuses = {c["status"] for c in checks}
    worst = BAD if BAD in statuses else WARN if WARN in statuses else OK
    verdict, message = VERDICTS[worst]
    return {
        "verdict": verdict, "message": message, "amount": amount, "saved": saved,
        "need": need, "checks": checks,
    }

