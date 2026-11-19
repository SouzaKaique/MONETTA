"""
Importação da fatura do cartão a partir do arquivo do banco (OFX ou o CSV do Nubank).

Cada linha da fatura corresponde a uma parcela na fatura do MONETTA. A prévia compara as
duas coisas: o que já existe (lançado à mão, gasto fixo ou parcela de compra antiga) é
ligado à parcela, e só o resto vira compra nova. A linha ligada ganha um identificador,
então importar o mesmo arquivo de novo não duplica nada.
"""
import csv
import hashlib
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

import sqlalchemy as sa

from ..extensions import db
from ..models import CardPurchase, Category, CreditCard, Installment, Invoice
from . import cards
from .periods import clamp_day, shift_month

MAX_BYTES = 1024 * 1024
MAX_ENTRIES = 1000
CENTS = Decimal("0.05")  # parcelas do banco podem diferir do MONETTA por arredondamento

INSTALLMENT = re.compile(r"\s*-\s*Parcela\s+(\d{1,2})\s*/\s*(\d{1,2})\s*$", re.I)
NUPAY = re.compile(r"\s*-\s*NuPay\s*$", re.I)
PAYMENT = re.compile(r"pagamento recebido|pagamento de fatura|pagamento efetuado", re.I)

# Palavras que sugerem a categoria quando a descrição ainda não apareceu antes.
KEYWORDS = [
    ("Transporte", ["uber", "99app", "99 pop", "99pop", "posto", "combustiv", "ipiranga", "shell",
                    "estacionamento", "pedagio", "sem parar", "metro", "onibus"]),
    ("Assinaturas", ["spotify", "netflix", "apple.com", "youtube", "prime video", "disney", "hbo",
                     "max.com", "claude", "anthropic", "openai", "chatgpt", "icloud", "deezer",
                     "google one", "google storage"]),
    ("Saúde", ["drogaria", "drogasil", "raia", "farmac", "pague menos", "dent", "clinica",
               "laborat", "unimed", "hospital", "otica"]),
    ("Alimentação", ["ifood", "restaurante", "lanche", "acai", "pizza", "burger", "mcdonald",
                     "arcos dourados", "padaria", "confeit", "supermerc", "mercado ", "milky",
                     "cafe", "feijo", "subway", "habib", "sorvete", "doceria", "hortifruti"]),
    ("Lazer", ["bar ", " bar", "boteco", "chopp", "cinema", "ingresso", "sympla", "steam",
               "playstation", "xbox", "nintendo", "show"]),
    ("Compras", ["americanas", "shopee", "mercado livre", "mercadolivre", "amazon", "magalu",
                 "magazine", "aliexpress", "shein", "renner", "riachuelo", "c&a", "mp *",
                 "kabum", "centauro", "netshoes", "hausport", "adidas", "nike", "fila"]),
    ("Educação", ["udemy", "alura", "curso", "livraria", "escola", "faculdade"]),
]


def brl(value: Decimal) -> str:
    return "R$ " + f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


class ImportProblem(Exception):
    """Arquivo que não dá para ler; a mensagem é mostrada ao usuário."""


@dataclass
class Entry:
    external_id: str
    posted: date
    memo: str
    amount: Decimal  # sempre positivo
    credit: bool
    number: int = 1
    count: int = 1
    description: str = ""
    status: str = "new"
    note: str | None = None
    installment: Installment | None = None
    category_id: UUID | None = None
    extra: dict = field(default_factory=dict)


# Leitura do arquivo

def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _tag(block: str, name: str) -> str | None:
    match = re.search(rf"<{name}>([^<\r\n]*)", block, re.I)
    return match.group(1).strip() if match else None


def _ofx_date(raw: str | None) -> date | None:
    if not raw or len(raw) < 8 or not raw[:8].isdigit():
        return None
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        return None


def _money(raw: str) -> Decimal:
    text = raw.strip().replace("R$", "").replace(" ", "")
    if "," in text:  # formato brasileiro: 1.234,56
        text = text.replace(".", "").replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ImportProblem("Há um valor que não consegui ler no arquivo.") from None
    if not value.is_finite() or abs(value) > Decimal("999999999.99"):
        raise ImportProblem("Há um valor inválido no arquivo.")
    return value.quantize(Decimal("0.01"))


