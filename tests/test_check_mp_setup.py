"""
Tests para el comando CLI check-mp-setup - B2B_B2C.
"""

import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner


class TestCheckMpSetup:
    """Tests para flask check-mp-setup."""

    def test_check_mp_setup_production_mode(self, app):
        """En producción (MP_SANDBOX=False) el comando avisa y sale."""
        runner = CliRunner()
        with app.app_context():
            app.config["MP_SANDBOX"] = False
            result = runner.invoke(app.cli.commands["check-mp-setup"], [])
            assert "MP_SANDBOX=False" in result.output
            assert result.exit_code == 0

    def test_check_mp_setup_missing_env_vars(self, app):
        """Reporta variables de entorno faltantes."""
        runner = CliRunner()
        with app.app_context():
            app.config["MP_SANDBOX"] = True
            app.config["MP_TEST_BUYER_EMAIL"] = ""
            app.config["MP_TEST_BUYER_USER_ID"] = ""
            app.config["MP_TEST_SELLERS_FILE"] = ""
            app.config["PUBLIC_BASE_URL"] = ""
            result = runner.invoke(app.cli.commands["check-mp-setup"], [])
            assert "NO CONFIGURADO" in result.output
            assert result.exit_code == 0

    def test_check_mp_setup_sellers_file_not_found(self, app):
        """Reporta si mp_test_sellers.json no existe."""
        runner = CliRunner()
        with app.app_context():
            app.config["MP_SANDBOX"] = True
            app.config["MP_TEST_BUYER_EMAIL"] = "test@test.com"
            app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
            app.config["MP_TEST_SELLERS_FILE"] = "/no/existe.json"
            app.config["PUBLIC_BASE_URL"] = "https://test.ngrok-free.app"
            result = runner.invoke(app.cli.commands["check-mp-setup"], [])
            assert "Error cargando vendedores" in result.output
            assert result.exit_code == 0

    def test_check_mp_setup_valid_config(self, app, db, monkeypatch):
        """Configuración válida: reporta OK."""
        runner = CliRunner()
        
        # Mock requests.get para /users/me
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": 3735930282}
        monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
        
        with app.app_context():
            app.config["MP_SANDBOX"] = True
            app.config["MP_TEST_BUYER_EMAIL"] = "test_buyer@sandbox.com"
            app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
            app.config["MP_TEST_SELLERS_FILE"] = "tests/fixtures/mp_test_sellers_valid.json"
            app.config["PUBLIC_BASE_URL"] = "https://test.ngrok-free.app"
            
            # Crear un archivo JSON válido temporal
            import json
            import tempfile
            import os
            
            sellers_data = [{
                "label": "Vendedor Test",
                "user_id": "3735930282",
                "access_token": "TEST_TOKEN_VALID",
                "public_key": "TEST_PUBLIC_VALID",
                "webhook_secret": "TEST_SECRET_VALID"
            }]
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(sellers_data, f)
                temp_path = f.name
            
            try:
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                result = runner.invoke(app.cli.commands["check-mp-setup"], [])
                assert "CONFIGURACIÓN OK" in result.output
                assert "token VÁLIDO, id coincide" in result.output
                assert result.exit_code == 0
            finally:
                os.unlink(temp_path)

    def test_check_mp_setup_token_valid_but_id_mismatch(self, app, db, monkeypatch):
        """Token válido pero user_id devuelto no coincide con JSON."""
        runner = CliRunner()
        
        # Mock requests.get para /users/me - devuelve ID diferente
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": 9999999999}  # ID diferente
        monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
        
        with app.app_context():
            app.config["MP_SANDBOX"] = True
            app.config["MP_TEST_BUYER_EMAIL"] = "test_buyer@sandbox.com"
            app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
            app.config["PUBLIC_BASE_URL"] = "https://test.ngrok-free.app"
            
            import json
            import tempfile
            import os
            
            sellers_data = [{
                "label": "Vendedor Test",
                "user_id": "3735930282",  # En JSON dice 3735930282
                "access_token": "TEST_TOKEN_VALID",
                "public_key": "TEST_PUBLIC_VALID",
                "webhook_secret": "TEST_SECRET_VALID"
            }]
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(sellers_data, f)
                temp_path = f.name
            
            try:
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                result = runner.invoke(app.cli.commands["check-mp-setup"], [])
                assert "NO COINCIDE" in result.output
                assert "9999999999" in result.output  # ID real devuelto
                assert result.exit_code == 0
            finally:
                os.unlink(temp_path)

    def test_check_mp_setup_network_error(self, app, db, monkeypatch):
        """Error de red al consultar /users/me: informa sin romper."""
        runner = CliRunner()
        
        # Mock requests.get para lanzar excepción de conexión
        import requests
        monkeypatch.setattr("requests.get", lambda *a, **kw: (_ for _ in ()).throw(requests.exceptions.ConnectionError("No hay red")))
        
        with app.app_context():
            app.config["MP_SANDBOX"] = True
            app.config["MP_TEST_BUYER_EMAIL"] = "test_buyer@sandbox.com"
            app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
            app.config["PUBLIC_BASE_URL"] = "https://test.ngrok-free.app"
            
            import json
            import tempfile
            import os
            
            sellers_data = [{
                "label": "Vendedor Test",
                "user_id": "3735930282",
                "access_token": "TEST_TOKEN_VALID",
                "public_key": "TEST_PUBLIC_VALID",
                "webhook_secret": "TEST_SECRET_VALID"
            }]
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(sellers_data, f)
                temp_path = f.name
            
            try:
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                result = runner.invoke(app.cli.commands["check-mp-setup"], [])
                assert "sin red" in result.output.lower() or "conexión" in result.output.lower()
                assert result.exit_code == 0
            finally:
                os.unlink(temp_path)

    def test_check_mp_setup_seller_same_as_buyer(self, app, db):
        """Detecta conflicto: vendedor tiene mismo user_id que comprador."""
        runner = CliRunner()
        
        with app.app_context():
            app.config["MP_SANDBOX"] = True
            app.config["MP_TEST_BUYER_EMAIL"] = "test_buyer@sandbox.com"
            app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
            app.config["PUBLIC_BASE_URL"] = "https://test.ngrok-free.app"
            
            import json
            import tempfile
            import os
            
            # Vendedor con MISMO user_id que comprador
            sellers_data = [{
                "label": "Vendedor Conflicto",
                "user_id": "3732708515",  # Igual que comprador
                "access_token": "TEST_TOKEN_VALID",
                "public_key": "TEST_PUBLIC_VALID",
                "webhook_secret": "TEST_SECRET_VALID"
            }]
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(sellers_data, f)
                temp_path = f.name
            
            try:
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                result = runner.invoke(app.cli.commands["check-mp-setup"], [])
                assert "CONFLICTO" in result.output
                assert "mismo user_id que el comprador" in result.output
                assert result.exit_code == 0
            finally:
                os.unlink(temp_path)

    def test_check_mp_setup_company_credentials_count(self, app, db):
        """Reporta cuántas empresas tienen y no tienen credenciales."""
        runner = CliRunner()
        
        with app.app_context():
            app.config["MP_SANDBOX"] = True
            app.config["MP_TEST_BUYER_EMAIL"] = "test_buyer@sandbox.com"
            app.config["MP_TEST_BUYER_USER_ID"] = "3732708515"
            app.config["PUBLIC_BASE_URL"] = "https://test.ngrok-free.app"
            
            import json
            import tempfile
            import os
            
            sellers_data = [{
                "label": "Vendedor Test",
                "user_id": "3735930282",
                "access_token": "TEST_TOKEN_VALID",
                "public_key": "TEST_PUBLIC_VALID",
                "webhook_secret": "TEST_SECRET_VALID"
            }]
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(sellers_data, f)
                temp_path = f.name
            
            try:
                app.config["MP_TEST_SELLERS_FILE"] = temp_path
                
                # Crear 2 empresas: 1 con credenciales, 1 sin
                from app.models.user import User, AccountType
                from app.models.company import Company
                
                user1 = User(username="test1", email="test1@test.com", 
                           password_hash="x", account_type=AccountType.EMPRESA)
                db.session.add(user1)
                db.session.flush()
                company1 = Company(owner_id=user1.id, name="Con Credenciales", 
                                  tax_id="30711111111",
                                  mp_seller_user_id="3735930282",
                                  mp_access_token="TOKEN",
                                  mp_public_key="PUBLIC")
                db.session.add(company1)
                
                user2 = User(username="test2", email="test2@test.com", 
                           password_hash="x", account_type=AccountType.EMPRESA)
                db.session.add(user2)
                db.session.flush()
                company2 = Company(owner_id=user2.id, name="Sin Credenciales", 
                                  tax_id="30722222222")
                db.session.add(company2)
                db.session.commit()
                
                result = runner.invoke(app.cli.commands["check-mp-setup"], [])
                assert "Total empresas: 2" in result.output
                assert "Con credenciales: 1" in result.output
                assert "Sin credenciales: 1" in result.output
                assert result.exit_code == 0
            finally:
                os.unlink(temp_path)