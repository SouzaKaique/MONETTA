"""Relatórios, CSV, backup, tokens do iPhone e cabeçalhos de segurança."""
import json
from datetime import date
from types import SimpleNamespace

import pytest

from app import create_app
from app.api import finance_common, integrations
from app.config import TestConfig
from app.extensions import db
from app.models import ApiToken
from app.services import dashboard as dash

from .conftest import register

CLOCK = {"today": date(2026, 3, 15)}
WEB = {"X-Monetta-Client": "web"}


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    CLOCK["today"] = date(2026, 3, 15)
    today = lambda settings: CLOCK["today"]  # noqa: E731
    monkeypatch.setattr(dash, "today_for", today)
    monkeypatch.setattr(finance_common, "today_for", today)
    monkeypatch.setattr(integrations, "today_for", today)


@pytest.fixture()
def setup(client):
    register(client)
    account = client.post("/api/accounts", json={
        "name": "Conta", "opening_balance": "1000.00", "opening_date": "2026-01-01",
    }).json
    return SimpleNamespace(account=account)


def tx(client, setup, kind, amount, day, category=None, name="Lançamento", status="confirmed"):
    res = client.post("/api/transactions", json={
        "kind": kind, "description": name, "amount": amount, "competence_date": day,
        "account_id": setup.account["id"], "category_id": category, "status": status,
    })
    assert res.status_code == 201, res.json


def category(client, name):
    return next(c["id"] for c in client.get("/api/categories").json
                if c["name"] == name and c["kind"] == "expense")


def card(client):
    return client.post("/api/cards", json={
        "name": "Nubank", "credit_limit": "3000.00", "closing_day": 20, "due_day": 25,
    }).json


def buy(client, c, amount="300.00", count=1, day="2026-03-10", name="Compra"):
    return client.post(f"/api/cards/{c['id']}/purchases", json={
        "description": name, "total_amount": amount, "installment_count": count, "purchase_date": day,
    })


def debt(client, amount="1000.00"):
    return client.post("/api/debts", json={
        "name": "Mãe", "creditor": "Maria", "original_amount": amount, "start_date": "2026-01-10",
    }).json


def report(client, period="month", month="2026-03"):
    res = client.get(f"/api/reports?period={period}&month={month}")
    assert res.status_code == 200, res.json
    return res.json


# Relatórios e séries

def test_totais_do_mes_contam_cada_valor_uma_vez(client, setup):
    tx(client, setup, "income", "4000.00", "2026-03-05")
    tx(client, setup, "expense", "500.00", "2026-03-06", category(client, "Moradia"))
    buy(client, card(client), "300.00")
    d = debt(client)
    client.post(f"/api/debts/{d['id']}/payments", json={
        "amount": "200.00", "paid_on": "2026-03-10", "account_id": setup.account["id"],
    })
    t = report(client)["totals"]
    assert t["income"] == "4000.00" and t["expenses"] == "800.00" and t["cards"] == "300.00"
    assert t["debt_paid"] == "200.00" and t["result"] == "3000.00" and t["savings_pct"] == 75


def test_pagar_fatura_nao_muda_o_relatorio(client, setup):
    tx(client, setup, "income", "1000.00", "2026-03-05")
    c = card(client)
    buy(client, c, "300.00")
    before = report(client)["totals"]
    invoice = client.get(f"/api/cards/{c['id']}").json["invoices"][0]
    client.post(f"/api/invoices/{invoice['id']}/payments", json={
        "amount": "300.00", "paid_on": "2026-03-15", "account_id": setup.account["id"],
    })
    assert report(client)["totals"] == before


def test_filtros_de_periodo(client, setup):
    tx(client, setup, "expense", "100.00", "2026-01-10")
    tx(client, setup, "expense", "200.00", "2026-03-10")
    assert report(client, "month")["totals"]["expenses"] == "200.00"
    quarter = report(client, "quarter")
    assert quarter["totals"]["expenses"] == "300.00"
    assert quarter["start"] == "2026-01-01" and quarter["end"] == "2026-03-31"
    year = report(client, "year")
    assert year["end"] == "2026-12-31" and len(year["evolution"]) == 12


