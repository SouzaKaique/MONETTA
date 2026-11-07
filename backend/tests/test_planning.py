"""Simulador até o salário, orçamento, calendário, Modo Recuperação e notificações."""
from datetime import date
from types import SimpleNamespace

import pytest

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
        "name": "Conta", "opening_balance": "1800.00", "opening_date": "2026-01-01",
    }).json
    return SimpleNamespace(account=account)


def category(client, name):
    return next(c for c in client.get("/api/categories").json
                if c["name"] == name and c["kind"] == "expense")["id"]


def salary(client, setup, day=28, amount="4000.00"):
    res = client.post("/api/recurrences", json={
        "kind": "income", "name": "Salário", "amount": amount, "day_of_month": day,
        "start_date": "2026-03-01", "is_salary": True, "account_id": setup.account["id"],
    })
    assert res.status_code == 201


def expense(client, setup, amount, day="2026-03-10", status="confirmed", cat=None, name="Conta"):
    body = {
        "kind": "expense", "description": name, "amount": amount, "competence_date": day,
        "status": status, "account_id": setup.account["id"], "category_id": cat,
    }
    res = client.post("/api/transactions", json=body)
    assert res.status_code == 201, res.json


def card(client, closing=20, due=25):
    return client.post("/api/cards", json={
        "name": "Nubank", "credit_limit": "3000.00", "closing_day": closing, "due_day": due,
    }).json


def buy(client, card_, amount, count=1, day="2026-03-10", cat=None):
    res = client.post(f"/api/cards/{card_['id']}/purchases", json={
        "description": "Compra", "total_amount": amount, "installment_count": count,
        "purchase_date": day, "category_id": cat,
    })
    assert res.status_code == 201, res.json


def debt(client, amount="3000.00", **extra):
    res = client.post("/api/debts", json={
        "name": "Mãe", "creditor": "Maria", "original_amount": amount,
        "start_date": "2026-01-10", **extra,
    })
    assert res.status_code == 201, res.json
    return res.json


def until(client, spend=None):
    query = f"?spend={spend}" if spend else ""
    return client.get(f"/api/planning/until-salary{query}").json


def activate(client, **extra):
    res = client.put("/api/recovery", json={"monthly_amount": "500.00", **extra})
    assert res.status_code == 200, res.json
    return res.json


def notifications(client):
    return client.get("/api/notifications").json


# Até o próximo salário

def test_exemplo_da_especificacao(client, setup):
    salary(client, setup)  # dia 28: faltam 13 dias
    expense(client, setup, "120.00", "2026-03-20", "pending", name="Internet")
    buy(client, card(client), "400.00")
    debt(client, agreed_amount="300.00", frequency="monthly")
    client.patch("/api/profile", json={"planned_reserve": "200.00"})

    s = until(client)
    assert s["balance"] == "1800.00" and s["committed"] == "1020.00"
    assert s["available"] == "780.00" and s["days_left"] == 13
    assert s["daily_limit"] == "60.00" and s["weekly_limit"] == "420.00"
    assert s["next_salary_date"] == "2026-03-28"
    assert {c["kind"] for c in s["commitments"]} == {"expense", "invoice", "debt", "reserve"}


def test_salario_futuro_nao_e_dinheiro_disponivel(client, setup):
    salary(client, setup, amount="9000.00")
    assert until(client)["available"] == "1800.00"


def test_dashboard_e_simulador_mostram_o_mesmo_disponivel(client, setup):
    salary(client, setup)
    expense(client, setup, "120.00", "2026-03-20", "pending")
    client.patch("/api/profile", json={"planned_reserve": "200.00"})
    assert until(client)["available"] == "1480.00"
    data = client.get("/api/dashboard?month=2026-03").json["summary"]
    assert data["available_to_spend"] == "1480.00"
    assert client.get("/api/planning").json["available"] == "1480.00"


