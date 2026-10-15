"""
Modelo de pago (Payment).

Registra la información de pagos procesados por Mercado Pago.
Un pedido puede tener múltiples intentos de pago, pero solo uno aprobado.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from app.extensions import db
from app.models.order import Order
from app.models.types import UTCDateTime


class PaymentStatus(Enum):
    """Estados de pago según Mercado Pago (mapeados)."""

    PENDING = "pending"
    APPROVED = "approved"
    AUTHORIZED = "authorized"
    IN_PROCESS = "in_process"
    IN_MEDIATION = "in_mediation"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REFUNDED = "refunded"
    CHARGED_BACK = "charged_back"
    REEMBOLSADO = "reembolsado"

    @classmethod
    def from_mp(cls, value: str) -> "PaymentStatus":
        """Convierte string de MP a enum, mapeando desconocidos a IN_PROCESS."""
        try:
            return cls(value)
        except ValueError:
            # Estados desconocidos -> IN_PROCESS (no rompe el flujo)
            return cls.IN_PROCESS

    @property
    def label(self) -> str:
        return {
            PaymentStatus.PENDING: "Pendiente",
            PaymentStatus.APPROVED: "Aprobado",
            PaymentStatus.AUTHORIZED: "Autorizado",
            PaymentStatus.IN_PROCESS: "En proceso",
            PaymentStatus.IN_MEDIATION: "En mediación",
            PaymentStatus.REJECTED: "Rechazado",
            PaymentStatus.CANCELLED: "Cancelado",
            PaymentStatus.EXPIRED: "Expirado",
            PaymentStatus.REFUNDED: "Devuelto",
            PaymentStatus.CHARGED_BACK: "Contracargo",
            PaymentStatus.REEMBOLSADO: "Reembolsado",
        }[self]


class Payment(db.Model):
    """
    Pago asociado a un pedido.

    Guarda la respuesta cruda de MP para auditoría y debugging.
    Un pedido solo puede tener UN pago con status=APPROVED.
    """

    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(
        db.Integer,
        db.ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = db.Column(db.String(20), nullable=False, default="mercadopago")
    mp_preference_id = db.Column(db.String(100), nullable=True, index=True)
    mp_payment_id = db.Column(
        db.String(100), unique=True, nullable=True, index=True
    )  # Se llena cuando MP crea el pago
    status = db.Column(
        db.Enum(PaymentStatus, native_enum=False, validate_strings=True),
        nullable=False,
        default=PaymentStatus.PENDING,
        index=True,
    )
    status_detail = db.Column(db.String(100), nullable=True)  # Detalle de MP (ej: "cc_rejected_bad_filled_date")
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    payment_method = db.Column(db.String(50), nullable=True)  # Lo que informa MP (visa, master, ticket, etc.)
    raw_response = db.Column(db.JSON, nullable=True)  # JSON completo de la respuesta de MP
    created_at = db.Column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relaciones
    order = db.relationship("Order", back_populates="payments", lazy="joined")

    def __repr__(self) -> str:
        return f"<Payment order={self.order_id} mp_id={self.mp_payment_id} status={self.status.value}>"

    @property
    def formatted_amount(self) -> str:
        return f"${self.amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @property
    def rejection_reason(self) -> str:
        """
        Traduce status_detail de MP a mensaje legible en español rioplatense.

        Returns:
            str: Mensaje amigable para el usuario.
        """
        if not self.status_detail:
            return "El pago fue rechazado."

        detail_map = {
            "cc_rejected_bad_filled_date": "Fecha de vencimiento inválida.",
            "cc_rejected_bad_filled_security_code": "Código de seguridad incorrecto.",
            "cc_rejected_bad_filled_card_number": "Número de tarjeta inválido.",
            "cc_rejected_insufficient_amount": "Fondos insuficientes.",
            "cc_rejected_high_risk": "Pago rechazado por riesgo alto.",
            "cc_rejected_call_for_authorize": "Requiere autorización del banco emisor.",
            "cc_rejected_other_reason": "Rechazado por el banco emisor.",
            "cc_rejected_card_disabled": "Tarjeta deshabilitada.",
            "expired": "El pago expiró.",
            "cancelled": "El pago fue cancelado.",
        }
        return detail_map.get(self.status_detail, "El pago no pudo procesarse.")

    def update_from_mp(self, mp_payment_data: dict) -> None:
        """
        Actualiza el pago con datos de la API de Mercado Pago.

        Args:
            mp_payment_data: Dict con la respuesta de payment().get() del SDK.
        """
        self.mp_payment_id = str(mp_payment_data.get("id", ""))
        self.status = PaymentStatus(mp_payment_data.get("status", "pending"))
        self.status_detail = mp_payment_data.get("status_detail")
        self.amount = Decimal(str(mp_payment_data.get("transaction_amount", "0")))
        self.payment_method = mp_payment_data.get("payment_method_id")
        self.raw_response = mp_payment_data
        self.updated_at = datetime.now(timezone.utc)
        db.session.add(self)


class PaymentMethodType(Enum):
    """Tipos de método de pago que ofrece MP (informativo)."""

    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    TICKET = "ticket"  # Efectivo (Pago Fácil, Rapipago, etc.)
    BANK_TRANSFER = "bank_transfer"
    WALLET = "wallet"  # Saldo en cuenta MP