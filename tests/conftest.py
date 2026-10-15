"""
Configuración de pytest - B2B_B2C.

Fixtures compartidas: app, client, db, usuarios de prueba, etc.
"""

import pytest
import tempfile
import json
import os
from decimal import Decimal
from app import create_app
from app.extensions import db as _db
from app.models.user import User, AccountType
from app.models.company import Company
from app.models.product import Product
from app.models.order import Order, OrderItem, OrderStatus
from app.models.payment import Payment, PaymentStatus
from werkzeug.security import generate_password_hash
from app.services.mp_accounts import _reset_cache_for_testing


@pytest.fixture(autouse=True)
def reset_mp_accounts_cache():
    """Resetea el cache de mp_accounts antes de cada test."""
    _reset_cache_for_testing()
    yield
    _reset_cache_for_testing()


@pytest.fixture(scope="session")
def mp_test_sellers_file():
    """Crea un archivo temporal mp_test_sellers.json válido para tests."""
    sellers_data = [{
        "label": "Vendedor Test",
        "user_id": "3735930282",
        "access_token": "TEST_TOKEN_1",
        "public_key": "TEST_PUBLIC_1",
        "webhook_secret": "TEST_SECRET_1"
    }]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(sellers_data, f)
        temp_path = f.name
    yield temp_path
    # Cleanup
    try:
        os.unlink(temp_path)
    except OSError:
        pass


@pytest.fixture(scope="session")
def app(mp_test_sellers_file):
    """App Flask en modo testing con mp_accounts configurado."""
    _app = create_app("testing")
    # Configurar mp_accounts para tests
    _app.config["MP_TEST_SELLERS_FILE"] = mp_test_sellers_file
    _app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
    _app.config["MP_TEST_BUYER_EMAIL"] = "test_buyer@sandbox.com"
    _app.config["MP_SANDBOX"] = True
    _app.config["MP_FORCE_TEST_BUYER_EMAIL"] = True
    with _app.app_context():
        _db.create_all()
        yield _app
        _db.drop_all()


@pytest.fixture(scope="function")
def client(app):
    """Test client."""
    return app.test_client()


@pytest.fixture(scope="function")
def db(app):
    """DB session con rollback automático por test."""
    with app.app_context():
        # Limpiar todas las tablas antes de cada test
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()
        yield _db
        _db.session.rollback()


# --- Helpers para crear usuarios (no fixtures autocommit) ---

def _create_cliente_user(db):
    user = User(
        username="cliente_test",
        email="cliente@test.com",
        password_hash=generate_password_hash("cliente123"),
        account_type=AccountType.CLIENTE,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _create_empresa_vendedora_user(db):
    user = User(
        username="techstore",
        email="techstore@test.com",
        password_hash=generate_password_hash("techstore123"),
        account_type=AccountType.EMPRESA,
    )
    db.session.add(user)
    db.session.flush()

    company = Company(
        owner_id=user.id,
        name="TechStore Argentina",
        tax_id="30711111112",
        description="Equipamiento informático",
    )
    db.session.add(company)
    db.session.commit()
    return user


def _create_empresa_compradora_user(db):
    user = User(
        username="empresa_compradora",
        email="empresa_compradora@test.com",
        password_hash=generate_password_hash("empresa123"),
        account_type=AccountType.EMPRESA,
    )
    db.session.add(user)
    db.session.flush()

    company = Company(
        owner_id=user.id,
        name="Empresa Compradora S.A.",
        tax_id="30712345678",
        description="Empresa de prueba para compras B2B",
    )
    db.session.add(company)
    db.session.commit()
    return user


def _create_producto_techstore(db, empresa_user):
    company = empresa_user.company
    product = Product(
        company_id=company.id,
        name="Laptop Gaming X1",
        description="Procesador i9, 32GB RAM, RTX 4080.",
        price=Decimal("1200000.00"),
        stock=10,
        is_active=True,
    )
    db.session.add(product)
    db.session.commit()
    return product


def _create_producto_stock_1(db, empresa_user):
    company = empresa_user.company
    product = Product(
        company_id=company.id,
        name="Producto Único",
        description="Stock 1",
        price=Decimal("1000.00"),
        stock=1,
        is_active=True,
    )
    db.session.add(product)
    db.session.commit()
    return product


# --- Fixtures que usan los helpers ---

@pytest.fixture
def cliente_user(db):
    return _create_cliente_user(db)


@pytest.fixture
def empresa_vendedora_user(db):
    return _create_empresa_vendedora_user(db)


@pytest.fixture
def empresa_compradora_user(db):
    return _create_empresa_compradora_user(db)


@pytest.fixture
def producto_techstore(db, empresa_vendedora_user):
    return _create_producto_techstore(db, empresa_vendedora_user)


@pytest.fixture
def producto_stock_1(db, empresa_vendedora_user):
    return _create_producto_stock_1(db, empresa_vendedora_user)


# --- Helpers de autenticación ---

def _login_user(client, email, password):
    """Login helper que retorna response."""
    return client.post("/auth/login", data={
        "email": email,
        "password": password,
    }, follow_redirects=True)


@pytest.fixture
def logged_client(client, db, cliente_user):
    """Client logueado como cliente."""
    _login_user(client, "cliente@test.com", "cliente123")
    return client


@pytest.fixture
def logged_empresa_client(client, db, empresa_vendedora_user):
    """Client logueado como empresa vendedora."""
    _login_user(client, "techstore@test.com", "techstore123")
    return client


@pytest.fixture
def logged_comprador_client(client, db, empresa_compradora_user):
    """Client logueado como empresa compradora."""
    _login_user(client, "empresa_compradora@test.com", "empresa123")
    return client


# --- Mock Mercado Pago ---

@pytest.fixture
def mock_mp(monkeypatch):
    """Mock del SDK de Mercado Pago."""
    class MockPreference:
        def create(self, data):
            return {"status": 201, "response": {
                "id": "pref_test_123",
                "init_point": "https://sandbox.mercadopago.com/checkout/v1/redirect?pref_id=pref_test_123",
                "sandbox_init_point": "https://sandbox.mercadopago.com/checkout/v1/redirect?pref_id=pref_test_123",
            }}

    class MockPayment:
        def get(self, payment_id):
            if payment_id == "pay_approved":
                return {"status": 200, "response": {
                    "id": 123456789,
                    "status": "approved",
                    "status_detail": "accredited",
                    "transaction_amount": 1200000.00,
                    "currency_id": "ARS",
                    "payment_method_id": "visa",
                    "external_reference": "test-ref-123",
                }}
            elif payment_id == "pay_rejected":
                return {"status": 200, "response": {
                    "id": 123456790,
                    "status": "rejected",
                    "status_detail": "cc_rejected_insufficient_amount",
                    "transaction_amount": 1200000.00,
                    "currency_id": "ARS",
                    "payment_method_id": "visa",
                    "external_reference": "test-ref-123",
                }}
            elif payment_id == "pay_pending":
                return {"status": 200, "response": {
                    "id": 123456791,
                    "status": "pending",
                    "status_detail": "pending_waiting_payment",
                    "transaction_amount": 1200000.00,
                    "currency_id": "ARS",
                    "payment_method_id": "ticket",
                    "external_reference": "test-ref-123",
                }}
            return {"status": 404, "response": {"message": "Not found"}}

        def search(self, filters):
            return {"status": 200, "response": {"results": []}}

    class MockSDK:
        def preference(self):
            return MockPreference()
        def payment(self):
            return MockPayment()

    import mercadopago
    monkeypatch.setattr(mercadopago, "SDK", lambda token: MockSDK())
    return MockSDK()