def _hash(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:40]


def _with_ids(rows: list[tuple]) -> list[Entry]:
    """Linhas iguais no mesmo arquivo (duas corridas de mesmo valor) ganham ids diferentes."""
    seen: Counter = Counter()
    entries = []
    for kind, fitid, posted, memo, value in rows:
        key = (kind, fitid, posted, memo, value)
        seen[key] += 1
        entries.append(Entry(
            external_id=_hash(kind, fitid, posted.isoformat(), memo, value, seen[key]),
            posted=posted, memo=memo, amount=abs(value), credit=value > 0 if kind == "ofx" else value < 0,
        ))
    return entries


def parse(data: bytes) -> tuple[list[Entry], date | None]:
    """Lê OFX (o arquivo "OFX" do banco) ou o CSV do Nubank. Devolve as linhas e o fim do período."""
    if len(data) > MAX_BYTES:
        raise ImportProblem("O arquivo passa de 1 MB.")
    text = _decode(data)
    if "<OFX>" in text.upper() or "OFXHEADER" in text.upper():
        rows = []
        for block in re.findall(r"<STMTTRN>(.*?)(?=</STMTTRN>|<STMTTRN>|</BANKTRANLIST>)", text, re.S | re.I):
            posted = _ofx_date(_tag(block, "DTPOSTED"))
            amount = _tag(block, "TRNAMT")
            memo = _tag(block, "MEMO") or _tag(block, "NAME") or ""
            if posted is None or not amount:
                continue
            rows.append(("ofx", _tag(block, "FITID") or "", posted, memo.strip(), _money(amount)))
        period_end = _ofx_date(_tag(text, "DTEND"))
    else:
        reader = csv.DictReader(io.StringIO(text))
        fields = {(name or "").strip().lower() for name in (reader.fieldnames or [])}
        if not {"date", "title", "amount"} <= fields:
            raise ImportProblem("Formato não reconhecido. Use o arquivo OFX ou o CSV exportado pelo app do Nubank.")
        rows = []
        for line in reader:
            line = {(k or "").strip().lower(): (v or "").strip() for k, v in line.items()}
            try:
                posted = date.fromisoformat(line["date"])
            except ValueError:
                raise ImportProblem("Há uma data que não consegui ler no arquivo.") from None
            if line["title"] and line["amount"]:
                rows.append(("csv", "", posted, line["title"], _money(line["amount"])))
        period_end = None
    if not rows:
        raise ImportProblem("Não encontrei lançamentos no arquivo.")
    if len(rows) > MAX_ENTRIES:
        raise ImportProblem("O arquivo tem lançamentos demais.")
    entries = _with_ids(rows)
    for entry in entries:
        _describe(entry)
    return entries, period_end


def _describe(entry: Entry) -> None:
    text = entry.memo
    match = INSTALLMENT.search(text)
    if match:
        number, count = int(match.group(1)), int(match.group(2))
        if 1 <= number <= count <= 48:
            entry.number, entry.count = number, count
        text = text[:match.start()]
    text = NUPAY.sub("", text).strip()
    if len(text) > 3 and text.isupper():
        text = text.title()
    entry.description = text[:160] or "Compra"


# Comparação

def normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", plain)


def similar(a: str, b: str) -> bool:
    na, nb = normalize(a), normalize(b)
    if len(na) < 3 or len(nb) < 3:
        return na == nb and bool(na)
    return na in nb or nb in na or (len(na) >= 6 and len(nb) >= 6 and na[:6] == nb[:6])


def default_month(card: CreditCard, entries: list[Entry], period_end: date | None) -> date:
    """Mês de vencimento da fatura do arquivo: pelo fim do período ou pelas compras."""
    if period_end:
        return cards.invoice_month_for(card, period_end - timedelta(days=1))
    months = Counter(cards.invoice_month_for(card, e.posted) for e in entries if not e.credit and e.count == 1)
    if not months:
        months = Counter(cards.invoice_month_for(card, e.posted) for e in entries)
    return months.most_common(1)[0][0]