def test_reserva_reduz_disponivel_mesmo_sem_salario(client, setup):
    client.patch("/api/profile", json={"planned_reserve": "200.00"})
    assert client.get("/api/dashboard?month=2026-03").json["summary"]["available_to_spend"] == "1600.00"


def test_sem_salario_cadastrado(client, setup):
    assert until(client) == {"has_salary": False}


def test_so_conta_compromissos_antes_do_salario(client, setup):
    salary(client, setup)
    expense(client, setup, "100.00", "2026-03-27", "pending")
    expense(client, setup, "999.00", "2026-03-28", "pending")
    expense(client, setup, "999.00", "2026-04-02", "pending")
    assert until(client)["committed"] == "100.00"


def test_conta_atrasada_entra_e_paga_sai(client, setup):
    salary(client, setup)
    expense(client, setup, "200.00", "2026-02-10", "pending")
    assert until(client)["committed"] == "200.00"
    tx = client.get("/api/transactions?status=pending&kind=expense").json["items"][0]
    client.post(f"/api/transactions/{tx['id']}/confirm", json={
        "paid_on": "2026-03-15", "account_id": setup.account["id"],
    })
    s = until(client)
    assert s["committed"] == "0.00" and s["balance"] == "1600.00"


def test_fatura_parcial_conta_so_o_restante(client, setup):
    salary(client, setup)
    c = card(client)
    buy(client, c, "400.00")
    invoice = client.get(f"/api/cards/{c['id']}").json["invoices"][0]
    client.post(f"/api/invoices/{invoice['id']}/payments", json={
        "amount": "150.00", "paid_on": "2026-03-15", "account_id": setup.account["id"],
    })
    s = until(client)
    assert s["committed"] == "250.00" and s["balance"] == "1650.00"
    assert s["available"] == "1400.00"


def test_minimo_de_seguranca_e_falta_de_dinheiro(client, setup):
    salary(client, setup)
    client.patch("/api/profile", json={"safety_minimum": "300.00"})
    expense(client, setup, "2000.00", "2026-03-20", "pending")
    s = until(client)
    assert s["available"] == "0.00" and s["daily_limit"] == "0.00"
    assert s["shortfall"] == "500.00"


def test_cenario_de_gasto_e_entrada_invalida(client, setup):
    salary(client, setup)
    s = until(client, "520.00")
    assert s["available"] == "1280.00" and s["scenario_spend"] == "520.00"
    assert client.get("/api/planning/until-salary?spend=abc").status_code == 422
    assert client.get("/api/planning/until-salary?spend=-1").status_code == 422
    assert client.get("/api/planning/until-salary?spend=NaN").status_code == 422


def test_atualiza_ao_registrar_despesa(client, setup):
    salary(client, setup)
    expense(client, setup, "100.00", "2026-03-15")
    assert until(client)["available"] == "1700.00"


def test_salario_ja_recebido_aponta_para_o_seguinte(client, setup):
    salary(client, setup, day=10)
    assert until(client)["next_salary_date"] == "2026-04-10"


def test_salario_hoje_conta_um_dia(client, setup):
    salary(client, setup, day=15)
    assert until(client)["days_left"] == 1


# Orçamento

def test_limite_e_gasto_incluem_cartao_uma_vez(client, setup):
    lazer = category(client, "Lazer")
    assert client.put("/api/budgets", json={"category_id": lazer, "amount": "300.00"}).status_code == 204
    expense(client, setup, "100.00", cat=lazer)
    buy(client, card(client), "60.00", cat=lazer)
    row = next(b for b in client.get("/api/planning").json["budgets"] if b["name"] == "Lazer")
    assert row["spent"] == "160.00" and row["remaining"] == "140.00" and row["pct"] == 53


