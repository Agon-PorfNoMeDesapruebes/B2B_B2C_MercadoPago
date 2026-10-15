"""
Blueprint de pedidos - B2B_B2C.

Mis compras, mis ventas, detalle, comprobante, cancelación.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models.order import Order, OrderStatus, OrderItem
from app.models.payment import Payment
from app.services.orders import cancel_order, expire_pending_orders

orders_bp = Blueprint("orders", __name__, url_prefix="/pedidos")


@orders_bp.route("/mis-compras")
@login_required
def my_purchases():
    """Listado de pedidos donde soy comprador."""
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "")

    query = Order.query.filter_by(buyer_id=current_user.id)
    if status_filter:
        try:
            query = query.filter_by(status=OrderStatus(status_filter))
        except ValueError:
            # Ignorar filtro inválido
            status_filter = ""

    pagination = query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

    return render_template(
        "orders/my_purchases.html",
        orders=pagination,
        status_filter=status_filter,
        status_choices=[s.value for s in OrderStatus],
    )


@orders_bp.route("/mis-ventas")
@login_required
def my_sales():
    """Listado de pedidos recibidos (solo empresas)."""
    if not current_user.is_empresa or not current_user.company:
        abort(403)

    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "")

    query = Order.query.filter_by(company_id=current_user.company.id)
    if status_filter:
        try:
            query = query.filter_by(status=OrderStatus(status_filter))
        except ValueError:
            # Ignorar filtro inválido
            status_filter = ""

    pagination = query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

    # Métricas para el dashboard de ventas
    from sqlalchemy import func
    totals = db.session.execute(
        db.select(
            Order.status,
            func.count(Order.id).label("count"),
            func.coalesce(func.sum(Order.total), 0).label("sum")
        )
        .where(Order.company_id == current_user.company.id)
        .group_by(Order.status)
    ).all()

    metrics = {row.status.value: {"count": row.count, "total": row.sum} for row in totals}

    return render_template(
        "orders/my_sales.html",
        orders=pagination,
        status_filter=status_filter,
        status_choices=[s.value for s in OrderStatus],
        metrics=metrics,
    )


@orders_bp.route("/<int:order_id>")
@login_required
def order_detail(order_id):
    """Comprobante persistente del pedido (accesible por comprador o vendedor)."""
    order = db.session.get(Order, order_id)
    if not order:
        abort(404)

    # Autorización: solo comprador o empresa vendedora
    is_buyer = order.buyer_id == current_user.id
    is_seller = current_user.is_empresa and current_user.company and current_user.company.id == order.company_id
    if not (is_buyer or is_seller):
        abort(404)

    payments = order.payments.order_by(Payment.created_at.desc()).all()
    items = order.items

    return render_template(
        "orders/detail.html",
        order=order,
        items=items,
        payments=payments,
        is_buyer=is_buyer,
        is_seller=is_seller,
    )


@orders_bp.route("/<int:order_id>/cancelar", methods=["POST"])
@login_required
def cancel_order_route(order_id):
    """Cancelar pedido pendiente (solo comprador)."""
    order = db.session.get(Order, order_id)
    if not order or order.buyer_id != current_user.id:
        abort(404)

    if order.status != OrderStatus.PENDIENTE:
        flash("Solo se pueden cancelar pedidos pendientes.", "error")
        return redirect(url_for("orders.order_detail", order_id=order.id))

    try:
        cancel_order(order)
        db.session.commit()
        flash("Pedido cancelado y stock devuelto.", "success")
    except Exception:
        db.session.rollback()
        flash("Error al cancelar.", "error")

    return redirect(url_for("orders.order_detail", order_id=order.id))


@orders_bp.route("/multi-checkout")
@login_required
def multi_checkout():
    """Resumen de múltiples pedidos (carrito con varias empresas)."""
    order_ids_param = request.args.get("order_ids", "")
    try:
        order_ids = [int(x) for x in order_ids_param.split(",") if x]
    except ValueError:
        order_ids = []

    orders = Order.query.filter(
        Order.id.in_(order_ids),
        Order.buyer_id == current_user.id,
        Order.status == OrderStatus.PENDIENTE
    ).all()

    if not orders:
        flash("No hay pedidos pendientes para pagar.", "warning")
        return redirect(url_for("cart.view_cart"))

    return render_template("orders/multi_checkout.html", orders=orders)


# --- CLI Command (también accesible via blueprint para testing) ---
@orders_bp.cli.command("expire")
def expire_orders_cli():
    """Expirar pedidos pendientes vencidos (flask expire-orders)."""
    count = expire_pending_orders()
    print(f"Pedidos expirados: {count}")