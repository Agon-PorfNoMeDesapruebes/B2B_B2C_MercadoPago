"""
Servicio de procesamiento de pagos - B2B_B2C.

Procesa la respuesta de MP (webhook o verificación manual) y actualiza Order/Payment.
"""

from decimal import Decimal
from app.extensions import db
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentStatus
from app.models.webhook_event import WebhookEvent


def process_mp_payment(mp_payment_data: dict) -> Payment:
    """
    Procesa un pago de Mercado Pago y actualiza BD.

    Args:
        mp_payment_data: Dict con respuesta de payment().get() del SDK.

    Returns:
        Payment: El pago creado/actualizado.

    Raises:
        ValueError: Si el monto/moneda no coinciden, o external_reference inválido.
    """
    mp_id = str(mp_payment_data.get("id", ""))
    status = mp_payment_data.get("status")
    status_detail = mp_payment_data.get("status_detail")
    amount = Decimal(str(mp_payment_data.get("transaction_amount", "0")))
    currency = mp_payment_data.get("currency_id", "ARS")
    payment_method = mp_payment_data.get("payment_method_id")
    external_reference = mp_payment_data.get("external_reference")

    if not external_reference:
        raise ValueError("Pago sin external_reference")

    # Buscar pedido por external_reference
    order = Order.query.filter_by(external_reference=external_reference).first()
    if not order:
        raise ValueError(f"Pedido no encontrado para external_reference={external_reference}")

    # Verificar monto y moneda
    if currency != "ARS":
        raise ValueError(f"Moneda inesperada: {currency}")
    if amount != order.total:
        raise ValueError(f"Monto no coincide: MP={amount}, Order={order.total}")

    # Mapear estado y actuar sobre Order ANTES de crear/actualizar Payment
    mp_status = PaymentStatus(status)

    if mp_status == PaymentStatus.APPROVED:
        # Si el pedido ya está en estado terminal (CANCELADO/EXPIRADO/RECHAZADO/REEMBOLSADO)
        # no forzar transición a PAGADO; registrar como late_approval para reembolso manual
        if order.status.is_final and order.status != OrderStatus.PAGADO:
            # No crear payment, solo registrar late_approval si no existe
            existing = Payment.query.filter_by(mp_payment_id=mp_id).first()
            if not existing:
                payment = Payment(
                    order_id=order.id,
                    provider="mercadopago",
                    mp_preference_id=order.mp_preference_id,
                    mp_payment_id=mp_id,
                    amount=amount,
                    status=PaymentStatus.APPROVED,
                    status_detail="late_approval",
                )
                db.session.add(payment)
                db.session.flush()
                return payment
            return Payment.query.filter_by(mp_payment_id=mp_id).first()
        else:
            order.transition_to(OrderStatus.PAGADO)
    elif mp_status == PaymentStatus.REJECTED:
        # REJECTED no cambia el estado del pedido a RECHAZADO (terminal)
        # El pedido se queda PENDIENTE con stock reservado, permitiendo reintentos
        # Solo registramos el pago rechazado para auditoría
        payment = Payment.query.filter_by(mp_payment_id=mp_id).first()
        if not payment:
            payment = Payment(
                order_id=order.id,
                provider="mercadopago",
                mp_preference_id=order.mp_preference_id,
                mp_payment_id=mp_id,
                amount=amount,
                status=PaymentStatus.REJECTED,
                status_detail=status_detail,
            )
            db.session.add(payment)
        # El pedido se queda PENDIENTE con stock reservado
    elif mp_status in (PaymentStatus.CANCELLED, PaymentStatus.EXPIRED):
        if mp_status == PaymentStatus.EXPIRED:
            order.transition_to(OrderStatus.EXPIRADO)
        else:
            order.transition_to(OrderStatus.CANCELADO)
    elif mp_status in (PaymentStatus.REFUNDED, PaymentStatus.CHARGED_BACK):
        if order.status == OrderStatus.PAGADO:
            order.transition_to(OrderStatus.REEMBOLSADO)
        else:
            payment = Payment.query.filter_by(mp_payment_id=mp_id).first()
            if not payment:
                payment = Payment(
                    order_id=order.id,
                    provider="mercadopago",
                    mp_preference_id=order.mp_preference_id,
                    mp_payment_id=mp_id,
                    amount=amount,
                    status=PaymentStatus.REEMBOLSADO,
                    status_detail=status_detail,
                )
                db.session.add(payment)
    elif mp_status == PaymentStatus.IN_PROCESS:
        pass

    # Crear o actualizar Payment por mp_payment_id (idempotencia por mp_payment_id)
    payment = Payment.query.filter_by(mp_payment_id=mp_id).first()
    if not payment:
        payment = Payment(
            order_id=order.id,
            provider="mercadopago",
            mp_preference_id=order.mp_preference_id,
            mp_payment_id=mp_id,
            amount=amount,
        )
        db.session.add(payment)

    # Actualizar con datos de MP
    payment.update_from_mp(mp_payment_data)

    db.session.add(order)
    db.session.add(payment)
    db.session.flush()

    return payment