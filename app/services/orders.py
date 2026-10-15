"""
Servicio de pedidos y stock - B2B_B2C.

Lógica de negocio central: creación atómica de pedidos, reserva de stock,
expiración, cancelación. Todo en transacciones explícitas.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Dict, Any
from sqlalchemy import text
from app.extensions import db
from app.models.product import Product
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User


def reserve_stock_for_items(items: List[Dict[str, Any]]) -> bool:
    """
    Reserva stock atómicamente para múltiples items.

    Args:
        items: Lista de dicts con 'product_id' y 'quantity'.

    Returns:
        bool: True si todo OK, False si algún stock insuficiente (no cambia nada).
    """
    for item in items:
        pid = item["product_id"]
        qty = item["quantity"]
        result = db.session.execute(
            text(
                "UPDATE products SET stock = stock - :qty "
                "WHERE id = :pid AND stock >= :qty AND is_active = 1"
            ),
            {"qty": qty, "pid": pid},
        )
        if result.rowcount == 0:
            return False
    db.session.flush()
    return True


def release_stock_for_order(order: Order) -> None:
    """Devuelve stock de todos los items de un pedido."""
    for item in order.items:
        product = item.product
        if product:
            product.stock += item.quantity
            db.session.add(product)


def create_orders_from_cart(buyer_id: int, cart: Dict[str, int]) -> List[Order]:
    """
    Crea pedidos a partir del carrito (uno por empresa vendedora).

    Args:
        buyer_id: ID del comprador.
        cart: Dict {product_id: quantity} de la sesión.

    Returns:
        List[Order]: Pedidos creados (pendientes, con stock reservado).

    Raises:
        ValueError: Validaciones fallidas (stock, mínimo, compra propia, etc.)
    """
    if not cart:
        raise ValueError("Carrito vacío.")

    buyer = db.session.get(User, buyer_id)
    if not buyer:
        raise ValueError("Comprador no encontrado.")

    # Cargar productos y validar
    product_ids = [int(pid) for pid in cart.keys()]
    products = {p.id: p for p in Product.query.filter(Product.id.in_(product_ids)).all()}

    min_qty = 50 if buyer.is_empresa else 1
    items_by_company = {}

    for pid_str, qty in cart.items():
        pid = int(pid_str)
        product = products.get(pid)

        if not product:
            raise ValueError(f"Producto {pid} no existe.")
        if not product.is_active:
            raise ValueError(f"«{product.name}» ya no está disponible.")
        if product.stock < qty:
            raise ValueError(f"Stock insuficiente para «{product.name}» (disponible: {product.stock}).")

        # No comprarse a sí mismo
        if buyer.is_empresa and buyer.company and product.company_id == buyer.company.id:
            raise ValueError("No podés comprar tus propios productos.")

        # Mínimo por línea
        if qty < min_qty:
            raise ValueError(
                f"«{product.name}» requiere mínimo {min_qty} unidades "
                f"(sos cuenta {'empresa' if buyer.is_empresa else 'cliente'})."
            )

        items_by_company.setdefault(product.company_id, []).append({
            "product_id": pid,
            "quantity": qty,
            "product": product,
        })

    # Verificar duplicados (pedido pendiente idéntico)
    created_orders = []
    for company_id, items in items_by_company.items():
        # Preparar datos para chequeo de duplicado
        items_data = [{"product_id": i["product_id"], "quantity": i["quantity"]} for i in items]

        existing = Order.find_pending_duplicate(buyer_id, company_id, items_data)
        if existing:
            created_orders.append(existing)
            continue

        # Reservar stock atómicamente
        if not reserve_stock_for_items(items):
            raise ValueError("Stock cambiado durante la reserva. Revisá el carrito e intentá de nuevo.")

        # Calcular total
        total = sum(
            Decimal(str(i["product"].price)) * i["quantity"]
            for i in items
        )

        # Crear Order
        order = Order(
            buyer_id=buyer_id,
            company_id=company_id,
            status=OrderStatus.PENDIENTE,
            total=total,
            buyer_type_snapshot=buyer.account_type.value,
            external_reference=Order.generate_external_reference(),
            expires_at=Order.calculate_expiry(),
        )
        db.session.add(order)
        db.session.flush()  # Para obtener order.id

        # Crear OrderItems con snapshots
        for item in items:
            product = item["product"]
            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name_snapshot=product.name,
                unit_price_snapshot=product.price,
                quantity=item["quantity"],
                subtotal=Decimal(str(product.price)) * item["quantity"],
            )
            db.session.add(order_item)

        created_orders.append(order)

    return created_orders


def cancel_order(order: Order) -> None:
    """
    Cancela un pedido PENDIENTE y devuelve stock.

    Args:
        order: Pedido a cancelar (debe ser PENDIENTE y del comprador actual).
    """
    if order.status != OrderStatus.PENDIENTE:
        raise ValueError("Solo se pueden cancelar pedidos pendientes.")

    order.mark_cancelled()
    db.session.add(order)


def expire_pending_orders() -> int:
    """
    Expira pedidos PENDIENTE vencidos y devuelve stock.

    Returns:
        int: Cantidad de pedidos expirados.
    """
    now = datetime.now(timezone.utc)
    expired_orders = Order.query.filter(
        Order.status == OrderStatus.PENDIENTE,
        Order.expires_at < now,
    ).all()

    count = 0
    for order in expired_orders:
        order.mark_expired()
        db.session.add(order)
        count += 1

    if count:
        db.session.commit()

    return count