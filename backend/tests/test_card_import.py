"""Importar a fatura do banco: só entra o que é novo, nada duplica e o total bate com o banco."""
import io
from datetime import date
from types import SimpleNamespace

import pytest

from app.api import finance_common
from app.services import card_import
from app.services import dashboard as dash

from .conftest import register

WEB = {"X-Monetta-Client": "web"}
CLOCK = {"today": date(2026, 11, 19)}


def ofx(*rows, end="20261201000000[-3:BRT]") -> bytes:
    body = "".join(
        f"<STMTTRN>\n<TRNTYPE>{'CREDIT' if amount > 0 else 'DEBIT'}</TRNTYPE>\n"
        f"<DTPOSTED>{day.replace('-', '')}000000[-3:BRT]</DTPOSTED>\n<TRNAMT>{amount:.2f}</TRNAMT>\n"
        f"<FITID>{fitid}</FITID>\n<MEMO>{memo}</MEMO>\n</STMTTRN>\n"
        for fitid, day, memo, amount in rows
    )
    return (
        "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nCHARSET:1252\n<OFX>\n<CREDITCARDMSGSRSV1>\n"
        "<CCSTMTTRNRS>\n<CCSTMTRS>\n<CURDEF>BRL</CURDEF>\n<BANKTRANLIST>\n"
        f"<DTSTART>20261101000000[-3:BRT]</DTSTART>\n<DTEND>{end}</DTEND>\n{body}"
        "</BANKTRANLIST>\n</CCSTMTRS>\n</CCSTMTTRNRS>\n</CREDITCARDMSGSRSV1>\n</OFX>\n"
    ).encode("utf-8")


BILL = ofx(
    ("a1", "2026-11-19", "Zp*Joao Vitor Francisc - Parcela 1/3", -88.75),
    ("a2", "2026-11-18", "Uber - NuPay", -10.94),
    ("a3", "2026-11-18", "ARCOS DOURADOS COMÉRCIO DE ALIMENTOS S.A. - NuPay", -41.48),
    ("a4", "2026-11-09", "Pagamento recebido", 2658.67),
    ("a5", "2026-11-01", "Hausport - Parcela 2/4", -71.51),
    ("a6", "2026-11-05", "Mp *Nlacessorios - Parcela 1/2", -47.77),
)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    CLOCK["today"] = date(2026, 11, 19)
    monkeypatch.setattr(dash, "today_for", lambda settings: CLOCK["today"])
    monkeypatch.setattr(finance_common, "today_for", lambda settings: CLOCK["today"])


@pytest.fixture()
def setup(client):
    register(client)
    card = client.post("/api/cards", json={
        "name": "Nubank", "credit_limit": "7200.00", "closing_day": 1, "due_day": 8,
    }).json
    categories = {c["name"]: c["id"] for c in client.get("/api/categories").json}
    return SimpleNamespace(card=card, categories=categories)


def preview(client, setup, data=BILL, name="fatura.ofx", month=None):
    form = {"file": (io.BytesIO(data), name)}
    if month:
        form["month"] = month
    return client.raw.post(
        f"/api/cards/{setup.card['id']}/import/preview", headers=WEB,
        data=form, content_type="multipart/form-data",
    )


def confirm(client, setup, result, skip=()):
    """Faz o que a tela faz: cria as novas marcadas e liga as que já existem."""
    rows = result["rows"]
    body = {
        "month": result["month"],
        "create": [{k: r[k] for k in ("external_id", "date", "description", "amount", "number",
                                      "count", "category_id")}
                   for r in rows if r["status"] == "new" and r["external_id"] not in skip],
        "link": [{"external_id": r["external_id"], "installment_id": r["installment_id"], "amount": r["amount"]}
                 for r in rows if r["status"] in ("existing", "fixed") and r["installment_id"]],
    }
    return client.post(f"/api/cards/{setup.card['id']}/import", json=body)


def invoices(client, setup):
    return {i["month"]: i["total"] for i in client.get(f"/api/cards/{setup.card['id']}").json["invoices"]}


def by_memo(result, start):
    return next(r for r in result["rows"] if r["memo"].startswith(start))


