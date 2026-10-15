"""
Tests para la integración de registro de empresa con asignación automática de vendedor MP.
"""

import pytest
import tempfile
import json
import os
from app.services.auth import register_user_with_company
from app.models.user import User, AccountType
from app.models.company import Company


class TestRegistroEmpresaConVendedorMP:
    """Tests de registro de empresa con asignación automática de vendedor de prueba."""

    def test_registro_empresa_asigna_vendedor_automaticamente(self, app, db):
        """Al registrar empresa en sandbox, se asigna vendedor de prueba automáticamente."""
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
        
        try:
            with app.app_context():
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
                app.config["MP_TEST_BUYER_EMAIL"] = "test_buyer@sandbox.com"
                app.config["MP_SANDBOX"] = True
                app.config["MP_FORCE_TEST_BUYER_EMAIL"] = True
                
                # Registrar empresa (esto llama a register_user_with_company internamente)
                user = register_user_with_company(
                    username="nueva_empresa",
                    email="nueva@test.com",
                    password="password123",
                    company_name="Nueva Empresa S.A.",
                    cuit="30999999995",  # CUIT válido
                    description="Empresa de prueba",
                )
                db.session.commit()
                
                # Verificar que la empresa tiene credenciales MP asignadas
                assert user.company is not None
                assert user.company.mp_seller_user_id == "3735930282"
                assert user.company.mp_access_token == "TEST_TOKEN_1"
                assert user.company.mp_public_key == "TEST_PUBLIC_1"
                assert user.company.mp_webhook_secret == "TEST_SECRET_1"
        finally:
            os.unlink(temp_path)

    def test_registro_empresa_sin_pool_disponible_no_rompe(self, app, db):
        """Si no hay pool de vendedores, el registro NO se rompe (warning y sigue)."""
        with app.app_context():
            app.config["MP_TEST_SELLERS_FILE"] = "/no/existe.json"
            app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
            app.config["MP_TEST_BUYER_EMAIL"] = "test_buyer@sandbox.com"
            app.config["MP_SANDBOX"] = True
            app.config["MP_FORCE_TEST_BUYER_EMAIL"] = True
            
            # Registrar empresa - no debe lanzar excepción
            user = register_user_with_company(
                username="empresa_sin_pool",
                email="sinpool@test.com",
                password="password123",
                company_name="Empresa Sin Pool S.A.",
                cuit="30888888888",
                description="Empresa sin pool",
            )
            db.session.commit()
            
            # Empresa creada pero SIN credenciales MP
            assert user.company is not None
            assert user.company.mp_seller_user_id is None
            assert user.company.mp_access_token is None
            assert user.company.mp_public_key is None

    def test_registro_empresa_en_produccion_no_asigna_vendedor(self, app, db):
        """En producción (MP_SANDBOX=False) no se asigna vendedor de prueba."""
        with app.app_context():
            app.config["MP_SANDBOX"] = False
            app.config["MP_ACCESS_TOKEN"] = "PROD_TOKEN"
            app.config["MP_PUBLIC_KEY"] = "PROD_PUBLIC"
            
            user = register_user_with_company(
                username="empresa_prod",
                email="prod@test.com",
                password="password123",
                company_name="Empresa Prod S.A.",
                cuit="30777777777",
                description="Empresa producción",
            )
            db.session.commit()
            
            # En producción no se asignan credenciales de prueba
            assert user.company is not None
            assert user.company.mp_seller_user_id is None
            assert user.company.mp_access_token is None
            assert user.company.mp_public_key is None

    def test_multiples_empresas_comparten_mismo_vendedor(self, app, db):
        """Múltiples empresas registradas comparten el mismo vendedor (pool de 1)."""
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
                app.config["MP_TEST_BUYER_EMAIL"] = "test_buyer@sandbox.com"
                app.config["MP_SANDBOX"] = True
                app.config["MP_FORCE_TEST_BUYER_EMAIL"] = True
                
                # Registrar 3 empresas
                empresas = []
                for i in range(3):
                    user = register_user_with_company(
                        username=f"empresa{i}",
                        email=f"empresa{i}@test.com",
                        password="password123",
                        company_name=f"Empresa {i} S.A.",
                        cuit=f"3099999999{i}",  # CUITs válidos distintos
                        description=f"Empresa {i}",
                    )
                    empresas.append(user.company)
                db.session.commit()
                
                # Todas deben tener el mismo vendedor asignado
                for company in empresas:
                    assert company.mp_seller_user_id == "3735930282"
                    assert company.mp_access_token == "TEST_TOKEN_1"
        finally:
            os.unlink(temp_path)