"""
Blueprint de carrito - B2B_B2C.

Carrito persistente en BD (tabla CartItem) + caché en sesión para latencia.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user
from app.extensions import db
from app.models.product import Product
from app.models.cart import CartItem
from app.forms.cart import CartUpdateForm, CartConfirmForm

cart_bp = Blueprint("cart", __name__, url_prefix="/carrito")


def _get_cart_from_db():
    """Obtiene el carrito del usuario desde la BD."""
    return CartItem.query.filter_by(user_id=current_user.id).all()


def _get_cart_dict():
    """Obtiene el carrito como dict {product_id: quantity} para compatibilidad."""
    items = _get_cart_from_db()
    return {str(item.product_id): item.quantity for item in items}


def _sync_session_cart():
    """Sincroniza el carrito de la sesión con la BD."""
    session["cart"] = _get_cart_dict()
    session.modified = True


@cart_bp.route("/")
@login_required
def view_cart():
    """Ver carrito agrupado por empresa con subtotales y avisos de mínimo."""
    cart_items = _get_cart_from_db()
    if not cart_items:
        return render_template("cart/empty.html")

    # Agrupar por empresa
    from collections import defaultdict
    grouped = defaultdict(list)
    for item in cart_items:
        product = item.product
        if product and product.is_active:
            grouped[product.company_id].append({"product": product, "quantity": item.quantity, "cart_item": item})

    # Calcular subtotales y avisos
    min_qty = 50 if current_user.is_empresa else 1
    companies_data = []
    grand_total = 0

    for company_id, items in grouped.items():
        company = items[0]["product"].company
        subtotal = 0
        for item in items:
            item["subtotal"] = item["product"].price * item["quantity"]
            item["meets_minimum"] = item["quantity"] >= min_qty
            subtotal += item["subtotal"]
        grand_total += subtotal
        companies_data.append({
            "company": company,
            "items": items,
            "subtotal": subtotal,
        })

    confirm_form = CartConfirmForm(cart_items=[
        {"product": item["product"], "quantity": item["quantity"]}
        for items in grouped.values() for item in items
    ], buyer_type="empresa" if current_user.is_empresa else "cliente")

    return render_template(
        "cart/view.html",
        companies_data=companies_data,
        grand_total=grand_total,
        min_qty=min_qty,
        confirm_form=confirm_form,
    )


@cart_bp.route("/agregar/<int:product_id>", methods=["POST"])
@login_required
def add_to_cart(product_id):
    """Agregar producto al carrito (o incrementar cantidad)."""
    product = db.session.get(Product, product_id)
    if not product:
        flash("Producto no encontrado.", "error")
        return redirect(request.referrer or url_for("companies.list_companies"))

    # Validaciones básicas
    if not product.is_active:
        flash("Este producto no está disponible.", "error")
        return redirect(request.referrer or url_for("companies.list_companies"))

    if product.stock <= 0:
        flash("Sin stock disponible.", "error")
        return redirect(request.referrer or url_for("companies.list_companies"))

    # No comprarse a sí mismo
    if current_user.is_empresa and current_user.company and product.company_id == current_user.company.id:
        flash("No podés comprar tus propios productos.", "error")
        return redirect(request.referrer or url_for("companies.list_companies"))

    # Verificar si ya existe en el carrito
    existing = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if existing:
        existing.quantity += 1
    else:
        new_item = CartItem(user_id=current_user.id, product_id=product_id, quantity=1)
        db.session.add(new_item)
    
    db.session.commit()
    _sync_session_cart()

    flash(f"«{product.name}» agregado al carrito.", "success")
    return redirect(request.referrer or url_for("cart.view_cart"))


@cart_bp.route("/actualizar", methods=["POST"])
@login_required
def update_cart():
    """Actualizar cantidad de una línea."""
    form = CartUpdateForm()
    if form.validate_on_submit():
        pid = form.product_id.data
        item = CartItem.query.filter_by(user_id=current_user.id, product_id=pid).first()
        if item:
            if form.quantity.data > 0:
                item.quantity = form.quantity.data
            else:
                db.session.delete(item)
            db.session.commit()
            _sync_session_cart()
            flash("Carrito actualizado.", "success")
        else:
            flash("Producto no está en el carrito.", "error")
    else:
        for field, errors in form.errors.items():
            for err in errors:
                flash(err, "error")
    return redirect(url_for("cart.view_cart"))


@cart_bp.route("/quitar/<int:product_id>", methods=["POST"])
@login_required
def remove_from_cart(product_id):
    """Quitar producto del carrito."""
    item = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if item:
        db.session.delete(item)
        db.session.commit()
        _sync_session_cart()
        flash("Producto quitado del carrito.", "success")
    return redirect(url_for("cart.view_cart"))


@cart_bp.route("/vaciar", methods=["POST"])
@login_required
def clear_cart():
    """Vaciar carrito completo."""
    CartItem.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    _sync_session_cart()
    flash("Carrito vaciado.", "success")
    return redirect(url_for("cart.view_cart"))


@cart_bp.route("/confirmar", methods=["POST"])
@login_required
def confirm_cart():
    """Confirmar carrito -> crear pedidos (uno por empresa) y redirigir a pagos."""
    from app.services.orders import create_orders_from_cart

    cart_items = _get_cart_from_db()
    if not cart_items:
        flash("Tu carrito está vacío.", "error")
        return redirect(url_for("cart.view_cart"))

    cart_dict = {str(item.product_id): item.quantity for item in cart_items}
    
    confirm_form = CartConfirmForm(
        cart_items=[
            {"product": item.product, "quantity": item.quantity}
            for item in cart_items
        ],
        buyer_type="empresa" if current_user.is_empresa else "cliente",
    )

    if not confirm_form.validate_on_submit():
        for field, errors in confirm_form.errors.items():
            for err in errors:
                flash(err, "error")
        return redirect(url_for("cart.view_cart"))

    try:
        orders = create_orders_from_cart(current_user.id, cart_dict)
        db.session.commit()

        # Guardar IDs de pedidos creados en sesión para el flujo de pago
        session["pending_order_ids"] = [o.id for o in orders]
        session.modified = True

        # Si es un solo pedido, ir directo a Bricks; si son varios, mostrar resumen
        if len(orders) == 1:
            return redirect(url_for("payments.bricks_checkout", order_id=orders[0].id))
        else:
            return redirect(url_for("orders.multi_checkout", order_ids=",".join(str(o.id) for o in orders)))

    except ValueError as e:
        db.session.rollback()
        flash(str(e), "error")
        return redirect(url_for("cart.view_cart"))
    except Exception:
        db.session.rollback()
        flash("Error al crear el pedido. Intentá de nuevo.", "error")
        return redirect(url_for("cart.view_cart"))