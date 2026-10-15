"""
Blueprint de webhooks - B2B_B2C.

POST /webhooks/mercadopago - Recibe notificaciones de Mercado Pago.
Exento de CSRF, validado por firma x-signature.

En sandbox: resuelve la empresa por user_id del cobrador (collector_id / user_id en el payload)
y valida la firma con el webhook_secret de ese vendedor.
"""

import hmac
import hashlib
import json
from flask import Blueprint, request, abort, current_app
from app.extensions import db, csrf
from app.models.webhook_event import WebhookEvent
from app.models.payment import Payment, PaymentStatus
from app.models.order import Order, OrderStatus
from app.services.mercadopago import get_payment
from app.services.payments import process_mp_payment
from app.services.mp_accounts import find_company_by_seller_user_id, get_webhook_secret_for_seller

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")

# Eximir CSRF solo para este endpoint
csrf.exempt(webhooks_bp)


def _verify_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """
    Valida firma x-signature de Mercado Pago.

    Formato: ts=1234567890,v1=abcdef...
    """
    if not signature_header or not secret:
        return False

    try:
        parts = dict(part.split("=") for part in signature_header.split(","))
        ts = parts.get("ts")
        v1 = parts.get("v1")

        if not ts or not v1:
            return False

        # Recalcular HMAC
        manifest = f"id:{json.loads(payload).get('data', {}).get('id', '')};request-id:{request.headers.get('x-request-id', '')};ts:{ts};"
        expected = hmac.new(
            secret.encode(), manifest.encode(), hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected, v1)
    except Exception:
        return False


def _is_transient_error(error: Exception) -> bool:
    """Determina si un error es transitorio (MP caído, timeout) vs permanente."""
    error_str = str(error).lower()
    transient_keywords = [
        "timeout", "timed out", "connection", "unreachable",
        "500", "502", "503", "504", "connection refused",
        "temporary", "unavailable", "maintenance"
    ]
    return any(kw in error_str for kw in transient_keywords)


@webhooks_bp.route("/mercadopago", methods=["POST"])
def mercadopago_webhook():
    """
    Webhook de Mercado Pago.

    1. Parsear payload para obtener collector_id / user_id del cobrador
    2. Resolver Company por mp_seller_user_id
    3. Validar firma con webhook_secret de ese vendedor (fallback al global)
    4. Ignora eventos que no sean type="payment"
    5. Registra evento en WebhookEvent (idempotencia)
    6. Consulta pago a API de MP con access_token de ese vendedor (source of truth)
    7. Procesa y actualiza Order/Payment via process_mp_payment
    8. Responde 200 OK rápido; 5xx en errores transitorios para que MP reintente
       Si no se puede resolver la empresa, responde 200 y registra el evento sin procesarlo.
    """
    payload = request.get_data()

    # 1. Parsear payload para obtener collector_id / user_id
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        current_app.logger.warning("Webhook MP: JSON inválido")
        abort(400)

    # 2. Ignorar eventos que no sean type="payment" (merchant_order, etc.)
    event_type = data.get("type")
    if event_type != "payment":
        current_app.logger.info(f"Webhook MP: ignorando evento type={event_type}")
        return "", 200

    mp_payment_id = str(data.get("data", {}).get("id", ""))
    if not mp_payment_id:
        current_app.logger.warning("Webhook MP: sin data.id")
        abort(400)

    # Extraer seller user_id del payload de MP
    # En notificaciones de payment, el cobrador está en data.collector_id o data.user_id
    seller_user_id = str(
        data.get("data", {}).get("collector_id")
        or data.get("user_id")
        or data.get("data", {}).get("user_id")
        or ""
    )

    # 3. Resolver Company por mp_seller_user_id
    company = None
    webhook_secret = None
    access_token = None

    if seller_user_id:
        company = find_company_by_seller_user_id(seller_user_id)
        if company:
            # Usar webhook_secret de ese vendedor
            webhook_secret = company.mp_webhook_secret
            access_token = company.mp_access_token
            current_app.logger.debug(f"Webhook MP: resuelto vendedor {seller_user_id} -> Company {company.id}")

    # Fallback: si no se resolvió, usar secret global (producción o compatibilidad)
    if not webhook_secret:
        webhook_secret = current_app.config.get("MP_WEBHOOK_SECRET", "")
        access_token = None  # get_payment usará el global
        if seller_user_id:
            current_app.logger.warning(f"Webhook MP: no se encontró Company para seller_user_id={seller_user_id}, "
                                       f"usando secret global")

    # 4. Validar firma (obligatorio en prod; en testing/dev se permite sin secret si ALLOW_UNSIGNED_WEBHOOKS=1)
    signature = request.headers.get("x-signature", "")
    if webhook_secret and not _verify_signature(payload, signature, webhook_secret):
        current_app.logger.warning("Webhook MP: firma inválida")
        abort(400)
    elif not webhook_secret and not current_app.config.get("ALLOW_UNSIGNED_WEBHOOKS", False) and not current_app.config.get("TESTING", False):
        current_app.logger.warning("Webhook MP: sin secret y sin ALLOW_UNSIGNED_WEBHOOKS")
        abort(400)

    # 5. Verificar idempotencia: ¿ya procesamos este mp_payment_id con éxito?
    existing_event = WebhookEvent.query.filter_by(
        mp_payment_id=mp_payment_id, processed=True
    ).first()
    if existing_event:
        current_app.logger.info(f"Webhook MP: mp_payment_id={mp_payment_id} ya procesado (event_id={existing_event.id})")
        return "", 200

    # 6. Registrar evento (idempotencia)
    event = WebhookEvent.create_from_request(mp_payment_id, data)
    db.session.add(event)
    db.session.commit()  # Commit temprano para tener el ID

    # 7. Consultar pago a API de MP (source of truth) con token del vendedor
    try:
        mp_payment = get_payment(mp_payment_id, access_token)
    except Exception as e:
        current_app.logger.exception("Error consultando pago MP")
        event.mark_processed(str(e))
        db.session.commit()
        # Error transitorio -> 5xx para que MP reintente
        if _is_transient_error(e):
            return "", 503
        # Error permanente -> 200 para que MP no reintente, pero logueamos
        current_app.logger.error(f"Error permanente consultando MP: {e}")
        return "", 200

    # 8. Procesar pago (actualiza Order + Payment + stock)
    # La idempotencia la maneja process_mp_payment por mp_payment_id
    try:
        process_mp_payment(mp_payment)
        event.mark_processed()
        db.session.commit()
    except Exception as e:
        current_app.logger.exception("Error procesando pago MP")
        db.session.rollback()
        event.mark_processed(str(e))
        db.session.commit()
        # Error transitorio -> 5xx para que MP reintente
        if _is_transient_error(e):
            return "", 503
        # Error permanente -> 200 para que MP no reintente, pero logueamos
        current_app.logger.error(f"Error permanente procesando pago: {e}")
        return "", 200

    return "", 200