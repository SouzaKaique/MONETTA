"""Wishlist: itens, metas, imagens, compra e "Posso comprar?"."""
from flask import Blueprint, Response, g, jsonify, request
from marshmallow import Schema, ValidationError, fields, validate

from ..extensions import db
from ..models import (
    CardPurchase, CreditCard, GoalContribution, SavingsGoal, Transaction, WishlistImage,
    WishlistItem,
)
from ..models.wishlist import URL_MAX
from ..services import advice, cards
from ..services import wishlist as service
from ..services.balances import ZERO
from ..services.cards import create_installments, invoice_month_for
from .common import error, load_body, login_required
from .finance_common import MoneyField, check_account, check_category, find_by_key, owned, save_once, today

bp = Blueprint("wishlist", __name__, url_prefix="/api")

MAX_IMAGE_BYTES = 2 * 1024 * 1024
OPEN_STATUS = validate.OneOf(list(service.OPEN_STATUSES))
PRIORITY = validate.Range(min=1, max=3)
NAME = validate.Length(min=1, max=120)
NOTES = {"allow_none": True, "validate": validate.Length(max=2000)}
# Só endereços web: um link "javascript:" em href seria executável.
WEB_URL = validate.URL(schemes={"http", "https"}, require_tld=True)
IMAGE_URL = validate.URL(schemes={"https"}, require_tld=True)


class ItemSchema(Schema):
    name = fields.String(required=True, validate=NAME)
    price = MoneyField(required=True)
    image_url = fields.String(load_default=None, allow_none=True, validate=[validate.Length(max=URL_MAX), IMAGE_URL])
    store_url = fields.String(load_default=None, allow_none=True, validate=[validate.Length(max=URL_MAX), WEB_URL])
    category_id = fields.UUID(load_default=None, allow_none=True)
    priority = fields.Integer(load_default=2, validate=PRIORITY)
    status = fields.String(load_default="desired", validate=OPEN_STATUS)
    notes = fields.String(load_default=None, **NOTES)
    target_amount = MoneyField(load_default=None, allow_none=True)
    monthly_amount = MoneyField(load_default=None, allow_none=True)
    target_date = fields.Date(load_default=None, allow_none=True)


class ItemUpdateSchema(Schema):
    name = fields.String(validate=NAME)
    price = MoneyField()
    image_url = fields.String(allow_none=True, validate=[validate.Length(max=URL_MAX), IMAGE_URL])
    store_url = fields.String(allow_none=True, validate=[validate.Length(max=URL_MAX), WEB_URL])
    category_id = fields.UUID(allow_none=True)
    priority = fields.Integer(validate=PRIORITY)
    status = fields.String(validate=OPEN_STATUS)
    notes = fields.String(**NOTES)
    target_amount = MoneyField()
    monthly_amount = MoneyField(allow_none=True)
    target_date = fields.Date(allow_none=True)


class ContributionSchema(Schema):
    amount = MoneyField(required=True)
    kind = fields.String(load_default="deposit", validate=validate.OneOf(["deposit", "withdraw"]))
    contributed_on = fields.Date(required=True)
    notes = fields.String(load_default=None, **NOTES)


class BuySchema(Schema):
    amount = MoneyField(required=True)
    bought_on = fields.Date(required=True)
    account_id = fields.UUID(load_default=None, allow_none=True)
    card_id = fields.UUID(load_default=None, allow_none=True)
    installments = fields.Integer(load_default=1, validate=validate.Range(min=1, max=48))


class CanBuySchema(Schema):
    amount = MoneyField(load_default=None, allow_none=True)
    item_id = fields.UUID(load_default=None, allow_none=True)
    card_id = fields.UUID(load_default=None, allow_none=True)
    installments = fields.Integer(load_default=1, validate=validate.Range(min=1, max=48))


def item_payload(item: WishlistItem) -> dict:
    saved = service.saved_of(item)
    goal = item.goal
    return {
        "id": str(item.id), "name": item.name, "price": item.price, "status": item.status,
        "priority": item.priority, "store_url": item.store_url, "image_url": item.image_url,
        "has_upload": item.image is not None,
        "category_id": str(item.category_id) if item.category_id else None,
        "category_name": item.category.name if item.category else None,
        "added_on": item.added_on.isoformat(), "notes": item.notes,
        "bought_on": item.bought_on.isoformat() if item.bought_on else None,
        "saved": saved, "target_amount": goal.target_amount,
        "remaining": max(ZERO, goal.target_amount - saved),
        "pct": min(100, round(saved / goal.target_amount * 100)),
        "reached": saved >= goal.target_amount,
        "monthly_amount": goal.monthly_amount,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "forecast": service.forecast(item, today()),
        "contributions": [{
            "id": str(c.id), "amount": c.amount, "date": c.contributed_on.isoformat(),
            "notes": c.notes,
        } for c in goal.contributions],
    }


