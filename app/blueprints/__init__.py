"""
Paquete de blueprints - B2B_B2C.

Registra todos los blueprints en app/__init__.py.
"""

from app.blueprints.auth import auth_bp
from app.blueprints.main import main_bp
from app.blueprints.companies import companies_bp
from app.blueprints.cart import cart_bp
from app.blueprints.orders import orders_bp
from app.blueprints.payments import payments_bp
from app.blueprints.webhooks import webhooks_bp

__all__ = [
    "auth_bp",
    "main_bp",
    "companies_bp",
    "cart_bp",
    "orders_bp",
    "payments_bp",
    "webhooks_bp",
]