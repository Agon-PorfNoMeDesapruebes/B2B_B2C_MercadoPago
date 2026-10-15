"""
Servicio de Mercado Pago - B2B_B2C.

Wrapper del SDK oficial para Checkout Pro y Checkout Bricks.
En sandbox usa credenciales por empresa; en producción usa globales.
"""

import mercadopago
from flask import current_app
from datetime import datetime, timedelta, timezone
from app.models.order import Order
from app.services.mp_accounts import get_mp_credentials, get_payer_email


_AR_TZ = timezone(timedelta(hours=-3))


def _get_sdk(access_token: str | None = None) -> mercadopago.SDK:
    """
    Obtiene instancia del SDK con access token.

    Args:
        access_token: Token de acceso. Si es None, usa el global de config (producción).
    """
    if access_token is None:
        token = current_app.config.get("MP_ACCESS_TOKEN", "")
        if not token:
            raise RuntimeError("MP_ACCESS_TOKEN no configurado")
        return mercadopago.SDK(token)
    return mercadopago.SDK(access_token)


def _mp_datetime(dt: datetime) -> str:
    """Formatea fecha al formato de MP: 2026-10-09T12:00:00.000-03:00."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(_AR_TZ)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "-03:00"


def create_preference(order: Order) -> dict:
    """
    Crea una preference de Checkout Pro para un pedido.

    Args:
        order: Pedido PENDIENTE con items cargados.

    Returns:
        dict: Respuesta de MP con 'id', 'init_point', 'sandbox_init_point', etc.
    """
    access_token, _ = get_mp_credentials(order)
    sdk = _get_sdk(access_token)

    # Construir items para MP
    mp_items = []
    for item in order.items:
        mp_items.append({
            "id": str(item.product_id),
            "title": item.product_name_snapshot[:100],  # MP limita título
            "description": item.product_name_snapshot[:255],
            "quantity": item.quantity,
            "currency_id": "ARS",
            "unit_price": float(item.unit_price_snapshot),
        })

    base_url = current_app.config["PUBLIC_BASE_URL"].rstrip("/")
    webhook_url = f"{base_url}/webhooks/mercadopago"

    # Email del pagador (en sandbox siempre el comprador de prueba)
    payer_email = get_payer_email(order, "")

    preference_data = {
        "items": mp_items,
        "external_reference": order.external_reference,
        "payer": {"email": payer_email},
        "back_urls": {
            "success": f"{base_url}/pagos/retorno/success",
            "failure": f"{base_url}/pagos/retorno/failure",
            "pending": f"{base_url}/pagos/retorno/pending",
        },
        "notification_url": webhook_url,
        "statement_descriptor": "B2B_B2C",
        "expires": True,
        "expiration_date_from": _mp_datetime(order.created_at),
        "expiration_date_to": _mp_datetime(order.expires_at),
    }

    # MP rechaza auto_return si las back_urls no son publicas (ej. localhost)
    if base_url.startswith("https://"):
        preference_data["auto_return"] = "approved"

    result = sdk.preference().create(preference_data)
    response = result.get("response", {})

    if result.get("status") not in (200, 201) or "id" not in response:
        error_msg = response.get("message", "Error desconocido")
        raise RuntimeError(f"MP Preference error: {error_msg}")

    return response


def get_payment(mp_payment_id: str, access_token: str | None = None) -> dict:
    """
    Consulta un pago a la API de Mercado Pago (source of truth).

    Args:
        mp_payment_id: ID del pago en MP.
        access_token: Token de acceso. Si None, usa global (producción o compatibilidad).

    Returns:
        dict: Datos completos del pago.
    """
    sdk = _get_sdk(access_token)
    result = sdk.payment().get(mp_payment_id)

    if result.get("status") != 200:
        raise RuntimeError(f"MP Get payment error: {result.get('response', {}).get('message', 'Unknown')}")

    return result["response"]


def search_payment_by_external_ref(external_reference: str, access_token: str | None = None) -> dict | None:
    """
    Busca pagos por external_reference (Plan B: botón 'Verificar pago').

    Args:
        external_reference: UUID del pedido.
        access_token: Token de acceso. Si None, usa global.

    Returns:
        dict o None: Primer pago encontrado o None.
    """
    sdk = _get_sdk(access_token)
    # Filtrar por external_reference
    filters = {"external_reference": external_reference, "sort": "date_created", "criteria": "desc"}
    result = sdk.payment().search(filters)

    if result.get("status") != 200:
        raise RuntimeError(f"MP Search error: {result.get('response', {}).get('message', 'Unknown')}")

    results = result["response"].get("results", [])
    return results[0] if results else None


def create_payment_bricks(order: Order, form_data: dict) -> dict:
    """
    Crea un pago en MP usando los datos del Brick (token, paymentMethodId, etc.).

    Args:
        order: Pedido a pagar.
        form_data: Datos del formulario del Brick (token, paymentMethodId, installments, etc.).

    Returns:
        dict: Respuesta de MP con el pago creado.
    """
    access_token, _ = get_mp_credentials(order)
    sdk = _get_sdk(access_token)

    # Email del pagador (en sandbox siempre el comprador de prueba)
    payer_email = get_payer_email(order, form_data.get("payer", {}).get("email", ""))

    payment_data = {
        "transaction_amount": float(order.total),
        "token": form_data.get("token"),
        "description": f"Pedido #{order.id} - {order.company.name}",
        "installments": form_data.get("installments", 1),
        "payment_method_id": form_data.get("paymentMethodId"),
        "payer": {
            "email": payer_email,
            "identification": {
                "type": form_data.get("identificationType"),
                "number": form_data.get("identificationNumber"),
            },
        },
        "external_reference": order.external_reference,
        "notification_url": f"{current_app.config['PUBLIC_BASE_URL'].rstrip('/')}/webhooks/mercadopago",
    }

    # Campos opcionales
    if form_data.get("issuerId"):
        payment_data["issuer_id"] = form_data.get("issuerId")

    # Idempotency key: una por order + token de tarjeta. El token cambia con cada
    # tarjeta/intento (reintento tras rechazo = key nueva) y un doble clic con el
    # mismo token devuelve el mismo pago en vez de cobrar dos veces.
    idempotency_key = f"{order.external_reference}-{form_data.get('token')}"

    # Usar request_options para enviar X-Idempotency-Key
    request_options = mercadopago.config.RequestOptions()
    request_options.custom_headers = {"X-Idempotency-Key": idempotency_key}

    result = sdk.payment().create(payment_data, request_options)
    response = result.get("response", {})

    if result.get("status") not in (200, 201):
        error_msg = response.get("message", "Error desconocido")
        # Loguear causa completa para debugging (sin tokens)
        cause = response.get("cause", [])
        current_app.logger.error(
            f"MP Payment error: status={result.get('status')}, message={error_msg}, cause={cause}"
        )
        raise RuntimeError(f"MP Payment error: {error_msg}")

    return response


def reconcile_pending_payments() -> int:
    """
    Reconcilia pagos pendientes consultando a Mercado Pago.

    Busca pedidos PENDIENTE y pagos en estados no finales,
    consulta a MP por external_reference y actualiza estados.
    En sandbox, usa el token de cada empresa para cada consulta.

    Returns:
        int: Cantidad de pagos reconciliados (estado cambiado).
    """
    from app.extensions import db
    from app.models.order import Order, OrderStatus
    from app.models.payment import Payment, PaymentStatus
    from app.services.payments import process_mp_payment

    # Pedidos PENDIENTE sin pago aprobado
    pending_orders = Order.query.filter(
        Order.status == OrderStatus.PENDIENTE,
        ~Order.payments.any(Payment.status == PaymentStatus.APPROVED)
    ).all()

    # Pagos en estados no finales (pending, in_process, etc.)
    pending_payments = Payment.query.filter(
        Payment.status.in_([
            PaymentStatus.PENDING,
            PaymentStatus.IN_PROCESS,
            PaymentStatus.IN_MEDIATION,
            PaymentStatus.AUTHORIZED,
        ])
    ).all()

    reconciled = 0

    # Reconciliar pedidos pendientes sin pago aprobado
    for order in pending_orders:
        try:
            access_token, _ = get_mp_credentials(order)
            mp_payment = search_payment_by_external_ref(order.external_reference, access_token)
            if mp_payment:
                process_mp_payment(mp_payment)
                db.session.commit()
                reconciled += 1
        except Exception as e:
            current_app.logger.warning(f"Error reconciliando pedido {order.id}: {e}")
            db.session.rollback()

    # Reconciliar pagos en estados intermedios
    for payment in pending_payments:
        try:
            # Resolver token por la empresa del pedido
            access_token, _ = get_mp_credentials(payment.order)
            mp_payment = get_payment(payment.mp_payment_id, access_token)
            if mp_payment:
                process_mp_payment(mp_payment)
                db.session.commit()
                reconciled += 1
        except Exception as e:
            current_app.logger.warning(f"Error reconciliando pago {payment.id}: {e}")
            db.session.rollback()

    return reconciled