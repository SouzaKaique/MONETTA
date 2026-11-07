"""Exportação em CSV, pronta para abrir no Excel em português."""
import csv
import io
from datetime import date
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import CardPurchase, Debt, DebtPayment, Invoice, Transaction, Transfer
from . import cards, debts, wishlist

STATUS = {"pending": "Pendente", "confirmed": "Confirmado"}
KIND = {"income": "Receita", "expense": "Despesa"}
# Planilhas executam células que começam com estes caracteres.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value: str | None) -> str:
    """Impede que um texto vire fórmula ao abrir o arquivo."""
    text = value or ""
    return f"'{text}" if text.startswith(FORMULA_PREFIXES) else text


def money(value: Decimal | None) -> str:
    return "" if value is None else f"{value:.2f}".replace(".", ",")


def day(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def _in_range(column, start: date | None, end: date | None) -> list:
    filters = []
    if start:
        filters.append(column >= start)
    if end:
        filters.append(column <= end)
    return filters


def transactions(user_id: UUID, start: date | None, end: date | None) -> tuple[list, list]:
    rows = db.session.scalars(
        sa.select(Transaction)
        .options(joinedload(Transaction.category), joinedload(Transaction.account))
        .where(Transaction.user_id == user_id, *_in_range(Transaction.competence_date, start, end))
        .order_by(Transaction.competence_date)
    ).all()
    header = ["Data", "Tipo", "Descrição", "Categoria", "Conta", "Valor", "Situação", "Pago em", "Fixa"]
    return header, [[
        day(t.competence_date), KIND[t.kind], safe_text(t.description),
        safe_text(t.category.name if t.category else ""), safe_text(t.account.name if t.account else ""),
        money(t.amount), STATUS[t.status], day(t.paid_on), "Sim" if t.is_fixed else "Não",
    ] for t in rows]


def card_purchases(user_id: UUID, start: date | None, end: date | None) -> tuple[list, list]:
    rows = db.session.scalars(
        sa.select(CardPurchase)
        .options(joinedload(CardPurchase.card), joinedload(CardPurchase.category))
        .where(CardPurchase.user_id == user_id, *_in_range(CardPurchase.purchase_date, start, end))
        .order_by(CardPurchase.purchase_date)
    ).all()
    header = ["Data", "Descrição", "Cartão", "Categoria", "Valor total", "Parcelas"]
    return header, [[
        day(p.purchase_date), safe_text(p.description), safe_text(p.card.name),
        safe_text(p.category.name if p.category else ""), money(p.total_amount), p.installment_count,
    ] for p in rows]


def invoices(user_id: UUID, start: date | None, end: date | None) -> tuple[list, list]:
    rows = db.session.scalars(
        sa.select(Invoice).options(joinedload(Invoice.card))
        .where(Invoice.user_id == user_id, *_in_range(Invoice.due_date, start, end))
        .order_by(Invoice.due_date)
    ).unique().all()
    header = ["Cartão", "Fechamento", "Vencimento", "Total", "Pago", "Restante"]
    data = []
    for invoice in rows:
        total, paid = cards.invoice_total(invoice), cards.invoice_paid(invoice)
        data.append([
            safe_text(invoice.card.name), day(invoice.closing_date), day(invoice.due_date),
            money(total), money(paid), money(total - paid),
        ])
    return header, data


def debt_list(user_id: UUID, start: date | None, end: date | None) -> tuple[list, list]:
    labels = {"pending": "Pendente", "in_payment": "Em pagamento", "paid": "Quitada"}
    header = ["Dívida", "Credor", "Valor original", "Total pago", "Saldo", "Situação", "Vencimento"]
    return header, [[
        safe_text(d.name), safe_text(d.creditor), money(d.original_amount), money(debts.total_paid(d)),
        money(debts.balance_of(d)), labels[debts.status_of(d)], day(d.due_date),
    ] for d in debts.user_debts(user_id)]


def debt_payments(user_id: UUID, start: date | None, end: date | None) -> tuple[list, list]:
    rows = db.session.execute(
        sa.select(DebtPayment, Debt.name).join(Debt)
        .where(DebtPayment.user_id == user_id, *_in_range(DebtPayment.paid_on, start, end))
        .order_by(DebtPayment.paid_on)
    ).all()
    header = ["Data", "Dívida", "Valor", "Conta", "Descrição"]
    return header, [[
        day(p.paid_on), safe_text(name), money(p.amount),
        safe_text(p.account.name if p.account else ""), safe_text(p.description),
    ] for p, name in rows]


def transfers(user_id: UUID, start: date | None, end: date | None) -> tuple[list, list]:
    rows = db.session.scalars(
        sa.select(Transfer).where(Transfer.user_id == user_id, *_in_range(Transfer.date, start, end))
        .order_by(Transfer.date)
    ).all()
    header = ["Data", "De", "Para", "Valor"]
    return header, [[
        day(t.date), safe_text(t.from_account.name), safe_text(t.to_account.name), money(t.amount),
    ] for t in rows]


def wishlist_items(user_id: UUID, start: date | None, end: date | None) -> tuple[list, list]:
    labels = {"desired": "Desejado", "planning": "Planejando", "saving": "Economizando",
              "bought": "Comprado", "given_up": "Desistido"}
    header = ["Item", "Preço", "Guardado", "Meta", "Situação", "Incluído em"]
    return header, [[
        safe_text(i.name), money(i.price), money(wishlist.saved_of(i)), money(i.goal.target_amount),
        labels[i.status], day(i.added_on),
    ] for i in wishlist.user_items(user_id)]


DATASETS = {
    "lancamentos": transactions, "compras-cartao": card_purchases, "faturas": invoices,
    "dividas": debt_list, "pagamentos-dividas": debt_payments, "transferencias": transfers,
    "wishlist": wishlist_items,
}


def render(header: list, rows: list) -> str:
    """Ponto e vírgula e BOM: é o que o Excel em português abre sem assistente."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return "﻿" + buffer.getvalue()
