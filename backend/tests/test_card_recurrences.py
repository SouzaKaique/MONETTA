"""Gasto fixo no cartão: entra em cada fatura, conta uma vez e não mexe na conta até o pagamento."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.api import finance_common
from app.services import dashboard as dash

from .conftest import register

CLOCK = {"today": date(2026, 3, 15)}


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    CLOCK["today"] = date(2026, 3, 15)
    monkeypatch.setattr(dash, "today_for", lambda settings: CLOCK["today"])
    monkeypatch.setattr(finance_common, "today_for", lambda settings: CLOCK["today"])


@pytest.fixture()
def setup(client):
    register(client)
    account = client.post("/api/accounts", json={
        "name": "Conta", "opening_balance": "1000.00", "opening_date": "2026-01-01",
    }).json
    card = client.post("/api/cards", json={
        "name": "Nubank", "credit_limit": "3000.00", "closing_day": 1, "due_day": 8,
    }).json
    return SimpleNamespace(account=account, card=card)


def fixed(client, setup, name="Academia", amount="119.90", day=11, **extra):
    res = client.post("/api/recurrences", json={
        "kind": "expense", "name": name, "amount": amount, "day_of_month": day,
        "start_date": "2026-03-01", "card_id": setup.card["id"], **extra,
    })
    assert res.status_code == 201, res.json
    return res.json


def invoices(client, card):
    return {i["month"]: i for i in client.get(f"/api/cards/{card['id']}").json["invoices"]}


def account_expenses(client):
    return [t for t in client.get("/api/transactions?month=2026-03").json["items"] if t["kind"] == "expense"]


def test_gasto_fixo_entra_em_cada_fatura(client, setup):
    rec = fixed(client, setup)
    assert rec["card_id"] == setup.card["id"] and rec["card_name"] == "Nubank"
    assert rec["account_id"] is None

    months = invoices(client, setup.card)
    # Dia 11 de março fecha em 01/04 e vence em 08/04; dia 11 de abril vai para maio.
    assert months["2026-04"]["total"] == "119.90"
    assert months["2026-05"]["total"] == "119.90"
    assert "2026-03" not in months


def test_nao_cria_saida_na_conta_nem_duplica(client, setup):
    fixed(client, setup)
    for _ in range(3):
        invoices(client, setup.card)
        client.get("/api/dashboard?month=2026-04")
    assert account_expenses(client) == []
    assert invoices(client, setup.card)["2026-04"]["total"] == "119.90"


def test_conta_uma_vez_como_despesa_do_mes_da_fatura(client, setup):
    fixed(client, setup)
    april = client.get("/api/dashboard?month=2026-04").json["summary"]
    other = client.post("/api/cards/{}/purchases".format(setup.card["id"]), json={
        "description": "Mercado", "total_amount": "10.00", "purchase_date": "2026-03-12",
    })
    assert other.status_code == 201
    after = client.get("/api/dashboard?month=2026-04").json["summary"]
    assert float(after["expenses_total"]) - float(april["expenses_total"]) == pytest.approx(10.0)


def test_mudar_valor_vale_dali_em_diante(client, setup):
    rec = fixed(client, setup, amount="114.40")
    res = client.patch(f"/api/recurrences/{rec['id']}", json={"amount": "120.00", "effective_from": "2026-04"})
    assert res.status_code == 200
    months = invoices(client, setup.card)
    assert months["2026-04"]["total"] == "114.40"  # compra de março mantém o valor
    assert months["2026-05"]["total"] == "120.00"


def test_fatura_paga_nao_muda(client, setup):
    rec = fixed(client, setup)
    april = invoices(client, setup.card)["2026-04"]
    paid = client.post(f"/api/invoices/{april['id']}/payments", json={
        "amount": "119.90", "paid_on": "2026-03-15", "account_id": setup.account["id"],
    })
    assert paid.status_code == 201
    client.patch(f"/api/recurrences/{rec['id']}", json={"amount": "200.00"})
    months = invoices(client, setup.card)
    assert months["2026-04"]["total"] == "119.90"
    assert months["2026-05"]["total"] == "200.00"


def test_apagar_compra_de_um_mes_nao_volta(client, setup):
    fixed(client, setup)
    purchases = client.get(f"/api/cards/{setup.card['id']}/purchases").json
    april = next(p for p in purchases if p["purchase_date"] == "2026-03-11")
    assert client.delete(f"/api/purchases/{april['id']}").status_code == 204
    months = invoices(client, setup.card)
    assert "2026-04" not in months and months["2026-05"]["total"] == "119.90"


def test_apagar_regra_remove_o_que_falta(client, setup):
    rec = fixed(client, setup)
    invoices(client, setup.card)
    assert client.delete(f"/api/recurrences/{rec['id']}").status_code == 204
    assert invoices(client, setup.card) == {}


def test_trocar_entre_conta_e_cartao(client, setup):
    rec = client.post("/api/recurrences", json={
        "kind": "expense", "name": "Spotify", "amount": "12.90", "day_of_month": 20,
        "start_date": "2026-03-01", "account_id": setup.account["id"],
    }).json
    assert len(account_expenses(client)) == 1

    res = client.patch(f"/api/recurrences/{rec['id']}", json={"card_id": setup.card["id"]})
    assert res.status_code == 200 and res.json["account_id"] is None
    assert account_expenses(client) == []
    assert invoices(client, setup.card)["2026-04"]["total"] == "12.90"

    res = client.patch(f"/api/recurrences/{rec['id']}", json={
        "card_id": None, "account_id": setup.account["id"],
    })
    assert res.status_code == 200
    assert invoices(client, setup.card) == {}
    assert len(account_expenses(client)) == 1


def test_receita_nao_vai_para_cartao(client, setup):
    res = client.post("/api/recurrences", json={
        "kind": "income", "name": "Extra", "amount": "800.00", "day_of_month": 28,
        "start_date": "2026-03-01", "card_id": setup.card["id"],
    })
    assert res.status_code == 422


def test_cartao_de_outro_usuario(client, setup):
    card = setup.card
    client.post("/api/auth/logout")
    register(client, email="outra@example.com")
    res = client.post("/api/recurrences", json={
        "kind": "expense", "name": "X", "amount": "10.00", "day_of_month": 5,
        "start_date": "2026-03-01", "card_id": card["id"],
    })
    assert res.status_code == 404


def test_cartao_com_gasto_fixo_nao_e_apagado(client, setup):
    rec = fixed(client, setup, start_date="2027-01-01")  # ainda sem compras geradas
    res = client.delete(f"/api/cards/{setup.card['id']}")
    assert res.status_code == 409
    client.delete(f"/api/recurrences/{rec['id']}")
    assert client.delete(f"/api/cards/{setup.card['id']}").status_code == 204


def test_backup_restaura_gasto_fixo_no_cartao(client, setup):
    fixed(client, setup)
    invoices(client, setup.card)
    backup = client.get("/api/backup").json
    client.post("/api/auth/logout")
    register(client, email="nova@example.com")
    res = client.post("/api/backup/restore", json=backup)
    assert res.status_code == 200, res.json
    rec = client.get("/api/recurrences").json[0]
    assert rec["card_name"] == "Nubank"
