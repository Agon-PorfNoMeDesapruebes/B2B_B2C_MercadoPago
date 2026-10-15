"""
Modelo de producto.

Publicados exclusivamente por empresas. Borrado lógico (is_active).
Precios en ARS con Decimal/Numeric(12,2).
"""

from datetime import datetime, timezone
from decimal import Decimal
from app.extensions import db
from app.models.company import Company
from app.models.types import UTCDateTime


class Product(db.Model):
    """
    Producto publicado por una empresa.

    - Solo la empresa dueña puede editar/eliminar (borrado lógico).
    - Precio >= 0, stock >= 0 validados en BD y aplicación.
    - Snapshots en OrderItem congelan nombre y precio al momento de la compra.
    """

    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(150), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    stock = db.Column(db.Integer, nullable=False, default=0)
    image_url = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Constraints a nivel BD
    __table_args__ = (
        db.CheckConstraint("price >= 0", name="ck_product_price_nonneg"),
        db.CheckConstraint("stock >= 0", name="ck_product_stock_nonneg"),
    )

    # Relaciones
    company = db.relationship("Company", back_populates="products", lazy="joined")
    order_items = db.relationship("OrderItem", back_populates="product", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Product {self.name} (${self.price}) stock={self.stock}>"

    # --- Propiedades de conveniencia ---

    @property
    def is_available(self) -> bool:
        """True si el producto está activo y tiene stock > 0."""
        return self.is_active and self.stock > 0

    @property
    def stock_status(self) -> str:
        """Estado de stock para badges: 'ok', 'low', 'out'."""
        if self.stock == 0:
            return "out"
        elif self.stock < 10:
            return "low"
        return "ok"

    @property
    def stock_status_label(self) -> str:
        """Etiqueta legible del estado de stock."""
        return {
            "ok": "Disponible",
            "low": "Pocas unidades",
            "out": "Agotado",
        }[self.stock_status]

    @property
    def stock_badge_class(self) -> str:
        """Clase CSS Bootstrap para el badge de stock."""
        return {
            "ok": "bg-success",
            "low": "bg-warning text-dark",
            "out": "bg-danger",
        }[self.stock_status]

    @property
    def formatted_price(self) -> str:
        """Precio formateado para ARS: $1.200,00"""
        # Usar locale en producción; aquí formateo manual simple
        return f"${self.price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # --- Métodos de stock atómico ---

    def reserve_stock(self, quantity: int) -> bool:
        """
        Reserva stock atómicamente usando UPDATE condicional.

        Args:
            quantity: Cantidad a reservar (debe ser > 0).

        Returns:
            bool: True si se reservó correctamente, False si stock insuficiente.
        """
        if quantity <= 0:
            return False

        result = db.session.execute(
            db.text(
                "UPDATE products SET stock = stock - :qty "
                "WHERE id = :pid AND stock >= :qty AND is_active = 1"
            ),
            {"qty": quantity, "pid": self.id},
        )
        db.session.flush()  # Sincronizar el estado en la sesión
        return result.rowcount > 0

    def release_stock(self, quantity: int) -> None:
        """
        Devuelve stock (para cancelaciones/expiraciones).

        Args:
            quantity: Cantidad a devolver.
        """
        if quantity <= 0:
            return
        self.stock += quantity
        db.session.add(self)

    # --- Métodos de clase ---

    @classmethod
    def get_active_by_company(cls, company_id: int):
        """Query base para productos activos de una empresa."""
        return db.session.execute(
            db.select(cls)
            .where(cls.company_id == company_id, cls.is_active.is_(True))
            .order_by(cls.created_at.desc())
        ).scalars()

    @classmethod
    def search_active(cls, company_id: int, query: str, page: int = 1, per_page: int = 12):
        """
        Busca productos activos de una empresa con paginación.

        Args:
            company_id: ID de la empresa.
            query: Término de búsqueda (nombre o descripción).
            page: Página (1-indexed).
            per_page: Items por página.

        Returns:
            Pagination object.
        """
        stmt = (
            db.select(cls)
            .where(
                cls.company_id == company_id,
                cls.is_active.is_(True),
                db.or_(
                    cls.name.ilike(f"%{query}%"),
                    cls.description.ilike(f"%{query}%"),
                ),
            )
            .order_by(cls.created_at.desc())
        )
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    @classmethod
    def create_for_company(
        cls,
        company: Company,
        name: str,
        price: Decimal,
        stock: int,
        description: str = "",
        image_url: str = "",
    ) -> "Product":
        """
        Crea un producto para una empresa.

        Args:
            company: Empresa dueña.
            name: Nombre del producto.
            price: Precio (Decimal, >= 0).
            stock: Stock inicial (int, >= 0).
            description: Descripción opcional.
            image_url: URL de imagen opcional.

        Returns:
            Product: El producto creado (sin commit).
        """
        return cls(
            company=company,
            name=name.strip(),
            description=description.strip() if description else "",
            price=price,
            stock=stock,
            image_url=image_url.strip() if image_url else "",
        )