"""Foto do produto: cópia do endereço da imagem ou busca na página da loja, sem acessar a internet."""
import socket

import pytest

from app.services import product_image

from .conftest import register

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
PAGE = (
    '<html><head><meta content="https://cdn.loja.com/foto.png" property="og:image">'
    "</head><body>Produto</body></html>"
)


class FakeResponse:
    def __init__(self, status=200, body=b"", content_type="text/html", location=None):
        self.status_code = status
        self.body = body
        self.headers = {"Content-Type": content_type}
        if location:
            self.headers["Location"] = location
        self.is_redirect = location is not None

    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def web(monkeypatch):
    """Sites falsos: endereço -> resposta. Todos os nomes resolvem para um IP público."""
    sites: dict[str, FakeResponse] = {}
    requested: list[str] = []

    def fake_get(url, **kwargs):
        requested.append(url)
        assert kwargs["allow_redirects"] is False
        return sites.get(url) or FakeResponse(404)

    def fake_resolve(host, *args):
        address = "127.0.0.1" if host == "interno.local" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(product_image.requests, "get", fake_get)
    monkeypatch.setattr(product_image.socket, "getaddrinfo", fake_resolve)
    return sites, requested


def new_item(client, **extra):
    res = client.post("/api/wishlist", json={"name": "Monitor", "price": "900.00", **extra})
    assert res.status_code == 201, res.json
    return res.json


def fetch(client, item):
    return client.post(f"/api/wishlist/{item['id']}/image/fetch")


def test_busca_foto_na_pagina_da_loja(client, web):
    sites, _ = web
    sites["https://loja.com/produto"] = FakeResponse(body=PAGE.encode())
    sites["https://cdn.loja.com/foto.png"] = FakeResponse(body=PNG, content_type="image/png")
    register(client)
    item = new_item(client, store_url="https://loja.com/produto")

    res = fetch(client, item)
    assert res.status_code == 200 and res.json["has_upload"] is True
    image = client.get(f"/api/wishlist/{item['id']}/image")
    assert image.data == PNG and image.mimetype == "image/png"


def test_prefere_endereco_da_imagem_informado(client, web):
    sites, requested = web
    sites["https://img.loja.com/a.png"] = FakeResponse(body=PNG, content_type="image/png")
    register(client)
    item = new_item(client, image_url="https://img.loja.com/a.png", store_url="https://loja.com/produto")

    assert fetch(client, item).status_code == 200
    assert requested == ["https://img.loja.com/a.png"]


def test_segue_redirecionamento_de_link_curto(client, web):
    sites, _ = web
    sites["https://curto.com/x"] = FakeResponse(302, location="https://loja.com/produto")
    sites["https://loja.com/produto"] = FakeResponse(body=PAGE.encode())
    sites["https://cdn.loja.com/foto.png"] = FakeResponse(body=PNG, content_type="image/png")
    register(client)
    item = new_item(client, store_url="https://curto.com/x")
    assert fetch(client, item).status_code == 200


def test_loja_que_bloqueia_explica_como_colar(client, web):
    sites, _ = web
    sites["https://loja.com/produto"] = FakeResponse(body=b"<html>Confirme que voce e humano</html>")
    register(client)
    item = new_item(client, store_url="https://loja.com/produto")

    res = fetch(client, item)
    assert res.status_code == 422 and "cole" in res.json["error"]
    assert client.get("/api/wishlist").json["items"][0]["has_upload"] is False


def test_recusa_endereco_da_rede_local(client, web):
    sites, requested = web
    register(client)
    item = new_item(client, store_url="http://interno.local/admin")
    res = fetch(client, item)
    assert res.status_code == 422 and requested == []


def test_recusa_redirecionamento_para_rede_local(client, web):
    sites, requested = web
    sites["https://loja.com/produto"] = FakeResponse(302, location="http://interno.local/admin")
    register(client)
    item = new_item(client, store_url="https://loja.com/produto")
    assert fetch(client, item).status_code == 422
    assert requested == ["https://loja.com/produto"]


def test_recusa_arquivo_que_nao_e_imagem(client, web):
    sites, _ = web
    sites["https://img.loja.com/a.png"] = FakeResponse(body=b"<html>erro</html>", content_type="image/png")
    register(client)
    item = new_item(client, image_url="https://img.loja.com/a.png")
    res = fetch(client, item)
    assert res.status_code == 422 and "imagem" in res.json["error"]


def test_sem_links_pede_um(client, web):
    register(client)
    res = fetch(client, new_item(client))
    assert res.status_code == 422


def test_item_de_outro_usuario(client, web):
    register(client)
    item = new_item(client, store_url="https://loja.com/produto")
    client.post("/api/auth/logout")
    register(client, email="outra@example.com")
    assert fetch(client, item).status_code == 404


@pytest.mark.parametrize(("html", "expected"), [
    ('<meta name="twitter:image" content="/img/p.jpg">', "https://loja.com/img/p.jpg"),
    ('<meta property="og:image" content="https://a.com/x.jpg?a=1&amp;b=2">', "https://a.com/x.jpg?a=1&b=2"),
    ('<script type="application/ld+json">{"@type":"Product","image":["https://a.com/1.jpg"]}</script>',
     "https://a.com/1.jpg"),
    ('<script type="application/ld+json">{"@graph":[{"image":{"url":"https://a.com/2.jpg"}}]}</script>',
     "https://a.com/2.jpg"),
    ('<link rel="image_src" href="https://a.com/3.jpg">', "https://a.com/3.jpg"),
    ('<meta property="og:image" content="javascript:alert(1)">', None),
    ("<p>nada</p>", None),
])
def test_encontra_foto_no_html(html, expected):
    assert product_image.find_page_image(html, "https://loja.com/produto/1") == expected
