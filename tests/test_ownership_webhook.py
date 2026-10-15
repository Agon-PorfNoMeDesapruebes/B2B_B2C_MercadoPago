"""
Tests de autorización (ownership), webhook y MP - B2B_B2C.
"""

import pytest
import json
from decimal import Decimal
from app.models.order import Order, OrderStatus, OrderItem
from app.models.payment import Payment, PaymentStatus
from app.models.product import Product
from app.models.webhook_event import WebhookEvent
from app.models.user import User, AccountType
from app.models.company import Company
from app.services.payments import process_mp_payment


class TestOwnership:
    """Usuarios solo ven sus propios pedidos/productos."""

    def test_cliente_no_ve_pedidos_ajenos(self, logged_client, cliente_user, db, empresa_vendedora_user):
        """Cliente no puede ver detalle de pedido de otro comprador."""
        # Crear pedido de otro usuario
        other = User(username="otro", email="otro@test.com", password_hash="x", account_type=AccountType.CLIENTE)
        db.session.add(other)
        db.session.flush()

        company = empresa_vendedora_user.company
        product = Product(company_id=company.id, name="P", price=Decimal("100"), stock=10, is_active=True)
        db.session.add(product)
        db.session.flush()

        order = Order(
            buyer_id=other.id,
            company_id=company.id,
            status=OrderStatus.PENDIENTE,
            total=Decimal("100"),
            buyer_type_snapshot=AccountType.CLIENTE,
            external_reference="ref-other",
        )
        db.session.add(order)
        db.session.flush()

        item = OrderItem(order_id=order.id, product_id=product.id, product_name_snapshot="P",
                         unit_price_snapshot=Decimal("100"), quantity=1, subtotal=Decimal("100"))
        db.session.add(item)
        db.session.commit()

        # Intentar acceder
        response = logged_client.get(f"/pedidos/{order.id}")
        assert response.status_code == 404

    def test_empresa_no_ve_pedidos_ajenos(self, logged_empresa_client, empresa_vendedora_user, db, cliente_user):
        """Empresa vendedora no ve pedidos de otras empresas."""
        # Crear otra empresa
        user2 = User(username="emp2", email="emp2@test.com", password_hash="x", account_type=AccountType.EMPRESA)
        db.session.add(user2)
        db.session.flush()
        company2 = Company(owner_id=user2.id, name="Emp2", tax_id="30788888888")
        db.session.add(company2)
        db.session.flush()

        product = Product(company_id=company2.id, name="P2", price=Decimal("100"), stock=10, is_active=True)
        db.session.add(product)
        db.session.flush()

        order = Order(
            buyer_id=cliente_user.id,
            company_id=company2.id,
            status=OrderStatus.PENDIENTE,
            total=Decimal("100"),
            buyer_type_snapshot=AccountType.CLIENTE,
            external_reference="ref-emp2",
        )
        db.session.add(order)
        db.session.commit()

        # TechStore (empresa_vendedora) intenta ver pedido de Emp2
        response = logged_empresa_client.get(f"/pedidos/{order.id}")
        assert response.status_code == 404

    def test_forjar_request_editar_producto_ajeno_403(self, logged_empresa_client, db, empresa_vendedora_user):
        """Forjar POST a editar producto de otra empresa -> 403."""
        # Crear otra empresa con producto
        user2 = User(username="emp2", email="emp2@test.com", password_hash="x", account_type=AccountType.EMPRESA)
        db.session.add(user2)
        db.session.flush()
        company2 = Company(owner_id=user2.id, name="Emp2", tax_id="30788888888")
        db.session.add(company2)
        db.session.flush()

        product = Product(company_id=company2.id, name="P2", price=Decimal("100"), stock=10, is_active=True)
        db.session.add(product)
        db.session.commit()

        # TechStore intenta editar producto de Emp2
        response = logged_empresa_client.post(f"/empresas/mi-empresa/productos/{product.id}/editar", data={
            "name": "Hackeado",
            "price": "1",
            "stock": "1",
        })
        assert response.status_code in (403, 404)

    def test_forzar_eliminar_producto_con_ventas_no_borra_fisico(self, logged_empresa_client, db, empresa_vendedora_user, cliente_user):
        """Producto con ventas -> borrado lógico, no físico."""
        company = empresa_vendedora_user.company
        product = Product(company_id=company.id, name="Con Ventas", price=Decimal("100"), stock=5, is_active=True)
        db.session.add(product)
        db.session.flush()

        # Crear pedido con este producto
        order = Order(
            buyer_id=cliente_user.id,
            company_id=company.id,
            status=OrderStatus.PAGADO,
            total=Decimal("100"),
            buyer_type_snapshot=AccountType.CLIENTE,
            external_reference="ref-sales",
        )
        db.session.add(order)
        db.session.flush()

        item = OrderItem(order_id=order.id, product_id=product.id, product_name_snapshot="Con Ventas",
                         unit_price_snapshot=Decimal("100"), quantity=1, subtotal=Decimal("100"))
        db.session.add(item)
        db.session.commit()

        product_id = product.id
        # Desactivar (borrado lógico)
        response = logged_empresa_client.post(f"/empresas/mi-empresa/productos/{product_id}/toggle")
        assert response.status_code == 302

        db.session.refresh(product)
        assert product.is_active is False
        # Pero sigue existiendo en BD
        assert Product.query.get(product_id) is not None


