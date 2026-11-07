"""Relatórios, exportação em CSV e backup."""
from datetime import date

from flask import Blueprint, Response, g, jsonify, request
from marshmallow import ValidationError, fields
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..extensions import db
from ..services import backup, exports, reports
from ..services.periods import parse_month
from .common import error, login_required
from .finance_common import today

bp = Blueprint("reports", __name__, url_prefix="/api")


def _date_arg(name: str) -> date | None:
    raw = request.args.get(name)
    if not raw:
        return None
    try:
        return fields.Date().deserialize(raw)
    except ValidationError as exc:
        raise ValidationError({name: ["Data inválida."]}) from exc


@bp.get("/reports")
@login_required
def get_report():
    period = request.args.get("period", "month")
    if period not in ("month", "quarter", "year"):
        return error("Período inválido.", 400)
    now = today()
    parsed = parse_month(request.args.get("month")) if request.args.get("month") else (now.year, now.month)
    if parsed is None:
        return error("Mês inválido; use AAAA-MM.", 400)
    return jsonify(reports.report(g.user.id, g.user.settings, now, period, *parsed))


@bp.get("/export/<dataset>.csv")
@login_required
def export_csv(dataset):
    builder = exports.DATASETS.get(dataset)
    if builder is None:
        return error("Exportação não encontrada.", 404)
    header, rows = builder(g.user.id, _date_arg("from"), _date_arg("to"))
    response = Response(exports.render(header, rows), mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = f'attachment; filename="monetta-{dataset}.csv"'
    return response


@bp.get("/backup")
@login_required
def download_backup():
    response = jsonify(backup.export_user(g.user.id, g.user.settings))
    name = f"monetta-backup-{today().isoformat()}.json"
    response.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


@bp.post("/backup/restore")
@login_required
def restore_backup():
    payload = request.get_json(silent=True)
    settings = g.user.settings
    try:
        counts = backup.restore_user(g.user.id, settings, payload)
        db.session.commit()
    except backup.BackupError as exc:
        db.session.rollback()
        return error(str(exc), 422)
    except (IntegrityError, SQLAlchemyError):
        db.session.rollback()
        return error("O arquivo tem dados inconsistentes. Nada foi alterado.", 422)
    return jsonify({"restored": counts})
