"""Cartões: datas de fatura, parcelas e a regra de não contar a mesma despesa duas vezes."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api import finance_common
from app.extensions import db
from app.models import Installment, Invoice
from app.services import cards as service
from app.services import dashboard as dash

from .conftest import register

CLOCK = {"today": date(2026, 3, 15)}
WEB = {"X-Monetta-Client": "web"}


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    CLOCK["today"] = date(2026, 3, 15)
    monkeypatch.setattr(dash, "today_for", lambda settings: CLOCK["today"])
    monkeypatch.setattr(finance_common, "today_for", lambda settings: CLOCK["today"])


@pytest.fixture()
def setup(client):
    register(client)
    account = client.post("/api/accounts", json={
        "name": "Conta", "opening_balance": "5000.00", "opening_date": "2026-01-01",
    }).json
    card = new_card(client)
    return SimpleNamespace(account=account, card=card)


def new_card(client, closing=20, due=28, limit="3000.00", name="Nubank"):
    res = client.post("/api/cards", json={
        "name": name, "credit_limit": limit, "closing_day": closing, "due_day": due,
    })
    assert res.status_code == 201, res.json
    return res.json


def buy(client, card, amount="900.00", count=6, day="2026-03-10", **extra):
    return client.post(f"/api/cards/{card['id']}/purchases", json={
        "description": "Compra", "total_amount": amount, "installment_count": count,
        "purchase_date": day, **extra,
    })


def invoices(client, card):
    return client.get(f"/api/cards/{card['id']}").json["invoices"]


def by_month(client, card):
    return {i["month"]: i for i in invoices(client, card)}


def pay(client, invoice, account, amount, paid_on="2026-03-15", **kwargs):
    return client.post(f"/api/invoices/{invoice['id']}/payments", json={
        "amount": amount, "paid_on": paid_on, "account_id": account["id"],
    }, **kwargs)


def summary(client, month="2026-03"):
    return client.get(f"/api/dashboard?month={month}").json["summary"]


# Datas

def fake_card(closing, due):
    return SimpleNamespace(closing_day=closing, due_day=due)


@pytest.mark.parametrize("closing,due,day,expected", [
    (20, 28, date(2026, 3, 19), date(2026, 3, 1)),  # véspera do fechamento ainda entra
    (20, 28, date(2026, 3, 20), date(2026, 4, 1)),  # no dia do fechamento já vai para a seguinte
    (20, 28, date(2026, 3, 21), date(2026, 4, 1)),
    (1, 8, date(2026, 11, 1), date(2026, 12, 1)),   # Nubank: compra do dia 1 vence no dia 8 seguinte
    (1, 8, date(2026, 10, 31), date(2026, 11, 1)),
    (25, 5, date(2026, 3, 10), date(2026, 4, 1)),   # vence no mês depois do fechamento
    (25, 5, date(2026, 3, 26), date(2026, 5, 1)),
    (31, 10, date(2026, 2, 27), date(2026, 3, 1)),  # dia 31 em fevereiro fecha no dia 28
    (31, 10, date(2026, 2, 28), date(2026, 4, 1)),
    (20, 28, date(2026, 12, 25), date(2027, 1, 1)),  # virada do ano
])
def test_compra_cai_na_fatura_certa(closing, due, day, expected):
    assert service.invoice_month_for(fake_card(closing, due), day) == expected


def test_datas_da_fatura():
    assert service.invoice_dates(fake_card(25, 5), date(2026, 4, 1)) == (date(2026, 3, 25), date(2026, 4, 5))
    assert service.invoice_dates(fake_card(31, 10), date(2026, 3, 1)) == (date(2026, 2, 28), date(2026, 3, 10))


# Parcelas

@pytest.mark.parametrize("total,count,expected", [
    ("900.00", 6, ["150.00"] * 6),
    ("1000.00", 3, ["333.34", "333.33", "333.33"]),
    ("100.00", 3, ["33.34", "33.33", "33.33"]),
    ("0.05", 2, ["0.03", "0.02"]),
])
def test_parcelas_somam_exatamente_o_total(total, count, expected):
    parts = service.split_installments(Decimal(total), count)
    assert [str(p) for p in parts] == expected
    assert sum(parts) == Decimal(total)


def test_exemplo_da_especificacao_seis_parcelas_em_seis_faturas(client, setup):
    assert buy(client, setup.card).status_code == 201
    rows = by_month(client, setup.card)
    assert sorted(rows) == ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    assert all(i["total"] == "150.00" for i in rows.values())


def test_parcelas_comprometem_meses_futuros(client, setup):
    buy(client, setup.card)
    assert summary(client, "2026-06")["card_commitment"] == "150.00"
    assert summary(client, "2026-06")["expenses_total"] == "150.00"
    assert summary(client, "2026-09")["card_commitment"] == "0.00"


def test_parcelas_ja_pagas_ficam_fora_de_fatura_e_limite(client, setup):
    res = buy(client, setup.card, "1200.00", 12, "2025-10-05", already_paid=5)
    assert res.status_code == 201
    rows = invoices(client, setup.card)
    assert len(rows) == 7 and rows[0]["month"] == "2026-03"
    assert client.get("/api/cards").json[0]["used"] == "700.00"
    assert all(r["status"] != "overdue" for r in rows)
    assert db.session.scalar(
        db.select(db.func.count()).select_from(Installment).where(Installment.invoice_id.is_(None))
    ) == 5


def test_nao_aceita_todas_as_parcelas_pagas(client, setup):
    assert buy(client, setup.card, count=3, already_paid=3).status_code == 422


def test_fatura_pode_ser_escolhida(client, setup):
    buy(client, setup.card, "100.00", 1, first_month="2026-04")
    assert list(by_month(client, setup.card)) == ["2026-04"]


def test_compra_futura_e_cartao_inativo(client, setup):
    assert buy(client, setup.card, day="2026-03-20").status_code == 422
    client.patch(f"/api/cards/{setup.card['id']}", json={"active": False})
    assert buy(client, setup.card).status_code == 409


# Integridade financeira

def test_compra_nao_altera_saldo_ate_o_pagamento(client, setup):
    buy(client, setup.card, "300.00", 1)
    s = summary(client)
    assert s["balance"] == "5000.00"
    assert s["open_invoices"] == "300.00"
    assert s["available_to_spend"] == "4700.00"


def test_pagar_fatura_nao_conta_a_despesa_de_novo(client, setup):
    buy(client, setup.card, "300.00", 1)
    before = summary(client)
    invoice = invoices(client, setup.card)[0]
    assert pay(client, invoice, setup.account, "300.00").status_code == 201

    after = summary(client)
    assert after["expenses_total"] == before["expenses_total"] == "300.00"
    assert after["card_commitment"] == "300.00"
    assert after["balance"] == "4700.00"
    assert after["open_invoices"] == "0.00"
    assert after["available_to_spend"] == before["available_to_spend"] == "4700.00"


def test_categoria_e_historico_somam_a_compra_uma_vez(client, setup):
    lazer = next(c["id"] for c in client.get("/api/categories").json if c["name"] == "Lazer")
    buy(client, setup.card, "300.00", 1, category_id=lazer)
    client.post("/api/transactions", json={
        "kind": "expense", "description": "Show", "amount": "50.00", "competence_date": "2026-03-10",
        "account_id": setup.account["id"], "category_id": lazer,
    })
    pay(client, invoices(client, setup.card)[0], setup.account, "300.00")
    data = client.get("/api/dashboard?month=2026-03").json
    assert data["by_category"] == [{"category": "Lazer", "total": "350.00"}]
    assert data["history"][-1]["expenses"] == "350.00"
    assert data["summary"]["expenses_variable"] == "50.00"


def test_pagamento_parcial_atualiza_restante(client, setup):
    buy(client, setup.card, "300.00", 1)
    invoice = invoices(client, setup.card)[0]
    res = pay(client, invoice, setup.account, "100.00")
    assert res.json["paid"] == "100.00" and res.json["remaining"] == "200.00"
    assert res.json["status"] == "partial"
    s = summary(client)
    assert s["open_invoices"] == "200.00"
    assert s["balance"] == "4900.00" and s["available_to_spend"] == "4700.00"


def test_pagamento_acima_do_restante_e_recusado(client, setup):
    buy(client, setup.card, "300.00", 1)
    invoice = invoices(client, setup.card)[0]
    assert pay(client, invoice, setup.account, "300.01").status_code == 422
    assert pay(client, invoice, setup.account, "300.00", paid_on="2026-03-16").status_code == 422


def test_pagamento_nao_duplica_com_mesma_chave(client, setup):
    buy(client, setup.card, "300.00", 1)
    invoice = invoices(client, setup.card)[0]
    headers = WEB | {"Idempotency-Key": "pay-1"}
    body = {"amount": "100.00", "paid_on": "2026-03-15", "account_id": setup.account["id"]}
    url = f"/api/invoices/{invoice['id']}/payments"
    assert client.raw.post(url, json=body, headers=headers).status_code == 201
    assert client.raw.post(url, json=body, headers=headers).status_code == 200
    assert invoices(client, setup.card)[0]["paid"] == "100.00"


def test_compra_nao_duplica_com_mesma_chave(client, setup):
    headers = WEB | {"Idempotency-Key": "buy-1"}
    body = {"description": "x", "total_amount": "100.00", "purchase_date": "2026-03-10"}
    url = f"/api/cards/{setup.card['id']}/purchases"
    client.raw.post(url, json=body, headers=headers)
    assert client.raw.post(url, json=body, headers=headers).status_code == 200
    assert invoices(client, setup.card)[0]["total"] == "100.00"


def test_compra_e_pagamento_simultaneos_nao_dao_erro(client, setup, monkeypatch):
    from app.api import cards as cards_api

    real = cards_api.find_by_key
    calls = {"count": 0}

    def blind_on_check(model, key):
        """Só a checagem inicial de cada envio deixa de ver o registro."""
        calls["count"] += 1
        return None if calls["count"] % 2 == 1 else real(model, key)

    url = f"/api/cards/{setup.card['id']}/purchases"
    body = {"description": "x", "total_amount": "100.00", "purchase_date": "2026-03-10"}
    first = client.raw.post(url, json=body, headers=WEB | {"Idempotency-Key": "corrida-c"})
    assert first.status_code == 201
    monkeypatch.setattr(cards_api, "find_by_key", blind_on_check)
    second = client.raw.post(url, json=body, headers=WEB | {"Idempotency-Key": "corrida-c"})
    assert second.status_code == 200 and second.json["id"] == first.json["id"]
    assert invoices(client, setup.card)[0]["total"] == "100.00"

    monkeypatch.setattr(cards_api, "find_by_key", real)
    invoice = invoices(client, setup.card)[0]
    pay_url = f"/api/invoices/{invoice['id']}/payments"
    pay_body = {"amount": "40.00", "paid_on": "2026-03-15", "account_id": setup.account["id"]}
    assert client.raw.post(pay_url, json=pay_body, headers=WEB | {"Idempotency-Key": "corrida-p"}).status_code == 201
    monkeypatch.setattr(cards_api, "find_by_key", blind_on_check)
    res = client.raw.post(pay_url, json=pay_body, headers=WEB | {"Idempotency-Key": "corrida-p"})
    assert res.status_code == 200
    assert res.json["paid"] == "40.00"


def test_remover_pagamento_devolve_saldo_e_divida(client, setup):
    buy(client, setup.card, "300.00", 1)
    invoice = invoices(client, setup.card)[0]
    pay(client, invoice, setup.account, "300.00")
    payment = client.get(f"/api/invoices/{invoice['id']}").json["payments"][0]
    client.raw.delete(f"/api/invoice-payments/{payment['id']}", headers=WEB)
    assert summary(client)["balance"] == "5000.00"
    assert invoices(client, setup.card)[0]["remaining"] == "300.00"


# Limite e situação

def test_limite_considera_parcelas_futuras_e_libera_ao_pagar(client, setup):
    buy(client, setup.card)
    card = client.get("/api/cards").json[0]
    assert card["used"] == "900.00" and card["available"] == "2100.00" and card["usage_pct"] == 30
    assert card["remaining_installments"] == 5 and card["future_invoices"] == "750.00"
    pay(client, invoices(client, setup.card)[0], setup.account, "150.00")
    card = client.get("/api/cards").json[0]
    assert card["available"] == "2250.00"
    assert card["current_invoice"] == "150.00"  # paga, mas ainda é a fatura do ciclo


@pytest.mark.parametrize("today,status", [
    (date(2026, 3, 15), "open"),
    (date(2026, 3, 19), "open"),
    (date(2026, 3, 20), "closed"),  # no dia do fechamento já não recebe compras
    (date(2026, 3, 22), "closed"),
    (date(2026, 3, 29), "overdue"),
])
def test_situacao_da_fatura(client, setup, today, status):
    buy(client, setup.card, "100.00", 1)
    CLOCK["today"] = today
    assert invoices(client, setup.card)[0]["status"] == status


def test_fatura_seguinte_e_futura_e_paga_fica_paga(client, setup):
    buy(client, setup.card, "200.00", 2)
    rows = invoices(client, setup.card)
    assert [r["status"] for r in rows] == ["open", "future"]
    pay(client, rows[0], setup.account, "100.00")
    assert invoices(client, setup.card)[0]["status"] == "paid"
    CLOCK["today"] = date(2026, 4, 2)
    assert invoices(client, setup.card)[0]["status"] == "paid"


def test_alertas(client, setup):
    buy(client, setup.card, "2700.00", 1)
    CLOCK["today"] = date(2026, 3, 26)
    messages = [a["message"] for a in client.get("/api/dashboard?month=2026-03").json["alerts"]]
    assert any("90% do limite" in m for m in messages)
    assert any("vence em 2 dia" in m for m in messages)
    CLOCK["today"] = date(2026, 4, 1)
    messages = [a["message"] for a in client.get("/api/dashboard?month=2026-04").json["alerts"]]
    assert any("em atraso" in m for m in messages)
    s = summary(client, "2026-04")
    assert s["overdue_invoices"] == "2700.00"
    assert s["available_to_spend"] == "2300.00"


def test_mudar_dias_preserva_faturas_fechadas(client, setup):
    buy(client, setup.card, "200.00", 2)
    CLOCK["today"] = date(2026, 3, 25)
    client.patch(f"/api/cards/{setup.card['id']}", json={"closing_day": 10, "due_day": 18})
    rows = invoices(client, setup.card)
    assert rows[0]["closing_date"] == "2026-03-20"
    assert rows[1]["closing_date"] == "2026-04-10" and rows[1]["due_date"] == "2026-04-18"


# Exclusões e isolamento

def test_excluir_compra_remove_parcelas_e_faturas_vazias(client, setup):
    purchase = buy(client, setup.card).json
    assert client.raw.delete(f"/api/purchases/{purchase['id']}", headers=WEB).status_code == 204
    assert invoices(client, setup.card) == []
    assert db.session.scalar(db.select(db.func.count()).select_from(Invoice)) == 0


def test_compra_com_fatura_paga_nao_pode_ser_excluida(client, setup):
    purchase = buy(client, setup.card, "300.00", 3).json
    pay(client, invoices(client, setup.card)[0], setup.account, "100.00")
    assert client.raw.delete(f"/api/purchases/{purchase['id']}", headers=WEB).status_code == 409


def test_cartao_com_compra_nao_pode_ser_excluido(client, setup):
    buy(client, setup.card)
    assert client.raw.delete(f"/api/cards/{setup.card['id']}", headers=WEB).status_code == 409


def test_conta_com_pagamento_de_fatura_nao_pode_ser_excluida(client, setup):
    buy(client, setup.card, "300.00", 1)
    pay(client, invoices(client, setup.card)[0], setup.account, "300.00")
    assert client.raw.delete(f"/api/accounts/{setup.account['id']}", headers=WEB).status_code == 409


def test_editar_compra_nao_muda_valor(client, setup):
    purchase = buy(client, setup.card).json
    res = client.patch(f"/api/purchases/{purchase['id']}", json={"description": "Novo nome"})
    assert res.json["description"] == "Novo nome"
    assert client.patch(f"/api/purchases/{purchase['id']}", json={"total_amount": "1"}).status_code == 422


def test_dias_iguais_sao_recusados(client, setup):
    res = client.post("/api/cards", json={
        "name": "x", "credit_limit": "1", "closing_day": 5, "due_day": 5,
    })
    assert res.status_code == 422


def test_dados_de_cartao_isolados_por_usuario(client, make_client, setup):
    purchase = buy(client, setup.card, "300.00", 1).json
    invoice = invoices(client, setup.card)[0]
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    mine = other.post("/api/accounts", json={"name": "B", "opening_date": "2026-01-01"}).json
    assert other.get("/api/cards").json == []
    assert other.get(f"/api/cards/{setup.card['id']}").status_code == 404
    assert other.get(f"/api/invoices/{invoice['id']}").status_code == 404
    assert pay(other, invoice, mine, "1.00").status_code == 404
    assert buy(other, setup.card).status_code == 404
    assert other.raw.delete(f"/api/purchases/{purchase['id']}", headers=WEB).status_code == 404
    assert other.get("/api/installments?month=2026-03").json["items"] == []
    assert summary(other)["card_commitment"] == "0.00"


def test_nao_paga_com_conta_de_outro_usuario(client, make_client, setup):
    buy(client, setup.card, "300.00", 1)
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    theirs = other.post("/api/accounts", json={"name": "B", "opening_date": "2026-01-01"}).json
    assert pay(client, invoices(client, setup.card)[0], theirs, "1.00").status_code == 422


def test_lista_de_parcelas_do_mes(client, setup):
    buy(client, setup.card, "900.00", 6)
    res = client.get("/api/installments?month=2026-04").json
    assert res["total"] == "150.00"
    assert res["items"][0]["number"] == 2 and res["items"][0]["count"] == 6
    assert client.get("/api/installments?month=x").status_code == 422
