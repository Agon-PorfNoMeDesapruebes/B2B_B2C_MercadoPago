"""
Modelos de pedido (Order) e items de pedido (OrderItem).

Un Order pertenece a un comprador (User) y a una empresa vendedora (Company).
OrderItem congela nombre y precio al momento de la compra (snapshots).
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from app.extensions import db
from app.models.user import User, AccountType
from app.models.company import Company
from app.models.product import Product
from app.models.types import UTCDateTime


class OrderStatus(Enum):
    """Estados posibles de un pedido."""

    PENDIENTE = "PENDIENTE"
    PAGADO = "PAGADO"
    RECHAZADO = "RECHAZADO"
    CANCELADO = "CANCELADO"
    EXPIRADO = "EXPIRADO"
    REEMBOLSADO = "REEMBOLSADO"

    @property
    def label(self) -> str:
        return self.value

    @property
    def badge_class(self) -> str:
        """Clase CSS Bootstrap para badge de estado."""
        return {
            OrderStatus.PENDIENTE: "bg-warning text-dark",
            OrderStatus.PAGADO: "bg-success",
            OrderStatus.RECHAZADO: "bg-danger",
            OrderStatus.CANCELADO: "bg-secondary",
            OrderStatus.EXPIRADO: "bg-dark",
            OrderStatus.REEMBOLSADO: "bg-info",
        }[self]

    @property
    def is_final(self) -> bool:
        """True si el estado es terminal (no vuelve a PENDIENTE)."""
        return self in (
            OrderStatus.PAGADO,
            OrderStatus.RECHAZADO,
            OrderStatus.CANCELADO,
            OrderStatus.EXPIRADO,
            OrderStatus.REEMBOLSADO,
        )

    @property
    def allows_payment(self) -> bool:
        """True si se puede iniciar un pago para este estado."""
        return self == OrderStatus.PENDIENTE

    def can_transition_to(self, nuevo_estado: "OrderStatus") -> bool:
        """Verifica si la transición es permitida."""
        from app.models.order import _ORDER_STATUS_TRANSITIONS
        permitidos = _ORDER_STATUS_TRANSITIONS.get(self.value, set())
        return nuevo_estado.value in permitidos


# Transiciones permitidas: estado_origen -> set(estados_destino_permitidos)
# Definido fuera del Enum para evitar que se convierta en miembro del enum
_ORDER_STATUS_TRANSITIONS = {
    "PENDIENTE": {"PAGADO", "RECHAZADO", "CANCELADO", "EXPIRADO"},
    "PAGADO": {"REEMBOLSADO"},
    "RECHAZADO": {"PENDIENTE"},  # Permitir reintentar
    # Los demás son terminales
}


class Order(db.Model):
    """
    Pedido de compra.

    Un pedido agrupa items de una sola empresa vendedora.
    El carrito puede tener productos de varias empresas, pero al confirmar
    se crea un Order por cada company_id.
    """

    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status = db.Column(
        db.Enum(OrderStatus, native_enum=False, validate_strings=True),
        nullable=False,
        default=OrderStatus.PENDIENTE,
        index=True,
    )
    total = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    buyer_type_snapshot = db.Column(
        db.Enum(AccountType, native_enum=False, validate_strings=True),
        nullable=False,
    )  # Guardar el tipo de cuenta del comprador al momento del pedido
    mp_preference_id = db.Column(db.String(100), nullable=True, index=True)
    external_reference = db.Column(
        db.String(36), unique=True, nullable=False, index=True
    )  # UUID para Mercado Pago
    created_at = db.Column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    expires_at = db.Column(
        UTCDateTime,
        nullable=False,
        default=lambda: Order.calculate_expiry(),
        index=True,
    )

    # Relaciones
    buyer = db.relationship(
        "User", back_populates="orders_as_buyer", foreign_keys=[buyer_id], lazy="joined"
    )
    company = db.relationship(
        "Company",
        back_populates="orders_as_seller",
        foreign_keys=[company_id],
        lazy="joined",
    )
    items = db.relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="joined",
    )
    payments = db.relationship(
        "Payment",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<Order #{self.id} {self.status.value} ${self.total} buyer={self.buyer_id}>"

    # --- Propiedades de conveniencia ---

    @property
    def is_expired(self) -> bool:
        """True si el pedido venció (según expires_at)."""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def can_cancel(self) -> bool:
        """True si el comprador puede cancelar (solo PENDIENTE y no vencido)."""
        return self.status == OrderStatus.PENDIENTE and not self.is_expired

    @property
    def can_pay(self) -> bool:
        """True si se puede intentar pagar (PENDIENTE, no vencido, sin pago aprobado)."""
        if self.status != OrderStatus.PENDIENTE or self.is_expired:
            return False
        # Verificar que no haya pago aprobado
        # Import local: payment.py importa Order, así que arriba sería circular
        from app.models.payment import PaymentStatus

        approved_payment = self.payments.filter_by(
            status=PaymentStatus.APPROVED
        ).first()
        return approved_payment is None

    @property
    def formatted_total(self) -> str:
        """Total formateado para ARS."""
        return f"${self.total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # --- Métodos de estado ---

    def mark_paid(self) -> None:
        """Marca el pedido como PAGADO (stock ya descontado en reserva)."""
        self.transition_to(OrderStatus.PAGADO)

    def mark_rejected(self, reason: str = "") -> None:
        """Marca como RECHAZADO y devuelve stock."""
        self.transition_to(OrderStatus.RECHAZADO)

    def mark_cancelled(self) -> None:
        """Marca como CANCELADO (por comprador) y devuelve stock."""
        self.transition_to(OrderStatus.CANCELADO)

    def mark_expired(self) -> None:
        """Marca como EXPIRADO (por expiración) y devuelve stock."""
        self.transition_to(OrderStatus.EXPIRADO)

    def _release_all_stock(self) -> None:
        """Devuelve el stock de todos los items del pedido."""
        for item in self.items:
            item.product.release_stock(item.quantity)

    def transition_to(self, nuevo_estado: "OrderStatus") -> None:
        """
        Cambia el estado validando la transición.
        
        Args:
            nuevo_estado: Nuevo estado al que transicionar.
            
        Raises:
            ValueError: Si la transición no es permitida.
        """
        from app.models.order import _ORDER_STATUS_TRANSITIONS
        if not self.status.can_transition_to(nuevo_estado):
            raise ValueError(
                f"Transición inválida: {self.status.value} -> {nuevo_estado.value}. "
                f"Permitidas desde {self.status.value}: {_ORDER_STATUS_TRANSITIONS.get(self.status.value, set())}"
            )
        
        # Devolver stock si la transición implica devolver stock
        transiciones_con_devolucion = {
            (OrderStatus.PENDIENTE, OrderStatus.RECHAZADO),
            (OrderStatus.PENDIENTE, OrderStatus.CANCELADO),
            (OrderStatus.PENDIENTE, OrderStatus.EXPIRADO),
            (OrderStatus.PAGADO, OrderStatus.REEMBOLSADO),
        }
        
        if (self.status, nuevo_estado) in transiciones_con_devolucion:
            self._release_all_stock()
        
        self.status = nuevo_estado
        db.session.add(self)

    # --- Métodos de clase ---

    @classmethod
    def generate_external_reference(cls) -> str:
        """Genera UUID único para external_reference de Mercado Pago."""
        return str(uuid.uuid4())

    @classmethod
    def calculate_expiry(cls, minutes: int = None) -> datetime:
        """Calcula la fecha de expiración (ahora + minutos)."""
        if minutes is None:
            from flask import current_app
            minutes = current_app.config.get("ORDER_EXPIRY_MINUTES", 30)
        return datetime.now(timezone.utc) + timedelta(minutes=minutes)

    @classmethod
    def find_pending_duplicate(
        cls, buyer_id: int, company_id: int, items_data: list[dict]
    ) -> "Order | None":
        """
        Busca un pedido PENDIENTE idéntico (mismo comprador, misma empresa, mismos items).

        Args:
            buyer_id: ID del comprador.
            company_id: ID de la empresa vendedora.
            items_data: Lista de dicts con product_id y quantity.

        Returns:
            Order o None.
        """
        # Buscar pedidos pendientes del mismo comprador a la misma empresa
        pending_orders = db.session.execute(
            db.select(cls)
            .where(
                cls.buyer_id == buyer_id,
                cls.company_id == company_id,
                cls.status == OrderStatus.PENDIENTE,
            )
            .order_by(cls.created_at.desc())
        ).unique().scalars().all()

        for order in pending_orders:
            if order._items_match(items_data):
                return order
        return None

    def _items_match(self, items_data: list[dict]) -> bool:
        """Compara si los items del pedido coinciden con los datos dados."""
        if len(self.items) != len(items_data):
            return False
        order_items = {(item.product_id, item.quantity) for item in self.items}
        new_items = {(item["product_id"], item["quantity"]) for item in items_data}
        return order_items == new_items


class OrderItem(db.Model):
    """
    Línea de pedido (item).

    Congela nombre y precio unitario al momento de la compra (snapshots).
    El subtotal = unit_price_snapshot * quantity.
    """

    __tablename__ = "order_items"

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("orders.id", ondelete="CASCADE"),
        primary_key=True,
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    product_name_snapshot = db.Column(db.String(150), nullable=False)
    unit_price_snapshot = db.Column(db.Numeric(12, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False)

    # Relaciones
    order = db.relationship("Order", back_populates="items", lazy="joined")
    product = db.relationship("Product", back_populates="order_items", lazy="joined")

    def __repr__(self) -> str:
        return f"<OrderItem order={self.order_id} product={self.product_id} x{self.quantity}>"

    @property
    def formatted_unit_price(self) -> str:
        return f"${self.unit_price_snapshot:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @property
    def formatted_subtotal(self) -> str:
        return f"${self.subtotal:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")