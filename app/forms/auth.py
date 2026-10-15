"""
Formularios de autenticación - B2B_B2C.

Registro diferenciado por tipo de cuenta (Empresa / Cliente).
Validaciones server-side + CSRF automático via Flask-WTF.
"""

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError
from app.models.user import User, AccountType
from app.models.company import Company


class LoginForm(FlaskForm):
    """Formulario de inicio de sesión."""

    email = StringField(
        "Correo electrónico",
        validators=[DataRequired(message="El email es obligatorio."), Email(message="Email inválido.")],
        render_kw={"placeholder": "tu@correo.com", "autocomplete": "email"},
    )
    password = PasswordField(
        "Contraseña",
        validators=[DataRequired(message="La contraseña es obligatoria.")],
        render_kw={"placeholder": "••••••••", "autocomplete": "current-password"},
    )
    remember = BooleanField("Recordarme", default=False)
    submit = SubmitField("Ingresar")


class RegisterBaseForm(FlaskForm):
    """Campos comunes a ambos tipos de registro."""

    username = StringField(
        "Nombre de usuario",
        validators=[
            DataRequired(message="El usuario es obligatorio."),
            Length(min=3, max=30, message="Entre 3 y 30 caracteres."),
        ],
        render_kw={"placeholder": "usuario123", "autocomplete": "username"},
    )
    email = StringField(
        "Correo electrónico",
        validators=[
            DataRequired(message="El email es obligatorio."),
            Email(message="Email inválido."),
        ],
        render_kw={"placeholder": "tu@correo.com", "autocomplete": "email"},
    )
    password = PasswordField(
        "Contraseña",
        validators=[
            DataRequired(message="La contraseña es obligatoria."),
            Length(min=8, message="Mínimo 8 caracteres."),
        ],
        render_kw={"placeholder": "••••••••", "autocomplete": "new-password"},
    )
    confirm_password = PasswordField(
        "Confirmar contraseña",
        validators=[
            DataRequired(message="Confirmá la contraseña."),
            EqualTo("password", message="Las contraseñas no coinciden."),
        ],
        render_kw={"placeholder": "••••••••", "autocomplete": "new-password"},
    )

    def validate_username(self, field):
        if User.get_by_username(field.data):
            raise ValidationError("Ese nombre de usuario ya está en uso.")

    def validate_email(self, field):
        if User.get_by_email(field.data):
            raise ValidationError("Ese correo ya está registrado.")


class RegisterEmpresaForm(RegisterBaseForm):
    """Registro de cuenta EMPRESA (crea User + Company en la misma transacción)."""

    company_name = StringField(
        "Nombre de la empresa",
        validators=[
            DataRequired(message="El nombre de la empresa es obligatorio."),
            Length(min=2, max=120, message="Entre 2 y 120 caracteres."),
        ],
        render_kw={"placeholder": "Mi Empresa S.A.", "autocomplete": "organization"},
    )
    cuit = StringField(
        "CUIT",
        validators=[
            DataRequired(message="El CUIT es obligatorio."),
            Length(min=11, max=13, message="CUIT inválido (11 dígitos)."),
        ],
        render_kw={"placeholder": "20-12345678-9", "autocomplete": "off"},
    )
    description = StringField(
        "Descripción (opcional)",
        validators=[Length(max=500, message="Máximo 500 caracteres.")],
        render_kw={"placeholder": "Describí tu negocio...", "rows": 3},
    )
    submit = SubmitField("Crear mi empresa")

    def validate_cuit(self, field):
        from app.models.company import Company
        normalized = Company.normalize_cuit(field.data)
        if not Company.validate_cuit(normalized):
            raise ValidationError("CUIT inválido (verificá el dígito verificador).")
        # Chequear unicidad en BD
        existing = Company.query.filter_by(tax_id=normalized).first()
        if existing:
            raise ValidationError("Ese CUIT ya está registrado.")

    def validate_company_name(self, field):
        existing = Company.query.filter_by(name=field.data.strip()).first()
        if existing:
            raise ValidationError("Ese nombre de empresa ya está en uso.")


class RegisterClienteForm(RegisterBaseForm):
    """Registro de cuenta CLIENTE (solo User)."""

    submit = SubmitField("Crear mi cuenta")