def test_mudar_limite_nao_altera_mes_anterior(client, setup):
    lazer = category(client, "Lazer")
    client.put("/api/budgets", json={"category_id": lazer, "amount": "300.00"})
    client.put("/api/budgets", json={"category_id": lazer, "amount": "200.00", "month": "2026-05"})

    def limit(month):
        rows = client.get(f"/api/planning?month={month}").json["budgets"]
        return next((b["limit"] for b in rows if b["name"] == "Lazer"), None)

    assert limit("2026-02") is None
    assert limit("2026-03") == "300.00" and limit("2026-04") == "300.00"
    assert limit("2026-05") == "200.00" and limit("2026-08") == "200.00"


def test_limite_retroativo_e_categoria_de_receita_sao_recusados(client, setup):
    lazer = category(client, "Lazer")
    res = client.put("/api/budgets", json={"category_id": lazer, "amount": "1", "month": "2026-02"})
    assert res.status_code == 422
    income = next(c["id"] for c in client.get("/api/categories").json if c["kind"] == "income")
    assert client.put("/api/budgets", json={"category_id": income, "amount": "1"}).status_code == 422


def test_zero_remove_o_limite(client, setup):
    lazer = category(client, "Lazer")
    client.put("/api/budgets", json={"category_id": lazer, "amount": "300.00"})
    client.put("/api/budgets", json={"category_id": lazer, "amount": "0"})
    assert client.get("/api/planning").json["budgets"] == []


def test_distribuicao_nao_soma_nada_duas_vezes(client, setup):
    salary(client, setup, amount="4000.00")
    expense(client, setup, "1000.00", cat=category(client, "Moradia"))
    expense(client, setup, "200.00", cat=category(client, "Lazer"))
    buy(client, card(client), "300.00", cat=category(client, "Lazer"))
    debt(client, agreed_amount="500.00", frequency="monthly")
    client.patch("/api/profile", json={"planned_reserve": "100.00"})

    data = client.get("/api/planning").json
    parts = {d["key"]: d["amount"] for d in data["distribution"]}
    assert parts == {
        "essential": "1000.00", "variable": "200.00", "cards": "300.00", "debts": "500.00",
        "reserve": "100.00", "wishlist": "0.00", "free": "1900.00",
    }
    assert data["income_expected"] == "4000.00" and data["income_received"] == "0.00"


def test_categorias_padrao_essenciais_e_personalizacao(client, setup):
    cats = {c["name"]: c for c in client.get("/api/categories").json if c["kind"] == "expense"}
    assert cats["Moradia"]["is_essential"] and not cats["Lazer"]["is_essential"]
    res = client.patch(f"/api/categories/{cats['Lazer']['id']}", json={"is_essential": True})
    assert res.json["is_essential"] is True


def test_compromissos_futuros_incluem_parcelas(client, setup):
    buy(client, card(client), "600.00", 3)
    expense(client, setup, "100.00", "2026-04-10", "pending")
    assert client.get("/api/planning").json["future_commitments"] == "500.00"


def test_orcamento_isolado_por_usuario(client, make_client, setup):
    lazer = category(client, "Lazer")
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    assert other.put("/api/budgets", json={"category_id": lazer, "amount": "1"}).status_code == 404


# Calendário

def test_calendario_reune_todos_os_eventos(client, setup):
    salary(client, setup)
    expense(client, setup, "90.00", "2026-03-05", cat=None, name="Mercado")
    c = card(client)
    buy(client, c, "200.00")
    d = debt(client, due_date="2026-03-30")
    client.post(f"/api/debts/{d['id']}/payments", json={
        "amount": "100.00", "paid_on": "2026-03-12", "account_id": setup.account["id"],
    })
    activate(client, target_date="2026-03-31")
    client.post("/api/recurrences", json={
        "kind": "expense", "name": "Internet", "amount": "120.00", "day_of_month": 18,
        "start_date": "2026-03-01",
    })

    events = client.get("/api/calendar?month=2026-03").json["events"]
    types = {e["type"] for e in events}
    assert types == {"salary", "bill", "recurring", "invoice_closing", "invoice_due", "debt", "goal"}
    assert [e["date"] for e in events] == sorted(e["date"] for e in events)
    salary_event = next(e for e in events if e["type"] == "salary")
    assert salary_event["status"] == "pending" and salary_event["transaction_id"]
    assert sum(e["type"] == "debt" for e in events) == 2