def test_evolucao_de_saldo_dividas_e_futuro_sem_saldo(client, setup):
    d = debt(client)
    tx(client, setup, "expense", "100.00", "2026-02-10")
    client.post(f"/api/debts/{d['id']}/payments", json={
        "amount": "300.00", "paid_on": "2026-03-10", "account_id": setup.account["id"],
    })
    rows = {r["month"]: r for r in report(client, "year")["evolution"]}
    assert rows["2026-02"]["balance"] == "900.00" and rows["2026-02"]["debt_balance"] == "1000.00"
    assert rows["2026-03"]["balance"] == "600.00" and rows["2026-03"]["debt_balance"] == "700.00"
    assert rows["2026-04"]["balance"] is None and rows["2026-04"]["debt_balance"] is None


def test_evolucao_do_mes_mostra_seis_meses(client, setup):
    rows = report(client)["evolution"]
    assert len(rows) == 6 and rows[-1]["month"] == "2026-03" and rows[0]["month"] == "2025-10"


def test_distribuicao_fecha_com_a_renda(client, setup):
    tx(client, setup, "income", "1000.00", "2026-03-05")
    tx(client, setup, "expense", "300.00", "2026-03-06", category(client, "Moradia"))
    tx(client, setup, "expense", "100.00", "2026-03-06", category(client, "Lazer"))
    parts = {d["key"]: d["amount"] for d in report(client)["distribution"]}
    assert parts == {"essential": "300.00", "variable": "100.00", "cards": "0.00",
                     "debts": "0.00", "saved": "0.00", "free": "600.00"}


def test_insights_e_historico_de_pagamentos(client, setup):
    tx(client, setup, "income", "1000.00", "2026-03-05")
    tx(client, setup, "expense", "100.00", "2026-02-10")
    tx(client, setup, "expense", "150.00", "2026-03-10", category(client, "Lazer"))
    d = debt(client)
    client.post(f"/api/debts/{d['id']}/payments", json={"amount": "50.00", "paid_on": "2026-03-10"})
    data = report(client)
    assert "Suas despesas subiram 50% em relação ao período anterior." in data["insights"]
    assert "Sua maior categoria de gastos foi lazer." in data["insights"]
    assert data["debt_payments"] == [{"date": "2026-03-10", "debt": "Mãe", "amount": "50.00"}]


def test_progresso_da_wishlist(client, setup):
    item = client.post("/api/wishlist", json={"name": "Fone", "price": "1000.00"}).json
    client.post(f"/api/wishlist/{item['id']}/contributions", json={
        "amount": "250.00", "contributed_on": "2026-03-10",
    })
    assert report(client)["wishlist"] == [
        {"name": "Fone", "saved": "250.00", "target": "1000.00", "pct": 25}
    ]


def test_dashboard_traz_series_e_distribuicao(client, setup):
    tx(client, setup, "income", "1000.00", "2026-03-05")
    buy(client, card(client), "300.00")
    data = client.get("/api/dashboard?month=2026-03").json
    last = data["history"][-1]
    assert last["cards"] == "300.00" and last["balance"] == "2000.00"
    assert last["commitment_pct"] == 30
    assert {d["key"] for d in data["distribution"]} >= {"essential", "cards", "free"}


def test_periodo_invalido(client, setup):
    assert client.get("/api/reports?period=x").status_code == 400
    assert client.get("/api/reports?month=abc").status_code == 400


# CSV

def test_csv_abre_no_excel_em_portugues(client, setup):
    tx(client, setup, "expense", "1234.50", "2026-03-10", name="Mercado")
    res = client.get("/api/export/lancamentos.csv")
    assert res.mimetype == "text/csv"
    assert "attachment" in res.headers["Content-Disposition"]
    text = res.data.decode("utf-8")
    assert text.startswith("﻿Data;Tipo;Descrição")
    assert "10/03/2026;Despesa;Mercado;;Conta;1234,50;Confirmado;10/03/2026;Não" in text


@pytest.mark.parametrize("name", ["=HYPERLINK(1)", "+1+1", "-2", "@SUM(A1)"])
def test_csv_neutraliza_formulas(client, setup, name):
    tx(client, setup, "expense", "10.00", "2026-03-10", name=name)
    text = client.get("/api/export/lancamentos.csv").data.decode("utf-8")
    assert f";'{name};" in text


def test_csv_filtra_periodo(client, setup):
    tx(client, setup, "expense", "10.00", "2026-01-10", name="Antigo")
    tx(client, setup, "expense", "10.00", "2026-03-10", name="Novo")
    text = client.get("/api/export/lancamentos.csv?from=2026-03-01&to=2026-03-31").data.decode()
    assert "Novo" in text and "Antigo" not in text
    assert client.get("/api/export/lancamentos.csv?from=abc").status_code == 422


