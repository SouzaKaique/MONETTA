"""Wishlist em PDF: só os itens do usuário, do filtro pedido, com foto, observações e link."""
import io
from datetime import date

import pytest
from PIL import Image

from app.api import finance_common
from app.services import dashboard as dash
from app.services import wishlist_pdf

from .conftest import register

WEB = {"X-Monetta-Client": "web"}


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(dash, "today_for", lambda settings: date(2026, 3, 15))
    monkeypatch.setattr(finance_common, "today_for", lambda settings: date(2026, 3, 15))


@pytest.fixture()
def readable(monkeypatch):
    """Fontes básicas e sem compressão: o texto aparece legível dentro do arquivo."""
    monkeypatch.setattr(wishlist_pdf, "SANS_FONTS", [])
    monkeypatch.setattr(wishlist_pdf, "SERIF_FONTS", [])
    monkeypatch.setattr(wishlist_pdf, "COMPRESS", False)


def picture(kind="PNG", size=(800, 400)) -> bytes:
    out = io.BytesIO()
    mode = "RGBA" if kind == "PNG" else "RGB"
    Image.new(mode, size, (20, 120, 90, 200) if mode == "RGBA" else (20, 120, 90)).save(out, kind)
    return out.getvalue()


def item(client, name="Monitor LG", **extra):
    res = client.post("/api/wishlist", json={"name": name, "price": "1299.90", **extra})
    assert res.status_code == 201, res.json
    return res.json


def upload(client, it, data):
    res = client.raw.post(
        f"/api/wishlist/{it['id']}/image", headers=WEB,
        data={"image": (io.BytesIO(data), "foto")}, content_type="multipart/form-data",
    )
    assert res.status_code == 200, res.json


def export(client, status=None):
    url = "/api/wishlist/export.pdf" + (f"?status={status}" if status else "")
    return client.get(url)


def test_exporta_pdf_com_dados_do_produto(client, readable):
    register(client)
    item(client, notes="27 polegadas, 180 Hz, IPS", target_date="2026-12-01",
         store_url="https://www.amazon.com.br/dp/B0DB6DF87Y?tag=rastreio&x=1")
    res = export(client)
    assert res.status_code == 200 and res.mimetype == "application/pdf"
    assert res.data.startswith(b"%PDF")
    assert 'filename="monetta-wishlist-2026-03-15.pdf"' in res.headers["Content-Disposition"]
    body = res.data.decode("latin-1")
    for text in ("Monitor LG", "R$ 1.299,90", "27 polegadas, 180 Hz, IPS", "amazon.com.br/dp/B0DB6DF87Y",
                 "Data desejada: 01/12/2026", "Prioridade m\xe9dia"):
        assert text in body, text
    assert "tag=rastreio" not in body.split("/URI")[0]  # o texto mostra o link curto
    assert "/URI (https://www.amazon.com.br/dp/B0DB6DF87Y?tag=rastreio&x=1)" in body  # e o link clica inteiro


def test_filtro_e_outro_usuario(client, readable):
    register(client)
    aberto = item(client, name="Cadeira")
    comprado = item(client, name="Teclado")
    account = client.post("/api/accounts", json={
        "name": "Conta", "opening_balance": "5000.00", "opening_date": "2026-01-01",
    }).json
    client.post(f"/api/wishlist/{comprado['id']}/buy", json={
        "amount": "1299.90", "bought_on": "2026-03-10", "account_id": account["id"],
    })
    body = export(client).data.decode("latin-1")
    assert "Cadeira" in body and "Teclado" not in body
    body = export(client, "bought").data.decode("latin-1")
    assert "Teclado" in body and "Cadeira" not in body and "Comprado em 10/03/2026" in body
    assert export(client, "qualquer").status_code == 400

    client.post("/api/auth/logout")
    register(client, email="outra@example.com")
    body = export(client, "all").data.decode("latin-1")
    assert "Cadeira" not in body and "Nenhum item" in body
    assert aberto  # o item da primeira conta existe, só não aparece para a outra


@pytest.mark.parametrize("kind", ["PNG", "JPEG", "WEBP"])
def test_inclui_foto_reduzida(client, readable, kind):
    register(client)
    upload(client, item(client), picture(kind, (2000, 1000)))
    res = export(client)
    assert res.status_code == 200
    assert b"/Subtype /Image" in res.data
    assert len(res.data) < 400_000  # foto grande é reduzida


def test_foto_corrompida_nao_quebra(client, readable):
    register(client)
    it = item(client)
    upload(client, it, b"\x89PNG\r\n\x1a\n" + b"lixo" * 50)
    res = export(client)
    assert res.status_code == 200 and "Sem foto" in res.data.decode("latin-1")


def test_texto_fora_do_latin1_com_fontes_basicas(client, readable):
    register(client)
    item(client, name="Fone 🎧 — sem fio", notes="Cor: “preto” • Bluetooth 5.3")
    res = export(client)
    assert res.status_code == 200
    body = res.data.decode("latin-1")
    assert "Fone ? - sem fio" in body and '"preto" - Bluetooth' in body


def test_muitos_itens_e_observacao_longa_quebram_paginas(client, readable):
    register(client)
    for n in range(12):
        item(client, name=f"Produto {n}", notes="Especifica\xe7\xe3o detalhada. " * (40 if n == 3 else 3))
    res = export(client)
    assert res.status_code == 200
    assert res.data.count(b"/Type /Page\n") >= 3 or res.data.count(b"/Type /Page ") >= 3 \
        or res.data.decode("latin-1").count("/Type /Page") - res.data.decode("latin-1").count("/Type /Pages") >= 3


def test_com_fontes_do_sistema(client):
    """Caminho normal: fontes do Windows (ou DejaVu), arquivo comprimido."""
    register(client)
    upload(client, item(client, name="Fone 🎧 ação", notes="Especificações"), picture())
    res = export(client, "all")
    assert res.status_code == 200 and res.data.startswith(b"%PDF")


def test_precisa_estar_logado(client):
    assert export(client).status_code == 401


def test_link_curto():
    assert wishlist_pdf.short_link("https://www.kabum.com.br/produto/1017202/monitor?aw=1") == \
        "kabum.com.br/produto/1017202/monitor"
    long = "https://loja.com/" + "a" * 200
    assert len(wishlist_pdf.short_link(long)) == 70


def test_formata_dinheiro():
    from decimal import Decimal
    assert wishlist_pdf.brl(Decimal("1234567.5")) == "R$ 1.234.567,50"
    assert wishlist_pdf.brl(Decimal("0")) == "R$ 0,00"