def test_previa_le_ofx_e_sugere_categorias(client, setup):
    res = preview(client, setup)
    assert res.status_code == 200, res.json
    result = res.json
    assert result["month"] == "2026-12" and result["due_date"] == "2026-12-08"
    assert result["file_total"] == "260.45"
    joao = by_memo(result, "Zp*Joao")
    assert (joao["description"], joao["number"], joao["count"], joao["status"]) == (
        "Zp*Joao Vitor Francisc", 1, 3, "new")
    assert by_memo(result, "Uber")["description"] == "Uber"
    assert by_memo(result, "Uber")["category_id"] == setup.categories["Transporte"]
    assert by_memo(result, "ARCOS")["description"].startswith("Arcos Dourados")
    assert by_memo(result, "ARCOS")["category_id"] == setup.categories["Alimentação"]
    assert by_memo(result, "Pagamento")["status"] == "payment"
    assert client.get(f"/api/cards/{setup.card['id']}").json["invoices"] == []  # prévia não grava


def test_importar_cria_parcelas_e_total_bate(client, setup):
    res = confirm(client, setup, preview(client, setup).json)
    assert res.status_code == 201 and res.json == {"created": 5, "linked": 0, "skipped": 0}
    months = invoices(client, setup)
    assert months["2026-12"] == "260.45"           # o mesmo total das compras do arquivo
    # João 2/3, Hausport 3/4 e Nlacessorios 2/2 (igual à 1ª até a próxima fatura corrigir os centavos)
    assert months["2027-01"] == "208.03"
    assert months["2027-02"] == "160.26"           # João 3/3, Hausport 4/4
    purchases = {p["description"]: p for p in client.get(f"/api/cards/{setup.card['id']}/purchases").json}
    hausport = purchases["Hausport"]
    assert hausport["installment_count"] == 4 and hausport["total_amount"] == "286.04"
    assert hausport["purchase_date"] == "2026-10-01"  # parcela 2: a compra foi um mês antes


def test_importar_de_novo_nao_duplica(client, setup):
    first = preview(client, setup).json
    confirm(client, setup, first)
    again = preview(client, setup).json
    statuses = {r["status"] for r in again["rows"]}
    assert statuses == {"imported", "payment"}
    assert confirm(client, setup, first).json == {"created": 0, "linked": 0, "skipped": 5}  # envio repetido
    assert invoices(client, setup)["2026-12"] == "260.45"


def test_reconhece_compras_lancadas_a_mao(client, setup):
    client.post(f"/api/cards/{setup.card['id']}/purchases", json={
        "description": "Uber", "total_amount": "10.94", "purchase_date": "2026-11-18",
    })
    client.post(f"/api/cards/{setup.card['id']}/purchases", json={
        "description": "Hausport", "total_amount": "286.04", "installment_count": 4,
        "purchase_date": "2026-10-01", "already_paid": 1, "first_month": "2026-11",
    })
    client.post(f"/api/cards/{setup.card['id']}/purchases", json={
        "description": "Compra que não está no arquivo", "total_amount": "15.00", "purchase_date": "2026-11-12",
    })
    result = preview(client, setup).json
    assert by_memo(result, "Uber")["status"] == "existing"
    assert by_memo(result, "Hausport")["status"] == "existing"  # parcela 2/4 da compra lançada
    assert [m["description"] for m in result["missing"]] == ["Compra que não está no arquivo"]

    res = confirm(client, setup, result)
    assert res.json == {"created": 3, "linked": 2, "skipped": 0}
    assert {r["status"] for r in preview(client, setup).json["rows"]} == {"imported", "payment"}


def test_diferenca_de_centavos_na_parcela_e_corrigida(client, setup):
    client.post(f"/api/cards/{setup.card['id']}/purchases", json={
        "description": "Mp *Nlacessorios", "total_amount": "95.54", "installment_count": 2,
        "purchase_date": "2026-11-05",
    })
    jan = ofx(("b1", "2026-12-05", "Mp *Nlacessorios - Parcela 2/2", -47.76), end="20270101000000[-3:BRT]")
    result = preview(client, setup, jan).json
    row = result["rows"][0]
    assert row["status"] == "existing" and "ajustado" in row["note"]
    confirm(client, setup, result)
    assert invoices(client, setup)["2027-01"] == "47.76"


def test_gasto_fixo_e_iof_ja_somado(client, setup):
    for name, amount, day in [("Academia", "119.90", 11), ("Claude", "118.40", 10)]:
        res = client.post("/api/recurrences", json={
            "kind": "expense", "name": name, "amount": amount, "day_of_month": day,
            "start_date": "2026-11-01", "card_id": setup.card["id"],
        })
        assert res.status_code == 201
    bill = ofx(
        ("c1", "2026-11-11", "Academia My Move", -119.90),
        ("c2", "2026-11-10", "Anthropic* Claude Sub", -114.40),
        ("c3", "2026-11-10", "IOF de compra internacional", -4.00),
    )
    result = preview(client, setup, bill).json
    assert by_memo(result, "Academia")["status"] == "fixed"
    claude = by_memo(result, "Anthropic")
    assert claude["status"] == "fixed" and "R$ 118,40" in claude["note"]
    assert by_memo(result, "IOF")["status"] == "included"
    confirm(client, setup, result)
    assert invoices(client, setup)["2026-12"] == "238.30"  # nada somado em dobro