def _invoice_items(card: CreditCard, month: date) -> list[Installment]:
    return list(db.session.scalars(
        sa.select(Installment).join(Invoice, Installment.invoice_id == Invoice.id)
        .where(Invoice.card_id == card.id, Invoice.reference_month == month)
        .order_by(Installment.id)
    ))


def _suggestions(user_id: UUID) -> tuple[dict[str, UUID], dict[str, UUID]]:
    """Categoria já usada para a mesma descrição e categorias do usuário por nome."""
    history: dict[str, UUID] = {}
    rows = db.session.execute(
        sa.select(CardPurchase.description, CardPurchase.category_id)
        .where(CardPurchase.user_id == user_id, CardPurchase.category_id.is_not(None))
        .order_by(CardPurchase.created_at)
    ).all()
    for description, category_id in rows:
        history[normalize(INSTALLMENT.sub("", description))] = category_id  # a mais recente vence
    names = {
        c.name: c.id for c in db.session.scalars(
            sa.select(Category).where(Category.user_id == user_id, Category.kind == "expense")
        )
    }
    return history, names


def _suggest(entry: Entry, history: dict, names: dict) -> UUID | None:
    key = normalize(entry.description)
    if key in history:
        return history[key]
    plain = " " + unicodedata.normalize("NFKD", entry.memo).encode("ascii", "ignore").decode().lower() + " "
    for category, words in KEYWORDS:
        if category in names and any(w in plain for w in words):
            return names[category]
    return None


def _same(entry: Entry, item: Installment) -> bool:
    """A linha da fatura é esta parcela?"""
    purchase = item.purchase
    if entry.count == 1 and purchase.installment_count == 1:
        if item.amount != entry.amount:
            return False
        return purchase.purchase_date == entry.posted or similar(purchase.description, entry.description)
    if purchase.installment_count != entry.count or item.number != entry.number:
        return False
    if abs(item.amount - entry.amount) > CENTS:
        return False
    return similar(purchase.description, entry.description) or (
        entry.number == 1 and purchase.purchase_date == entry.posted
    )


def match(user_id: UUID, card: CreditCard, entries: list[Entry], month: date) -> list[Installment]:
    """Marca cada linha e devolve as parcelas da fatura que não apareceram no arquivo."""
    used_ids = {
        row[0]: row[1] for row in db.session.execute(
            sa.select(Installment.external_id, Installment.id)
            .where(Installment.user_id == user_id, Installment.external_id.is_not(None))
        )
    }
    items = _invoice_items(card, month)
    free = {item.id: item for item in items}
    by_id = {item.id: item for item in items}
    debits = []

    for entry in entries:
        if entry.credit:
            if PAYMENT.search(entry.memo):
                entry.status, entry.note = "payment", "Pagamento de fatura anterior: não é compra."
            else:
                entry.status = "credit"
                entry.note = "Estorno ou crédito: não é importado. Se devolveram uma compra, ajuste-a."
            continue
        if entry.external_id in used_ids:
            entry.status, entry.note = "imported", "Já importada antes."
            item = by_id.get(used_ids[entry.external_id])
            if item is not None:
                free.pop(item.id, None)
            continue
        debits.append(entry)

    def claim(entry: Entry, item: Installment, status: str, note: str | None = None) -> None:
        entry.status, entry.installment, entry.note = status, item, note
        free.pop(item.id, None)

    # 1. Mesma compra: valor, parcela e data ou nome.
    for entry in debits:
        found = next((i for i in free.values() if not i.purchase.recurrence_id and _same(entry, i)), None)
        if found:
            note = None
            if found.amount != entry.amount:
                note = f"Valor ajustado de {brl(found.amount)} para o da fatura."
            claim(entry, found, "existing", note)
    # 2. Gasto fixo: mesmo valor, ou nome parecido com valor diferente.
    pending = [e for e in debits if e.status == "new"]
    for entry in pending:
        found = next((i for i in free.values() if i.purchase.recurrence_id and i.amount == entry.amount), None)
        if found:
            claim(entry, found, "fixed", f"Gasto fixo {found.purchase.description}.")
    for entry in [e for e in pending if e.status == "new"]:
        found = next((i for i in free.values()
                      if i.purchase.recurrence_id and similar(i.purchase.description, entry.description)), None)
        if found:
            diff = found.amount - entry.amount
            entry.extra["diff"] = diff
            claim(entry, found, "fixed",
                  f"Gasto fixo {found.purchase.description}: no MONETTA está {brl(found.amount)}.")
    # 3. IOF que já está somado no valor de um gasto fixo (assinatura em dólar).
    fixed_diffs = [e for e in debits if e.status == "fixed" and e.extra.get("diff", 0) > 0]
    for entry in [e for e in debits if e.status == "new" and normalize(e.description).startswith("iof")]:
        owner = next((f for f in fixed_diffs if f.extra["diff"] == entry.amount), None)
        if owner:
            entry.status = "included"
            entry.note = f"Já somado no gasto fixo {owner.installment.purchase.description}."
            fixed_diffs.remove(owner)
    return list(free.values())


