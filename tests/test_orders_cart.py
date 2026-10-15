"""
Tests de carrito, pedidos y reglas de negocio - B2B_B2C.
"""

import pytest
from decimal import Decimal
from app.models.order import Order, OrderStatus, OrderItem
from app.models.product import Product
from app.models.payment import Payment, PaymentStatus
from app.models.user import User, AccountType
from app.models.company import Company
from app.services.orders import create_orders_from_cart, cancel_order, expire_pending_orders, reserve_stock_for_items


class TestCarrito:
    """Carrito en sesión."""

    def test_agregar_producto_cliente(self, logged_client, producto_techstore):
        response = logged_client.post(f"/carrito/agregar/{producto_techstore.id}", follow_redirects=True)
        assert response.status_code == 200
        with logged_client.session_transaction() as sess:
            assert str(producto_techstore.id) in sess.get("cart", {})

    def test_agregar_producto_empresa_compradora(self, logged_comprador_client, producto_techstore):
        response = logged_comprador_client.post(f"/carrito/agregar/{producto_techstore.id}", follow_redirects=True)
        assert response.status_code == 200

    def test_no_agregar_producto_propio(self, logged_empresa_client, producto_techstore):
        """Empresa no puede agregar su propio producto."""
        response = logged_empresa_client.post(f"/carrito/agregar/{producto_techstore.id}", follow_redirects=True)
        assert b"no pod" in response.data.lower() or b"propio" in response.data.lower()
        with logged_empresa_client.session_transaction() as sess:
            assert str(producto_techstore.id) not in sess.get("cart", {})

    def test_actualizar_cantidad_carrito(self, logged_client, producto_techstore):
        logged_client.post(f"/carrito/agregar/{producto_techstore.id}")
        response = logged_client.post("/carrito/actualizar", data={
            "product_id": producto_techstore.id,
            "quantity": 3,
        }, follow_redirects=True)
        assert response.status_code == 200
        with logged_client.session_transaction() as sess:
            assert sess["cart"][str(producto_techstore.id)] == 3

    def test_quitar_producto_carrito(self, logged_client, producto_techstore):
        logged_client.post(f"/carrito/agregar/{producto_techstore.id}")
        response = logged_client.post(f"/carrito/quitar/{producto_techstore.id}", follow_redirects=True)
        assert response.status_code == 200
        with logged_client.session_transaction() as sess:
            assert str(producto_techstore.id) not in sess.get("cart", {})


class TestMinimosPorLinea:
    """Mínimo 50 u. para empresas, 1 u. para clientes."""

    def test_cliente_puede_comprar_1_unidad(self, logged_client, producto_techstore, db, cliente_user):
        logged_client.post(f"/carrito/agregar/{producto_techstore.id}")
        from app.services.orders import create_orders_from_cart
        with logged_client.session_transaction() as sess:
            cart = sess["cart"]
        orders = create_orders_from_cart(cliente_user.id, cart)
        assert len(orders) == 1
        assert orders[0].items[0].quantity == 1
        # Mejor testear el servicio directamente

    def test_empresa_requiere_minimo_50(self, logged_comprador_client, producto_techstore, db, empresa_compradora_user):
        """Empresa compradora necesita mínimo 50 por línea."""
        # Llenar carrito con 10 unidades
        with logged_comprador_client.session_transaction() as sess:
            sess["cart"] = {str(producto_techstore.id): 10}

        from app.services.orders import create_orders_from_cart
        with pytest.raises(ValueError, match="m.nimo 50"):
            create_orders_from_cart(empresa_compradora_user.id, {str(producto_techstore.id): 10})

    def test_empresa_puede_comprar_50_o_mas(self, db, empresa_compradora_user, producto_techstore):
        """Empresa compradora puede comprar 50+ unidades."""
        from app.services.orders import create_orders_from_cart
        # Aumentar stock para el test
        producto_techstore.stock = 100
        db.session.commit()

        orders = create_orders_from_cart(empresa_compradora_user.id, {str(producto_techstore.id): 50})
        assert len(orders) == 1
        assert orders[0].items[0].quantity == 50


class TestStockAtomico:
    """Reserva de stock atómica (UPDATE condicional)."""

    def test_reserva_stock_exitosa(self, db, producto_techstore):
        ok = reserve_stock_for_items([{"product_id": producto_techstore.id, "quantity": 3}])
        assert ok is True
        db.session.refresh(producto_techstore)
        assert producto_techstore.stock == 7  # 10 - 3

    def test_reserva_stock_insuficiente_falla(self, db, producto_techstore):
        ok = reserve_stock_for_items([{"product_id": producto_techstore.id, "quantity": 20}])
        assert ok is False
        db.session.refresh(producto_techstore)
        assert producto_techstore.stock == 10  # Sin cambios

    def test_concurrencia_dos_compradores_stock_1(self, db, producto_stock_1, cliente_user):
        """Dos compradores intentan comprar el último item; solo uno lo logra."""
        from app.services.orders import create_orders_from_cart

        # Cliente 1 compra 1
        orders1 = create_orders_from_cart(cliente_user.id, {str(producto_stock_1.id): 1})
        assert len(orders1) == 1

        # Crear segundo cliente
        cliente2 = User(username="cliente2", email="cliente2@test.com", password_hash="x", account_type=AccountType.CLIENTE)
        db.session.add(cliente2)
        db.session.commit()

        # Cliente 2 intenta comprar 1 (stock ya 0)
        with pytest.raises(ValueError, match="Stock insuficiente"):
            create_orders_from_cart(cliente2.id, {str(producto_stock_1.id): 1})

        db.session.refresh(producto_stock_1)
        assert producto_stock_1.stock == 0


