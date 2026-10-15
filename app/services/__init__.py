"""
Paquete de servicios - B2B_B2C.

Lógica de negocio separada de los blueprints.
"""

from app.services.auth import register_user_with_company
from app.services.orders import (
    create_orders_from_cart,
    cancel_order,
    expire_pending_orders,
    reserve_stock_for_items,
    release_stock_for_order,
)
from app.services.mercadopago import (
    create_preference,
    get_payment,
    search_payment_by_external_ref,
    reconcile_pending_payments,
)
from app.services.payments import process_mp_payment
from app.services.reports import get_dashboard_metrics
from app.services.seed import seed_database

__all__ = [
    "register_user_with_company",
    "create_orders_from_cart",
    "cancel_order",
    "expire_pending_orders",
    "reserve_stock_for_items",
    "release_stock_for_order",
    "create_preference",
    "get_payment",
    "search_payment_by_external_ref",
    "reconcile_pending_payments",
    "process_mp_payment",
    "get_dashboard_metrics",
    "seed_database",
]