def preview(user_id: UUID, card: CreditCard, data: bytes, month: date | None) -> dict:
    entries, period_end = parse(data)
    target = month or default_month(card, entries, period_end)
    missing = match(user_id, card, entries, target)
    history, names = _suggestions(user_id)
    for entry in entries:
        if entry.status == "new":
            entry.category_id = _suggest(entry, history, names)
    closing, due = cards.invoice_dates(card, target)
    invoice = db.session.scalar(sa.select(Invoice).filter_by(card_id=card.id, reference_month=target))
    return {
        "month": target.strftime("%Y-%m"),
        "closing_date": closing.isoformat(),
        "due_date": due.isoformat(),
        "invoice_total": cards.invoice_total(invoice) if invoice else Decimal("0.00"),
        "file_total": sum((e.amount for e in entries if not e.credit), Decimal("0.00")),
        "rows": [_row(e) for e in entries],
        "missing": [{
            "installment_id": str(i.id), "description": i.purchase.description, "amount": i.amount,
            "date": i.purchase.purchase_date.isoformat(), "fixed": i.purchase.recurrence_id is not None,
            "number": i.number, "count": i.purchase.installment_count,
        } for i in missing],
    }


def _row(entry: Entry) -> dict:
    return {
        "external_id": entry.external_id, "date": entry.posted.isoformat(), "memo": entry.memo,
        "description": entry.description, "amount": entry.amount, "number": entry.number,
        "count": entry.count, "status": entry.status, "note": entry.note,
        "installment_id": str(entry.installment.id) if entry.installment else None,
        "category_id": str(entry.category_id) if entry.category_id else None,
    }


# Gravação

def create(user_id: UUID, card: CreditCard, month: date, row: dict) -> Installment:
    """Compra nova. Parcela N de M entra com as anteriores já pagas, como se viesse de antes."""
    number, count, amount = row["number"], row["count"], row["amount"]
    back = number - 1
    year, mon = shift_month(row["date"].year, row["date"].month, -back)
    purchase = CardPurchase(
        user_id=user_id, card=card, category_id=row["category_id"], description=row["description"].strip(),
        total_amount=amount * count, purchase_date=clamp_day(year, mon, row["date"].day),
        installment_count=count,
    )
    db.session.add(purchase)
    db.session.flush()
    first_year, first_month = shift_month(month.year, month.month, -back)
    cards.create_installments(purchase, date(first_year, first_month, 1), back)
    item = purchase.installments[number - 1]
    item.external_id = row["external_id"]
    return item


def link(item: Installment, external_id: str, amount: Decimal | None) -> None:
    """Liga a linha à parcela existente e corrige diferença de centavos da compra lançada à mão."""
    if item.external_id is None:
        item.external_id = external_id
    purchase = item.purchase
    if (amount is not None and amount != item.amount and abs(amount - item.amount) <= CENTS
            and purchase.recurrence_id is None and not cards.has_paid_invoice(purchase)):
        purchase.total_amount += amount - item.amount
        item.amount = amount
        item.others_amount = min(item.others_amount, amount)
        purchase.others_amount = min(purchase.others_amount, purchase.total_amount)
