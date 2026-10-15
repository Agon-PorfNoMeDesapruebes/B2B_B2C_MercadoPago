"""
Modelo de carrito - B2B_B2C.

Carrito persistente en BD (tabla CartItem).
"""
from datetime import datetime, timezone
from app.extensions import db
from app.models.types import UTCDateTime
from app.models.user import User
from app.models.product import Product


class CartItem(db.Model):
    """
    Ítem de carrito persistente en BD.
    
    Un usuario puede tener múltiples items en su carrito.
    """
    __tablename__ = "cart_items"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relaciones
    user = db.relationship("User", backref=db.backref("cart_items", lazy="dynamic", cascade="all, delete-orphan"))
    product = db.relationship("Product")

    # Unicidad: un usuario solo puede tener una línea por producto
    __table_args__ = (db.UniqueConstraint("user_id", "product_id", name="uq_cart_user_product"),)

    def __repr__(self):
        return f"<CartItem user={self.user_id} product={self.product_id} qty={self.quantity}>"