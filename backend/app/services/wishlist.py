"""Valores guardados, previsões e indicadores da wishlist."""
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import joinedload, selectinload

from ..extensions import db
from ..models import GoalContribution, SavingsGoal, WishlistItem
from .balances import ZERO
from .periods import shift_month

OPEN_STATUSES = ("desired", "planning", "saving")
AVERAGE_DAYS = 90
AVERAGE_MONTHS = 3


def is_open(item: WishlistItem) -> bool:
    return item.status in OPEN_STATUSES


def saved_of(item: WishlistItem) -> Decimal:
    return max(ZERO, sum((c.amount for c in item.goal.contributions), ZERO))


def user_items(user_id: UUID) -> list[WishlistItem]:
    return list(db.session.scalars(
        sa.select(WishlistItem)
        .options(joinedload(WishlistItem.category),
                 joinedload(WishlistItem.goal).selectinload(SavingsGoal.contributions),
                 selectinload(WishlistItem.image))
        .where(WishlistItem.user_id == user_id)
        .order_by(WishlistItem.priority, WishlistItem.added_on.desc(), WishlistItem.created_at.desc())
    ).unique())


def saved_total(user_id: UUID) -> Decimal:
    """Só metas abertas: comprar ou desistir libera o valor guardado."""
    return sum((saved_of(i) for i in user_items(user_id) if is_open(i)), ZERO)


def contributed_between(user_id: UUID, start: date, end: date) -> Decimal:
    total = db.session.scalar(
        sa.select(sa.func.sum(GoalContribution.amount)).where(
            GoalContribution.user_id == user_id,
            GoalContribution.contributed_on.between(start, end),
        )
    ) or ZERO
    return max(ZERO, total)


def planned_monthly(user_id: UUID) -> Decimal:
    return sum(
        (i.goal.monthly_amount or ZERO for i in user_items(user_id)
         if is_open(i) and saved_of(i) < i.goal.target_amount),
        ZERO,
    )


def _pace(item: WishlistItem, today: date) -> Decimal | None:
    """Valor mensal definido ou, sem ele, a média guardada nos últimos meses."""
    if item.goal.monthly_amount:
        return item.goal.monthly_amount
    recent = sum(
        (c.amount for c in item.goal.contributions
         if c.contributed_on >= today - timedelta(days=AVERAGE_DAYS)),
        ZERO,
    )
    return recent / AVERAGE_MONTHS if recent > 0 else None


def forecast(item: WishlistItem, today: date) -> dict:
    remaining = item.goal.target_amount - saved_of(item)
    if remaining <= 0:
        return {"months": 0, "month": today.strftime("%Y-%m")}
    pace = _pace(item, today)
    if pace is None:
        return {"months": None, "month": None}
    months = int((remaining / pace).to_integral_value(rounding=ROUND_CEILING))
    year, month = shift_month(today.year, today.month, months)
    return {"months": months, "month": f"{year:04d}-{month:02d}"}


def indicators(items: list[WishlistItem], today: date) -> dict:
    active = [i for i in items if is_open(i)]
    # Próxima compra: a que chega primeiro à meta; empate fica para a maior prioridade.
    timed = [(forecast(i, today)["months"], i.priority, i) for i in active]
    timed = [row for row in timed if row[0] is not None]
    upcoming = min(timed, key=lambda row: row[:2])[2] if timed else None
    return {
        "total_value": sum((i.price for i in active), ZERO),
        "total_saved": sum((saved_of(i) for i in active), ZERO),
        "count": len(active),
        "completed": sum(1 for i in items if i.status == "bought"),
        "next_purchase": upcoming.name if upcoming else None,
    }


def reached_goals(user_id: UUID) -> list[WishlistItem]:
    return [
        i for i in user_items(user_id)
        if is_open(i) and saved_of(i) >= i.goal.target_amount
    ]