class TestCreacionPedidos:
    """Creación de pedidos desde carrito."""

    def test_un_pedido_por_empresa_vendedora(self, db, cliente_user, empresa_vendedora_user):
        """Carrito con productos de 1 empresa -> 1 pedido."""
        # Crear 2 productos de la misma empresa
        company = empresa_vendedora_user.company
        p1 = Product(company_id=company.id, name="Prod 1", price=Decimal("100"), stock=100, is_active=True)
        p2 = Product(company_id=company.id, name="Prod 2", price=Decimal("200"), stock=100, is_active=True)
        db.session.add_all([p1, p2])
        db.session.commit()

        cart = {str(p1.id): 2, str(p2.id): 1}
        orders = create_orders_from_cart(cliente_user.id, cart)
        assert len(orders) == 1
        assert orders[0].company_id == company.id
        assert len(orders[0].items) == 2

    def test_dos_pedidos_si_dos_empresas(self, db, cliente_user, empresa_vendedora_user):
        """Carrito con productos de 2 empresas -> 2 pedidos."""
        # Segunda empresa
        user2 = User(username="empresa2", email="emp2@test.com", password_hash="x", account_type=AccountType.EMPRESA)
        db.session.add(user2)
        db.session.flush()
        company2 = Company(owner_id=user2.id, name="Empresa 2", tax_id="30799999999")
        db.session.add(company2)
        db.session.flush()

        p1 = Product(company_id=empresa_vendedora_user.company.id, name="P1", price=Decimal("100"), stock=100, is_active=True)
        p2 = Product(company_id=company2.id, name="P2", price=Decimal("200"), stock=100, is_active=True)
        db.session.add_all([p1, p2])
        db.session.commit()

        cart = {str(p1.id): 1, str(p2.id): 1}
        orders = create_orders_from_cart(cliente_user.id, cart)
        assert len(orders) == 2
        company_ids = {o.company_id for o in orders}
        assert company_ids == {empresa_vendedora_user.company.id, company2.id}

    def test_pedido_duplicado_pendiente_se_reutiliza(self, db, cliente_user, producto_techstore):
        """Si ya existe pedido pendiente idéntico, se reutiliza."""
        cart = {str(producto_techstore.id): 3}
        orders1 = create_orders_from_cart(cliente_user.id, cart)
        orders2 = create_orders_from_cart(cliente_user.id, cart)
        assert orders1[0].id == orders2[0].id  # Mismo objeto


class TestCancelacionYExpiracion:
    """Cancelación y expiración devuelven stock."""

    def test_cancelar_pedido_devuelve_stock(self, db, cliente_user, producto_techstore):
        from app.services.orders import create_orders_from_cart, cancel_order

        cart = {str(producto_techstore.id): 5}
        orders = create_orders_from_cart(cliente_user.id, cart)
        order = orders[0]
        db.session.refresh(producto_techstore)
        assert producto_techstore.stock == 5  # 10 - 5

        cancel_order(order)
        db.session.commit()
        db.session.refresh(producto_techstore)
        assert producto_techstore.stock == 10  # Devuelto

    def test_expirar_pedidos_devuelve_stock(self, db, cliente_user, producto_techstore):
        from app.services.orders import create_orders_from_cart, expire_pending_orders
        from datetime import datetime, timedelta, timezone

        cart = {str(producto_techstore.id): 3}
        orders = create_orders_from_cart(cliente_user.id, cart)
        order = orders[0]
        # Forzar expiración
        order.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.session.commit()

        count = expire_pending_orders()
        assert count == 1
        db.session.refresh(producto_techstore)
        assert producto_techstore.stock == 10  # Devuelto


class TestNoDoblePago:
    """Un pedido no se paga dos veces."""

    def test_pago_aprobado_bloquea_segundo_pago(self, db, cliente_user, producto_techstore):
        from app.services.orders import create_orders_from_cart
        from app.services.payments import process_mp_payment

        cart = {str(producto_techstore.id): 2}
        orders = create_orders_from_cart(cliente_user.id, cart)
        order = orders[0]

        # Simular pago aprobado
        mp_data = {
            "id": "pay_test_1",
            "status": "approved",
            "status_detail": "accredited",
            "transaction_amount": float(order.total),
            "currency_id": "ARS",
            "payment_method_id": "visa",
            "external_reference": order.external_reference,
        }
        process_mp_payment(mp_data)
        db.session.commit()

        # Verificar que está pagado
        db.session.refresh(order)
        assert order.status == OrderStatus.PAGADO

        # Intentar pagar de nuevo -> no debe crear otro pago aprobado
        # Con la nueva máquina de estados, PAGADO solo puede ir a REEMBOLSADO
        mp_data2 = mp_data.copy()
        mp_data2["id"] = "pay_test_2"
        # El segundo intento de aprobar el mismo pedido debería fallar silenciosamente o ser ignorado
        # El estado machine no permite PAGADO -> PAGADO
        try:
            process_mp_payment(mp_data2)
            db.session.commit()
        except ValueError:
            # Se espera que falle la transición inválida
            pass
        db.session.commit()

        # Solo 1 pago aprobado (el segundo intento no crea otro pago aprobado)
        approved = Payment.query.filter_by(order_id=order.id, status=PaymentStatus.APPROVED).count()
        assert approved == 1
        
        # El pedido sigue en PAGADO
        db.session.refresh(order)
        assert order.status == OrderStatus.PAGADO