@pytest.mark.parametrize("dataset", [
    "compras-cartao", "faturas", "dividas", "pagamentos-dividas", "transferencias", "wishlist",
])
def test_todos_os_conjuntos_exportam(client, setup, dataset):
    c = card(client)
    buy(client, c)
    d = debt(client)
    client.post(f"/api/debts/{d['id']}/payments", json={"amount": "1.00", "paid_on": "2026-03-10"})
    client.post("/api/wishlist", json={"name": "Fone", "price": "10.00"})
    assert client.get(f"/api/export/{dataset}.csv").status_code == 200


def test_csv_desconhecido_e_isolamento(client, make_client, setup):
    tx(client, setup, "expense", "10.00", "2026-03-10", name="Segredo")
    assert client.get("/api/export/usuarios.csv").status_code == 404
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    assert "Segredo" not in other.get("/api/export/lancamentos.csv").data.decode()
    assert make_client().get("/api/export/lancamentos.csv").status_code == 401


# Backup

def full_data(client, setup):
    moradia = category(client, "Moradia")
    client.post("/api/recurrences", json={
        "kind": "income", "name": "Salário", "amount": "4000.00", "day_of_month": 28,
        "start_date": "2026-03-01", "is_salary": True, "account_id": setup.account["id"],
    })
    tx(client, setup, "expense", "700.00", "2026-03-05", moradia, "Aluguel")
    c = card(client)
    buy(client, c, "600.00", 3)
    invoice = client.get(f"/api/cards/{c['id']}").json["invoices"][0]
    client.post(f"/api/invoices/{invoice['id']}/payments", json={
        "amount": "100.00", "paid_on": "2026-03-15", "account_id": setup.account["id"],
    })
    d = debt(client)
    client.post(f"/api/debts/{d['id']}/payments", json={
        "amount": "200.00", "paid_on": "2026-03-10", "account_id": setup.account["id"],
    })
    client.put("/api/budgets", json={"category_id": moradia, "amount": "900.00"})
    client.put("/api/recovery", json={"monthly_amount": "300.00", "priority_debt_ids": [d["id"]]})
    item = client.post("/api/wishlist", json={"name": "Fone", "price": "1000.00"}).json
    client.post(f"/api/wishlist/{item['id']}/contributions", json={
        "amount": "250.00", "contributed_on": "2026-03-10",
    })
    client.patch("/api/profile", json={"safety_minimum": "150.00"})


def test_backup_e_restauracao_recriam_os_mesmos_numeros(client, make_client, setup):
    full_data(client, setup)
    payload = client.get("/api/backup").json
    assert client.get("/api/backup").headers["Content-Disposition"].startswith("attachment")
    original = client.get("/api/dashboard?month=2026-03").json

    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    res = other.post("/api/backup/restore", json=payload)
    assert res.status_code == 200, res.json
    restored = other.get("/api/dashboard?month=2026-03").json
    assert restored["summary"] == original["summary"]
    assert restored["history"] == original["history"]
    assert other.get("/api/recovery").json["status"]["next_debt"] == "Mãe"
    assert len(other.get("/api/categories").json) == len(client.get("/api/categories").json)

    # Os dois usuários ficam independentes: novos identificadores, nada compartilhado.
    assert other.get("/api/accounts").json[0]["id"] != setup.account["id"]
    other.patch(f"/api/accounts/{other.get('/api/accounts').json[0]['id']}", json={"name": "Nova"})
    assert client.get("/api/accounts").json[0]["name"] == "Conta"


def test_restauracao_so_em_conta_vazia(client, setup):
    payload = client.get("/api/backup").json
    res = client.post("/api/backup/restore", json=payload)
    assert res.status_code == 422 and "conta sem dados" in res.json["error"]
    assert len(client.get("/api/accounts").json) == 1


def invalid_payloads(payload):
    unknown_table = {**payload, "tables": {"users": []}}
    extra_field = json.loads(json.dumps(payload))
    extra_field["tables"]["accounts"][0]["user_id"] = "x"
    bad_type = json.loads(json.dumps(payload))
    bad_type["tables"]["accounts"][0]["opening_balance"] = "NaN"
    return [{}, {"app": "outro"}, {**payload, "version": 99}, unknown_table, extra_field, bad_type]


