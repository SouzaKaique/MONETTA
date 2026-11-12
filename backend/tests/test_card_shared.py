"""Parte de outras pessoas: fica na fatura, que é paga inteira, mas não conta como despesa sua."""
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
    client.post("/api/accounts", json={
        "name": "Conta", "opening_balance": "1000.00", "opening_date": "2026-01-01",
    })
    card = client.post("/api/cards", json={
        "name": "Nubank", "credit_limit": "3000.00", "closing_day": 1, "due_day": 8,
    }).json
    category = next(c for c in client.get("/api/categories").json if c["name"] == "Lazer")
    return SimpleNamespace(card=card, category=category)


def buy(client, setup, amount="100.00", count=1, **extra):
    res = client.post(f"/api/cards/{setup.card['id']}/purchases", json={
        "description": "Show", "total_amount": amount, "installment_count": count,
        "purchase_date": "2026-03-10", "category_id": setup.category["id"], **extra,
    })
    assert res.status_code == 201, res.json
    return res.json


def invoice(client, setup, month="2026-04"):
    rows = {i["month"]: i for i in client.get(f"/api/cards/{setup.card['id']}").json["invoices"]}
    return client.get(f"/api/invoices/{rows[month]['id']}").json


def april(client):
    return client.get("/api/dashboard?month=2026-04").json


def test_anular_tira_da_despesa_mas_nao_da_fatura(client, setup):
    purchase = buy(client, setup)
    before = april(client)["summary"]["expenses_total"]

    res = client.patch(f"/api/purchases/{purchase['id']}", json={"others_amount": "100.00"})
    assert res.status_code == 200
    assert res.json["others_amount"] == "100.00" and res.json["own_amount"] == "0.00"

    inv = invoice(client, setup)
    assert inv["total"] == "100.00" and inv["remaining"] == "100.00"  # a fatura continua inteira
    assert inv["installments"][0]["own_amount"] == "0.00"
    dashboard = april(client)
    assert float(before) - float(dashboard["summary"]["expenses_total"]) == pytest.approx(100.0)
    assert all(c["category"] != "Lazer" for c in dashboard["by_category"])


def test_desfazer_volta_a_contar(client, setup):
    purchase = buy(client, setup)
    before = april(client)["summary"]["expenses_total"]
    client.patch(f"/api/purchases/{purchase['id']}", json={"others_amount": "100.00"})
    client.patch(f"/api/purchases/{purchase['id']}", json={"others_amount": "0"})
    assert april(client)["summary"]["expenses_total"] == before


def test_dividir_compra_parcelada(client, setup):
    purchase = buy(client, setup, amount="100.00", count=3, others_amount="66.67")
    assert purchase["own_amount"] == "33.33"
    parts = [invoice(client, setup, m)["installments"][0] for m in ("2026-04", "2026-05", "2026-06")]
    assert [p["amount"] for p in parts] == ["33.34", "33.33", "33.33"]
    assert [p["others_amount"] for p in parts] == ["22.23", "22.22", "22.22"]
    assert all(float(p["others_amount"]) <= float(p["amount"]) for p in parts)


def test_parte_dos_outros_nao_passa_do_total(client, setup):
    purchase = buy(client, setup)
    res = client.patch(f"/api/purchases/{purchase['id']}", json={"others_amount": "100.01"})
    assert res.status_code == 422
    res = client.post(f"/api/cards/{setup.card['id']}/purchases", json={
        "description": "X", "total_amount": "10.00", "purchase_date": "2026-03-10",
        "others_amount": "10.01",
    })
    assert res.status_code == 422


def test_assinatura_dividida_no_cartao(client, setup):
    res = client.post("/api/recurrences", json={
        "kind": "expense", "name": "iCloud", "amount": "66.90", "others_amount": "44.60",
        "day_of_month": 20, "start_date": "2026-03-01", "card_id": setup.card["id"],
    })
    assert res.status_code == 201, res.json
    assert res.json["others_amount"] == "44.60"
    item = invoice(client, setup)["installments"][0]
    assert item["amount"] == "66.90" and item["own_amount"] == "22.30"
    assert april(client)["summary"]["card_commitment"] == "22.30"

    res = client.patch(f"/api/recurrences/{res.json['id']}", json={"others_amount": "70.00"})
    assert res.status_code == 422


def test_limite_usa_valor_inteiro(client, setup):
    purchase = buy(client, setup, amount="300.00")
    client.patch(f"/api/purchases/{purchase['id']}", json={"others_amount": "300.00"})
    card = client.get(f"/api/cards/{setup.card['id']}").json
    assert card["used"] == "300.00"