def test_csv_do_nubank(client, setup):
    data = (
        "date,title,amount\n"
        "2026-11-11,Academia My Move,\"119,90\"\n"
        "2026-11-09,Pagamento recebido,\"- 2.658,67\"\n"
        "2026-11-08,Jim.Com* Leal Leal T - Parcela 1/3,\"70,00\"\n"
        "2026-11-05,Uber - NuPay,\"10,94\"\n"
        "2026-11-05,Uber - NuPay,\"10,94\"\n"
        "2026-11-04,Compra grande,\"1.234,56\"\n"
    ).encode("utf-8")
    result = preview(client, setup, data, "fatura.csv").json
    assert result["month"] == "2026-12"
    assert [r["status"] for r in result["rows"]].count("new") == 5
    ubers = [r for r in result["rows"] if r["description"] == "Uber"]
    assert len(ubers) == 2 and ubers[0]["external_id"] != ubers[1]["external_id"]  # duas corridas iguais
    assert by_memo(result, "Compra grande")["amount"] == "1234.56"
    assert by_memo(result, "Pagamento")["status"] == "payment"
    confirm(client, setup, result)
    assert invoices(client, setup)["2026-12"] == "1446.34"


def test_arquivo_em_cp1252(client, setup):
    data = ofx(("d1", "2026-11-10", "Padaria São João", -9.50)).decode("utf-8").encode("cp1252")
    row = preview(client, setup, data).json["rows"][0]
    assert row["description"] == "Padaria São João"


def test_escolher_outra_fatura(client, setup):
    result = preview(client, setup, month="2027-01").json
    assert result["month"] == "2027-01" and result["due_date"] == "2027-01-08"


def test_estorno_nao_e_importado(client, setup):
    data = ofx(("e1", "2026-11-12", "Estorno Loja X", 50.00), ("e2", "2026-11-12", "Loja X", -50.00))
    result = preview(client, setup, data).json
    assert by_memo(result, "Estorno")["status"] == "credit"


@pytest.mark.parametrize("data,name", [
    (b"isto nao e uma fatura", "x.txt"),
    (b"data,descricao\n2026-01-01,x\n", "x.csv"),
    (ofx(), "vazia.ofx"),
    (b"x" * (card_import.MAX_BYTES + 10), "grande.ofx"),
])
def test_arquivo_invalido(client, setup, data, name):
    res = preview(client, setup, data, name)
    assert res.status_code == 422 and res.json["error"]


def test_seguranca(client, setup):
    result = preview(client, setup).json
    confirm(client, setup, result)
    mine = client.get(f"/api/cards/{setup.card['id']}/purchases").json[0]
    card_id = setup.card["id"]

    client.post("/api/auth/logout")
    register(client, email="outra@example.com")
    other = SimpleNamespace(card=client.post("/api/cards", json={
        "name": "Outro", "credit_limit": "100.00", "closing_day": 1, "due_day": 8,
    }).json)
    assert client.raw.post(f"/api/cards/{card_id}/import/preview", headers=WEB,
                           data={"file": (io.BytesIO(BILL), "f.ofx")},
                           content_type="multipart/form-data").status_code == 404
    # Ligar a linha a uma parcela de outra pessoa não é aceito.
    res = client.post(f"/api/cards/{other.card['id']}/import", json={
        "month": "2026-12",
        "link": [{"external_id": "x" * 10, "installment_id": mine["id"]}],
    })
    assert res.status_code == 422
    # Categoria de outra conta também não.
    res = client.post(f"/api/cards/{other.card['id']}/import", json={
        "month": "2026-12",
        "create": [{"external_id": "y" * 10, "date": "2026-11-10", "description": "X", "amount": "1.00",
                    "category_id": setup.categories["Lazer"]}],
    })
    assert res.status_code == 422


def test_cartao_desativado(client, setup):
    result = preview(client, setup).json
    client.patch(f"/api/cards/{setup.card['id']}", json={"active": False})
    assert confirm(client, setup, result).status_code == 409