def test_arquivo_invalido_e_recusado_sem_alterar_nada(client, make_client, setup):
    payload = client.get("/api/backup").json
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    categories = len(other.get("/api/categories").json)
    for bad in invalid_payloads(payload):
        assert other.post("/api/backup/restore", json=bad).status_code == 422
    assert other.get("/api/accounts").json == []
    assert len(other.get("/api/categories").json) == categories


def test_backup_nao_alcanca_dados_de_outro_usuario(client, make_client, setup):
    """Referência a uma conta real de outra pessoa não existe dentro do arquivo."""
    tx(client, setup, "expense", "10.00", "2026-03-10")
    payload = client.get("/api/backup").json
    payload["tables"]["accounts"] = []
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    res = other.post("/api/backup/restore", json=payload)
    assert res.status_code == 422 and "inexistente" in res.json["error"]


def test_backup_nao_inclui_senha_nem_sessoes(client, setup):
    text = client.get("/api/backup").data.decode()
    assert "argon2" not in text and "token_hash" not in text and "password" not in text


# Tokens e lançamentos externos

@pytest.fixture()
def token(client, setup):
    res = client.post("/api/tokens", json={"name": "iPhone"})
    assert res.status_code == 201
    return res.json["token"]


def send(client, token, **body):
    body = {"amount": "12.50", "description": "Café"} | body
    return client.raw.post("/api/integrations/expenses", json=body,
                           headers={"Authorization": f"Bearer {token}"})


def test_token_aparece_uma_vez_e_fica_so_o_hash(client, token):
    stored = db.session.scalar(db.select(ApiToken))
    assert stored.token_hash != token and token not in str(client.get("/api/tokens").json)
    assert client.get("/api/tokens").json[0]["prefix"] == token[:10]


def test_lancamento_pelo_atalho_atualiza_indicadores(client, setup, token):
    res = send(client, token, amount="12,50", category="alimentação", payment_method="pix")
    assert res.status_code == 201 and res.json["ok"] and "R$ 12,50" in res.json["message"]
    item = client.get("/api/transactions?kind=expense").json["items"][0]
    assert item["status"] == "confirmed" and item["category_name"] == "Alimentação"
    assert item["account_name"] == "Conta" and item["payment_method"] == "pix"
    assert client.get("/api/dashboard?month=2026-03").json["summary"]["balance"] == "987.50"


@pytest.mark.parametrize("value,expected", [
    ("12.5", "12.50"), ("1.234,56", "1234.56"), ("R$ 9,90", "9.90"), (15, "15.00"),
])
def test_atalho_aceita_formatos_de_valor(client, token, value, expected):
    assert send(client, token, amount=value, description=f"v{value}").status_code == 201
    assert client.get("/api/transactions?kind=expense").json["items"][0]["amount"] == expected


@pytest.mark.parametrize("value", ["abc", "0", "-5", "NaN", "Infinity"])
def test_atalho_recusa_valor_invalido(client, token, value):
    assert send(client, token, amount=value).status_code == 422


def test_atalho_nao_duplica(client, token):
    first = send(client, token, request_id="abc")
    second = send(client, token, request_id="abc")
    assert first.status_code == 201 and second.status_code == 200 and second.json["duplicate"]
    third = send(client, token)
    fourth = send(client, token)
    assert third.status_code == 201 and fourth.json["duplicate"]
    assert client.get("/api/transactions?kind=expense").json["count"] == 2


def test_atalho_no_cartao_com_parcelas(client, token):
    card(client)
    res = send(client, token, amount="300.00", card="nubank", installments=3)
    assert res.status_code == 201
    assert client.get("/api/cards").json[0]["used"] == "300.00"
    assert client.get("/api/transactions?kind=expense").json["count"] == 0
    assert send(client, token, card="Inexistente").status_code == 422


def test_varias_contas_sem_escolha_fica_pendente(client, setup, token):
    client.post("/api/accounts", json={"name": "Outra", "opening_date": "2026-01-01"})
    send(client, token)
    item = client.get("/api/transactions?kind=expense").json["items"][0]
    assert item["status"] == "pending" and item["account_name"] is None
    assert send(client, token, account="Outra", description="x").status_code == 201
    assert send(client, token, account="Nada", description="y").status_code == 422


