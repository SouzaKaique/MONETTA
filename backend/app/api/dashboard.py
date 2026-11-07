from flask import Blueprint, g, jsonify, request

from ..services.dashboard import build_dashboard
from ..services.periods import parse_month, today_for
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
    else:
        parsed = parse_month(raw)
        if parsed is None:
            return error("Mês inválido; use AAAA-MM.", 400)
        year, month = parsed
    return jsonify(build_dashboard(g.user.id, settings, year, month))
