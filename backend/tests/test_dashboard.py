"""Regras de integridade financeira refletidas nos indicadores."""
from datetime import date
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Account, Category, Transaction, User
from app.services import dashboard as service

from .conftest import register

TODAY = date(2026, 3, 15)


@pytest.fixture()
def user(client, monkeypatch):
    monkeypatch.setattr(service, "today_for", lambda settings: TODAY)
    register(client)
    user = db.session.scalar(db.select(User))
    db.session.add(Account(user_id=user.id, name="Conta", opening_balance=Decimal("1000.00"),
                           opening_date=date(2026, 1, 1)))
    db.session.commit()
    return user


def tx(user, kind, amount, competence=TODAY, status="confirmed", paid_on=TODAY, **extra):
    account = db.session.scalar(db.select(Account).filter_by(user_id=user.id))
    db.session.add(Transaction(
        user_id=user.id, account_id=account.id, kind=kind, amount=Decimal(amount), status=status,
        competence_date=competence, paid_on=paid_on if status == "confirmed" else None,
        description="t", **extra,
    ))
    db.session.commit()


def get(client, month="2026-03"):
    return client.get(f"/api/dashboard?month={month}").json


def test_valores_monetarios_sao_strings_exatas(client, user):
    tx(user, "expense", "0.10")
    tx(user, "expense", "0.20")
    assert get(client)["summary"]["expenses_total"] == "0.30"
    assert get(client)["summary"]["balance"] == "999.70"


def test_salario_previsto_nao_e_dinheiro_recebido(client, user):
    tx(user, "income", "5000.00", status="pending", is_salary=True)
    s = get(client)["summary"]
    assert s["salary_expected"] == "5000.00"
    assert s["salary_received"] == "0.00"
    assert s["balance"] == "1000.00"
    assert s["available_to_spend"] == "1000.00"


def test_receita_extra_so_entra_apos_confirmacao(client, user):
    tx(user, "income", "300.00", status="pending")
    assert get(client)["summary"]["extra_income"] == "0.00"
    tx(user, "income", "200.00")
    s = get(client)["summary"]
    assert s["extra_income"] == "200.00" and s["balance"] == "1200.00"


def test_pendente_reduz_disponivel_mas_nao_o_saldo(client, user):
    tx(user, "expense", "400.00", status="pending")
    s = get(client)["summary"]
    assert s["balance"] == "1000.00"
    assert s["expenses_pending"] == "400.00"
    assert s["projected_balance"] == "600.00"
    assert s["available_to_spend"] == "600.00"


def test_minimo_de_seguranca_e_disponivel_nunca_negativo(client, user):
    user.settings.safety_minimum = Decimal("100.00")
    db.session.commit()
    tx(user, "expense", "200.00", status="pending")
    assert get(client)["summary"]["available_to_spend"] == "700.00"
    tx(user, "expense", "5000.00", status="pending")
    data = get(client)
    assert data["summary"]["available_to_spend"] == "0.00"
    assert any("negativo" in a["message"] for a in data["alerts"])


def test_competencia_e_caixa_sao_separados(client, user):
    """Despesa de fevereiro paga em março pesa em fevereiro, mas sai do saldo em março."""
    tx(user, "expense", "150.00", competence=date(2026, 2, 20), paid_on=date(2026, 3, 2))
    assert get(client, "2026-02")["summary"]["expenses_total"] == "150.00"
    assert get(client, "2026-02")["summary"]["balance"] == "1000.00"
    assert get(client, "2026-03")["summary"]["expenses_total"] == "0.00"
    assert get(client, "2026-03")["summary"]["balance"] == "850.00"


def test_mes_passado_nao_tem_disponivel_e_futuro_nao_tem_saldo(client, user):
    assert get(client, "2026-02")["summary"]["available_to_spend"] is None
    assert get(client, "2026-04")["summary"]["balance"] is None


def test_modulos_futuros_nao_fingem_zero(client, user):
    s = get(client)["summary"]
    assert s["saved_total"] is None and s["reserves"] is None


def test_comprometimento_e_alerta(client, user):
    tx(user, "income", "1000.00", status="pending", is_salary=True)
    tx(user, "expense", "850.00", status="pending")
    data = get(client)
    assert data["summary"]["income_commitment_pct"] == 85
    assert any("85%" in a["message"] for a in data["alerts"])


def test_sem_renda_comprometimento_e_nulo(client, user):
    tx(user, "expense", "10.00")
    assert get(client)["summary"]["income_commitment_pct"] is None


def test_historico_e_categorias(client, user):
    cat = db.session.scalar(db.select(Category).filter_by(name="Lazer", user_id=user.id))
    tx(user, "expense", "80.00", category_id=cat.id)
    tx(user, "expense", "20.00")
    data = get(client)
    assert len(data["history"]) == 6 and data["history"][-1]["month"] == "2026-03"
    assert data["by_category"][0] == {"category": "Lazer", "total": "80.00"}
    assert data["by_category"][1]["category"] == "Sem categoria"


def test_dados_isolados_por_usuario(client, make_client, user):
    tx(user, "expense", "999.00")
    other = make_client()
    register(other, email="bia@example.com", name="Bia")
    data = get(other)
    assert data["summary"]["expenses_total"] == "0.00"
    assert data["has_data"] is False


def test_conta_atrasada_de_mes_anterior_reduz_o_disponivel(client, user):
    tx(user, "expense", "300.00", competence=date(2026, 2, 10), status="pending")
    tx(user, "expense", "100.00", status="pending")
    data = get(client)
    s = data["summary"]
    assert s["expenses_pending"] == "100.00"
    assert s["overdue_expenses"] == "300.00"
    assert s["available_to_spend"] == "600.00"
    assert any("atrasadas" in a["message"] for a in data["alerts"])


def test_fixas_variaveis_e_dinheiro_livre(client, user):
    tx(user, "income", "2000.00", is_salary=True)
    tx(user, "expense", "500.00", is_fixed=True)
    tx(user, "expense", "200.00")
    s = get(client)["summary"]
    assert s["expenses_fixed"] == "500.00" and s["expenses_variable"] == "200.00"
    assert s["free_money"] == "1300.00"
    assert s["income_received"] == "2000.00" and s["income_expected"] == "2000.00"


def test_mes_invalido(client, user):
    assert client.get("/api/dashboard?month=2026-13").status_code == 400