def _check_owned_category(category_id) -> None:
    if category_id is not None:
        check_category(category_id, "expense")


def _item_key() -> str | None:
    key = request.headers.get("Idempotency-Key")
    if key and len(key) > 64:
        raise ValidationError({"_": ["Idempotency-Key inválida."]})
    return key


@bp.get("/wishlist")
@login_required
def list_items():
    items = service.user_items(g.user.id)
    return jsonify({
        "items": [item_payload(i) for i in items],
        "indicators": service.indicators(items, today()),
    })


@bp.post("/wishlist")
@login_required
def create_item():
    data = load_body(ItemSchema())
    _check_owned_category(data["category_id"])
    target = data.pop("target_amount") or data["price"]
    monthly = data.pop("monthly_amount")
    target_date = data.pop("target_date")
    data["name"] = data["name"].strip()

    item = WishlistItem(user_id=g.user.id, added_on=today(), **data)
    item.goal = SavingsGoal(
        user_id=g.user.id, target_amount=target, monthly_amount=monthly, target_date=target_date,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify(item_payload(item)), 201


@bp.patch("/wishlist/<uuid:item_id>")
@login_required
def update_item(item_id):
    item = owned(WishlistItem, item_id)
    data = load_body(ItemUpdateSchema())
    if "category_id" in data:
        _check_owned_category(data["category_id"])
    if "status" in data and not service.is_open(item):
        return error("Use Reabrir para voltar a este item.", 409)
    for field in ("target_amount", "monthly_amount", "target_date"):
        if field in data:
            setattr(item.goal, field, data.pop(field))
    for field, value in data.items():
        setattr(item, field, value)
    db.session.commit()
    return jsonify(item_payload(item))


@bp.delete("/wishlist/<uuid:item_id>")
@login_required
def delete_item(item_id):
    item = owned(WishlistItem, item_id)
    if item.goal.contributions:
        return error("Este item tem valores guardados. Use Desisti para preservar o histórico.", 409)
    db.session.delete(item)
    db.session.commit()
    return "", 204


@bp.post("/wishlist/<uuid:item_id>/contributions")
@login_required
def contribute(item_id):
    item = owned(WishlistItem, item_id)
    key = _item_key()
    existing = find_by_key(GoalContribution, key)
    if existing:
        return jsonify(item_payload(existing.goal.item)), 200
    if not service.is_open(item):
        return error("Este item está encerrado.", 409)

    data = load_body(ContributionSchema())
    if data["contributed_on"] > today():
        raise ValidationError({"contributed_on": ["A data não pode estar no futuro."]})
    amount = data["amount"]
    if data["kind"] == "withdraw":
        if amount > service.saved_of(item):
            raise ValidationError({"amount": ["O valor é maior do que o guardado."]})
        amount = -amount

    item.goal.contributions.append(GoalContribution(
        user_id=g.user.id, amount=amount, contributed_on=data["contributed_on"],
        notes=data["notes"], idempotency_key=key,
    ))
    if amount > 0 and item.status != "saving":
        item.status = "saving"
    duplicate = save_once(GoalContribution, key)
    if duplicate:
        return jsonify(item_payload(duplicate.goal.item)), 200
    db.session.refresh(item.goal)
    return jsonify(item_payload(item)), 201


@bp.delete("/goal-contributions/<uuid:contribution_id>")
@login_required
def delete_contribution(contribution_id):
    db.session.delete(owned(GoalContribution, contribution_id))
    db.session.commit()
    return "", 204


@bp.post("/wishlist/<uuid:item_id>/buy")
@login_required
def buy_item(item_id):
    """Registra a despesa uma única vez, à vista ou no cartão, e libera o valor guardado."""
    item = owned(WishlistItem, item_id)
    if not service.is_open(item):
        return error("Este item já está encerrado.", 409)
    data = load_body(BuySchema())
    if data["bought_on"] > today():
        raise ValidationError({"bought_on": ["A compra não pode estar no futuro."]})
    if bool(data["account_id"]) == bool(data["card_id"]):
        raise ValidationError({"account_id": ["Escolha uma conta ou um cartão."]})

    if data["card_id"]:
        card = owned(CreditCard, data["card_id"])
        if not card.active:
            return error("Este cartão está desativado.", 409)
        purchase = CardPurchase(
            user_id=g.user.id, card=card, category_id=item.category_id, description=item.name,
            total_amount=data["amount"], purchase_date=data["bought_on"],
            installment_count=data["installments"],
        )
        db.session.add(purchase)
        db.session.flush()
        create_installments(purchase, invoice_month_for(card, data["bought_on"]), 0)
        item.card_purchase = purchase
    else:
        check_account(data["account_id"])
        tx = Transaction(
            user_id=g.user.id, account_id=data["account_id"], category_id=item.category_id,
            kind="expense", status="confirmed", description=item.name, amount=data["amount"],
            competence_date=data["bought_on"], paid_on=data["bought_on"],
        )
        db.session.add(tx)
        item.transaction = tx

    item.status = "bought"
    item.bought_on = data["bought_on"]
    db.session.commit()
    return jsonify(item_payload(item))


@bp.post("/wishlist/<uuid:item_id>/give-up")
@login_required
def give_up_item(item_id):
    item = owned(WishlistItem, item_id)
    if not service.is_open(item):
        return error("Este item já está encerrado.", 409)
    item.status = "given_up"
    db.session.commit()
    return jsonify(item_payload(item))


@bp.post("/wishlist/<uuid:item_id>/reopen")
@login_required
def reopen_item(item_id):
    """
    Desfazer uma compra remove a despesa criada por ela. Sem isso, o valor guardado
    voltaria a ser separado enquanto a despesa continuaria descontada: contado duas vezes.
    """
    item = owned(WishlistItem, item_id)
    if service.is_open(item):
        return error("Este item já está aberto.", 409)

    purchase = item.card_purchase
    if purchase is not None:
        if cards.has_paid_invoice(purchase):
            return error("Há pagamento em uma fatura desta compra. Remova o pagamento antes.", 409)
        card_id = purchase.card_id
        item.card_purchase = None
        db.session.delete(purchase)
        db.session.flush()
        cards.remove_empty_invoices(card_id)
    if item.transaction is not None:
        db.session.delete(item.transaction)
        item.transaction = None

    item.status = "saving" if item.goal.contributions else "desired"
    item.bought_on = None
    db.session.commit()
    return jsonify(item_payload(item))


@bp.post("/wishlist/can-buy")
@login_required
def can_buy():
    data = load_body(CanBuySchema())
    item = owned(WishlistItem, data["item_id"]) if data["item_id"] else None
    card = owned(CreditCard, data["card_id"]) if data["card_id"] else None
    amount = data["amount"] or (item.price if item else None)
    if amount is None:
        raise ValidationError({"amount": ["Informe o valor."]})
    return jsonify(advice.analyze(
        g.user.id, g.user.settings, today(), amount, item, card, data["installments"],
    ))


# Imagens

def _image_type(data: bytes) -> str | None:
    """Confere o conteúdo: extensão e tipo informados pelo navegador podem mentir."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@bp.post("/wishlist/<uuid:item_id>/image")
@login_required
def upload_image(item_id):
    item = owned(WishlistItem, item_id)
    file = request.files.get("image")
    if file is None:
        return error("Envie uma imagem.", 422)
    data = file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        return error("A imagem precisa ter até 2 MB.", 422)
    content_type = _image_type(data)
    if content_type is None:
        return error("Use uma imagem PNG, JPEG ou WEBP.", 422)
    if item.image:
        item.image.data, item.image.content_type = data, content_type
    else:
        item.image = WishlistImage(data=data, content_type=content_type)
    db.session.commit()
    return jsonify(item_payload(item))


@bp.get("/wishlist/<uuid:item_id>/image")
@login_required
def get_image(item_id):
    item = owned(WishlistItem, item_id)
    if item.image is None:
        return error("Imagem não encontrada.", 404)
    response = Response(item.image.data, mimetype=item.image.content_type)
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@bp.delete("/wishlist/<uuid:item_id>/image")
@login_required
def delete_image(item_id):
    item = owned(WishlistItem, item_id)
    item.image = None
    db.session.commit()
    return "", 204

