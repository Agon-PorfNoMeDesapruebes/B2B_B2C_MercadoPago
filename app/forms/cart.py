"""
Formularios de carrito y confirmación de pedido - B2B_B2C.
"""

from flask_wtf import FlaskForm
from wtforms import HiddenField, IntegerField, SubmitField, BooleanField
from wtforms.validators import DataRequired, NumberRange, Optional, ValidationError


class CartUpdateForm(FlaskForm):
    """Actualizar cantidad de una línea del carrito."""

    product_id = HiddenField(validators=[DataRequired()])
    quantity = IntegerField(
        "Cantidad",
        validators=[DataRequired(), NumberRange(min=1, message="Mínimo 1 unidad.")],
        render_kw={"min": "1", "class": "cart-quantity-input"},
    )
    submit = SubmitField("Actualizar")


class CartConfirmForm(FlaskForm):
    """Confirmar pedido - valida mínimos por línea según tipo de cuenta."""

    # Los items vienen en la sesión; este form solo lleva CSRF + confirmación
    confirm = BooleanField(
        "Confirmo que los datos son correctos y quiero proceder al pago",
        validators=[DataRequired(message="Debés confirmar para continuar.")],
    )
    submit = SubmitField("Confirmar y pagar")

    def __init__(self, *args, cart_items=None, buyer_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cart_items = cart_items or []
        self.buyer_type = buyer_type  # 'empresa' o 'cliente'
        self.min_qty = 50 if buyer_type == 'empresa' else 1

    def validate_confirm(self, field):
        if not field.data:
            raise ValidationError("Debés confirmar para continuar.")
        # Validar mínimos por línea
        for item in self.cart_items:
            if item['quantity'] < self.min_qty:
                raise ValidationError(
                    f"El producto '{item['product'].name}' requiere mínimo "
                    f"{self.min_qty} unidades (sos cuenta {self.buyer_type})."
                )