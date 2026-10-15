"""
Modelo de empresa (Company).

Cada cuenta empresa tiene exactamente una Company asociada.
Contiene datos fiscales y de presentación del sector/tienda.
"""

from datetime import datetime, timezone
from app.extensions import db
from app.models.user import User
from app.models.types import UTCDateTime


class Company(db.Model):
    """
    Empresa vendedora (sector/tienda en el marketplace).

    Relación 1:1 con User (owner). Solo usuarios con account_type=EMPRESA
    pueden tener una Company.
    """

    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    tax_id = db.Column(db.String(13), unique=True, nullable=False, index=True)  # CUIT sin guiones
    description = db.Column(db.Text, nullable=True)
    logo_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # --- Mercado Pago credentials (sandbox per-company) ---
    # Nullable: solo se usan en MP_SANDBOX=True; en producción se usan credenciales globales.
    # NUNCA renderizar mp_access_token ni mp_webhook_secret en templates ni logs.
    mp_seller_user_id = db.Column(db.String(50), nullable=True, index=True)  # User ID del vendedor de prueba en MP
    mp_access_token = db.Column(db.String(200), nullable=True)  # Access token del vendedor de prueba
    mp_public_key = db.Column(db.String(200), nullable=True)    # Public key del vendedor de prueba
    mp_webhook_secret = db.Column(db.String(200), nullable=True)  # Secret para validar webhooks de este vendedor

    # Relaciones
    owner = db.relationship("User", back_populates="company", lazy="joined")
    products = db.relationship(
        "Product",
        back_populates="company",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    orders_as_seller = db.relationship(
        "Order",
        back_populates="company",
        foreign_keys="Order.company_id",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<Company {self.name} (CUIT: {self.tax_id})>"

    # --- Validaciones y utilidades ---

    @staticmethod
    def normalize_cuit(cuit: str) -> str:
        """
        Normaliza CUIT: quita guiones y espacios, deja solo dígitos.

        Args:
            cuit: CUIT con o sin formato (ej: "20-12345678-9").

        Returns:
            str: Solo 11 dígitos.
        """
        return "".join(ch for ch in cuit if ch.isdigit())

    @staticmethod
    def validate_cuit(cuit: str) -> bool:
        """
        Valida CUIT argentino (11 dígitos + dígito verificador módulo 11).

        Args:
            cuit: CUIT normalizado (11 dígitos).

        Returns:
            bool: True si el dígito verificador es correcto.
        """
        cuit = Company.normalize_cuit(cuit)
        if len(cuit) != 11 or not cuit.isdigit():
            return False

        # Pesos para el algoritmo módulo 11 (de izquierda a derecha, excluyendo el DV)
        # Pesos oficiales AFIP: 5, 4, 3, 2, 7, 6, 5, 4, 3, 2
        weights = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
        digits = [int(d) for d in cuit[:10]]
        dv = int(cuit[10])

        total = sum(d * w for d, w in zip(digits, weights))
        remainder = total % 11
        
        # Algoritmo oficial AFIP
        if remainder == 0:
            calculated_dv = 0
        elif remainder == 1:
            calculated_dv = 9
        else:
            calculated_dv = 11 - remainder

        return calculated_dv == dv

    @property
    def formatted_cuit(self) -> str:
        """CUIT formateado para mostrar: XX-XXXXXXXX-X."""
        cuit = self.tax_id
        if len(cuit) == 11:
            return f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}"
        return cuit

    @property
    def active_products_count(self) -> int:
        """Cantidad de productos activos (para mostrar en tarjetas)."""
        return self.products.filter_by(is_active=True).count()

    @classmethod
    def create_for_owner(
        cls,
        owner: User,
        name: str,
        tax_id: str,
        description: str = "",
    ) -> "Company":
        """
        Crea una empresa para un usuario dueño.

        Args:
            owner: Usuario dueño (debe ser account_type=EMPRESA).
            name: Nombre único de la empresa.
            tax_id: CUIT válido (11 dígitos).
            description: Descripción opcional.

        Returns:
            Company: La empresa creada (sin commit).
        """
        normalized_cuit = cls.normalize_cuit(tax_id)
        return cls(
            owner=owner,
            name=name.strip(),
            tax_id=normalized_cuit,
            description=description.strip() if description else "",
        )