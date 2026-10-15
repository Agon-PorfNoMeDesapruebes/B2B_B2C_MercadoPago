"""
Blueprint de pagos - B2B_B2C.

Checkout Pro de Mercado Pago, Checkout Bricks, verificación, reconciliación.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, current_app, jsonify
from flask_login import login_required, current_user
from app.extensions import db, csrf
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentStatus
from app.services.mercadopago import create_preference, get_payment, search_payment_by_external_ref, create_payment_bricks
from app.services.mp_accounts import get_mp_credentials

payments_bp = Blueprint("payments", __name__, url_prefix="/pagos")


@payments_bp.route("/checkout/<int:order_id>")
@login_required
def checkout(order_id):
    """Iniciar checkout: crear preference MP y redirigir."""
    order = db.session.get(Order, order_id)
    if not order or order.buyer_id != current_user.id:
        abort(404)

    if order.status != OrderStatus.PENDIENTE:
        flash("Este pedido no está pendiente de pago.", "warning")
        return redirect(url_for("orders.order_detail", order_id=order.id))

    # Verificar que no haya pago aprobado ya
    approved = order.payments.filter_by(status=PaymentStatus.APPROVED).first()
    if approved:
        flash("Este pedido ya fue pagado.", "info")
        return redirect(url_for("orders.order_detail", order_id=order.id))

    try:
        # Crear preference en MP
        preference = create_preference(order)
        order.mp_preference_id = preference["id"]
        db.session.add(order)
        db.session.commit()

        # Redirigir al checkout de MP
        init_point = preference.get("sandbox_init_point") or preference.get("init_point")
        return redirect(init_point)

    except Exception as e:
        current_app.logger.exception("Error creando preference MP")
        flash("No se pudo iniciar el pago. Intentá de nuevo.", "error")
        return redirect(url_for("orders.order_detail", order_id=order.id))


# ============================================================
# CHECKOUT BRICKS (Iframe embebido - usuario no sale de la app)
# ============================================================

@payments_bp.route("/bricks/<int:order_id>")
@login_required
def bricks_checkout(order_id):
    """Checkout embebido con Mercado Pago Bricks (iframe seguro)."""
    order = db.session.get(Order, order_id)
    if not order or order.buyer_id != current_user.id:
        abort(404)

    if order.status != OrderStatus.PENDIENTE:
        flash("Este pedido no está pendiente de pago.", "warning")
        return redirect(url_for("orders.order_detail", order_id=order.id))

    # Verificar que no haya pago aprobado ya
    approved = order.payments.filter_by(status=PaymentStatus.APPROVED).first()
    if approved:
        flash("Este pedido ya fue pagado.", "info")
        return redirect(url_for("orders.order_detail", order_id=order.id))

    try:
        # Crear preference en MP
        preference = create_preference(order)
        order.mp_preference_id = preference["id"]
        db.session.commit()
    except Exception as e:
        current_app.logger.exception("Error creando preference MP")
        flash("No se pudo iniciar el pago. Intentá de nuevo.", "error")
        return redirect(url_for("orders.order_detail", order_id=order.id))

    # Obtener credenciales de la empresa del pedido (sandbox: por empresa; prod: global)
    _, mp_public_key = get_mp_credentials(order)

    # Email del comprador de prueba para precargar en el Brick (sandbox)
    sandbox = current_app.config.get("MP_SANDBOX", True)
    test_buyer_email = current_app.config.get("MP_TEST_BUYER_EMAIL", "") if sandbox else ""

    # Renderiza template con Bricks
    return render_template(
        "payments/bricks_checkout.html",
        order=order,
        preference_id=preference["id"],
        mp_public_key=mp_public_key,
        test_buyer_email=test_buyer_email,
    )


@payments_bp.route("/bricks/submit", methods=["POST"])
@login_required
@csrf.exempt  # Token va en header X-CSRFToken
def bricks_submit():
    """Recibe formData del Brick y crea el pago en MP."""
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "Datos inválidos"}), 400

    form_data = data.get("formData", {})
    preference_id = data.get("preferenceId")

    # Buscar pedido por preference_id
    order = Order.query.filter_by(mp_preference_id=preference_id).first()
    if not order or order.buyer_id != current_user.id:
        return jsonify({"status": "error", "message": "Pedido no encontrado"}), 404

    try:
        # Crear pago en MP usando el token del Brick
        response = create_payment_bricks(order, form_data)

        # Procesar respuesta usando la MISMA lógica del webhook
        from app.services.payments import process_mp_payment
        payment = process_mp_payment(response)
        db.session.commit()

        # Responder al Brick
        if payment.status.value == "approved":
            return jsonify({"status": "approved"})
        elif payment.status.value == "pending":
            return jsonify({"status": "pending"})
        else:
            return jsonify({
                "status": "rejected",
                "reason": payment.status_detail or "rejected"
            })

    except RuntimeError as e:
        # Error de MP: loguear cuerpo completo sin tokens, devolver mensaje real solo en debug
        current_app.logger.error(f"MP Payment error: {e}")
        if current_app.debug:
            return jsonify({"status": "error", "message": str(e)}), 500
        return jsonify({"status": "error", "message": "Error interno"}), 500
    except Exception as e:
        current_app.logger.exception("Error procesando pago Bricks")
        if current_app.debug:
            return jsonify({"status": "error", "message": str(e)}), 500
        return jsonify({"status": "error", "message": "Error interno"}), 500


@payments_bp.route("/retorno/success")
@login_required
def payment_success():
    """Retorno de MP (success) - solo informa, no marca pagado."""
    order_id = request.args.get("external_reference")
    payment_id = request.args.get("payment_id")
    status = request.args.get("status")

    order = None
    if order_id:
        order = Order.query.filter_by(external_reference=order_id, buyer_id=current_user.id).first()

    return render_template(
        "payments/return.html",
        order=order,
        mp_status=status,
        mp_payment_id=payment_id,
        title="Pago procesado",
        message="Tu pago está siendo procesado. Volvé en unos minutos para ver el estado confirmado."
    )


@payments_bp.route("/retorno/failure")
@login_required
def payment_failure():
    """Retorno de MP (failure)."""
    order_id = request.args.get("external_reference")
    order = None
    if order_id:
        order = Order.query.filter_by(external_reference=order_id, buyer_id=current_user.id).first()

    return render_template(
        "payments/return.html",
        order=order,
        mp_status="rejected",
        title="Pago no completado",
        message="El pago no pudo procesarse. Podés reintentar desde el detalle del pedido."
    )


@payments_bp.route("/retorno/pending")
@login_required
def payment_pending():
    """Retorno de MP (pending - ej. pago en efectivo)."""
    order_id = request.args.get("external_reference")
    order = None
    if order_id:
        order = Order.query.filter_by(external_reference=order_id, buyer_id=current_user.id).first()

    return render_template(
        "payments/return.html",
        order=order,
        mp_status="pending",
        title="Pago pendiente",
        message="El pago está pendiente (ej. pago en efectivo). Se confirmará automáticamente cuando se acredite."
    )


@payments_bp.route("/verificar/<int:order_id>", methods=["POST"])
@login_required
def verify_payment(order_id):
    """Botón 'Verificar pago' - Plan B: consulta a MP por external_reference."""
    order = db.session.get(Order, order_id)
    if not order:
        abort(404)

    # Autorización: comprador o vendedor
    is_buyer = order.buyer_id == current_user.id
    is_seller = current_user.is_empresa and current_user.company and current_user.company.id == order.company_id
    if not (is_buyer or is_seller):
        abort(403)

    if order.status == OrderStatus.PAGADO:
        flash("Este pedido ya está marcado como pagado.", "info")
        return redirect(url_for("orders.order_detail", order_id=order.id))

    try:
        # Buscar pago en MP por external_reference usando credenciales de la empresa
        access_token, _ = get_mp_credentials(order)
        mp_payment = search_payment_by_external_ref(order.external_reference, access_token)
        if mp_payment:
            # Procesar como lo haría el webhook
            from app.services.payments import process_mp_payment
            process_mp_payment(mp_payment)
            db.session.commit()
            flash("Estado de pago actualizado desde Mercado Pago.", "success")
        else:
            flash("No se encontró pago en Mercado Pago para este pedido.", "warning")
    except Exception as e:
        current_app.logger.exception("Error verificando pago")
        flash("Error al consultar Mercado Pago.", "error")

    return redirect(url_for("orders.order_detail", order_id=order.id))