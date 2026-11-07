"""Datas e formatação: hoje no fuso do usuário, aritmética de meses e reais."""
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..models import AppSettings


def format_brl(value: Decimal) -> str:
    text = f"{value:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return f"R$ {text}"


def today_for(settings: AppSettings) -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def clamp_day(year: int, month: int, day: int) -> date:
    """Dia 31 em fevereiro vira o último dia do mês."""
    return date(year, month, min(day, monthrange(year, month)[1]))


def parse_month(raw: str | None) -> tuple[int, int] | None:
    """Converte 'AAAA-MM'; retorna None se o texto for inválido."""
    if not raw or len(raw) != 7 or raw[4] != "-":
        return None
    try:
        year, month = int(raw[:4]), int(raw[5:])
    except ValueError:
        return None
    return (year, month) if 2000 <= year <= 2100 and 1 <= month <= 12 else None
