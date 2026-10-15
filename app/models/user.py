"""
Modelo de usuario de la aplicación.

Define los tipos de cuenta (empresa/cliente) y la autenticación.
"""

import enum
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db
from flask_login import UserMixin
from app.models.types import UTCDateTime


class AccountType(enum.Enum):
    """Tipos de cuenta disponibles. Elegidos al registrarse y fijos."""

    EMPRESA = "EMPRESA"
    CLIENTE = "CLIENTE"

    @property
    def label(self) -> str:
        """Etiqueta legible para la UI."""
        return {
            AccountType.EMPRESA: "Empresa",
            AccountType.CLIENTE: "Cliente",
        }[self]


class User(db.Model, UserMixin):
    """
    Usuario del sistema.

    Cada usuario tiene un tipo de cuenta fijo (empresa/cliente).
    Las empresas tienen un registro Company asociado (1:1).
    """

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    account_type = db.Column(
        db.Enum(AccountType, native_enum=False, validate_strings=True),
        nullable=False,
        default=AccountType.CLIENTE,
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relaciones
    company = db.relationship(
        "Company",
        back_populates="owner",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="joined",
    )
    orders_as_buyer = db.relationship(
        "Order",
        back_populates="buyer",
        foreign_keys="Order.buyer_id",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.account_type.value})>"

    # --- Propiedades de conveniencia ---

    @property
    def is_empresa(self) -> bool:
        """True si el usuario es una cuenta empresa."""
        return self.account_type == AccountType.EMPRESA

    @property
    def is_cliente(self) -> bool:
        """True si el usuario es una cuenta cliente."""
        return self.account_type == AccountType.CLIENTE

    @property
    def min_qty_per_line(self) -> int:
        """Mínimo de unidades por línea de pedido según tipo de cuenta."""
        from app.config import config_by_name
        # Nota: en runtime se usa current_app.config
        # Aquí devolvemos los defaults; el servicio usa app.config
        return 50 if self.is_empresa else 1

    # --- Métodos de contraseña ---

    def set_password(self, password: str) -> None:
        """
        Hashea y guarda la contraseña.

        Usa scrypt (default de Werkzeug >= 2.0) que es resistente a GPU.
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verifica la contraseña contra el hash almacenado."""
        return check_password_hash(self.password_hash, password)

    # --- Métodos de clase ---

    @classmethod
    def get_by_email(cls, email: str):
        """
        Busca usuario por email normalizado (minúsculas).

        Args:
            email: Email a buscar.

        Returns:
            User o None.
        """
        return db.session.execute(
            db.select(cls).where(cls.email == email.lower().strip())
        ).scalar_one_or_none()

    @classmethod
    def get_by_username(cls, username: str):
        """Busca usuario por username exacto."""
        return db.session.execute(
            db.select(cls).where(cls.username == username)
        ).scalar_one_or_none()

    @classmethod
    def create_user(
        cls,
        username: str,
        email: str,
        password: str,
        account_type: AccountType,
    ) -> "User":
        """
        Crea un nuevo usuario con validaciones básicas.

        Args:
            username: Nombre de usuario único.
            email: Email único (se normaliza a minúsculas).
            password: Contraseña en texto plano (mín. 8 chars validado en form).
            account_type: AccountType.EMPRESA o AccountType.CLIENTE.

        Returns:
            User: El usuario creado (sin commit).
        """
        user = cls(
            username=username.strip(),
            email=email.lower().strip(),
            account_type=account_type,
        )
        user.set_password(password)
        return user