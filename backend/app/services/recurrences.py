"""
Geração de lançamentos recorrentes.

A geração é idempotente: roda antes de cada leitura, compara com o que já existe
e a constraint (recurrence_id, occurrence_date) impede duplicar em requisições paralelas.
"""
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from ..extensions import db
from ..models import Recurrence, RecurrenceAmount, RecurrenceSkip, Transaction
from .periods import clamp_day, month_bounds, shift_month

MAX_MONTHS_AHEAD = 24


def occurrences(rec: Recurrence, until: date) -> Iterator[date]:
    """Datas da regra entre generate_from e `until`, respeitando end_date."""
    last = min(until, rec.end_date) if rec.end_date else until
    first = rec.generate_from

    if rec.frequency in ("weekly", "biweekly"):
        step = timedelta(days=7 if rec.frequency == "weekly" else 14)
        current = rec.start_date
        while current <= last:
            if current >= first:
                yield current
            current += step
    elif rec.frequency == "monthly":
        year, month = first.year, first.month
        while date(year, month, 1) <= last:
            current = clamp_day(year, month, rec.day_of_month)
            if first <= current <= last:
                yield current
            year, month = shift_month(year, month, 1)
    else:  # yearly
        year = rec.start_date.year
        while date(year, 1, 1) <= last:
            current = clamp_day(year, rec.start_date.month, rec.start_date.day)
            if first <= current <= last:
                yield current
            year += 1


def period_key(rec: Recurrence, day: date) -> tuple:
    """
    Identifica a ocorrência pelo período. Assim, mudar o dia de pagamento de uma
    regra mensal não recria o mês que já existe em outra data.
    """
    if rec.frequency == "monthly":
        return (day.year, day.month)
    if rec.frequency == "yearly":
        return (day.year,)
    return (day,)


def amount_for(rec: Recurrence, day: date) -> Decimal:
    """Último valor em vigor no mês da ocorrência."""
    month_start = day.replace(day=1)
    valid = [a for a in rec.amounts if a.effective_from <= month_start]
    return (valid[-1] if valid else rec.amounts[0]).amount


def generate(user_id: UUID, until: date) -> int:
    """Cria as ocorrências que faltam até `until`; retorna quantas foram criadas."""
    rules = db.session.scalars(
        sa.select(Recurrence).where(Recurrence.user_id == user_id, Recurrence.active)
    ).all()
    created = 0
    for rec in rules:
        existing = db.session.scalars(
            sa.select(Transaction.occurrence_date).where(Transaction.recurrence_id == rec.id)
        ).all()
        taken = {period_key(rec, d) for d in existing}
        taken |= {period_key(rec, s.occurrence_date) for s in rec.skips}

        for day in occurrences(rec, until):
            if period_key(rec, day) in taken:
                continue
            result = db.session.execute(
                insert(Transaction).values(
                    id=db.func.gen_random_uuid(), user_id=user_id, account_id=rec.account_id,
                    category_id=rec.category_id, recurrence_id=rec.id, occurrence_date=day,
                    kind=rec.kind, status="pending", is_salary=rec.is_salary, is_fixed=True,
                    amount_overridden=False, description=rec.name, amount=amount_for(rec, day),
                    competence_date=day, payment_method=rec.payment_method,
                    created_at=db.func.now(), updated_at=db.func.now(),
                ).on_conflict_do_nothing(index_elements=["recurrence_id", "occurrence_date"])
            )
            created += result.rowcount
    if created:
        db.session.commit()
    return created


def generation_horizon(today: date, requested: date | None = None) -> date:
    """Sempre cobre o mês seguinte; meses mais distantes só quando consultados."""
    year, month = shift_month(today.year, today.month, 1)
    horizon = month_bounds(year, month)[1]
    limit = month_bounds(*shift_month(today.year, today.month, MAX_MONTHS_AHEAD))[1]
    return min(max(horizon, requested or horizon), limit)


def pending_from(rec: Recurrence, start: date) -> list[Transaction]:
    return list(db.session.scalars(
        sa.select(Transaction).where(
            Transaction.recurrence_id == rec.id,
            Transaction.status == "pending",
            Transaction.occurrence_date >= start,
        )
    ))


def set_amount(rec: Recurrence, amount: Decimal, effective_from: date) -> None:
    """Registra um valor a partir de um mês, reescrevendo se esse mês já tiver valor."""
    version = next((a for a in rec.amounts if a.effective_from == effective_from), None)
    if version:
        version.amount = amount
    else:
        rec.amounts.append(RecurrenceAmount(amount=amount, effective_from=effective_from))
        rec.amounts.sort(key=lambda a: a.effective_from)


def sync_pending(rec: Recurrence, start: date) -> None:
    """
    Leva a mudança da regra às ocorrências pendentes a partir de `start`.
    Confirmadas nunca mudam: são histórico. Editadas à mão mantêm o valor.
    """
    for tx in pending_from(rec, start):
        if rec.frequency == "monthly":
            moved = clamp_day(tx.occurrence_date.year, tx.occurrence_date.month, rec.day_of_month)
            tx.occurrence_date = tx.competence_date = moved
        tx.category_id = rec.category_id
        tx.account_id = rec.account_id
        tx.payment_method = rec.payment_method
        if not tx.amount_overridden:
            tx.description = rec.name
            tx.amount = amount_for(rec, tx.occurrence_date)


def remove_pending(rec: Recurrence, start: date) -> None:
    for tx in pending_from(rec, start):
        db.session.delete(tx)


def skip_occurrence(tx: Transaction) -> None:
    """Chamado ao apagar uma ocorrência gerada, para ela não reaparecer."""
    if tx.recurrence_id and tx.occurrence_date:
        db.session.execute(
            insert(RecurrenceSkip).values(
                id=db.func.gen_random_uuid(), recurrence_id=tx.recurrence_id,
                occurrence_date=tx.occurrence_date,
            ).on_conflict_do_nothing()
        )
