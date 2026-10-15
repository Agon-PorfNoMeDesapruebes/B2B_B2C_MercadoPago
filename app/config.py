import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar .env desde la raíz del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    """Configuración base común a todos los entornos."""

    # Seguridad - OBLIGATORIO: la app no arranca sin SECRET_KEY
    SECRET_KEY: str = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY no configurada. Definila en .env")

    # Base de datos
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'app.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ECHO: bool = False

    # Flask-Login
    LOGIN_DISABLED: bool = False
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    SESSION_COOKIE_SECURE: bool = False  # True solo en producción con HTTPS
    REMEMBER_COOKIE_HTTPONLY: bool = True
    REMEMBER_COOKIE_SAMESITE: str = "Lax"
    REMEMBER_COOKIE_SECURE: bool = False

    # Flask-WTF CSRF
    WTF_CSRF_ENABLED: bool = True
    WTF_CSRF_TIME_LIMIT: int = 3600  # 1 hora

    # Flask-Limiter
    RATELIMIT_DEFAULT: str = "200 per minute"
    RATELIMIT_STORAGE_URL: str = "memory://"
    RATELIMIT_STRATEGY: str = "fixed-window"

    # Mercado Pago - OBLIGATORIO en prod/staging
    MP_ACCESS_TOKEN: str = os.environ.get("MP_ACCESS_TOKEN", "")
    MP_PUBLIC_KEY: str = os.environ.get("MP_PUBLIC_KEY", "")
    MP_WEBHOOK_SECRET: str = os.environ.get("MP_WEBHOOK_SECRET", "")
    MP_SANDBOX: bool = True  # Siempre True en este TP (cuenta de prueba)

    # Mercado Pago Sandbox Test Accounts (solo usado si MP_SANDBOX=True)
    # Comprador de prueba: email para payer.email en preferencias/pagos
    MP_TEST_BUYER_EMAIL: str = os.environ.get("MP_TEST_BUYER_EMAIL", "")
    # Comprador de prueba: user_id para validar que no sea igual a vendedores
    MP_TEST_BUYER_USER_ID: str = os.environ.get("MP_TEST_BUYER_USER_ID", "")
    # Forzar email de comprador de prueba en sandbox (default True).
    # Con True: get_payer_email devuelve siempre MP_TEST_BUYER_EMAIL.
    # Con False: usa el email del formulario (para probar rechazos de MP por pagador).
    MP_FORCE_TEST_BUYER_EMAIL: bool = os.environ.get("MP_FORCE_TEST_BUYER_EMAIL", "true").lower() in ("1", "true", "yes", "on")
    # Archivo JSON con pool de vendedores de prueba (NO versionar, ver .gitignore)
    # Formato: [{"label": "...", "user_id": "...", "access_token": "...", "public_key": "...", "webhook_secret": "..."}, ...]
    MP_TEST_SELLERS_FILE: str = os.environ.get("MP_TEST_SELLERS_FILE", "mp_test_sellers.json")

    # URL pública para webhooks y back_urls (ngrok/túnel)
    PUBLIC_BASE_URL: str = os.environ.get("PUBLIC_BASE_URL", "http://localhost:5000")

    # Moneda y locale
    CURRENCY: str = "ARS"
    LOCALE: str = "es_AR"

    # Paginación
    PRODUCTS_PER_PAGE: int = 12
    ORDERS_PER_PAGE: int = 20

    # Pedidos
    ORDER_EXPIRY_MINUTES: int = 30
    MIN_QTY_COMPANY: int = 50  # Mínimo por línea para cuentas empresa
    MIN_QTY_CLIENT: int = 1    # Mínimo por línea para cuentas cliente


class DevelopmentConfig(Config):
    """Configuración para desarrollo local."""

    DEBUG: bool = True
    SQLALCHEMY_ECHO: bool = True
    SESSION_COOKIE_SECURE: bool = False
    REMEMBER_COOKIE_SECURE: bool = False


class TestingConfig(Config):
    """Configuración para tests automatizados."""

    TESTING: bool = True
    DEBUG: bool = True
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"
    SQLALCHEMY_ECHO: bool = False
    WTF_CSRF_ENABLED: bool = False  # Desactivar CSRF en tests
    LOGIN_DISABLED: bool = False
    RATELIMIT_ENABLED: bool = False
    MP_SANDBOX: bool = True
    MP_ACCESS_TOKEN: str = "TEST_TOKEN"
    MP_PUBLIC_KEY: str = "TEST_PUBLIC_KEY"
    PUBLIC_BASE_URL: str = "http://localhost"


class ProductionConfig(Config):
    """Configuración para producción."""

    DEBUG: bool = False
    SQLALCHEMY_ECHO: bool = False
    SESSION_COOKIE_SECURE: bool = True
    REMEMBER_COOKIE_SECURE: bool = True
    MP_SANDBOX: bool = False  # En producción real sería False


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}