def test_opcoes_para_o_atalho(client, token):
    card(client)
    res = client.raw.get("/api/integrations/options", headers={"Authorization": f"Bearer {token}"})
    assert "Lazer" in res.json["categories"]
    assert res.json["accounts"] == ["Conta"] and res.json["cards"] == ["Nubank"]


def test_token_revogado_para_de_funcionar(client, token):
    assert send(client, token).status_code == 201
    token_id = client.get("/api/tokens").json[0]["id"]
    assert client.raw.delete(f"/api/tokens/{token_id}", headers=WEB).status_code == 204
    assert send(client, token, description="b").status_code == 401
    assert client.get("/api/tokens").json == []


@pytest.mark.parametrize("header", [{}, {"Authorization": "Bearer x"}, {"Authorization": "Bearer mt_falso"}])
def test_sem_token_valido_nao_entra(client, setup, header):
    res = client.raw.post("/api/integrations/expenses", json={"amount": "1", "description": "x"}, headers=header)
    assert res.status_code == 401


def test_token_so_serve_para_integracoes(client, token):
    headers = {"Authorization": f"Bearer {token}"} | WEB
    other = client.raw.application.test_client()
    assert other.get("/api/dashboard", headers=headers).status_code == 401
    assert other.get("/api/auth/me", headers=headers).status_code == 401


def test_token_nao_cria_outro_token(client, token):
    other = client.raw.application.test_client()
    res = other.post("/api/tokens", json={"name": "x"},
                     headers=WEB | {"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


def test_token_de_outro_usuario_nao_pode_ser_revogado(client, make_client, token):
    token_id = client.get("/api/tokens").json[0]["id"]
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    assert other.raw.delete(f"/api/tokens/{token_id}", headers=WEB).status_code == 404


def test_limite_de_requisicoes_do_token(client, token):
    for number in range(integrations.REQUESTS_PER_MINUTE):
        assert send(client, token, description=f"d{number}").status_code == 201
    assert send(client, token, description="excesso").status_code == 429


def test_limite_de_tokens(client, setup):
    for number in range(integrations.MAX_TOKENS):
        assert client.post("/api/tokens", json={"name": f"t{number}"}).status_code == 201
    assert client.post("/api/tokens", json={"name": "x"}).status_code == 409


# Segurança

def test_limite_de_login_por_endereco(client, setup):
    body = {"email": "ninguem@example.com", "password": "errada-123"}
    for _ in range(20):
        client.post("/api/auth/login", json=body)
    assert client.post("/api/auth/login", json=body).status_code == 429


def test_erros_saem_em_portugues_sem_detalhes_internos(client):
    assert client.get("/api/dashboard").json == {"error": "Entre na sua conta para continuar."}
    assert client.get("/api/nao-existe").json == {"error": "Não encontrado."}


def test_cabecalhos_de_seguranca(client):
    res = client.get("/api/health")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Cache-Control"] == "no-store"


class ProductionConfig(TestConfig):
    SERVE_FRONTEND = True
    PUBLIC_URL = "https://monetta.example.com"


def test_modo_producao_serve_app_com_politica_de_seguranca(app, tmp_path, monkeypatch):
    import app as package
    (tmp_path / "index.html").write_text("<html>MONETTA</html>", encoding="utf8")
    (tmp_path / "main.js").write_text("ok", encoding="utf8")
    (tmp_path.parent / "segredo.txt").write_text("segredo", encoding="utf8")
    monkeypatch.setattr(package, "FRONTEND_DIR", tmp_path)
    web = create_app(ProductionConfig).test_client()

    page = web.get("/planejamento")
    assert b"MONETTA" in page.data
    assert "script-src 'self'" in page.headers["Content-Security-Policy"]
    assert "unsafe-eval" not in page.headers["Content-Security-Policy"]
    assert page.headers["Strict-Transport-Security"].startswith("max-age=")
    assert web.get("/main.js").data == b"ok"
    assert b"segredo" not in web.get("/../segredo.txt").data
    assert b"segredo" not in web.get("/%2e%2e/segredo.txt").data
    assert web.get("/api/nao-existe").status_code == 404


def test_cookie_seguro_em_https(app):
    web = create_app(ProductionConfig).test_client()
    res = web.post("/api/auth/register", headers=WEB, json={
        "account_name": "Ana", "email": "ana@example.com", "password": "senha-de-teste-1",
    })
    cookie = res.headers["Set-Cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie


