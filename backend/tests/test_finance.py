"""Contas, lançamentos, recorrências e transferências pela API."""
from datetime import date

import pytest

from app.api import finance_common
from app.extensions import db
from app.models import Transaction
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
def account(client):
    register(client)
    return new_account(client)


def new_account(client, name="Conta", balance="1000.00", opening="2026-01-01"):
    res = client.post("/api/accounts", json={
        "name": name, "opening_balance": balance, "opening_date": opening,
    })
    assert res.status_code == 201
    return res.json


def category(client, name, kind="expense"):
    return next(c for c in client.get("/api/categories").json
                if c["name"] == name and c["kind"] == kind)["id"]


def expense(client, account, amount="100.00", day="2026-03-10", **extra):
    body = {
        "kind": "expense", "description": "Mercado", "amount": amount,
        "competence_date": day, "account_id": account["id"],
    }
    return client.post("/api/transactions", json=body | extra)


def salary(client, account=None, amount="5000.00", start="2026-01-01", day=5, **extra):
    res = client.post("/api/recurrences", json={
        "kind": "income", "name": "Salário", "amount": amount, "day_of_month": day,
        "start_date": start, "is_salary": True,
        "account_id": account["id"] if account else None, **extra,
    })
    assert res.status_code == 201, res.json
    return res.json


def items(client, query="kind=income&month=2026-03"):
    return client.get(f"/api/transactions?{query}").json["items"]


def month_items(client, month):
    return items(client, f"kind=income&month={month}")


def confirm(client, tx_id, account, paid_on="2026-03-05", **extra):
    return client.post(f"/api/transactions/{tx_id}/confirm", json={
        "paid_on": paid_on, "account_id": account["id"], **extra,
    })


def balance(client):
    return client.get("/api/dashboard?month=2026-03").json["summary"]["balance"]


# Lançamentos

def test_lancamento_pago_atualiza_saldo_da_conta(client, account):
    assert expense(client, account, "150.25").status_code == 201
    assert client.get("/api/accounts").json[0]["balance"] == "849.75"
    assert balance(client) == "849.75"


def test_pago_exige_conta_e_nao_aceita_data_futura(client, account):
    res = expense(client, account, account_id=None)
    assert res.status_code == 422 and "account_id" in res.json["fields"]
    assert expense(client, account, day="2026-03-20").status_code == 422
    assert expense(client, account, day="2026-03-20", status="pending").status_code == 201


@pytest.mark.parametrize("amount", ["0", "-5", "NaN", "Infinity", "abc"])
def test_rejeita_valor_invalido(client, account, amount):
    assert expense(client, account, amount).status_code == 422


def test_idempotency_key_evita_duplicar(client, account):
    body = {"kind": "expense", "description": "Café", "amount": "9.90",
            "competence_date": "2026-03-10", "account_id": account["id"]}
    headers = WEB | {"Idempotency-Key": "abc-1"}
    first = client.raw.post("/api/transactions", json=body, headers=headers)
    second = client.raw.post("/api/transactions", json=body, headers=headers)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json["id"] == second.json["id"]
    assert client.get("/api/transactions?kind=expense").json["count"] == 1