def test_vencimento_mostra_restante_e_paga_fica_concluida(client, setup):
    c = card(client)
    buy(client, c, "200.00")
    invoice = client.get(f"/api/cards/{c['id']}").json["invoices"][0]
    pay = {"amount": "50.00", "paid_on": "2026-03-15", "account_id": setup.account["id"]}
    client.post(f"/api/invoices/{invoice['id']}/payments", json=pay)

    def due_event():
        events = client.get("/api/calendar?month=2026-03").json["events"]
        return next(e for e in events if e["type"] == "invoice_due")

    assert due_event()["amount"] == "150.00" and due_event()["status"] == "pending"
    client.post(f"/api/invoices/{invoice['id']}/payments", json=pay | {"amount": "150.00"})
    assert due_event()["status"] == "done"


def test_calendario_gera_mes_futuro_e_valida_entrada(client, setup):
    salary(client, setup)
    events = client.get("/api/calendar?month=2026-09").json["events"]
    assert [e["date"] for e in events] == ["2026-09-28"]
    assert client.get("/api/calendar?month=x").status_code == 422


def test_calendario_isolado_por_usuario(client, make_client, setup):
    salary(client, setup)
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    assert other.get("/api/calendar?month=2026-03").json["events"] == []


# Modo Recuperação

def test_ativar_guarda_divida_inicial_e_acompanha_reducao(client, setup):
    d = debt(client)
    data = activate(client)
    assert data["active"] and data["status"]["initial_debt"] == "3000.00"
    client.post(f"/api/debts/{d['id']}/payments", json={
        "amount": "600.00", "paid_on": "2026-03-10", "account_id": setup.account["id"],
    })
    s = client.get("/api/recovery").json["status"]
    assert s["current_debt"] == "2400.00" and s["paid"] == "600.00" and s["reduction_pct"] == 20
    assert s["next_debt"] == "Mãe" and s["forecast"]["months"] == 5
    assert s["forecast"]["finish_month"] == "2026-08"
    assert s["evolution"][-1] == {"month": "2026-03", "balance": "2400.00"}
    assert s["evolution"][-2]["balance"] == "3000.00"


def test_desativar_preserva_dados_e_reativar_mantem_inicio(client, setup):
    debt(client)
    activate(client, reserve_minimum="200.00")
    off = client.post("/api/recovery/deactivate").json
    assert off["active"] is False and off["config"]["ended_on"] == "2026-03-15"
    assert off["status"]["initial_debt"] == "3000.00"
    assert client.get("/api/dashboard?month=2026-03").json["recovery_active"] is False

    debt(client, "1000.00")
    on = activate(client, monthly_amount="700.00")
    assert on["active"] and on["status"]["initial_debt"] == "3000.00"
    assert on["config"]["ended_on"] is None and on["config"]["started_on"] == "2026-03-15"


def test_valor_mensal_e_reserva_reduzem_o_disponivel(client, setup):
    debt(client, agreed_amount="100.00", frequency="monthly")
    client.patch("/api/profile", json={"safety_minimum": "50.00"})
    s = client.get("/api/dashboard?month=2026-03").json["summary"]
    assert s["debt_due"] == "100.00" and s["available_to_spend"] == "1650.00"
    activate(client, reserve_minimum="200.00")
    s = client.get("/api/dashboard?month=2026-03").json["summary"]
    assert s["debt_due"] == "500.00" and s["safety_minimum"] == "200.00"
    assert s["available_to_spend"] == "1100.00"
    client.post("/api/recovery/deactivate")
    s = client.get("/api/dashboard?month=2026-03").json["summary"]
    assert s["debt_due"] == "100.00" and s["available_to_spend"] == "1650.00"


