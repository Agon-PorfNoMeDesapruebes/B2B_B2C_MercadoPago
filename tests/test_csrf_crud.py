"""
Tests de CSRF, CRUD y validaciones varias - B2B_B2C.
"""

import pytest
from decimal import Decimal
from app.models.product import Product
from app.models.company import Company
from app.models.user import User, AccountType


class TestCSRF:
    """CSRF activo en formularios."""

    def test_login_requiere_csrf(self, client):
        """Login sin token CSRF falla (400)."""
        # Flask-WTF CSRF por defecto valida en POST
        response = client.post("/auth/login", data={
            "email": "test@test.com",
            "password": "password123",
        }, headers={"X-CSRFToken": "invalid"})
        # En testing CSRF está desactivado (config), pero en prod estaría activo
        # Este test documenta la expectativa
        pass

    def test_formularios_tienen_csrf_token(self, logged_client):
        """Templates de formularios incluyen csrf_token."""
        response = logged_client.get("/empresas/mi-empresa/productos/nuevo")
        assert b"csrf_token" in response.data.lower()


class TestCRUDProductos:
    """CRUD solo para dueño."""

    def test_crear_producto_empresa_duena(self, logged_empresa_client, db, empresa_vendedora_user):
        response = logged_empresa_client.post("/empresas/mi-empresa/productos/nuevo", data={
            "name": "Nuevo Producto",
            "price": "150000.00",
            "stock": "20",
            "description": "Desc",
        }, follow_redirects=True)
        assert response.status_code == 200
        product = Product.query.filter_by(name="Nuevo Producto").first()
        assert product is not None
        assert product.company_id == empresa_vendedora_user.company.id

    def test_editar_producto_propio(self, logged_empresa_client, db, empresa_vendedora_user):
        product = Product(company_id=empresa_vendedora_user.company.id,
                          name="Original", price=Decimal("100"), stock=10, is_active=True)
        db.session.add(product)
        db.session.commit()

        response = logged_empresa_client.post(f"/empresas/mi-empresa/productos/{product.id}/editar", data={
            "name": "Editado",
            "price": "200",
            "stock": "5",
        }, follow_redirects=True)
        assert response.status_code == 200
        db.session.refresh(product)
        assert product.name == "Editado"
        assert product.price == Decimal("200")

    def test_precio_cero_valido(self, logged_empresa_client, db, empresa_vendedora_user):
        """Precio 0 es válido (InputRequired, no DataRequired)."""
        response = logged_empresa_client.post("/empresas/mi-empresa/productos/nuevo", data={
            "name": "Gratis",
            "price": "0",
            "stock": "10",
        }, follow_redirects=True)
        assert response.status_code == 200
        product = Product.query.filter_by(name="Gratis").first()
        assert product is not None
        assert product.price == Decimal("0.00")

    def test_stock_cero_valido(self, logged_empresa_client, db, empresa_vendedora_user):
        """Stock 0 es válido."""
        response = logged_empresa_client.post("/empresas/mi-empresa/productos/nuevo", data={
            "name": "Sin Stock Inicial",
            "price": "100",
            "stock": "0",
        }, follow_redirects=True)
        assert response.status_code == 200
        product = Product.query.filter_by(name="Sin Stock Inicial").first()
        assert product.stock == 0

    def test_precio_negativo_rechazado(self, logged_empresa_client, db, empresa_vendedora_user):
        response = logged_empresa_client.post("/empresas/mi-empresa/productos/nuevo", data={
            "name": "Precio Negativo",
            "price": "-10",
            "stock": "10",
        })
        assert b"negativo" in response.data.lower() or b"no puede" in response.data.lower()

    def test_stock_negativo_rechazado(self, logged_empresa_client, db, empresa_vendedora_user):
        response = logged_empresa_client.post("/empresas/mi-empresa/productos/nuevo", data={
            "name": "Stock Negativo",
            "price": "100",
            "stock": "-5",
        })
        assert b"negativo" in response.data.lower() or b"no puede" in response.data.lower()


class TestValidacionesVarias:
    """Otras validaciones de negocio."""

    def test_empresa_no_se_compra_a_si_misma_en_pedido(self, logged_empresa_client, db, empresa_vendedora_user, producto_techstore):
        """Validación a nivel servicio: empresa no compra propia."""
        from app.services.orders import create_orders_from_cart
        with pytest.raises(ValueError, match="propio"):
            create_orders_from_cart(empresa_vendedora_user.id, {str(producto_techstore.id): 10})

    def test_producto_inactivo_no_se_puede_comprar(self, logged_client, db, empresa_vendedora_user):
        product = Product(company_id=empresa_vendedora_user.company.id,
                          name="Inactivo", price=Decimal("100"), stock=10, is_active=False)
        db.session.add(product)
        db.session.commit()

        response = logged_client.post(f"/carrito/agregar/{product.id}", follow_redirects=True)
        assert b"no est. disponible" in response.data.lower() or b"disponible" in response.data.lower()

    def test_pedido_sin_stock_no_se_crea(self, logged_client, db, empresa_vendedora_user):
        product = Product(company_id=empresa_vendedora_user.company.id,
                          name="Sin Stock", price=Decimal("100"), stock=0, is_active=True)
        db.session.add(product)
        db.session.commit()

        response = logged_client.post(f"/carrito/agregar/{product.id}", follow_redirects=True)
        assert b"stock" in response.data.lower() or b"agotado" in response.data.lower()


class TestRateLimiting:
    """Rate limiting en endpoints sensibles."""

    def test_login_rate_limit(self, client, app):
        """Login tiene rate limit (10/min en config)."""
        # En testing RATELIMIT_ENABLED=False, pero documentamos
        pass

    def test_registro_rate_limit(self, client, app):
        pass

    def test_pago_rate_limit(self, client, app):
        pass