class TestWebhook:
    """Webhook de Mercado Pago."""

    def test_webhook_firma_invalida_rechazado(self, client, app):
        """Webhook con firma inválida -> 400."""
        with app.app_context():
            app.config["MP_WEBHOOK_SECRET"] = "test_secret"

        payload = {"data": {"id": "pay_123"}, "type": "payment"}
        response = client.post("/webhooks/mercadopago",
                               data=json.dumps(payload),
                               content_type="application/json",
                               headers={"x-signature": "ts=123,v1=invalid"})
        assert response.status_code == 400

    def test_webhook_idempotencia_mismo_pago(self, client, app, db, cliente_user, producto_techstore, mock_mp):
        """Reenviar mismo webhook no duplica pago ni descuenta stock."""
        with app.app_context():
            app.config["MP_WEBHOOK_SECRET"] = ""

        # Crear pedido pendiente
        from app.services.orders import create_orders_from_cart
        cart = {str(producto_techstore.id): 2}
        orders = create_orders_from_cart(cliente_user.id, cart)
        order = orders[0]
        db.session.commit()

        initial_stock = producto_techstore.stock

        # Webhook payload simulado
        payload = {
            "data": {"id": "pay_webhook_1"},
            "type": "payment",
        }

        # Mock the get_payment in both mercadopago and webhooks modules
        import app.services.mercadopago as mp_module
        import app.blueprints.webhooks as webhooks_module
        original_get_payment = mp_module.get_payment
        
        def mock_get_payment(payment_id, access_token=None):
            if payment_id == "pay_webhook_1":
                return {
                    "id": 123456789,
                    "status": "approved",
                    "status_detail": "accredited",
                    "transaction_amount": float(order.total),
                    "currency_id": "ARS",
                    "payment_method_id": "visa",
                    "external_reference": order.external_reference,
                }
            raise RuntimeError("Not found")
        
        mp_module.get_payment = mock_get_payment
        webhooks_module.get_payment = mock_get_payment

        try:
            # Primera vez
            response1 = client.post("/webhooks/mercadopago",
                                    data=json.dumps(payload),
                                    content_type="application/json")
            assert response1.status_code == 200

            # Segunda vez (duplicado)
            response2 = client.post("/webhooks/mercadopago",
                                    data=json.dumps(payload),
                                    content_type="application/json")
            assert response2.status_code == 200

            # Verificar: 1 evento procesado (el segundo es idempotente y se ignora), 1 solo pago, stock descontado 1 vez
            db.session.refresh(order)
            db.session.refresh(producto_techstore)
            assert order.status == OrderStatus.PAGADO
            # initial_stock is 8 (after order creation), stock remains 8 after webhook (already reserved)
            assert producto_techstore.stock == initial_stock
            assert Payment.query.filter_by(order_id=order.id, status=PaymentStatus.APPROVED).count() == 1
            # Idempotency: solo 1 evento procesado (el segundo es ignorado por idempotencia)
            assert WebhookEvent.query.filter_by(mp_payment_id="pay_webhook_1", processed=True).count() == 1
        finally:
            mp_module.get_payment = original_get_payment

    def test_webhook_monto_distinto_rechazado(self, client, app, db, cliente_user, producto_techstore):
        """Webhook con monto que no coincide -> no cambia estado."""
        with app.app_context():
            app.config["MP_WEBHOOK_SECRET"] = ""

        from app.services.orders import create_orders_from_cart
        cart = {str(producto_techstore.id): 1}
        orders = create_orders_from_cart(cliente_user.id, cart)
        order = orders[0]
        db.session.commit()

        # Webhook con monto diferente
        payload = {
            "data": {"id": "pay_wrong_amount"},
            "type": "payment",
        }
        # El service get_payment mockeado devuelve monto correcto,
        # pero si forzamos monto distinto en process_mp_payment falla
        from app.services.payments import process_mp_payment
        mp_data = {
            "id": "pay_wrong_amount",
            "status": "approved",
            "status_detail": "accredited",
            "transaction_amount": 999999.99,  # Distinto al pedido
            "currency_id": "ARS",
            "payment_method_id": "visa",
            "external_reference": order.external_reference,
        }
        with pytest.raises(ValueError, match="Monto no coincide"):
            process_mp_payment(mp_data)

        db.session.refresh(order)
        assert order.status == OrderStatus.PENDIENTE  # Sin cambios