def test_envios_simultaneos_com_a_mesma_chave_nao_dao_erro(client, account, monkeypatch):
    """A primeira checagem não vê o registro, como acontece quando dois envios chegam juntos."""
    from app.api import transactions

    calls = iter([None])
    monkeypatch.setattr(transactions, "find_by_key", lambda model, key: next(calls, None))
    body = {"kind": "expense", "description": "Café", "amount": "9.90",
            "competence_date": "2026-03-10", "account_id": account["id"]}
    headers = WEB | {"Idempotency-Key": "corrida-1"}
    first = client.raw.post("/api/transactions", json=body, headers=headers)
    second = client.raw.post("/api/transactions", json=body, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 200 and second.json["id"] == first.json["id"]
    assert client.get("/api/transactions?kind=expense").json["count"] == 1


def test_confirmar_e_desfazer(client, account):
    tx = expense(client, account, status="pending").json
    assert balance(client) == "1000.00"
    res = confirm(client, tx["id"], account, "2026-03-11", amount="120.00")
    assert res.json["status"] == "confirmed" and res.json["amount"] == "120.00"
    assert balance(client) == "880.00"
    assert confirm(client, tx["id"], account).status_code == 409
    client.post(f"/api/transactions/{tx['id']}/unconfirm")
    assert balance(client) == "1000.00"


def test_filtros(client, account):
    lazer = category(client, "Lazer")
    expense(client, account, "50.00", description="Cinema 100%", category_id=lazer)
    expense(client, account, "500.00", description="Aluguel")
    expense(client, account, "10.00", day="2026-02-10")

    def listed(query):
        return client.get(f"/api/transactions?{query}").json

    assert listed("month=2026-03")["count"] == 2
    assert listed("month=2026-03")["total"] == "550.00"
    assert listed(f"category_id={lazer}")["count"] == 1
    assert listed("min_amount=100&max_amount=600")["count"] == 1
    assert listed("q=cinema")["count"] == 1
    assert listed("q=%25")["count"] == 1  # % é literal, não curinga
    assert listed("status=pending")["count"] == 0
    assert client.get("/api/transactions?month=abc").status_code == 422
    assert client.get("/api/transactions?category_id=abc").status_code == 422


# Isolamento entre usuários

def test_nao_acessa_registro_de_outro_usuario(client, make_client, account):
    tx = expense(client, account).json
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    assert other.patch(f"/api/transactions/{tx['id']}", json={"amount": "1"}).status_code == 404
    assert other.raw.delete(f"/api/transactions/{tx['id']}", headers=WEB).status_code == 404
    assert other.patch(f"/api/accounts/{account['id']}", json={"name": "x"}).status_code == 404
    assert other.get("/api/accounts").json == []


def test_nao_usa_conta_ou_categoria_de_outro_usuario(client, make_client, account):
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    mine = new_account(other, "Minha")
    assert expense(other, account).status_code == 422
    assert expense(other, mine, category_id=category(client, "Lazer")).status_code == 422


def test_categoria_de_receita_nao_serve_em_despesa(client, account):
    wrong = category(client, "Salário", "income")
    assert expense(client, account, category_id=wrong).status_code == 422


# Recorrências

def test_gera_salario_previsto_sem_contar_como_recebido(client, account):
    salary(client, account)
    rows = items(client)
    assert len(rows) == 1 and rows[0]["status"] == "pending" and rows[0]["is_salary"]
    s = client.get("/api/dashboard?month=2026-03").json["summary"]
    assert s["salary_expected"] == "5000.00" and s["salary_received"] == "0.00"
    assert s["balance"] == "1000.00" and s["available_to_spend"] == "1000.00"


def test_gerar_varias_vezes_nao_duplica(client, account):
    salary(client, account)
    for _ in range(3):
        client.get("/api/dashboard?month=2026-03")
        items(client)
    assert len(items(client)) == 1
    assert db.session.scalar(db.select(db.func.count()).select_from(Transaction)) == 4  # jan a abr


def test_mes_futuro_consultado_gera_sob_demanda(client, account):
    salary(client, account)
    assert month_items(client, "2026-09")[0]["competence_date"] == "2026-09-05"
    assert month_items(client, "2099-01") == []  # além do limite


def test_dia_31_vira_ultimo_dia_do_mes(client, account):
    salary(client, account, day=31)
    assert month_items(client, "2026-02")[0]["competence_date"] == "2026-02-28"


def test_reajuste_nao_altera_meses_anteriores(client, account):
    rec = salary(client, account)
    confirm(client, month_items(client, "2026-01")[0]["id"], account, "2026-01-05")

    res = client.patch(f"/api/recurrences/{rec['id']}", json={"amount": "6000.00"})
    assert res.status_code == 200 and res.json["amount"] == "6000.00"
    assert month_items(client, "2026-01")[0]["amount"] == "5000.00"
    assert month_items(client, "2026-02")[0]["amount"] == "5000.00"
    assert month_items(client, "2026-03")[0]["amount"] == "6000.00"
    assert month_items(client, "2026-05")[0]["amount"] == "6000.00"
    assert [h["amount"] for h in res.json["amount_history"]] == ["5000.00", "6000.00"]


def test_reajuste_futuro_mantem_mes_atual(client, account):
    rec = salary(client, account)
    client.patch(f"/api/recurrences/{rec['id']}",
                 json={"amount": "7000.00", "effective_from": "2026-04"})
    assert items(client)[0]["amount"] == "5000.00"
    assert month_items(client, "2026-04")[0]["amount"] == "7000.00"
    assert client.get("/api/recurrences").json[0]["amount"] == "5000.00"


def test_reajuste_retroativo_e_recusado(client, account):
    rec = salary(client, account)
    res = client.patch(f"/api/recurrences/{rec['id']}",
                       json={"amount": "1.00", "effective_from": "2026-02"})
    assert res.status_code == 422
    assert month_items(client, "2026-02")[0]["amount"] == "5000.00"


def test_confirmado_no_mes_do_reajuste_nao_muda(client, account):
    rec = salary(client, account)
    confirm(client, items(client)[0]["id"], account)
    client.patch(f"/api/recurrences/{rec['id']}", json={"amount": "6000.00"})
    assert items(client)[0]["amount"] == "5000.00"


def test_valor_editado_a_mao_sobrevive_ao_reajuste(client, account):
    rec = salary(client, account)
    tx = month_items(client, "2026-04")[0]
    client.patch(f"/api/transactions/{tx['id']}", json={"amount": "5500.00"})
    client.patch(f"/api/recurrences/{rec['id']}", json={"amount": "6000.00"})
    assert month_items(client, "2026-04")[0]["amount"] == "5500.00"


def test_mudar_o_dia_nao_recria_mes_confirmado(client, account):
    rec = salary(client, account)
    confirm(client, items(client)[0]["id"], account)
    client.patch(f"/api/recurrences/{rec['id']}", json={"day_of_month": 10})
    client.get("/api/dashboard?month=2026-03")
    assert len(items(client)) == 1
    assert items(client)[0]["competence_date"] == "2026-03-05"
    assert month_items(client, "2026-04")[0]["competence_date"] == "2026-04-10"


def test_ocorrencia_apagada_nao_volta(client, account):
    salary(client, account)
    client.raw.delete(f"/api/transactions/{items(client)[0]['id']}", headers=WEB)
    client.get("/api/dashboard?month=2026-03")
    assert items(client) == []
    assert len(month_items(client, "2026-04")) == 1


def test_pausar_e_reativar_nao_cria_meses_da_pausa(client, account):
    rec = salary(client, account)
    client.patch(f"/api/recurrences/{rec['id']}", json={"active": False})
    assert month_items(client, "2026-04") == []
    assert len(month_items(client, "2026-02")) == 1  # passado preservado

    CLOCK["today"] = date(2026, 6, 10)
    client.patch(f"/api/recurrences/{rec['id']}", json={"active": True})
    assert month_items(client, "2026-05") == []
    assert len(month_items(client, "2026-07")) == 1


def test_apagar_regra_preserva_confirmados(client, account):
    rec = salary(client, account)
    confirm(client, month_items(client, "2026-01")[0]["id"], account, "2026-01-05")
    client.raw.delete(f"/api/recurrences/{rec['id']}", headers=WEB)
    assert client.get("/api/recurrences").json == []
    assert len(month_items(client, "2026-01")) == 1
    assert items(client) == []


def test_data_de_termino_remove_pendentes_seguintes(client, account):
    rec = salary(client, account)
    client.patch(f"/api/recurrences/{rec['id']}", json={"end_date": "2026-03-31"})
    assert len(items(client)) == 1
    assert month_items(client, "2026-04") == []


@pytest.mark.parametrize("frequency,start,count", [
    ("weekly", "2026-03-01", 5),
    ("biweekly", "2026-03-01", 3),
    ("yearly", "2025-03-20", 1),
])
def test_frequencias(client, account, frequency, start, count):
    res = client.post("/api/recurrences", json={
        "kind": "expense", "name": "Regra", "amount": "10", "frequency": frequency,
        "start_date": start,
    })
    assert res.status_code == 201
    assert len(items(client, "kind=expense&month=2026-03")) == count


def test_despesa_recorrente_e_fixa(client, account):
    client.post("/api/recurrences", json={
        "kind": "expense", "name": "Internet", "amount": "120.00", "day_of_month": 20,
        "start_date": "2026-03-01",
    })
    s = client.get("/api/dashboard?month=2026-03").json["summary"]
    assert s["expenses_fixed"] == "120.00"
    assert client.get("/api/transactions?fixed=true").json["count"] >= 1


def test_despesa_nao_pode_ser_salario(client, account):
    res = client.post("/api/recurrences", json={
        "kind": "expense", "name": "x", "amount": "1", "day_of_month": 1,
        "start_date": "2026-03-01", "is_salary": True,
    })
    assert res.status_code == 422


# Contas, transferências e categorias

def test_transferencia_nao_e_receita_nem_despesa(client, account):
    savings = new_account(client, "Poupança", "0.00")
    res = client.post("/api/transfers", json={
        "from_account_id": account["id"], "to_account_id": savings["id"],
        "amount": "300.00", "date": "2026-03-10",
    })
    assert res.status_code == 201
    balances = {a["name"]: a["balance"] for a in client.get("/api/accounts").json}
    assert balances == {"Conta": "700.00", "Poupança": "300.00"}
    s = client.get("/api/dashboard?month=2026-03").json["summary"]
    assert s["balance"] == "1000.00" and s["expenses_total"] == "0.00"
    assert s["income_received"] == "0.00"


def test_transferencia_para_a_mesma_conta_e_recusada(client, account):
    assert client.post("/api/transfers", json={
        "from_account_id": account["id"], "to_account_id": account["id"],
        "amount": "1.00", "date": "2026-03-10",
    }).status_code == 422


def test_saldo_real_nao_altera_saldo_calculado(client, account):
    res = client.patch(f"/api/accounts/{account['id']}", json={"real_balance": "950.00"})
    assert res.json["balance"] == "1000.00"
    assert res.json["real_balance"] == "950.00"
    assert res.json["difference"] == "-50.00"
    assert balance(client) == "1000.00"


def test_movimento_antes_da_abertura_nao_altera_saldo(client):
    register(client)
    late = new_account(client, opening="2026-03-01")
    expense(client, late, "200.00", day="2026-02-10")
    assert client.get("/api/accounts").json[0]["balance"] == "1000.00"


def test_conta_com_movimento_nao_pode_ser_excluida(client, account):
    expense(client, account)
    assert client.raw.delete(f"/api/accounts/{account['id']}", headers=WEB).status_code == 409
    assert client.patch(f"/api/accounts/{account['id']}", json={"active": False}).status_code == 200
    assert balance(client) == "0.00"


def test_categoria_personalizada(client, account):
    res = client.post("/api/categories", json={"name": "Pets", "kind": "expense", "icon": "heart"})
    assert res.status_code == 201
    assert client.post("/api/categories", json={"name": "pets", "kind": "expense"}).status_code == 409
    assert expense(client, account, category_id=res.json["id"]).status_code == 201
    assert client.raw.delete(f"/api/categories/{res.json['id']}", headers=WEB).status_code == 409


def test_minimo_de_seguranca_pelo_perfil(client, account):
    res = client.patch("/api/profile", json={"safety_minimum": "200.00"})
    assert res.json["safety_minimum"] == "200.00"
    s = client.get("/api/dashboard?month=2026-03").json["summary"]
    assert s["available_to_spend"] == "800.00"
    assert client.patch("/api/profile", json={"safety_minimum": "-1"}).status_code == 422