def test_pagamento_no_mes_nao_desconta_duas_vezes(client, setup):
    d = debt(client)
    activate(client)
    before = client.get("/api/dashboard?month=2026-03").json["summary"]["available_to_spend"]
    client.post(f"/api/debts/{d['id']}/payments", json={
        "amount": "500.00", "paid_on": "2026-03-12", "account_id": setup.account["id"],
    })
    s = client.get("/api/dashboard?month=2026-03").json["summary"]
    assert s["debt_due"] == "0.00" and s["available_to_spend"] == before == "1300.00"


def test_dividas_prioritarias_vem_primeiro(client, setup):
    client.post("/api/debts", json={
        "name": "Pequena", "creditor": "x", "original_amount": "100.00", "start_date": "2026-01-01",
    })
    big = debt(client)
    data = activate(client, priority_debt_ids=[big["id"]], strategy="snowball")
    assert data["status"]["next_debt"] == "Mãe"


def test_prioritaria_de_outro_usuario_e_recusada(client, make_client, setup):
    d = debt(client)
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    res = other.put("/api/recovery", json={"monthly_amount": "1", "priority_debt_ids": [d["id"]]})
    assert res.status_code == 422


def test_recomendacoes_e_limite_nao_essencial(client, setup):
    salary(client, setup)
    lazer = category(client, "Lazer")
    expense(client, setup, "400.00", cat=lazer, name="Festa")
    expense(client, setup, "300.00", cat=category(client, "Moradia"))
    debt(client)
    s = activate(client, non_essential_limit="250.00")["status"]
    assert s["non_essential"]["spent"] == "400.00"
    assert any("passaram do limite" in t and "lazer" in t for t in s["recommendations"])


def test_nova_compra_parcelada_gera_recomendacao_sem_bloquear(client, setup):
    debt(client)
    activate(client)
    buy(client, card(client), "600.00", 3)
    s = client.get("/api/recovery").json["status"]
    assert any("parcelada" in t for t in s["recommendations"])
    assert any("parcelada" in a["message"] for a in client.get("/api/dashboard?month=2026-03").json["alerts"])


def test_impacto_de_compra_nao_planejada(client, setup):
    debt(client)
    activate(client)
    res = client.post("/api/recovery/impact", json={"amount": "1000.00"}).json
    assert res["months_before"] == 6 and res["months_after"] == 8 and res["delay_months"] == 2
    assert client.post("/api/recovery/impact", json={"amount": "0"}).status_code == 422


def test_meta_de_data_indica_valor_necessario(client, setup):
    debt(client)
    s = activate(client, monthly_amount="100.00", target_date="2026-09-30")["status"]
    assert s["on_target"] is False
    assert any("R$ 500 por mês" in t for t in s["recommendations"])
    s = activate(client, monthly_amount="600.00", target_date="2026-09-30")["status"]
    assert s["on_target"] is True


def test_meta_de_reducao_compara_com_meses_anteriores(client, setup):
    lazer = category(client, "Lazer")
    expense(client, setup, "400.00", "2026-02-10", cat=lazer)
    expense(client, setup, "300.00", "2026-03-10", cat=lazer)
    debt(client)
    s = activate(client, spending_goal_pct=50)["status"]
    assert s["non_essential"]["baseline"] == "400.00"
    assert s["non_essential"]["goal_amount"] == "200.00"
    assert any("meta de redução" in t for t in s["recommendations"])


def test_sem_plano(client, setup):
    assert client.get("/api/recovery").json == {"configured": False, "active": False}
    assert client.post("/api/recovery/deactivate").status_code == 404
    assert client.post("/api/recovery/impact", json={"amount": "1"}).status_code == 404


# Notificações

def test_mesma_situacao_nao_notifica_duas_vezes(client, setup):
    expense(client, setup, "100.00", "2026-02-10", "pending")
    first = notifications(client)
    assert first["unread"] == 1 and "atrasadas" in first["items"][0]["message"]
    assert notifications(client)["unread"] == 1