class TestEstadosMP:
    """Mapeo de estados de Mercado Pago."""

    def test_approved_marca_pagado(self, db, cliente_user, producto_techstore):
        from app.services.orders import create_orders_from_cart
        cart = {str(producto_techstore.id): 1}
        orders = create_orders_from_cart(cliente_user.id, cart)
        order = orders[0]
        db.session.commit()

        mp_data = {
            "id": "pay_approved_1",
            "status": "approved",
            "status_detail": "accredited",
            "transaction_amount": float(order.total),
            "currency_id": "ARS",
            "payment_method_id": "visa",
            "external_reference": order.external_reference,
        }
        process_mp_payment(mp_data)
        db.session.commit()

        db.session.refresh(order)
        assert order.status == OrderStatus.PAGADO

    def test_rejected_mantiene_pendiente_y_stock_reservado(self, db, cliente_user, producto_techstore):
        from app.services.orders import create_orders_from_cart
        cart = {str(producto_techstore.id): 3}
        orders = create_orders_from_cart(cliente_user.id, cart)
        order = orders[0]
        # initial_stock es el stock ANTES de reservar (10)
        initial_stock = producto_techstore.stock
        db.session.commit()

        # Verificar que el stock se reservó (10 - 3 = 7)
        db.session.refresh(producto_techstore)
        assert producto_techstore.stock == initial_stock - 3

        mp_data = {
            "id": "pay_rejected_1",
            "status": "rejected",
            "status_detail": "cc_rejected_insufficient_amount",
            "transaction_amount": float(order.total),
            "currency_id": "ARS",
            "payment_method_id": "visa",
            "external_reference": order.external_reference,
        }
        process_mp_payment(mp_data)
        db.session.commit()

        db.session.refresh(order)
        db.session.refresh(producto_techstore)
        # Rejected NO cambia el estado a RECHAZADO, se queda PENDIENTE
        # (permite reintentar, stock sigue reservado)
        assert order.status == OrderStatus.PENDIENTE
        # Stock sigue reservado (no se devuelve)
        assert producto_techstore.stock == initial_stock - 3

    def test_pending_marca_pendiente(self, db, cliente_user, producto_techstore):
        from app.services.orders import create_orders_from_cart
        cart = {str(producto_techstore.id): 1}
        orders = create_orders_from_cart(cliente_user.id, cart)
        order = orders[0]
        db.session.commit()

        mp_data = {
            "id": "pay_pending_1",
            "status": "pending",
            "status_detail": "pending_waiting_payment",
            "transaction_amount": float(order.total),
            "currency_id": "ARS",
            "payment_method_id": "ticket",
            "external_reference": order.external_reference,
        }
        process_mp_payment(mp_data)
        db.session.commit()

        db.session.refresh(order)
        assert order.status == OrderStatus.PENDIENTE

    def test_cancelled_expired_marca_cancelado_expirado(self, db, cliente_user, producto_techstore):
        from app.services.orders import create_orders_from_cart
        cart = {str(producto_techstore.id): 1}
        orders = create_orders_from_cart(cliente_user.id, cart)
        order = orders[0]
        db.session.commit()

        for status, expected in [("cancelled", OrderStatus.CANCELADO), ("expired", OrderStatus.EXPIRADO)]:
            order.status = OrderStatus.PENDIENTE  # Reset
            db.session.commit()

            mp_data = {
                "id": f"pay_{status}_1",
                "status": status,
                "status_detail": status,
                "transaction_amount": float(order.total),
                "currency_id": "ARS",
                "payment_method_id": "visa",
                "external_reference": order.external_reference,
            }
            process_mp_payment(mp_data)
            db.session.commit()

            db.session.refresh(order)
            assert order.status == expected

    def test_refunded_charged_back_marca_reembolsado_devuelve_stock(self, db, cliente_user, producto_techstore):
        from app.services.orders import create_orders_from_cart
        cart = {str(producto_techstore.id): 2}
        orders = create_orders_from_cart(cliente_user.id, cart)
        order = orders[0]
        db.session.commit()

        for status in ["refunded", "charged_back"]:
            # Set stock to post-payment state (8) before each refund test
            producto_techstore.stock = 8
            db.session.commit()

            order.status = OrderStatus.PAGADO
            db.session.commit()

            mp_data = {
                "id": f"pay_{status}_1",
                "status": status,
                "status_detail": status,
                "transaction_amount": float(order.total),
                "currency_id": "ARS",
                "payment_method_id": "visa",
                "external_reference": order.external_reference,
            }
            process_mp_payment(mp_data)
            db.session.commit()

            db.session.refresh(order)
            db.session.refresh(producto_techstore)
            # refunded/charged_back en PAGADO -> REEMBOLSADO (stock devuelto)
            assert order.status == OrderStatus.REEMBOLSADO
            assert producto_techstore.stock == 10