"""Dívidas: saldo, pagamentos, estratégias e simulador."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api import debts as debts_api
from app.api import finance_common
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
    return SimpleNamespace(account=account)


def new_debt(client, name="Mãe", amount="3000.00", **extra):
    res = client.post("/api/debts", json={
        "name": name, "creditor": "Maria", "original_amount": amount,
        "start_date": "2026-01-10", **extra,
    })
    assert res.status_code == 201, res.json
    return res.json


def pay(client, debt, amount, account=None, paid_on="2026-03-10"):
    return client.post(f"/api/debts/{debt['id']}/payments", json={
        "amount": amount, "paid_on": paid_on,
        "account_id": account["id"] if account else None,
    })


def summary(client, month="2026-03"):
    return client.get(f"/api/dashboard?month={month}").json["summary"]


def listed(client, strategy=None):
    query = f"?strategy={strategy}" if strategy else ""
    return client.get(f"/api/debts{query}").json


def names(client, strategy):
    return [d["name"] for d in listed(client, strategy)["items"]]


def simulate(client, amounts, **extra):
    res = client.post("/api/debts/simulate", json={"amounts": amounts, **extra})
    assert res.status_code == 200, res.json
    return res.json


# Saldo e pagamentos

def test_dívida_nova_fica_pendente_e_sem_juros(client, setup):
    debt = new_debt(client)
    assert debt["status"] == "pending" and debt["balance"] == "3000.00"
    assert debt["interest_rate"] is None and debt["due_date"] is None and debt["paid_pct"] == 0


def test_pagamento_reduz_saldo_e_atualiza_situacao(client, setup):
    debt = new_debt(client)
    res = pay(client, debt, "1000.00", setup.account)
    assert res.status_code == 201
    assert res.json["balance"] == "2000.00" and res.json["status"] == "in_payment"
    assert res.json["total_paid"] == "1000.00" and res.json["paid_pct"] == 33
    res = pay(client, debt, "2000.00", setup.account)
    assert res.json["balance"] == "0.00" and res.json["status"] == "paid"
    assert res.json["paid_pct"] == 100


def test_pagamento_acima_do_saldo_ou_futuro_e_recusado(client, setup):
    debt = new_debt(client, amount="100.00")
    assert pay(client, debt, "100.01").status_code == 422
    assert pay(client, debt, "10.00", paid_on="2026-03-16").status_code == 422


def test_divida_ja_parcialmente_paga_no_cadastro(client, setup):
    debt = new_debt(client, amount="3000.00", current_balance="1800.00")
    assert debt["balance"] == "1800.00" and debt["total_paid"] == "1200.00"
    assert debt["status"] == "in_payment" and debt["paid_pct"] == 40


def test_pagamento_sai_da_conta_e_nao_e_despesa(client, setup):
    debt = new_debt(client)
    pay(client, debt, "500.00", setup.account)
    s = summary(client)
    assert s["balance"] == "4500.00"
    assert s["expenses_total"] == "0.00"
    assert s["debt_payments"] == "500.00"
    assert s["pending_debts"] == "2500.00"


def test_pagamento_antigo_sem_conta_nao_altera_saldo(client, setup):
    debt = new_debt(client)
    res = pay(client, debt, "500.00", None, paid_on="2026-02-10")
    assert res.json["balance"] == "2500.00"
    assert summary(client)["balance"] == "5000.00"


def test_remover_pagamento_devolve_tudo(client, setup):
    debt = new_debt(client)
    payment = pay(client, debt, "500.00", setup.account).json["payments"][0]
    client.raw.delete(f"/api/debt-payments/{payment['id']}", headers=WEB)
    assert listed(client)["items"][0]["balance"] == "3000.00"
    assert summary(client)["balance"] == "5000.00"


def test_pagamento_nao_duplica_com_mesma_chave(client, setup):
    debt = new_debt(client)
    body = {"amount": "100.00", "paid_on": "2026-03-10", "account_id": setup.account["id"]}
    headers = WEB | {"Idempotency-Key": "d-1"}
    url = f"/api/debts/{debt['id']}/payments"
    assert client.raw.post(url, json=body, headers=headers).status_code == 201
    assert client.raw.post(url, json=body, headers=headers).status_code == 200
    assert listed(client)["items"][0]["balance"] == "2900.00"


def test_pagamentos_simultaneos_nao_dao_erro(client, setup, monkeypatch):
    debt = new_debt(client)
    body = {"amount": "100.00", "paid_on": "2026-03-10", "account_id": setup.account["id"]}
    headers = WEB | {"Idempotency-Key": "d-2"}
    url = f"/api/debts/{debt['id']}/payments"
    client.raw.post(url, json=body, headers=headers)
    real = debts_api.find_by_key
    calls = iter([None])
    monkeypatch.setattr(debts_api, "find_by_key", lambda m, k: next(calls, real(m, k)))
    assert client.raw.post(url, json=body, headers=headers).status_code == 200
    assert listed(client)["items"][0]["balance"] == "2900.00"


def test_saldo_nao_pode_ficar_abaixo_do_pago(client, setup):
    debt = new_debt(client)
    pay(client, debt, "1000.00")
    assert client.patch(f"/api/debts/{debt['id']}", json={"opening_balance": "500.00"}).status_code == 422
    assert client.patch(f"/api/debts/{debt['id']}", json={"opening_balance": "2000.00"}).status_code == 200


def test_divida_com_pagamento_nao_pode_ser_excluida(client, setup):
    debt = new_debt(client)
    pay(client, debt, "100.00")
    assert client.raw.delete(f"/api/debts/{debt['id']}", headers=WEB).status_code == 409


def test_conta_com_pagamento_de_divida_nao_pode_ser_excluida(client, setup):
    pay(client, new_debt(client), "100.00", setup.account)
    assert client.raw.delete(f"/api/accounts/{setup.account['id']}", headers=WEB).status_code == 409


def test_frequencia_exige_valor_combinado(client, setup):
    res = client.post("/api/debts", json={
        "name": "x", "creditor": "y", "original_amount": "10", "start_date": "2026-01-01",
        "frequency": "monthly",
    })
    assert res.status_code == 422


# Obrigações do mês

def test_valor_combinado_reduz_disponivel_sem_ser_despesa(client, setup):
    new_debt(client, agreed_amount="300.00", frequency="monthly")
    s = summary(client)
    assert s["debt_due"] == "300.00" and s["available_to_spend"] == "4700.00"
    assert s["expenses_total"] == "0.00" and s["balance"] == "5000.00"


def test_pagar_o_combinado_nao_desconta_duas_vezes(client, setup):
    debt = new_debt(client, agreed_amount="300.00", frequency="monthly")
    before = summary(client)["available_to_spend"]
    pay(client, debt, "300.00", setup.account)
    s = summary(client)
    assert s["debt_due"] == "0.00" and s["balance"] == "4700.00"
    assert s["available_to_spend"] == before == "4700.00"


def test_pagamento_parcial_do_combinado(client, setup):
    debt = new_debt(client, agreed_amount="300.00", frequency="monthly")
    pay(client, debt, "100.00", setup.account)
    s = summary(client)
    assert s["debt_due"] == "200.00" and s["available_to_spend"] == "4700.00"


def test_quinzenal_conta_dois_pagamentos_e_respeita_saldo(client, setup):
    new_debt(client, amount="150.00", agreed_amount="100.00", frequency="biweekly")
    assert summary(client)["debt_due"] == "150.00"


def test_divida_sem_combinado_nao_gera_obrigacao(client, setup):
    new_debt(client)
    assert summary(client)["debt_due"] == "0.00"
    assert summary(client)["available_to_spend"] == "5000.00"


def test_comprometimento_e_dinheiro_livre_incluem_dividas(client, setup):
    client.post("/api/transactions", json={
        "kind": "income", "description": "Salário", "amount": "2000.00",
        "competence_date": "2026-03-05", "account_id": setup.account["id"],
    })
    new_debt(client, agreed_amount="500.00", frequency="monthly")
    s = summary(client)
    assert s["income_commitment_pct"] == 25 and s["free_money"] == "1500.00"


def test_alertas(client, setup):
    new_debt(client, "Vencida", due_date="2026-03-01")
    new_debt(client, "Próxima", due_date="2026-03-17")
    debt = new_debt(client, "Paga", amount="100.00", due_date="2026-03-01")
    pay(client, debt, "100.00")
    messages = [a["message"] for a in client.get("/api/dashboard?month=2026-03").json["alerts"]]
    assert "A dívida Vencida está vencida." in messages
    assert "A dívida Próxima vence em 2 dia(s)." in messages
    assert not any("Paga" in m for m in messages)
    assert any(m.startswith("Você quitou 2%") for m in messages)


# Estratégias

@pytest.fixture()
def three(client, setup):
    new_debt(client, "Grande", "5000.00", interest_rate="1.000", priority=3, due_date="2026-08-01")
    new_debt(client, "Pequena", "500.00", priority=2)
    new_debt(client, "Cara", "2000.00", interest_rate="8.000", priority=1, due_date="2026-05-01")


def test_bola_de_neve_prioriza_menor_saldo(client, three):
    assert names(client, "snowball") == ["Pequena", "Cara", "Grande"]


def test_avalanche_prioriza_maior_juro_e_sem_juros_por_ultimo(client, three):
    assert names(client, "avalanche") == ["Cara", "Grande", "Pequena"]


def test_vencimento_e_importancia(client, three):
    assert names(client, "due_date") == ["Cara", "Grande", "Pequena"]
    assert names(client, "priority") == ["Cara", "Pequena", "Grande"]


def test_ordem_personalizada(client, three):
    debts = {d["name"]: d["id"] for d in listed(client)["items"]}
    wanted = ["Grande", "Cara", "Pequena"]
    res = client.post("/api/debts/order", json={"ids": [debts[n] for n in wanted]})
    assert res.status_code == 204
    assert client.get("/api/auth/me").json["debt_strategy"] == "custom"
    assert names(client, "custom") == wanted


def test_ordem_nao_aceita_divida_de_outro_usuario(client, make_client, three):
    debts = [d["id"] for d in listed(client)["items"]]
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    assert other.post("/api/debts/order", json={"ids": debts}).status_code == 422


def test_quitada_vai_para_o_fim_e_proxima_divida(client, three):
    small = next(d for d in listed(client)["items"] if d["name"] == "Pequena")
    pay(client, small, "500.00")
    data = listed(client, "snowball")
    assert [d["name"] for d in data["items"]] == ["Cara", "Grande", "Pequena"]
    assert data["summary"]["next_debt"] == "Cara"
    assert data["summary"]["balance"] == "7000.00" and data["summary"]["paid"] == "500.00"


def test_estrategia_salva_no_perfil(client, setup):
    assert client.patch("/api/profile", json={"debt_strategy": "avalanche"}).json["debt_strategy"] == "avalanche"
    assert listed(client)["strategy"] == "avalanche"
    assert client.patch("/api/profile", json={"debt_strategy": "x"}).status_code == 422
    assert client.get("/api/debts?strategy=x").status_code == 400


# Simulador

def test_exemplo_da_especificacao(client, setup):
    new_debt(client)
    data = simulate(client, ["300.00", "500.00", "750.00"])
    a, b, c = data["scenarios"]
    assert (a["months"], b["months"], c["months"]) == (10, 6, 4)
    assert (a["months_saved"], b["months_saved"], c["months_saved"]) == (0, 4, 6)
    assert a["total_interest"] == "0.00" and a["total_paid"] == "3000.00"
    assert a["finish_month"] == "2027-01" and c["finish_month"] == "2026-07"
    assert a["timeline"][0] == {"month": "2026-03", "balance": "3000.00"}
    assert a["timeline"][1]["balance"] == "2700.00" and a["timeline"][-1]["balance"] == "0.00"


def test_juros_estimados_e_economia(client, setup):
    new_debt(client, amount="1000.00", interest_rate="2.000")
    slow, fast = simulate(client, ["100.00", "200.00"])["scenarios"]
    assert slow["months"] == 12 and fast["months"] == 6
    assert Decimal(slow["total_paid"]) == Decimal("1000.00") + Decimal(slow["total_interest"])
    assert Decimal(fast["interest_saved"]) > 0
    assert slow["timeline"][1]["balance"] == "920.00"  # 1000 + 20 de juros - 100


def test_pagamento_extra_antecipa(client, setup):
    new_debt(client)
    assert simulate(client, ["500.00"], extra="1000.00")["scenarios"][0]["months"] == 4


def test_valor_que_nao_cobre_juros_nunca_termina(client, setup):
    new_debt(client, amount="1000.00", interest_rate="10.000")
    scenario = simulate(client, ["50.00"])["scenarios"][0]
    assert scenario["feasible"] is False and scenario["months"] is None
    assert simulate(client, ["50.00", "300.00"])["scenarios"][1]["months_saved"] is None


def test_sobra_passa_para_a_proxima_divida(client, setup):
    new_debt(client, "A", "100.00")
    new_debt(client, "B", "1000.00")
    scenario = simulate(client, ["300.00"], strategy="snowball")["scenarios"][0]
    assert scenario["months"] == 4
    assert {p["name"]: p["months"] for p in scenario["payoff"]} == {"A": 1, "B": 4}


def test_avalanche_paga_menos_juros_que_bola_de_neve(client, setup):
    new_debt(client, "Barata", "1000.00", interest_rate="1.000")
    new_debt(client, "Cara", "2000.00", interest_rate="10.000")
    snowball = simulate(client, ["400.00"], strategy="snowball")["scenarios"][0]
    avalanche = simulate(client, ["400.00"], strategy="avalanche")["scenarios"][0]
    assert Decimal(avalanche["total_interest"]) < Decimal(snowball["total_interest"])


def test_nao_recomenda_acima_do_que_sobra(client, setup):
    client.post("/api/transactions", json={
        "kind": "income", "description": "Salário", "amount": "2000.00",
        "competence_date": "2026-03-05", "account_id": setup.account["id"],
    })
    client.post("/api/transactions", json={
        "kind": "expense", "description": "Aluguel", "amount": "1200.00",
        "competence_date": "2026-03-05", "account_id": setup.account["id"],
    })
    client.patch("/api/profile", json={"safety_minimum": "100.00"})
    new_debt(client)
    data = simulate(client, ["700.00", "701.00"])
    assert data["capacity"] == "700.00"
    assert [s["above_capacity"] for s in data["scenarios"]] == [False, True]


def test_sem_renda_nao_ha_teto(client, setup):
    new_debt(client)
    data = simulate(client, ["300.00"])
    assert data["capacity"] is None and data["scenarios"][0]["above_capacity"] is False


def test_sem_dividas_e_entrada_invalida(client, setup):
    assert simulate(client, ["300.00"])["scenarios"][0]["months"] == 0
    assert client.post("/api/debts/simulate", json={"amounts": []}).status_code == 422
    assert client.post("/api/debts/simulate", json={"amounts": ["0"]}).status_code == 422


# Isolamento

def test_dividas_isoladas_por_usuario(client, make_client, setup):
    debt = new_debt(client)
    payment = pay(client, debt, "100.00", setup.account).json["payments"][0]
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    assert listed(other)["items"] == []
    assert summary(other)["pending_debts"] == "0.00"
    assert pay(other, debt, "1.00").status_code == 404
    assert other.patch(f"/api/debts/{debt['id']}", json={"name": "x"}).status_code == 404
    assert other.raw.delete(f"/api/debts/{debt['id']}", headers=WEB).status_code == 404
    assert other.raw.delete(f"/api/debt-payments/{payment['id']}", headers=WEB).status_code == 404
    assert simulate(other, ["100.00"])["scenarios"][0]["months"] == 0


def test_nao_paga_com_conta_de_outro_usuario(client, make_client, setup):
    debt = new_debt(client)
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    theirs = other.post("/api/accounts", json={"name": "B", "opening_date": "2026-01-01"}).json
    assert pay(client, debt, "1.00", theirs).status_code == 422