def test_ler_uma_e_todas(client, setup):
    expense(client, setup, "100.00", "2026-02-10", "pending")
    c = card(client, closing=20, due=25)
    client.patch(f"/api/cards/{c['id']}", json={"credit_limit": "100.00"})
    buy(client, c, "90.00")
    data = notifications(client)
    assert data["unread"] == 2
    assert client.post(f"/api/notifications/{data['items'][0]['id']}/read").status_code == 204
    assert notifications(client)["unread"] == 1
    assert client.post("/api/notifications/read-all").status_code == 204
    data = notifications(client)
    assert data["unread"] == 0 and all(i["read"] for i in data["items"])


def test_notificacao_lida_nao_volta(client, setup):
    expense(client, setup, "100.00", "2026-02-10", "pending")
    notifications(client)
    client.post("/api/notifications/read-all")
    assert notifications(client)["unread"] == 0


def test_orcamento_avisa_perto_e_ao_passar(client, setup):
    lazer = category(client, "Lazer")
    client.put("/api/budgets", json={"category_id": lazer, "amount": "100.00"})
    expense(client, setup, "85.00", cat=lazer)
    assert "85% do orçamento de lazer" in notifications(client)["items"][0]["message"]
    expense(client, setup, "20.00", cat=lazer)
    assert "105% do orçamento de lazer" in notifications(client)["items"][0]["message"]
    assert notifications(client)["unread"] == 2


def test_preferencias_de_limite_e_silencio(client, setup):
    lazer = category(client, "Lazer")
    client.put("/api/budgets", json={"category_id": lazer, "amount": "100.00"})
    expense(client, setup, "60.00", cat=lazer)
    assert notifications(client)["unread"] == 0
    prefs = client.patch("/api/profile", json={"alert_prefs": {"budget_pct": 50}}).json["alert_prefs"]
    assert prefs["budget_pct"] == 50 and prefs["due_days"] == 3
    assert notifications(client)["unread"] == 1
    client.post("/api/notifications/read-all")

    client.patch("/api/profile", json={"alert_prefs": {"muted": ["budget"]}})
    expense(client, setup, "60.00", cat=lazer)
    assert notifications(client)["unread"] == 0
    assert client.patch("/api/profile", json={"alert_prefs": {"muted": ["x"]}}).status_code == 422
    assert client.patch("/api/profile", json={"alert_prefs": {"budget_pct": 5}}).status_code == 422


def test_aumento_de_gastos(client, setup):
    lazer = category(client, "Lazer")
    expense(client, setup, "100.00", "2026-02-10", cat=lazer)
    expense(client, setup, "120.00", "2026-03-10", cat=lazer)
    messages = [i["message"] for i in notifications(client)["items"]]
    assert "Seus gastos com lazer aumentaram 20%." in messages


def test_divida_quitada_vira_conquista(client, setup):
    d = debt(client, "100.00")
    client.post(f"/api/debts/{d['id']}/payments", json={
        "amount": "100.00", "paid_on": "2026-03-10", "account_id": setup.account["id"],
    })
    messages = [i["message"] for i in notifications(client)["items"]]
    assert "Você quitou a dívida Mãe." in messages


def test_limite_diario(client, setup):
    salary(client, setup)  # 13 dias
    expense(client, setup, "150.00", "2026-03-15")
    messages = [i["message"] for i in notifications(client)["items"]]
    assert "Seu orçamento diário está próximo do limite." in messages


def test_pode_aumentar_pagamento(client, setup):
    salary(client, setup)
    debt(client)
    messages = [i["message"] for i in notifications(client)["items"]]
    assert any("aumentar o pagamento" in m for m in messages)


def test_notificacoes_isoladas_por_usuario(client, make_client, setup):
    expense(client, setup, "100.00", "2026-02-10", "pending")
    item = notifications(client)["items"][0]
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    assert notifications(other)["items"] == []
    assert other.post(f"/api/notifications/{item['id']}/read").status_code == 404
