import re

from flask import Blueprint, g, jsonify, request

from ..services.dashboard import build_dashboard, today_for
from .common import error, login_required

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@bp.get("")
@login_required
def dashboard():
    settings = g.user.settings
    raw = request.args.get("month")
    if raw is None:
        today = today_for(settings)
        year, month = today.year, today.month
    elif re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", raw) and raw >= "2000":
        year, month = int(raw[:4]), int(raw[5:])
    else:
        return error("Mês inválido; use AAAA-MM.", 400)
    return jsonify(build_dashboard(g.user.id, settings, year, month))
