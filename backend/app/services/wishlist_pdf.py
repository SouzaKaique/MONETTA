"""
Wishlist em PDF: foto, preço, meta, especificações (observações) e link de cada produto.

Usa as fontes do sistema quando existem, para acentos e símbolos saírem certos. Sem elas,
cai nas fontes básicas do PDF, que só têm o alfabeto latino: o resto vira "?" em vez de erro.
"""
import io
import logging
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from PIL import Image, UnidentifiedImageError

from ..models import WishlistItem
from . import wishlist as service

MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
STATUS = {
    "desired": "Desejado", "planning": "Planejando", "saving": "Economizando",
    "bought": "Comprado", "given_up": "Desistido",
}
PRIORITY = {1: "alta", 2: "média", 3: "baixa"}
FILTERS = {
    "open": ("Em aberto", service.OPEN_STATUSES),
    "bought": ("Comprados", ("bought",)),
    "given_up": ("Desistidos", ("given_up",)),
    "all": ("Todos os itens", tuple(STATUS)),
}

# Cores do MONETTA
BRAND = (18, 60, 47)
MINT = (143, 211, 176)
INK = (33, 37, 41)
MUTED = (108, 117, 125)
LINE = (222, 226, 230)
SOFT = (244, 246, 245)

LOGO = Path(__file__).resolve().parents[3] / "docs" / "marca" / "monetta-logo.png"
_WINDOWS_FONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
SANS_FONTS = [
    (_WINDOWS_FONTS / "segoeui.ttf", _WINDOWS_FONTS / "segoeuib.ttf"),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
     Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
]
SERIF_FONTS = [
    (_WINDOWS_FONTS / "georgia.ttf", _WINDOWS_FONTS / "georgiab.ttf"),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
     Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf")),
]

# Ao reduzir a fonte, o fontTools avisa de tabelas que descarta e que o PDF não usa.
logging.getLogger("fontTools.subset").setLevel(logging.ERROR)

PHOTO = 38  # lado da foto, em mm
GAP = 5
PAD = 4
COMPRESS = True  # os testes desligam para conseguir ler o texto do arquivo


def brl(value: Decimal | None) -> str:
    if value is None:
        return "—"
    text = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {text}"


