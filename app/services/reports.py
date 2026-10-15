"""
Servicio de reportes y métricas - B2B_B2C.

Consultas SQL reales para dashboards (cero datos hardcodeados).
"""

from decimal import Decimal
from sqlalchemy import func, case
from app.extensions import db
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.models.company import Company
from app.models.user import User


def get_dashboard_metrics(user: User) -> dict:
    """
    Calcula métricas reales para el dashboard según tipo de cuenta.

    Args:
        user: Usuario actual.

    Returns:
        dict: Métricas para template.
    """
    if user.is_empresa and user.company:
        return _empresa_metrics(user.company)
    else:
        return _cliente_metrics(user)


def _empresa_metrics(company: Company) -> dict:
    """Métricas para panel de empresa (vendedora)."""
    # Ventas (pedidos donde esta empresa es vendedora)
    sales_query = db.session.query(
        Order.status,
        func.count(Order.id).label("count"),
        func.coalesce(func.sum(Order.total), 0).label("total")
    ).filter_by(company_id=company.id).group_by(Order.status)

    sales_by_status = {
        row.status.value: {"count": row.count, "total": Decimal(str(row.total or 0))}
        for row in sales_query.all()
    }

    # Totales
    total_cobrado = sales_by_status.get("PAGADO", {}).get("total", Decimal("0"))
    total_pendiente = sales_by_status.get("PENDIENTE", {}).get("total", Decimal("0"))
    total_pedidos = sum(s["count"] for s in sales_by_status.values())

    # Stock bajo (productos activos con stock < 10)
    low_stock = Product.query.filter(
        Product.company_id == company.id,
        Product.is_active.is_(True),
        Product.stock < 10,
        Product.stock > 0
    ).count()

    out_of_stock = Product.query.filter(
        Product.company_id == company.id,
        Product.is_active.is_(True),
        Product.stock == 0
    ).count()

    return {
        "tipo": "empresa",
        "total_cobrado": total_cobrado,
        "total_pendiente": total_pendiente,
        "total_pedidos": total_pedidos,
        "stock_bajo": low_stock,
        "stock_agotado": out_of_stock,
        "sales_by_status": sales_by_status,
    }


def _cliente_metrics(user: User) -> dict:
    """Métricas para panel de cliente (comprador)."""
    purchases_query = db.session.query(
        Order.status,
        func.count(Order.id).label("count"),
        func.coalesce(func.sum(Order.total), 0).label("total")
    ).filter_by(buyer_id=user.id).group_by(Order.status)

    purchases_by_status = {
        row.status.value: {"count": row.count, "total": Decimal(str(row.total or 0))}
        for row in purchases_query.all()
    }

    total_gastado = purchases_by_status.get("PAGADO", {}).get("total", Decimal("0"))
    total_pendiente = purchases_by_status.get("PENDIENTE", {}).get("total", Decimal("0"))
    total_pedidos = sum(s["count"] for s in purchases_by_status.values())

    return {
        "tipo": "cliente",
        "total_gastado": total_gastado,
        "total_pendiente": total_pendiente,
        "total_pedidos": total_pedidos,
        "purchases_by_status": purchases_by_status,
    }


def get_sales_report(company_id: int, date_from=None, date_to=None) -> list:
    """
    Reporte de ventas detallado para exportación.

    Returns:
        list[dict]: Filas con pedido, items, pago, estado.
    """
    query = db.session.query(Order).filter_by(company_id=company_id)

    if date_from:
        query = query.filter(Order.created_at >= date_from)
    if date_to:
        query = query.filter(Order.created_at <= date_to)

    orders = query.order_by(Order.created_at.desc()).all()

    rows = []
    for order in orders:
        for item in order.items:
            rows.append({
                "pedido_id": order.id,
                "fecha": order.created_at.strftime("%Y-%m-%d %H:%M"),
                "comprador": order.buyer.username,
                "comprador_email": order.buyer.email,
                "producto": item.product_name_snapshot,
                "cantidad": item.quantity,
                "precio_unitario": Decimal(str(item.unit_price_snapshot)),
                "subtotal": Decimal(str(item.subtotal)),
                "total_pedido": Decimal(str(order.total)),
                "estado": order.status.value,
                "pago_estado": order.payments[0].status.value if order.payments else "SIN_PAGO",
                "pago_fecha": order.payments[0].created_at.strftime("%Y-%m-%d %H:%M") if order.payments else "",
            })

    return rows