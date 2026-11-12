"""
Busca a foto de um produto: baixa o endereço da imagem ou procura a foto na página da loja.

Guardar uma cópia evita depender do site da loja, que troca ou bloqueia os endereços
das fotos com o tempo. Lojas que exigem verificação de robô ficam de fora: nesses casos
o usuário cola ou envia a imagem.
"""
import ipaddress
import json
import re
import socket
from html import unescape
from urllib.parse import urljoin, urlsplit

import requests

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_PAGE_BYTES = 3 * 1024 * 1024
TIMEOUT = 8
MAX_REDIRECTS = 5
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}


class ImageNotFound(Exception):
    """A foto não pôde ser obtida; a mensagem é mostrada ao usuário."""


def image_type(data: bytes) -> str | None:
    """Confere o conteúdo: extensão e tipo informados podem mentir."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _check_public(url: str) -> None:
    """Só endereços públicos: o servidor não pode ser usado para ler a rede local."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ImageNotFound("Endereço inválido.")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, None)}
    except (socket.gaierror, UnicodeError):
        raise ImageNotFound("Não foi possível acessar o site.") from None
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if not ip.is_global:
            raise ImageNotFound("Endereço não permitido.")


def _get(url: str, limit: int, accept: str) -> tuple[bytes, str, str]:
    """Baixa até `limit` bytes, conferindo cada redirecionamento. Devolve conteúdo, tipo e endereço final."""
    for _ in range(MAX_REDIRECTS + 1):
        _check_public(url)
        try:
            response = requests.get(
                url, headers={**HEADERS, "Accept": accept}, timeout=TIMEOUT,
                allow_redirects=False, stream=True,
            )
        except requests.RequestException:
            raise ImageNotFound("Não foi possível acessar o site.") from None
        with response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            if response.status_code != 200:
                raise ImageNotFound("O site não liberou a página.")
            data = b""
            for chunk in response.iter_content(64 * 1024):
                data += chunk
                if len(data) > limit:
                    raise ImageNotFound("O arquivo é grande demais.")
            return data, response.headers.get("Content-Type", ""), url
    raise ImageNotFound("O site redirecionou vezes demais.")


def download_image(url: str) -> tuple[bytes, str]:
    try:
        data, _, _ = _get(url, MAX_IMAGE_BYTES, "image/webp,image/png,image/jpeg,image/*")
    except ImageNotFound as exc:
        if str(exc) == "O arquivo é grande demais.":
            raise ImageNotFound("A imagem precisa ter até 2 MB.") from None
        raise
    content_type = image_type(data)
    if content_type is None:
        raise ImageNotFound("O endereço não é de uma imagem PNG, JPEG ou WEBP.")
    return data, content_type


_META = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = re.compile(r'([\w:-]+)\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)')
_LINK = re.compile(r"<link\b[^>]*>", re.I)
_JSON_LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.I | re.S)
_META_KEYS = ("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src")


def _attrs(tag: str) -> dict[str, str]:
    return {k.lower(): unescape(v.strip("\"'")) for k, v in _ATTR.findall(tag)}


def _json_ld_image(node) -> str | None:
    if isinstance(node, list):
        return next(filter(None, map(_json_ld_image, node)), None)
    if not isinstance(node, dict):
        return None
    image = node.get("image")
    if isinstance(image, str):
        return image
    if isinstance(image, list) and image:
        first = image[0]
        return first if isinstance(first, str) else (first or {}).get("url")
    if isinstance(image, dict):
        return image.get("url")
    return _json_ld_image(node.get("@graph"))


def find_page_image(html: str, base_url: str) -> str | None:
    """Foto de divulgação da página: Open Graph, Twitter, dados estruturados ou image_src."""
    found: dict[str, str] = {}
    for tag in _META.findall(html):
        attrs = _attrs(tag)
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key in _META_KEYS and attrs.get("content") and key not in found:
            found[key] = attrs["content"]
    candidate = next((found[k] for k in _META_KEYS if k in found), None)
    if candidate is None:
        for block in _JSON_LD.findall(html):
            try:
                candidate = _json_ld_image(json.loads(block.strip()))
            except ValueError:
                continue
            if candidate:
                break
    if candidate is None:
        for tag in _LINK.findall(html):
            attrs = _attrs(tag)
            if attrs.get("rel", "").lower() == "image_src" and attrs.get("href"):
                candidate = attrs["href"]
                break
    if not candidate:
        return None
    url = urljoin(base_url, candidate.strip())
    return url if urlsplit(url).scheme in ("http", "https") else None


def image_from_store(store_url: str) -> tuple[bytes, str, str]:
    """Abre a página da loja e baixa a foto do produto. Devolve conteúdo, tipo e endereço da foto."""
    data, content_type, final_url = _get(store_url, MAX_PAGE_BYTES, "text/html,application/xhtml+xml")
    if "html" not in content_type.lower():
        raise ImageNotFound("O link não abre uma página de produto.")
    image_url = find_page_image(data.decode("utf-8", errors="replace"), final_url)
    if image_url is None:
        raise ImageNotFound(
            "Esta loja não mostra a foto para outros programas. Copie a imagem do produto e cole aqui."
        )
    image, kind = download_image(image_url)
    return image, kind, image_url