def day(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "—"


def month_label(value: str | None) -> str | None:
    if not value:
        return None
    year, month = value.split("-")
    return f"{MONTHS[int(month) - 1]}/{year}"


def short_link(url: str) -> str:
    """Endereço legível no papel: domínio e caminho, sem os parâmetros de rastreio."""
    parts = urlsplit(url)
    host = parts.netloc.removeprefix("www.")
    path = parts.path.rstrip("/")
    text = host + path
    return text if len(text) <= 70 else text[:67] + "..."


def _photo(item: WishlistItem) -> io.BytesIO | None:
    """Foto reduzida para o PDF não ficar pesado; arquivo ilegível fica sem foto."""
    if item.image is None:
        return None
    try:
        with Image.open(io.BytesIO(item.image.data)) as source:
            source.thumbnail((600, 600))
            image = source.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    flat = Image.new("RGB", image.size, (255, 255, 255))
    flat.paste(image, mask=image.getchannel("A"))
    out = io.BytesIO()
    flat.save(out, "JPEG", quality=85)
    out.seek(0)
    return out


class WishlistPDF(FPDF):
    def __init__(self, title: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.list_title = title
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(True, margin=18)
        self.set_compression(COMPRESS)
        self.sans, self.serif, self.unicode = self._load_fonts()
        self.set_title(f"Wishlist - {title}")
        self.set_creator("MONETTA")

    def _load_fonts(self) -> tuple[str, str, bool]:
        sans = self._first_font("Sans", SANS_FONTS)
        serif = self._first_font("Serif", SERIF_FONTS)
        if sans and serif:
            return sans, serif, True
        return "Helvetica", "Times", False

    def _first_font(self, family: str, options) -> str | None:
        for regular, bold in options:
            if regular.is_file() and bold.is_file():
                self.add_font(family, "", str(regular))
                self.add_font(family, "B", str(bold))
                return family
        return None

    def text_of(self, value: str) -> str:
        if self.unicode:
            return value
        # Fontes básicas só têm latin-1: troca os sinais comuns e marca o resto com "?".
        for old, new in (("—", "-"), ("–", "-"), ("…", "..."), ("“", '"'), ("”", '"'),
                         ("‘", "'"), ("’", "'"), ("•", "-"), ("›", ">")):
            value = value.replace(old, new)
        return value.encode("latin-1", "replace").decode("latin-1")

    def font(self, size: float, bold: bool = False, serif: bool = False, color=INK) -> None:
        self.set_font(self.serif if serif else self.sans, "B" if bold else "", size)
        self.set_text_color(*color)

    def write_cell(self, w: float, h: float, text: str, **kwargs) -> None:
        self.cell(w, h, self.text_of(text), new_x=kwargs.pop("new_x", XPos.LMARGIN),
                  new_y=kwargs.pop("new_y", YPos.NEXT), **kwargs)

    def lines_height(self, w: float, h: float, text: str) -> float:
        lines = self.multi_cell(w, h, self.text_of(text), dry_run=True, output="LINES")
        return len(lines) * h

    def footer(self) -> None:
        self.set_y(-12)
        self.font(8, color=MUTED)
        self.cell(0, 5, self.text_of(f"MONETTA · Wishlist · {self.list_title}"))
        self.set_x(self.l_margin)
        self.cell(0, 5, f"{self.page_no()}/{{nb}}", align="R")


def build(items: list[WishlistItem], status: str, today: date, owner: str | None) -> bytes:
    title, statuses = FILTERS[status]
    chosen = [i for i in items if i.status in statuses]
    pdf = WishlistPDF(title)
    pdf.add_page()
    _header(pdf, chosen, title, today, owner)
    if not chosen:
        pdf.font(11, color=MUTED)
        pdf.write_cell(0, 8, "Nenhum item nesta lista.")
    for item in chosen:
        _item(pdf, item, today)
    return bytes(pdf.output())


def _header(pdf: WishlistPDF, items: list[WishlistItem], title: str, today: date, owner: str | None) -> None:
    x, y = pdf.l_margin, pdf.get_y()
    if LOGO.is_file():
        pdf.image(str(LOGO), x, y, 12, 12)
        x += 15
    pdf.set_xy(x, y - 0.5)
    pdf.font(22, bold=True, serif=True, color=BRAND)
    pdf.write_cell(0, 9, "Wishlist", new_x=XPos.LEFT)
    pdf.set_x(x)
    pdf.font(9.5, color=MUTED)
    who = f"{owner} · " if owner else ""
    pdf.write_cell(0, 5, f"{who}{title} · exportada em {day(today)}")
    pdf.ln(5)

    open_items = [i for i in items if service.is_open(i)]
    figures = [
        ("Itens", str(len(items))),
        ("Valor total", brl(sum((i.price for i in items), Decimal("0")))),
        ("Já guardado", brl(sum((service.saved_of(i) for i in open_items), Decimal("0")))),
    ]
    width = (pdf.epw - 2 * 4) / 3
    top = pdf.get_y()
    for index, (label, value) in enumerate(figures):
        left = pdf.l_margin + index * (width + 4)
        pdf.set_fill_color(*SOFT)
        pdf.rect(left, top, width, 16, style="F", round_corners=True, corner_radius=2)
        pdf.set_xy(left + 4, top + 2.5)
        pdf.font(8, color=MUTED)
        pdf.write_cell(width - 8, 4, label, new_x=XPos.LEFT)
        pdf.set_x(left + 4)
        pdf.font(12, bold=True)
        pdf.write_cell(width - 8, 7, value)
    pdf.set_y(top + 16 + 7)


def _details(item: WishlistItem, today: date) -> list[str]:
    tags = [STATUS[item.status], f"Prioridade {PRIORITY[item.priority]}"]
    if item.category:
        tags.append(item.category.name)
    tags.append(f"Adicionado em {day(item.added_on)}")
    lines = [" · ".join(tags)]

    goal = item.goal
    saved = service.saved_of(item)
    if item.status == "bought":
        lines.append(f"Comprado em {day(item.bought_on)}")
    elif service.is_open(item):
        pct = min(100, round(saved / goal.target_amount * 100)) if goal.target_amount else 0
        goal_line = f"Guardado {brl(saved)} de {brl(goal.target_amount)} ({pct}%)"
        if goal.monthly_amount:
            goal_line += f" · {brl(goal.monthly_amount)} por mês"
        lines.append(goal_line)
        plan = []
        if goal.target_date:
            plan.append(f"Data desejada: {day(goal.target_date)}")
        forecast = service.forecast(item, today)
        if forecast["months"] == 0:
            plan.append("Meta atingida")
        elif forecast["month"]:
            plan.append(f"Previsão para atingir a meta: {month_label(forecast['month'])}")
        if plan:
            lines.append(" · ".join(plan))
    return lines


def _item(pdf: WishlistPDF, item: WishlistItem, today: date) -> None:
    text_x = pdf.l_margin + PAD + PHOTO + GAP
    text_w = pdf.epw - PAD * 2 - PHOTO - GAP
    details = _details(item, today)
    notes = (item.notes or "").strip()

    # Altura do bloco, para não partir um produto entre duas páginas.
    pdf.font(13, bold=True, serif=True)
    name_h = pdf.lines_height(text_w - 38, 6, item.name)
    pdf.font(9)
    details_h = sum(pdf.lines_height(text_w, 4.6, line) for line in details)
    notes_h = 0.0
    if notes:
        pdf.font(9.5)
        notes_h = 6 + pdf.lines_height(text_w, 4.8, notes)
    link_h = 10 if item.store_url else 0
    body_h = name_h + 1.5 + details_h + notes_h + link_h
    height = max(PHOTO, body_h) + PAD * 2
    if pdf.get_y() + height > pdf.page_break_trigger and pdf.get_y() > pdf.t_margin + 1:
        pdf.add_page()

    top = pdf.get_y()
    page = pdf.page_no()
    left = pdf.l_margin
    # Um produto muito longo pode passar de uma página: aí o quadro acompanha só o começo.
    frame_h = min(height, pdf.page_break_trigger - top)
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.3)
    pdf.rect(left, top, pdf.epw, frame_h, style="D", round_corners=True, corner_radius=3)

    photo = _photo(item)
    photo_x, photo_y = left + PAD, top + PAD
    if photo:
        with Image.open(photo) as probe:
            width, height_px = probe.size
        photo.seek(0)
        scale = min(PHOTO / width, PHOTO / height_px)
        w, h = width * scale, height_px * scale
        pdf.image(photo, photo_x + (PHOTO - w) / 2, photo_y + (PHOTO - h) / 2, w, h)
    else:
        pdf.set_fill_color(*SOFT)
        pdf.rect(photo_x, photo_y, PHOTO, PHOTO, style="F", round_corners=True, corner_radius=2)
        pdf.set_xy(photo_x, photo_y + PHOTO / 2 - 2.5)
        pdf.font(8, color=MUTED)
        pdf.write_cell(PHOTO, 5, "Sem foto", align="C")

    # Nome e preço
    pdf.set_xy(text_x + text_w - 38, top + PAD)
    pdf.font(12, bold=True, color=BRAND)
    pdf.write_cell(38, 6, brl(item.price), align="R")
    pdf.set_xy(text_x, top + PAD)
    pdf.font(13, bold=True, serif=True)
    pdf.multi_cell(text_w - 38, 6, pdf.text_of(item.name), new_x=XPos.LEFT, new_y=YPos.NEXT)
    pdf.ln(1.5)

    pdf.font(9, color=MUTED)
    for line in details:
        pdf.set_x(text_x)
        pdf.multi_cell(text_w, 4.6, pdf.text_of(line), new_x=XPos.LEFT, new_y=YPos.NEXT)

    if notes:
        pdf.ln(1.5)
        pdf.set_x(text_x)
        pdf.font(8, bold=True, color=BRAND)
        pdf.write_cell(text_w, 4.5, "ESPECIFICAÇÕES E OBSERVAÇÕES", new_x=XPos.LEFT)
        pdf.set_x(text_x)
        pdf.font(9.5)
        pdf.multi_cell(text_w, 4.8, pdf.text_of(notes), new_x=XPos.LEFT, new_y=YPos.NEXT)

    if item.store_url:
        pdf.ln(2)
        pdf.set_x(text_x)
        pdf.font(8, bold=True, color=BRAND)
        pdf.write_cell(text_w, 4, "ONDE COMPRAR", new_x=XPos.LEFT)
        pdf.set_x(text_x)
        pdf.font(9.5, color=(25, 110, 80))
        pdf.write_cell(text_w, 5, short_link(item.store_url), link=item.store_url)

    if pdf.page_no() == page:
        pdf.set_y(max(pdf.get_y(), top + height) + 4)
    else:
        pdf.ln(4)
