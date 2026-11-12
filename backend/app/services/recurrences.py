"""
Geração de lançamentos recorrentes.

A geração é idempotente: roda antes de cada leitura, compara com o que já existe
e a constraint (recurrence_id, occurrence_date) impede duplicar em requisições paralelas.

Uma regra com cartão gera compras na fatura em vez de lançamentos na conta: a despesa
conta uma vez, pela fatura, e o pagamento da fatura tira o dinheiro da conta.
"""
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from ..extensions import db
from ..models import (
    CardPurchase, Installment, Recurrence, RecurrenceAmount, RecurrenceSkip, Transaction,
)
from . import cards
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
        if rec.card_id and not rec.card.active:
            continue  # cartão desativado não recebe compras novas
        # Ocorrências já criadas como lançamento ou compra contam: trocar a regra entre
        # conta e cartão não recria meses que já existem do outro jeito.
        existing = db.session.scalars(
            sa.select(Transaction.occurrence_date).where(Transaction.recurrence_id == rec.id)
            .union_all(
                sa.select(CardPurchase.occurrence_date).where(CardPurchase.recurrence_id == rec.id)
            )
        ).all()
        taken = {period_key(rec, d) for d in existing}
        taken |= {period_key(rec, s.occurrence_date) for s in rec.skips}

        for day in occurrences(rec, until):
            if period_key(rec, day) in taken:
                continue
            if rec.card_id:
                created += _card_purchase(rec, day)
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


def _card_purchase(rec: Recurrence, day: date) -> int:
    """Compra à vista na fatura que recebe o dia da ocorrência."""
    amount = amount_for(rec, day)
    others = min(rec.others_amount or Decimal("0.00"), amount)  # o valor pode ter baixado
    purchase_id = db.session.scalar(
        insert(CardPurchase).values(
            id=db.func.gen_random_uuid(), user_id=rec.user_id, card_id=rec.card_id,
            category_id=rec.category_id, description=rec.name, total_amount=amount,
            others_amount=others,
            purchase_date=day, installment_count=1, recurrence_id=rec.id, occurrence_date=day,
            created_at=db.func.now(), updated_at=db.func.now(),
        ).on_conflict_do_nothing(index_elements=["recurrence_id", "occurrence_date"])
        .returning(CardPurchase.id)
    )
    if purchase_id is None:
        return 0
    invoice = cards.get_invoice(rec.card, cards.invoice_month_for(rec.card, day))
    db.session.add(Installment(
        user_id=rec.user_id, purchase_id=purchase_id, number=1,
        amount=amount, others_amount=others, invoice_id=invoice.id,
    ))
    db.session.flush()
    return 1


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
    Compras no cartão em fatura ainda sem pagamento são refeitas pela próxima geração.
    """
    _remove_purchases(rec, start)
    if rec.card_id:
        for tx in pending_from(rec, start):
            db.session.delete(tx)
        return
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
    _remove_purchases(rec, start)


def _remove_purchases(rec: Recurrence, start: date) -> None:
    """Compras geradas a partir de `start`, exceto as de fatura que já recebeu pagamento."""
    purchases = db.session.scalars(
        sa.select(CardPurchase).where(
            CardPurchase.recurrence_id == rec.id, CardPurchase.occurrence_date >= start,
        )
    ).all()
    touched = set()
    for purchase in purchases:
        if not cards.has_paid_invoice(purchase):
            touched.add(purchase.card_id)
            db.session.delete(purchase)
    if touched:
        db.session.flush()
        for card_id in touched:
            cards.remove_empty_invoices(card_id)


def skip_occurrence(tx: Transaction) -> None:
    """Chamado ao apagar uma ocorrência gerada, para ela não reaparecer."""
    if tx.recurrence_id and tx.occurrence_date:
        db.session.execute(
            insert(RecurrenceSkip).values(
                id=db.func.gen_random_uuid(), recurrence_id=tx.recurrence_id,
                occurrence_date=tx.occurrence_date,
            ).on_conflict_do_nothing()
        )
