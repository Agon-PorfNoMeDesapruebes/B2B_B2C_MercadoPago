"""
Tests de autenticación y registro - B2B_B2C.
"""

import pytest
from app.models.user import User, AccountType
from app.models.company import Company


class TestRegistroCliente:
    """Registro de cuenta CLIENTE."""

    def test_registro_cliente_exitoso(self, client):
        response = client.post("/auth/registrar/cliente", data={
            "username": "nuevocliente",
            "email": "nuevo@test.com",
            "password": "password123",
            "confirm_password": "password123",
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b"Cuenta creada" in response.data or b"Bienvenido" in response.data

        user = User.get_by_email("nuevo@test.com")
        assert user is not None
        assert user.account_type == AccountType.CLIENTE
        assert user.check_password("password123")

    def test_registro_cliente_email_duplicado(self, client, cliente_user):
        response = client.post("/auth/registrar/cliente", data={
            "username": "otro",
            "email": "cliente@test.com",  # Ya existe
            "password": "password123",
            "confirm_password": "password123",
        })
        assert b"ya est" in response.data.lower()  # "ya está registrado"

    def test_registro_cliente_username_duplicado(self, client, cliente_user):
        response = client.post("/auth/registrar/cliente", data={
            "username": "cliente_test",  # Ya existe
            "email": "otro@test.com",
            "password": "password123",
            "confirm_password": "password123",
        })
        assert b"ya est" in response.data.lower()

    def test_registro_cliente_password_corto(self, client):
        response = client.post("/auth/registrar/cliente", data={
            "username": "user1",
            "email": "user1@test.com",
            "password": "123",  # Muy corto
            "confirm_password": "123",
        })
        assert b"m.nimo 8" in response.data.lower() or b"8 caracter" in response.data.lower()

    def test_registro_cliente_passwords_no_coinciden(self, client):
        response = client.post("/auth/registrar/cliente", data={
            "username": "user2",
            "email": "user2@test.com",
            "password": "password123",
            "confirm_password": "otra123",
        })
        assert b"no coinciden" in response.data.lower()


class TestRegistroEmpresa:
    """Registro de cuenta EMPRESA (User + Company)."""

    def test_registro_empresa_exitoso(self, client):
        response = client.post("/auth/registrar/empresa", data={
            "username": "miempresa",
            "email": "miempresa@test.com",
            "password": "password123",
            "confirm_password": "password123",
            "company_name": "Mi Empresa S.A.",
            "cuit": "30999999995",  # CUIT válido (base 3099999999 + DV=5)
            "description": "Vendo cosas",
        }, follow_redirects=True)
        assert response.status_code == 200

        user = User.get_by_email("miempresa@test.com")
        assert user is not None
        assert user.account_type == AccountType.EMPRESA
        assert user.company is not None
        assert user.company.name == "Mi Empresa S.A."
        assert user.company.tax_id == "30999999995"

    def test_registro_empresa_cuit_invalido(self, client):
        response = client.post("/auth/registrar/empresa", data={
            "username": "empresa1",
            "email": "emp1@test.com",
            "password": "password123",
            "confirm_password": "password123",
            "company_name": "Empresa 1",
            "cuit": "12345",  # Inválido
        })
        assert b"cuit inv" in response.data.lower() or b"inv.lido" in response.data.lower()

    def test_registro_empresa_cuit_duplicado(self, client, empresa_vendedora_user):
        response = client.post("/auth/registrar/empresa", data={
            "username": "empresa2",
            "email": "emp2@test.com",
            "password": "password123",
            "confirm_password": "password123",
            "company_name": "Empresa 2",
            "cuit": "30711111113",  # Ya usado por techstore
        })
        assert b"cuit" in response.data.lower() and (b"ya" in response.data.lower() or b"registrad" in response.data.lower())


class TestLogin:
    """Inicio de sesión."""

    def test_login_cliente_exitoso(self, client, cliente_user):
        response = client.post("/auth/login", data={
            "email": "cliente@test.com",
            "password": "cliente123",
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b"Hola" in response.data or b"Panel" in response.data

    def test_login_empresa_exitoso(self, client, empresa_vendedora_user):
        response = client.post("/auth/login", data={
            "email": "techstore@test.com",
            "password": "techstore123",
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_login_credenciales_invalidas(self, client, cliente_user):
        response = client.post("/auth/login", data={
            "email": "cliente@test.com",
            "password": "wrongpassword",
        })
        assert b"credenciales inv" in response.data.lower() or b"incorrect" in response.data.lower()

    def test_login_email_inexistente_no_revela_info(self, client):
        """Mismo mensaje genérico para email inexistente y password wrong."""
        response = client.post("/auth/login", data={
            "email": "noexiste@test.com",
            "password": "password123",
        })
        assert b"credenciales inv" in response.data.lower() or b"incorrect" in response.data.lower()


class TestLogout:
    """Cierre de sesión."""

    def test_logout_limpia_sesion_y_carrito(self, logged_client, cliente_user, producto_techstore):
        # Agregar al carrito
        logged_client.post(f"/carrito/agregar/{producto_techstore.id}")
        with logged_client.session_transaction() as sess:
            assert "cart" in sess and sess["cart"]

        # Logout
        response = logged_client.post("/auth/logout", follow_redirects=True)
        assert response.status_code == 200

        # Verificar sesión limpia
        with logged_client.session_transaction() as sess:
            assert "cart" not in sess or not sess.get("cart")