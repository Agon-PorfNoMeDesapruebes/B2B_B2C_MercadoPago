"""
Tests para mp_accounts - B2B_B2C.
"""

import pytest
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.services.mp_accounts import (
    load_test_sellers,
    get_test_buyer_user_id,
    validate_sellers_vs_buyer,
    assign_test_seller,
    get_mp_credentials,
    get_payer_email,
    get_webhook_secret_for_seller,
    find_company_by_seller_user_id,
    _reset_cache_for_testing,
)
from app.models.company import Company
from app.models.order import Order


@pytest.fixture(autouse=True)
def reset_mp_accounts_cache():
    """Resetea el cache de mp_accounts antes de cada test."""
    _reset_cache_for_testing()
    yield
    _reset_cache_for_testing()


class TestLoadTestSellers:
    """Tests para load_test_sellers()."""

    def test_load_valid_sellers(self, app):
        """Carga vendedores válidos desde archivo JSON."""
        sellers_data = [
            {
                "label": "Vendedor 1",
                "user_id": "3735930282",
                "access_token": "TEST_TOKEN_1",
                "public_key": "TEST_PUBLIC_1",
                "webhook_secret": "TEST_SECRET_1"
            },
            {
                "label": "Vendedor 2",
                "user_id": "3760597960",
                "access_token": "TEST_TOKEN_2",
                "public_key": "TEST_PUBLIC_2",
                "webhook_secret": "TEST_SECRET_2"
            }
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                sellers = load_test_sellers()
                assert len(sellers) == 2
                assert sellers[0].label == "Vendedor 1"
                assert sellers[0].user_id == "3735930282"
                assert sellers[1].label == "Vendedor 2"
        finally:
            os.unlink(temp_path)

    def test_load_missing_file_raises(self, app):
        """Archivo inexistente lanza RuntimeError."""
        with app.app_context():
            app.config["MP_TEST_SELLERS_FILE"] = "/no/existe.json"
            with pytest.raises(RuntimeError, match="no encontrado"):
                load_test_sellers()

    def test_load_invalid_json_raises(self, app):
        """JSON inválido lanza RuntimeError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{ invalid json }")
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                with pytest.raises(RuntimeError, match="JSON inv"):
                    load_test_sellers()
        finally:
            os.unlink(temp_path)

    def test_load_empty_list_raises(self, app):
        """Lista vacía lanza RuntimeError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([], f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                with pytest.raises(RuntimeError, match="lista no vacía"):
                    load_test_sellers()
        finally:
            os.unlink(temp_path)

    def test_load_missing_fields_raises(self, app):
        """Campos faltantes lanza RuntimeError."""
        sellers_data = [{"label": "Vendedor 1"}]  # Faltan campos
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                with pytest.raises(RuntimeError, match="faltan campos"):
                    load_test_sellers()
        finally:
            os.unlink(temp_path)

    def test_load_empty_field_raises(self, app):
        """Campo vacío lanza RuntimeError."""
        sellers_data = [{
            "label": "Vendedor 1",
            "user_id": "",
            "access_token": "TOKEN",
            "public_key": "PUBLIC",
            "webhook_secret": "SECRET"
        }]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                with pytest.raises(RuntimeError, match="vacío"):
                    load_test_sellers()
        finally:
            os.unlink(temp_path)

    def test_cache_works(self, app):
        """Segunda llamada usa cache."""
        sellers_data = [{
            "label": "Vendedor 1",
            "user_id": "3735930282",
            "access_token": "TEST_TOKEN_1",
            "public_key": "TEST_PUBLIC_1",
            "webhook_secret": "TEST_SECRET_1"
        }]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                sellers1 = load_test_sellers()
                sellers2 = load_test_sellers()
                assert sellers1 is sellers2  # Mismo objeto (cache)
        finally:
            os.unlink(temp_path)


class TestGetTestBuyerUserId:
    """Tests para get_test_buyer_user_id()."""

    def test_get_buyer_user_id(self, app):
        """Obtiene el user_id del comprador de .env."""
        with app.app_context():
            app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
            buyer_id = get_test_buyer_user_id()
            assert buyer_id == "3732708515"

    def test_missing_buyer_user_id_raises(self, app):
        """Sin config lanza RuntimeError."""
        with app.app_context():
            app.config["MP_TEST_BUYER_USER_ID"] = ""
            with pytest.raises(RuntimeError, match="MP_TEST_BUYER_USER_ID no configurado"):
                get_test_buyer_user_id()


class TestValidateSellersVsBuyer:
    """Tests para validate_sellers_vs_buyer()."""

    def test_valid_sellers_different_from_buyer(self, app):
        """Vendedores distintos al comprador: OK."""
        sellers_data = [{
            "label": "Vendedor 1",
            "user_id": "3735930282",  # Distinto al buyer
            "access_token": "TEST_TOKEN_1",
            "public_key": "TEST_PUBLIC_1",
            "webhook_secret": "TEST_SECRET_1"
        }]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
                app.config["MP_SANDBOX"] = True
                # No debe lanzar excepción
                validate_sellers_vs_buyer()
        finally:
            os.unlink(temp_path)

    def test_seller_same_as_buyer_raises(self, app):
        """Vendedor igual al comprador lanza RuntimeError."""
        sellers_data = [{
            "label": "Vendedor 1",
            "user_id": "3732708515",  # Igual al buyer
            "access_token": "TEST_TOKEN_1",
            "public_key": "TEST_PUBLIC_1",
            "webhook_secret": "TEST_SECRET_1"
        }]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
                app.config["MP_SANDBOX"] = True
                with pytest.raises(RuntimeError, match="misma cuenta que el comprador"):
                    validate_sellers_vs_buyer()
        finally:
            os.unlink(temp_path)

    def test_production_mode_skips_validation(self, app):
        """En producción (MP_SANDBOX=False) saltea validación."""
        sellers_data = [{
            "label": "Vendedor 1",
            "user_id": "3732708515",  # Igual al buyer
            "access_token": "TEST_TOKEN_1",
            "public_key": "TEST_PUBLIC_1",
            "webhook_secret": "TEST_SECRET_1"
        }]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
                app.config["MP_SANDBOX"] = False
                # No debe lanzar excepción en producción
                validate_sellers_vs_buyer()
        finally:
            os.unlink(temp_path)


class TestAssignTestSeller:
    """Tests para assign_test_seller()."""

    def test_assign_seller_to_company(self, app, db):
        """Asigna vendedor a empresa sin credenciales."""
        sellers_data = [{
            "label": "Vendedor 1",
            "user_id": "3735930282",
            "access_token": "TEST_TOKEN_1",
            "public_key": "TEST_PUBLIC_1",
            "webhook_secret": "TEST_SECRET_1"
        }, {
            "label": "Vendedor 2",
            "user_id": "3760597960",
            "access_token": "TEST_TOKEN_2",
            "public_key": "TEST_PUBLIC_2",
            "webhook_secret": "TEST_SECRET_2"
        }]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
                app.config["MP_SANDBOX"] = True
                
                # Crear empresa sin credenciales
                from app.models.user import User, AccountType
                user = User(username="test_seller", email="test_seller@test.com", 
                           password_hash="x", account_type=AccountType.EMPRESA)
                db.session.add(user)
                db.session.flush()
                
                company = Company(owner_id=user.id, name="Test Company", 
                                 tax_id="30712345678")
                db.session.add(company)
                db.session.commit()
                
                # Asignar vendedor
                seller = assign_test_seller(company)
                
                assert seller is not None
                assert company.mp_seller_user_id == "3735930282"  # Primer vendedor (menos usado)
                assert company.mp_access_token == "TEST_TOKEN_1"
                assert company.mp_public_key == "TEST_PUBLIC_1"
                assert company.mp_webhook_secret == "TEST_SECRET_1"
        finally:
            os.unlink(temp_path)

    def test_round_robin_assignment(self, app, db):
        """Round-robin: siguiente empresa obtiene siguiente vendedor."""
        sellers_data = [{
            "label": "Vendedor 1",
            "user_id": "3735930282",
            "access_token": "TEST_TOKEN_1",
            "public_key": "TEST_PUBLIC_1",
            "webhook_secret": "TEST_SECRET_1"
        }, {
            "label": "Vendedor 2",
            "user_id": "3760597960",
            "access_token": "TEST_TOKEN_2",
            "public_key": "TEST_PUBLIC_2",
            "webhook_secret": "TEST_SECRET_2"
        }]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
                app.config["MP_SANDBOX"] = True
                
                from app.models.user import User, AccountType
                
                # Primera empresa -> Vendedor 1
                user1 = User(username="test1", email="test1@test.com", 
                           password_hash="x", account_type=AccountType.EMPRESA)
                db.session.add(user1)
                db.session.flush()
                company1 = Company(owner_id=user1.id, name="Test Company 1", 
                                  tax_id="30711111111")
                db.session.add(company1)
                db.session.commit()
                assign_test_seller(company1)
                
                # Segunda empresa -> Vendedor 2
                user2 = User(username="test2", email="test2@test.com", 
                           password_hash="x", account_type=AccountType.EMPRESA)
                db.session.add(user2)
                db.session.flush()
                company2 = Company(owner_id=user2.id, name="Test Company 2", 
                                  tax_id="30722222222")
                db.session.add(company2)
                db.session.commit()
                assign_test_seller(company2)
                
                assert company1.mp_seller_user_id == "3735930282"
                assert company2.mp_seller_user_id == "3760597960"
        finally:
            os.unlink(temp_path)

    def test_pool_of_one_seller_shared_by_multiple_companies(self, app, db):
        """Pool de 1 vendedor: todas las empresas comparten el mismo vendedor."""
        sellers_data = [{
            "label": "Vendedor Compartido",
            "user_id": "3735930282",
            "access_token": "TEST_TOKEN_1",
            "public_key": "TEST_PUBLIC_1",
            "webhook_secret": "TEST_SECRET_1"
        }]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
                app.config["MP_SANDBOX"] = True
                
                from app.models.user import User, AccountType
                
                # Crear 5 empresas
                companies = []
                for i in range(5):
                    user = User(username=f"test{i}", email=f"test{i}@test.com", 
                               password_hash="x", account_type=AccountType.EMPRESA)
                    db.session.add(user)
                    db.session.flush()
                    company = Company(owner_id=user.id, name=f"Test Company {i}", 
                                     tax_id=f"3071111111{i}")
                    db.session.add(company)
                    companies.append(company)
                db.session.commit()
                
                # Asignar vendedor a todas
                for company in companies:
                    assign_test_seller(company)
                
                # Todas deben tener el mismo vendedor
                for company in companies:
                    assert company.mp_seller_user_id == "3735930282"
                    assert company.mp_access_token == "TEST_TOKEN_1"
                    assert company.mp_public_key == "TEST_PUBLIC_1"
                    assert company.mp_webhook_secret == "TEST_SECRET_1"
        finally:
            os.unlink(temp_path)

    def test_company_already_has_credentials_returns_existing(self, app, db):
        """Empresa con credenciales existentes retorna el mismo vendedor."""
        sellers_data = [{
            "label": "Vendedor 1",
            "user_id": "3735930282",
            "access_token": "TEST_TOKEN_1",
            "public_key": "TEST_PUBLIC_1",
            "webhook_secret": "TEST_SECRET_1"
        }]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
                app.config["MP_SANDBOX"] = True
                
                from app.models.user import User, AccountType
                user = User(username="test_seller", email="test_seller@test.com", 
                           password_hash="x", account_type=AccountType.EMPRESA)
                db.session.add(user)
                db.session.flush()
                
                company = Company(owner_id=user.id, name="Test Company", 
                                 tax_id="30712345678",
                                 mp_seller_user_id="3735930282",
                                 mp_access_token="TEST_TOKEN_1",
                                 mp_public_key="TEST_PUBLIC_1",
                                 mp_webhook_secret="TEST_SECRET_1")
                db.session.add(company)
                db.session.commit()
                
                seller = assign_test_seller(company)
                
                assert seller.user_id == "3735930282"
        finally:
            os.unlink(temp_path)

    def test_no_sellers_available_raises(self, app, db):
        """Sin vendedores disponibles lanza RuntimeError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([], f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
                app.config["MP_SANDBOX"] = True
                
                from app.models.user import User, AccountType
                user = User(username="test", email="test@test.com", 
                           password_hash="x", account_type=AccountType.EMPRESA)
                db.session.add(user)
                db.session.flush()
                company = Company(owner_id=user.id, name="Test", tax_id="30712345678")
                db.session.add(company)
                db.session.commit()
                
                with pytest.raises(RuntimeError, match="lista no vac"):
                    assign_test_seller(company)
        finally:
            os.unlink(temp_path)


class TestGetMpCredentials:
    """Tests para get_mp_credentials()."""

    def test_sandbox_returns_company_credentials(self, app, db):
        """En sandbox devuelve credenciales de la empresa del pedido."""
        sellers_data = [{
            "label": "Vendedor 1",
            "user_id": "3735930282",
            "access_token": "TEST_TOKEN_1",
            "public_key": "TEST_PUBLIC_1",
            "webhook_secret": "TEST_SECRET_1"
        }]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
                app.config["MP_SANDBOX"] = True
                app.config["MP_ACCESS_TOKEN"] = "GLOBAL_TOKEN"
                app.config["MP_PUBLIC_KEY"] = "GLOBAL_PUBLIC"
                
                from app.models.user import User, AccountType
                from app.models.order import Order, OrderStatus
                from datetime import datetime, timezone
                
                user = User(username="test", email="test@test.com", 
                           password_hash="x", account_type=AccountType.EMPRESA)
                db.session.add(user)
                db.session.flush()
                
                company = Company(owner_id=user.id, name="Test Company", 
                                 tax_id="30712345678",
                                 mp_seller_user_id="3735930282",
                                 mp_access_token="TEST_TOKEN_1",
                                 mp_public_key="TEST_PUBLIC_1",
                                 mp_webhook_secret="TEST_SECRET_1")
                db.session.add(company)
                db.session.flush()
                
                order = Order(
                    buyer_id=user.id,
                    company_id=company.id,
                    status=OrderStatus.PENDIENTE,
                    total=1000,
                    buyer_type_snapshot=AccountType.EMPRESA,
                    external_reference="test-ref-123",
                    created_at=datetime.now(timezone.utc),
                )
                db.session.add(order)
                db.session.commit()
                
                access_token, public_key = get_mp_credentials(order)
                
                assert access_token == "TEST_TOKEN_1"
                assert public_key == "TEST_PUBLIC_1"
        finally:
            os.unlink(temp_path)

    def test_production_returns_global_credentials(self, app, db):
        """En producción devuelve credenciales globales."""
        with app.app_context():
            app.config["MP_SANDBOX"] = False
            app.config["MP_ACCESS_TOKEN"] = "GLOBAL_TOKEN"
            app.config["MP_PUBLIC_KEY"] = "GLOBAL_PUBLIC"
            
            from app.models.user import User, AccountType
            from app.models.order import Order, OrderStatus
            from datetime import datetime, timezone
            
            user = User(username="test", email="test@test.com", 
                       password_hash="x", account_type=AccountType.EMPRESA)
            db.session.add(user)
            db.session.flush()
            
            company = Company(owner_id=user.id, name="Test Company", 
                             tax_id="30712345678")
            db.session.add(company)
            db.session.flush()
            
            order = Order(
                buyer_id=user.id,
                company_id=company.id,
                status=OrderStatus.PENDIENTE,
                total=1000,
                buyer_type_snapshot=AccountType.EMPRESA,
                external_reference="test-ref-123",
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(order)
            db.session.commit()
            
            access_token, public_key = get_mp_credentials(order)
            
            assert access_token == "GLOBAL_TOKEN"
            assert public_key == "GLOBAL_PUBLIC"

    def test_sandbox_lazy_assignment_works(self, app, db):
        """En sandbox, empresa sin credenciales las obtiene por lazy assignment."""
        sellers_data = [{
            "label": "Vendedor 1",
            "user_id": "3735930282",
            "access_token": "TEST_TOKEN_1",
            "public_key": "TEST_PUBLIC_1",
            "webhook_secret": "TEST_SECRET_1"
        }]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
                app.config["MP_SANDBOX"] = True
                
                from app.models.user import User, AccountType
                from app.models.order import Order, OrderStatus
                from datetime import datetime, timezone
                
                user = User(username="test", email="test@test.com", 
                           password_hash="x", account_type=AccountType.EMPRESA)
                db.session.add(user)
                db.session.flush()
                
                # Empresa SIN credenciales MP
                company = Company(owner_id=user.id, name="Test Company", 
                                 tax_id="30712345678")
                db.session.add(company)
                db.session.flush()
                
                order = Order(
                    buyer_id=user.id,
                    company_id=company.id,
                    status=OrderStatus.PENDIENTE,
                    total=1000,
                    buyer_type_snapshot=AccountType.EMPRESA,
                    external_reference="test-ref-123",
                    created_at=datetime.now(timezone.utc),
                )
                db.session.add(order)
                db.session.commit()
                
                # Lazy assignment: debe asignar credenciales automáticamente
                access_token, public_key = get_mp_credentials(order)
                
                assert access_token == "TEST_TOKEN_1"
                assert public_key == "TEST_PUBLIC_1"
                
                # Verificar que la empresa ahora tiene las credenciales persistidas
                db.session.refresh(company)
                assert company.mp_seller_user_id == "3735930282"
                assert company.mp_access_token == "TEST_TOKEN_1"
                assert company.mp_public_key == "TEST_PUBLIC_1"
        finally:
            os.unlink(temp_path)

    def test_sandbox_lazy_assignment_fails_without_pool(self, app, db):
        """En sandbox sin pool de vendedores, lazy assignment falla con error claro."""
        with app.app_context():
            app.config["MP_TEST_SELLERS_FILE"] = "/no/existe.json"
            app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
            app.config["MP_SANDBOX"] = True
            
            from app.models.user import User, AccountType
            from app.models.order import Order, OrderStatus
            from datetime import datetime, timezone
            
            user = User(username="test", email="test@test.com", 
                       password_hash="x", account_type=AccountType.EMPRESA)
            db.session.add(user)
            db.session.flush()
            
            company = Company(owner_id=user.id, name="Test Company", 
                             tax_id="30712345678")
            db.session.add(company)
            db.session.flush()
            
            order = Order(
                buyer_id=user.id,
                company_id=company.id,
                status=OrderStatus.PENDIENTE,
                total=1000,
                buyer_type_snapshot=AccountType.EMPRESA,
                external_reference="test-ref-123",
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(order)
            db.session.commit()
            
            with pytest.raises(RuntimeError, match="no se pudieron asignar"):
                get_mp_credentials(order)


class TestGetPayerEmail:
    """Tests para get_payer_email()."""

    def test_sandbox_returns_test_buyer_email(self, app, db):
        """En sandbox devuelve SIEMPRE el email del comprador de prueba."""
        with app.app_context():
            app.config["MP_SANDBOX"] = True
            app.config["MP_TEST_BUYER_EMAIL"] = "test_buyer@sandbox.com"
            
            from app.models.user import User, AccountType
            from app.models.order import Order, OrderStatus
            from datetime import datetime, timezone
            
            user = User(username="test", email="test@test.com", 
                       password_hash="x", account_type=AccountType.EMPRESA)
            db.session.add(user)
            db.session.flush()
            
            company = Company(owner_id=user.id, name="Test Company", 
                             tax_id="30712345678")
            db.session.add(company)
            db.session.flush()
            
            order = Order(
                buyer_id=user.id,
                company_id=company.id,
                status=OrderStatus.PENDIENTE,
                total=1000,
                buyer_type_snapshot=AccountType.EMPRESA,
                external_reference="test-ref-123",
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(order)
            db.session.commit()
            
            # Email del formulario (debería ignorarse en sandbox)
            form_email = "usuario@real.com"
            email = get_payer_email(order, form_email)
            
            assert email == "test_buyer@sandbox.com"

    def test_production_returns_form_email(self, app, db):
        """En producción devuelve el email del formulario."""
        with app.app_context():
            app.config["MP_SANDBOX"] = False
            
            from app.models.user import User, AccountType
            from app.models.order import Order, OrderStatus
            from datetime import datetime, timezone
            
            user = User(username="test", email="test@test.com", 
                       password_hash="x", account_type=AccountType.EMPRESA)
            db.session.add(user)
            db.session.flush()
            
            company = Company(owner_id=user.id, name="Test Company", 
                             tax_id="30712345678")
            db.session.add(company)
            db.session.flush()
            
            order = Order(
                buyer_id=user.id,
                company_id=company.id,
                status=OrderStatus.PENDIENTE,
                total=1000,
                buyer_type_snapshot=AccountType.EMPRESA,
                external_reference="test-ref-123",
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(order)
            db.session.commit()
            
            form_email = "usuario@real.com"
            email = get_payer_email(order, form_email)
            
            assert email == "usuario@real.com"

    def test_sandbox_missing_test_buyer_email_raises(self, app, db):
        """En sandbox sin MP_TEST_BUYER_EMAIL lanza RuntimeError."""
        with app.app_context():
            app.config["MP_SANDBOX"] = True
            app.config["MP_TEST_BUYER_EMAIL"] = ""
            
            from app.models.user import User, AccountType
            from app.models.order import Order, OrderStatus
            from datetime import datetime, timezone
            
            user = User(username="test", email="test@test.com", 
                       password_hash="x", account_type=AccountType.EMPRESA)
            db.session.add(user)
            db.session.flush()
            
            company = Company(owner_id=user.id, name="Test Company", 
                             tax_id="30712345678")
            db.session.add(company)
            db.session.flush()
            
            order = Order(
                buyer_id=user.id,
                company_id=company.id,
                status=OrderStatus.PENDIENTE,
                total=1000,
                buyer_type_snapshot=AccountType.EMPRESA,
                external_reference="test-ref-123",
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(order)
            db.session.commit()
            
            with pytest.raises(RuntimeError, match="MP_TEST_BUYER_EMAIL no configurado"):
                get_payer_email(order, "test@test.com")

    def test_sandbox_force_test_buyer_email_true(self, app, db):
        """Con MP_FORCE_TEST_BUYER_EMAIL=True (default), usa email de prueba."""
        with app.app_context():
            app.config["MP_SANDBOX"] = True
            app.config["MP_TEST_BUYER_EMAIL"] = "test_buyer@sandbox.com"
            app.config["MP_FORCE_TEST_BUYER_EMAIL"] = True
            
            from app.models.user import User, AccountType
            from app.models.order import Order, OrderStatus
            from datetime import datetime, timezone
            
            user = User(username="test", email="test@test.com", 
                       password_hash="x", account_type=AccountType.EMPRESA)
            db.session.add(user)
            db.session.flush()
            
            company = Company(owner_id=user.id, name="Test Company", 
                             tax_id="30712345678")
            db.session.add(company)
            db.session.flush()
            
            order = Order(
                buyer_id=user.id,
                company_id=company.id,
                status=OrderStatus.PENDIENTE,
                total=1000,
                buyer_type_snapshot=AccountType.EMPRESA,
                external_reference="test-ref-123",
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(order)
            db.session.commit()
            
            form_email = "usuario@real.com"
            email = get_payer_email(order, form_email)
            
            assert email == "test_buyer@sandbox.com"

    def test_sandbox_force_test_buyer_email_false(self, app, db):
        """Con MP_FORCE_TEST_BUYER_EMAIL=False, usa email del formulario."""
        with app.app_context():
            app.config["MP_SANDBOX"] = True
            app.config["MP_TEST_BUYER_EMAIL"] = "test_buyer@sandbox.com"
            app.config["MP_FORCE_TEST_BUYER_EMAIL"] = False
            
            from app.models.user import User, AccountType
            from app.models.order import Order, OrderStatus
            from datetime import datetime, timezone
            
            user = User(username="test", email="test@test.com", 
                       password_hash="x", account_type=AccountType.EMPRESA)
            db.session.add(user)
            db.session.flush()
            
            company = Company(owner_id=user.id, name="Test Company", 
                             tax_id="30712345678")
            db.session.add(company)
            db.session.flush()
            
            order = Order(
                buyer_id=user.id,
                company_id=company.id,
                status=OrderStatus.PENDIENTE,
                total=1000,
                buyer_type_snapshot=AccountType.EMPRESA,
                external_reference="test-ref-123",
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(order)
            db.session.commit()
            
            form_email = "usuario@real.com"
            email = get_payer_email(order, form_email)
            
            assert email == "usuario@real.com"

    def test_sandbox_force_test_buyer_email_false_missing_form_email(self, app, db):
        """Con MP_FORCE_TEST_BUYER_EMAIL=False y sin email en formulario, devuelve string vacío."""
        with app.app_context():
            app.config["MP_SANDBOX"] = True
            app.config["MP_TEST_BUYER_EMAIL"] = "test_buyer@sandbox.com"
            app.config["MP_FORCE_TEST_BUYER_EMAIL"] = False
            
            from app.models.user import User, AccountType
            from app.models.order import Order, OrderStatus
            from datetime import datetime, timezone
            
            user = User(username="test", email="test@test.com", 
                       password_hash="x", account_type=AccountType.EMPRESA)
            db.session.add(user)
            db.session.flush()
            
            company = Company(owner_id=user.id, name="Test Company", 
                             tax_id="30712345678")
            db.session.add(company)
            db.session.flush()
            
            order = Order(
                buyer_id=user.id,
                company_id=company.id,
                status=OrderStatus.PENDIENTE,
                total=1000,
                buyer_type_snapshot=AccountType.EMPRESA,
                external_reference="test-ref-123",
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(order)
            db.session.commit()
            
            form_email = ""
            email = get_payer_email(order, form_email)
            
            assert email == ""


class TestWebhookHelpers:
    """Tests para helpers de webhook."""

    def test_get_webhook_secret_for_seller(self, app):
        """Obtiene webhook_secret del vendedor por user_id."""
        sellers_data = [{
            "label": "Vendedor 1",
            "user_id": "3735930282",
            "access_token": "TEST_TOKEN_1",
            "public_key": "TEST_PUBLIC_1",
            "webhook_secret": "TEST_SECRET_1"
        }, {
            "label": "Vendedor 2",
            "user_id": "3760597960",
            "access_token": "TEST_TOKEN_2",
            "public_key": "TEST_PUBLIC_2",
            "webhook_secret": "TEST_SECRET_2"
        }]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sellers_data, f)
            temp_path = f.name
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
                app.config["MP_SANDBOX"] = True
                
                secret = get_webhook_secret_for_seller("3735930282")
                assert secret == "TEST_SECRET_1"
                
                secret = get_webhook_secret_for_seller("3760597960")
                assert secret == "TEST_SECRET_2"
                
                # Vendedor inexistente
                secret = get_webhook_secret_for_seller("9999999999")
                assert secret is None
        finally:
            os.unlink(temp_path)

    def test_find_company_by_seller_user_id(self, app, db):
        """Busca Company por mp_seller_user_id."""
        with app.app_context():
            from app.models.user import User, AccountType
            
            user = User(username="test", email="test@test.com", 
                       password_hash="x", account_type=AccountType.EMPRESA)
            db.session.add(user)
            db.session.flush()
            
            company = Company(owner_id=user.id, name="Test Company", 
                             tax_id="30712345678",
                             mp_seller_user_id="3735930282")
            db.session.add(company)
            db.session.commit()
            
            found = find_company_by_seller_user_id("3735930282")
            assert found is not None
            assert found.id == company.id
            
            # No encontrado
            found = find_company_by_seller_user_id("9999999999")
            assert found is None