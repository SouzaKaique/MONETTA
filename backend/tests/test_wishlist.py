"""Wishlist: metas, compra sem duplicidade, imagens e "Posso comprar?"."""
from datetime import date
from io import BytesIO
from types import SimpleNamespace

import pytest

from app.api import finance_common
from app.services import dashboard as dash

from .conftest import register

CLOCK = {"today": date(2026, 3, 15)}
WEB = {"X-Monetta-Client": "web"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    CLOCK["today"] = date(2026, 3, 15)
    monkeypatch.setattr(dash, "today_for", lambda settings: CLOCK["today"])
    monkeypatch.setattr(finance_common, "today_for", lambda settings: CLOCK["today"])


@pytest.fixture()
def setup(client):
    register(client)
    account = client.post("/api/accounts", json={
        "name": "Conta", "opening_balance": "2000.00", "opening_date": "2026-01-01",
    }).json
    return SimpleNamespace(account=account)


def item(client, name="Fone", price="1000.00", **extra):
    res = client.post("/api/wishlist", json={"name": name, "price": price, **extra})
    assert res.status_code == 201, res.json
    return res.json


def save(client, it, amount="300.00", kind="deposit", day="2026-03-10"):
    return client.post(f"/api/wishlist/{it['id']}/contributions", json={
        "amount": amount, "kind": kind, "contributed_on": day,
    })


def listed(client):
    return client.get("/api/wishlist").json


def summary(client):
    return client.get("/api/dashboard?month=2026-03").json["summary"]


def salary(client, setup, day=28, amount="4000.00"):
    res = client.post("/api/recurrences", json={
        "kind": "income", "name": "Salário", "amount": amount, "day_of_month": day,
        "start_date": "2026-03-01", "is_salary": True, "account_id": setup.account["id"],
    })
    assert res.status_code == 201


def until(client):
    return client.get("/api/planning/until-salary").json


def card(client, limit="3000.00"):
    return client.post("/api/cards", json={
        "name": "Nubank", "credit_limit": limit, "closing_day": 20, "due_day": 25,
    }).json


def check(client, **body):
    res = client.post("/api/wishlist/can-buy", json=body)
    assert res.status_code == 200, res.json
    return res.json


def status_of(result, label):
    return next(c["status"] for c in result["checks"] if c["label"] == label)


# Itens e metas

def test_criar_item_cria_meta_com_o_preco(client, setup):
    it = item(client, store_url="https://loja.example.com/fone")
    assert it["status"] == "desired" and it["target_amount"] == "1000.00"
    assert it["saved"] == "0.00" and it["remaining"] == "1000.00" and it["pct"] == 0
    assert it["added_on"] == "2026-03-15"


@pytest.mark.parametrize("field,value", [
    ("store_url", "javascript:alert(1)"),
    ("store_url", "ftp://loja.example.com"),
    ("image_url", "http://sem-https.example.com/a.png"),
    ("image_url", "data:image/png;base64,AAAA"),
])
def test_links_inseguros_sao_recusados(client, setup, field, value):
    res = client.post("/api/wishlist", json={"name": "x", "price": "1", field: value})
    assert res.status_code == 422


def test_guardar_nao_e_despesa_nem_altera_conta(client, setup):
    it = item(client)
    res = save(client, it, "300.00")
    assert res.status_code == 201
    assert res.json["saved"] == "300.00" and res.json["pct"] == 30 and res.json["status"] == "saving"
    s = summary(client)
    assert s["balance"] == "2000.00" and s["expenses_total"] == "0.00"
    assert s["saved_total"] == "300.00" and s["reserves"] == "300.00"
    assert s["available_to_spend"] == "1700.00"
    assert client.get("/api/accounts").json[0]["balance"] == "2000.00"


def test_retirar_devolve_ao_disponivel(client, setup):
    it = item(client)
    save(client, it, "300.00")
    assert save(client, it, "100.00", "withdraw").json["saved"] == "200.00"
    assert summary(client)["available_to_spend"] == "1800.00"
    assert save(client, it, "500.00", "withdraw").status_code == 422


def test_guardar_nao_aceita_data_futura_ou_item_encerrado(client, setup):
    it = item(client)
    assert save(client, it, day="2026-03-16").status_code == 422
    client.post(f"/api/wishlist/{it['id']}/give-up")
    assert save(client, it).status_code == 409


def test_guardar_nao_duplica_com_mesma_chave(client, setup):
    it = item(client)
    body = {"amount": "100.00", "contributed_on": "2026-03-10"}
    headers = WEB | {"Idempotency-Key": "w-1"}
    url = f"/api/wishlist/{it['id']}/contributions"
    assert client.raw.post(url, json=body, headers=headers).status_code == 201
    assert client.raw.post(url, json=body, headers=headers).status_code == 200
    assert listed(client)["items"][0]["saved"] == "100.00"


def test_reserva_planejada_abate_o_que_foi_guardado(client, setup):
    salary(client, setup)
    client.patch("/api/profile", json={"planned_reserve": "200.00"})
    assert until(client)["available"] == "1800.00"
    save(client, item(client), "150.00")
    s = until(client)
    assert s["available"] == "1800.00"  # os 150 guardados fazem parte dos 200 de reserva
    assert {c["kind"]: c["amount"] for c in s["commitments"]} == {"reserve": "50.00", "saved": "150.00"}
    save(client, listed(client)["items"][0], "100.00")
    assert until(client)["available"] == "1750.00"
    assert {c["kind"] for c in until(client)["commitments"]} == {"saved"}


def test_previsao_pelo_valor_mensal(client, setup):
    it = item(client, monthly_amount="150.00")
    assert it["forecast"] == {"months": 7, "month": "2026-10"}
    assert save(client, it, "400.00").json["forecast"]["months"] == 4


def test_previsao_pela_media_e_sem_ritmo(client, setup):
    it = item(client, "A")
    assert it["forecast"]["months"] is None
    assert save(client, it, "300.00").json["forecast"]["months"] == 7  # 100 por mês


def test_meta_diferente_do_preco_e_meta_atingida(client, setup):
    it = item(client, target_amount="200.00")
    res = save(client, it, "250.00").json
    assert res["reached"] and res["pct"] == 100 and res["remaining"] == "0.00"
    assert res["forecast"]["months"] == 0
    messages = [n["message"] for n in client.get("/api/notifications").json["items"]]
    assert "Você atingiu a meta de Fone." in messages


def test_indicadores(client, setup):
    a = item(client, "A", "1000.00", monthly_amount="100.00")
    item(client, "B", "500.00", monthly_amount="400.00")
    c = item(client, "C", "300.00")
    d = item(client, "D", "50.00")
    save(client, a, "200.00")
    client.post(f"/api/wishlist/{c['id']}/buy", json={
        "amount": "300.00", "bought_on": "2026-03-10", "account_id": setup.account["id"],
    })
    client.post(f"/api/wishlist/{d['id']}/give-up")
    ind = listed(client)["indicators"]
    assert ind == {
        "total_value": "1500.00", "total_saved": "200.00", "count": 2, "completed": 1,
        "next_purchase": "B",
    }


# Compra

def test_comprar_a_vista_registra_despesa_uma_vez_e_libera_guardado(client, setup):
    it = item(client)
    save(client, it, "1000.00")
    res = client.post(f"/api/wishlist/{it['id']}/buy", json={
        "amount": "950.00", "bought_on": "2026-03-14", "account_id": setup.account["id"],
    })
    assert res.status_code == 200 and res.json["status"] == "bought"
    s = summary(client)
    assert s["expenses_total"] == "950.00" and s["balance"] == "1050.00"
    assert s["saved_total"] == "0.00" and s["available_to_spend"] == "1050.00"
    assert client.get("/api/transactions?kind=expense").json["count"] == 1


def test_comprar_no_cartao_gera_parcelas_e_nao_mexe_na_conta(client, setup):
    it = item(client, price="900.00")
    c = card(client)
    res = client.post(f"/api/wishlist/{it['id']}/buy", json={
        "amount": "900.00", "bought_on": "2026-03-10", "card_id": c["id"], "installments": 3,
    })
    assert res.status_code == 200
    s = summary(client)
    assert s["balance"] == "2000.00" and s["card_commitment"] == "300.00"
    assert client.get("/api/transactions?kind=expense").json["count"] == 0
    assert client.get("/api/cards").json[0]["used"] == "900.00"


def test_compra_nao_repete_e_exige_uma_forma_de_pagamento(client, setup):
    it = item(client)
    url = f"/api/wishlist/{it['id']}/buy"
    pay = {"amount": "10.00", "bought_on": "2026-03-10"}
    assert client.post(url, json=pay).status_code == 422
    c = card(client)
    both = pay | {"account_id": setup.account["id"], "card_id": c["id"]}
    assert client.post(url, json=both).status_code == 422
    assert client.post(url, json=pay | {"bought_on": "2026-03-16", "account_id": setup.account["id"]}).status_code == 422
    assert client.post(url, json=pay | {"account_id": setup.account["id"]}).status_code == 200
    assert client.post(url, json=pay | {"account_id": setup.account["id"]}).status_code == 409
    assert client.get("/api/transactions?kind=expense").json["count"] == 1


def test_desistir_libera_guardado_e_preserva_historico(client, setup):
    it = item(client)
    save(client, it, "300.00")
    res = client.post(f"/api/wishlist/{it['id']}/give-up").json
    assert res["status"] == "given_up" and len(res["contributions"]) == 1
    assert summary(client)["saved_total"] == "0.00"
    assert summary(client)["available_to_spend"] == "2000.00"
    back = client.post(f"/api/wishlist/{it['id']}/reopen").json
    assert back["status"] == "saving" and summary(client)["saved_total"] == "300.00"


def test_desfazer_compra_a_vista_remove_a_despesa(client, setup):
    it = item(client)
    save(client, it, "1000.00")
    client.post(f"/api/wishlist/{it['id']}/buy", json={
        "amount": "1000.00", "bought_on": "2026-03-14", "account_id": setup.account["id"],
    })
    before = summary(client)
    assert before["balance"] == "1000.00" and before["saved_total"] == "0.00"
    res = client.post(f"/api/wishlist/{it['id']}/reopen").json
    assert res["status"] == "saving" and res["bought_on"] is None
    s = summary(client)
    assert s["balance"] == "2000.00" and s["expenses_total"] == "0.00"
    assert s["saved_total"] == "1000.00" and s["available_to_spend"] == "1000.00"
    assert client.get("/api/transactions?kind=expense").json["count"] == 0


def test_desfazer_compra_no_cartao_remove_parcelas(client, setup):
    it = item(client, price="900.00")
    c = card(client)
    client.post(f"/api/wishlist/{it['id']}/buy", json={
        "amount": "900.00", "bought_on": "2026-03-10", "card_id": c["id"], "installments": 3,
    })
    assert client.post(f"/api/wishlist/{it['id']}/reopen").status_code == 200
    assert client.get("/api/cards").json[0]["used"] == "0.00"
    assert client.get(f"/api/cards/{c['id']}").json["invoices"] == []


def test_nao_desfaz_compra_com_fatura_paga(client, setup):
    it = item(client, price="300.00")
    c = card(client)
    client.post(f"/api/wishlist/{it['id']}/buy", json={
        "amount": "300.00", "bought_on": "2026-03-10", "card_id": c["id"],
    })
    invoice = client.get(f"/api/cards/{c['id']}").json["invoices"][0]
    client.post(f"/api/invoices/{invoice['id']}/payments", json={
        "amount": "100.00", "paid_on": "2026-03-15", "account_id": setup.account["id"],
    })
    assert client.post(f"/api/wishlist/{it['id']}/reopen").status_code == 409
    assert listed(client)["items"][0]["status"] == "bought"


def test_despesa_apagada_a_mao_nao_impede_reabrir(client, setup):
    it = item(client)
    client.post(f"/api/wishlist/{it['id']}/buy", json={
        "amount": "1000.00", "bought_on": "2026-03-14", "account_id": setup.account["id"],
    })
    tx = client.get("/api/transactions?kind=expense").json["items"][0]
    client.raw.delete(f"/api/transactions/{tx['id']}", headers=WEB)
    assert client.post(f"/api/wishlist/{it['id']}/reopen").status_code == 200


def test_status_manual_nao_reabre_item_encerrado(client, setup):
    it = item(client)
    client.post(f"/api/wishlist/{it['id']}/give-up")
    assert client.patch(f"/api/wishlist/{it['id']}", json={"status": "planning"}).status_code == 409
    assert client.patch(f"/api/wishlist/{it['id']}", json={"status": "bought"}).status_code == 422


def test_excluir_item_com_valor_guardado_e_recusado(client, setup):
    it = item(client)
    save(client, it)
    assert client.raw.delete(f"/api/wishlist/{it['id']}", headers=WEB).status_code == 409
    other = item(client, "B")
    assert client.raw.delete(f"/api/wishlist/{other['id']}", headers=WEB).status_code == 204


# Planejamento e recuperação

def test_planejamento_mostra_wishlist_sem_somar_duas_vezes(client, setup):
    salary(client, setup)
    client.patch("/api/profile", json={"planned_reserve": "100.00"})
    it = item(client, monthly_amount="200.00")
    save(client, it, "150.00")
    data = client.get("/api/planning").json
    parts = {d["key"]: d["amount"] for d in data["distribution"]}
    assert parts["wishlist"] == "200.00" and parts["reserve"] == "0.00"
    assert parts["free"] == "3800.00" and data["saved_total"] == "150.00"


def test_recuperacao_reduz_wishlist_e_sugere_adiar(client, setup):
    salary(client, setup)
    item(client, monthly_amount="200.00")
    client.post("/api/debts", json={
        "name": "Mãe", "creditor": "M", "original_amount": "3000.00", "start_date": "2026-01-01",
    })
    plan = client.put("/api/recovery", json={"monthly_amount": "500.00"}).json
    assert any("adiar a wishlist" in t and "R$ 200,00" in t for t in plan["status"]["recommendations"])
    parts = {d["key"]: d["amount"] for d in client.get("/api/planning").json["distribution"]}
    assert parts["wishlist"] == "0.00"


def test_calendario_mostra_meta_do_item(client, setup):
    item(client, target_date="2026-03-30")
    events = client.get("/api/calendar?month=2026-03").json["events"]
    assert [(e["type"], e["title"]) for e in events] == [("goal", "Meta: Fone")]


# Posso comprar?

def test_compra_dentro_do_planejamento(client, setup):
    salary(client, setup, day=20)
    client.patch("/api/profile", json={"safety_minimum": "100.00"})
    res = check(client, amount="300.00")
    assert res["verdict"] == "buy" and res["message"] == "Compra dentro do planejamento"
    assert res["need"] == "300.00"


def test_compra_que_usa_boa_parte_exige_atencao(client, setup):
    salary(client, setup, day=20)
    client.patch("/api/profile", json={"safety_minimum": "100.00"})
    res = check(client, amount="1500.00")
    assert res["verdict"] == "attention" and res["message"] == "Compra possível, mas exige atenção"
    assert status_of(res, "Saldo disponível") == "warning"


def test_compra_acima_do_disponivel_e_melhor_adiar(client, setup):
    salary(client, setup, day=20)
    res = check(client, amount="2500.00")
    assert res["verdict"] == "postpone" and res["message"] == "Melhor adiar"
    assert status_of(res, "Saldo disponível") == "bad"


def test_valor_guardado_conta_para_o_proprio_item(client, setup):
    salary(client, setup, day=20)
    client.patch("/api/profile", json={"safety_minimum": "100.00"})
    it = item(client, price="1000.00")
    save(client, it, "1000.00")
    res = check(client, item_id=it["id"])
    assert res["need"] == "0.00" and res["saved"] == "1000.00"
    assert res["verdict"] == "buy"


def test_conta_atrasada_faz_adiar(client, setup):
    salary(client, setup, day=20)
    client.post("/api/transactions", json={
        "kind": "expense", "description": "Luz", "amount": "50.00", "competence_date": "2026-02-10",
        "status": "pending", "account_id": setup.account["id"],
    })
    res = check(client, amount="10.00")
    assert res["verdict"] == "postpone" and status_of(res, "Despesas comprometidas") == "bad"


def test_divida_pendente_exige_atencao_e_vencida_faz_adiar(client, setup):
    salary(client, setup, day=20)
    client.patch("/api/profile", json={"safety_minimum": "100.00"})
    client.post("/api/debts", json={
        "name": "M", "creditor": "x", "original_amount": "100.00", "start_date": "2026-01-01",
    })
    assert check(client, amount="10.00")["verdict"] == "attention"
    client.post("/api/debts", json={
        "name": "N", "creditor": "x", "original_amount": "100.00", "start_date": "2026-01-01",
        "due_date": "2026-03-01",
    })
    assert check(client, amount="10.00")["verdict"] == "postpone"


def test_cartao_sem_limite_faz_adiar_e_parcelas_longas_exigem_atencao(client, setup):
    salary(client, setup, day=20)
    client.patch("/api/profile", json={"safety_minimum": "100.00"})
    c = card(client, "500.00")
    res = check(client, amount="600.00", card_id=c["id"], installments=2)
    assert res["verdict"] == "postpone" and status_of(res, "Limite do cartão") == "bad"
    big = card(client, "9000.00")
    res = check(client, amount="600.00", card_id=big["id"], installments=6)
    assert status_of(res, "Faturas futuras") == "warning" and res["need"] == "100.00"


def test_limite_de_categoria(client, setup):
    salary(client, setup, day=20)
    client.patch("/api/profile", json={"safety_minimum": "100.00"})
    lazer = next(c["id"] for c in client.get("/api/categories").json if c["name"] == "Lazer")
    client.put("/api/budgets", json={"category_id": lazer, "amount": "50.00"})
    it = item(client, price="100.00", category_id=lazer)
    assert status_of(check(client, item_id=it["id"]), "Limite da categoria") == "warning"


def test_modo_recuperacao_pesa_mais(client, setup):
    salary(client, setup, day=20)
    client.patch("/api/profile", json={"safety_minimum": "100.00"})
    client.post("/api/debts", json={
        "name": "M", "creditor": "x", "original_amount": "3000.00", "start_date": "2026-01-01",
    })
    assert check(client, amount="10.00")["verdict"] == "attention"
    client.put("/api/recovery", json={"monthly_amount": "500.00"})
    res = check(client, amount="1000.00")
    assert res["verdict"] == "postpone"
    detail = next(c["detail"] for c in res["checks"] if c["label"] == "Modo Recuperação")
    assert "atrasaria a quitação em 2 meses" in detail


def test_recuperacao_com_valor_ja_guardado_so_pede_atencao(client, setup):
    salary(client, setup, day=20)
    client.patch("/api/profile", json={"safety_minimum": "100.00"})
    it = item(client, price="100.00")
    save(client, it, "100.00")
    client.put("/api/recovery", json={"monthly_amount": "500.00"})
    assert check(client, item_id=it["id"])["verdict"] == "attention"


def test_entrada_invalida(client, setup):
    assert client.post("/api/wishlist/can-buy", json={}).status_code == 422
    assert client.post("/api/wishlist/can-buy", json={"amount": "-1"}).status_code == 422


# Imagens

def upload(client, it, data=PNG, name="a.png"):
    return client.raw.post(
        f"/api/wishlist/{it['id']}/image", headers=WEB,
        data={"image": (BytesIO(data), name)}, content_type="multipart/form-data",
    )


def test_enviar_e_ler_imagem(client, setup):
    it = item(client)
    res = upload(client, it)
    assert res.status_code == 200 and res.json["has_upload"]
    image = client.get(f"/api/wishlist/{it['id']}/image")
    assert image.status_code == 200 and image.data == PNG
    assert image.mimetype == "image/png"
    assert image.headers["X-Content-Type-Options"] == "nosniff"
    client.raw.delete(f"/api/wishlist/{it['id']}/image", headers=WEB)
    assert client.get(f"/api/wishlist/{it['id']}/image").status_code == 404


def test_imagem_valida_o_conteudo_e_o_tamanho(client, setup):
    it = item(client)
    assert upload(client, it, b"<svg onload=alert(1)>", "a.png").status_code == 422
    assert upload(client, it, b"<html>", "a.jpg").status_code == 422
    assert upload(client, it, PNG + b"0" * (2 * 1024 * 1024)).status_code == 422
    assert client.raw.post(f"/api/wishlist/{it['id']}/image", headers=WEB).status_code == 422


# Isolamento

def test_wishlist_isolada_por_usuario(client, make_client, setup):
    it = item(client)
    upload(client, it)
    save(client, it)
    contribution = listed(client)["items"][0]["contributions"][0]
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    assert listed(other)["items"] == []
    assert summary(other)["saved_total"] == "0.00"
    assert other.patch(f"/api/wishlist/{it['id']}", json={"name": "x"}).status_code == 404
    assert save(other, it).status_code == 404
    assert other.get(f"/api/wishlist/{it['id']}/image").status_code == 404
    assert other.raw.delete(f"/api/goal-contributions/{contribution['id']}", headers=WEB).status_code == 404
    assert other.post("/api/wishlist/can-buy", json={"item_id": it["id"]}).status_code == 404


def test_compra_nao_usa_conta_ou_cartao_de_outro_usuario(client, make_client, setup):
    c = card(client)
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    mine = item(other)
    body = {"amount": "10.00", "bought_on": "2026-03-10"}
    url = f"/api/wishlist/{mine['id']}/buy"
    assert other.post(url, json=body | {"account_id": setup.account["id"]}).status_code == 422
    assert other.post(url, json=body | {"card_id": c["id"]}).status_code == 404


def test_categoria_de_outro_usuario_e_recusada(client, make_client, setup):
    lazer = next(c["id"] for c in client.get("/api/categories").json if c["name"] == "Lazer")
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    res = other.post("/api/wishlist", json={"name": "x", "price": "1", "category_id": lazer})
    assert res.status_code == 422
