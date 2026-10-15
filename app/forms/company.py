"""
Formularios de empresa y productos - B2B_B2C.
"""

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DecimalField, IntegerField, SubmitField, FileField, HiddenField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError, InputRequired, URL
from decimal import Decimal
from app.models.company import Company


class CompanyForm(FlaskForm):
    """Formulario para crear empresa (usado en registro, pero también editable)."""

    name = StringField(
        "Nombre de la empresa",
        validators=[DataRequired(), Length(min=2, max=120)],
        render_kw={"placeholder": "Mi Empresa S.A."},
    )
    tax_id = StringField(
        "CUIT",
        validators=[DataRequired(), Length(min=11, max=13)],
        render_kw={"placeholder": "20-12345678-9"},
    )
    description = TextAreaField(
        "Descripción",
        validators=[Optional(), Length(max=1000)],
        render_kw={"placeholder": "Contá qué vende tu empresa...", "rows": 4},
    )
    logo_url = StringField(
        "URL del logo (opcional)",
        validators=[Optional(), Length(max=500), URL(message="Debe ser una URL válida (http/https).", require_tld=False)],
        render_kw={"placeholder": "https://ejemplo.com/logo.png"},
    )
    submit = SubmitField("Guardar empresa")

    def __init__(self, *args, current_company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_company = current_company

    def validate_name(self, field):
        existing = Company.query.filter_by(name=field.data.strip()).first()
        if existing and existing != self.current_company:
            raise ValidationError("Ese nombre ya está en uso.")

    def validate_tax_id(self, field):
        normalized = Company.normalize_cuit(field.data)
        if not Company.validate_cuit(normalized):
            raise ValidationError("CUIT inválido.")
        existing = Company.query.filter_by(tax_id=normalized).first()
        if existing and existing != self.current_company:
            raise ValidationError("Ese CUIT ya está registrado.")


class CompanyEditForm(CompanyForm):
    """Edición de empresa (mismos campos, validación excluyendo la actual)."""
    pass


class ProductForm(FlaskForm):
    """CRUD de productos - Solo dueño de la empresa."""

    name = StringField(
        "Nombre del producto",
        validators=[DataRequired(message="El nombre es obligatorio."), Length(min=2, max=150)],
        render_kw={"placeholder": "Ej: Laptop Gaming X1"},
    )
    description = TextAreaField(
        "Descripción",
        validators=[Optional(), Length(max=2000)],
        render_kw={"placeholder": "Detalles, especificaciones...", "rows": 4},
    )
    price = DecimalField(
        "Precio (ARS)",
        validators=[
            InputRequired(message="El precio es obligatorio."),
            NumberRange(min=0, message="El precio no puede ser negativo."),
        ],
        places=2,
        render_kw={"placeholder": "120000.00", "step": "0.01", "min": "0"},
    )
    stock = IntegerField(
        "Stock",
        validators=[
            InputRequired(message="El stock es obligatorio."),
            NumberRange(min=0, message="El stock no puede ser negativo."),
        ],
        render_kw={"placeholder": "10", "min": "0"},
    )
    expected_stock = HiddenField()  # Stock esperado (para actualización atómica)
    image_url = StringField(
        "URL de imagen (opcional)",
        validators=[Optional(), Length(max=500), URL(message="Debe ser una URL válida (http/https).", require_tld=False)],
        render_kw={"placeholder": "https://ejemplo.com/foto.jpg"},
    )
    is_active = HiddenField(default="1")  # Borrado lógico via checkbox en template
    submit = SubmitField("Guardar producto")

    def validate_price(self, field):
        # Rechazar NaN / Inf
        if field.data is not None:
            try:
                val = Decimal(str(field.data))
                if val.is_nan() or val.is_infinite():
                    raise ValidationError("Precio inválido.")
            except Exception:
                raise ValidationError("Precio inválido.")