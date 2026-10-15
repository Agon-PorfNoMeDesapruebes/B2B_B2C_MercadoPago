"""
Factory de la aplicación B2B_B2C.

Crea y configura la instancia de Flask usando el patrón Application Factory.
Registra blueprints, extensiones, comandos CLI y handlers de errores.
"""

import os
import logging
import sys
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, request
from app.config import config_by_name
from app.extensions import db, login_manager, csrf, migrate, limiter
from app.models import User


def create_app(config_name: str = None) -> Flask:
    """
    Crea la aplicación Flask.

    Args:
        config_name: Nombre de la configuración (development, testing, production).
                     Si es None, usa FLASK_ENV o 'default'.

    Returns:
        Flask: Instancia configurada de la aplicación.
    """
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "default")

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_by_name[config_name])

    # Asegurar que existe la carpeta instance
    os.makedirs(app.instance_path, exist_ok=True)

    # Inicializar extensiones
    _init_extensions(app)

    # Registrar blueprints
    _register_blueprints(app)

    # Registrar comandos CLI
    _register_cli_commands(app)

    # Registrar handlers de errores
    _register_error_handlers(app)

    # Configurar logging
    _configure_logging(app)

    # Template context processors
    _register_template_context(app)

    # Request hooks
    _register_request_hooks(app)

    app.logger.info(f"B2B_B2C iniciado en modo {config_name}")
    return app


def _init_extensions(app: Flask) -> None:
    """Inicializa todas las extensiones Flask."""
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    # User loader para Flask-Login (usa db.session.get en SQLAlchemy 2.x)
    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        try:
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None


def _register_blueprints(app: Flask) -> None:
    """Registra todos los blueprints de la aplicación."""
    from app.blueprints.auth import auth_bp
    from app.blueprints.main import main_bp
    from app.blueprints.companies import companies_bp
    from app.blueprints.cart import cart_bp
    from app.blueprints.orders import orders_bp
    from app.blueprints.payments import payments_bp
    from app.blueprints.webhooks import webhooks_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(companies_bp, url_prefix="/empresas")
    app.register_blueprint(cart_bp, url_prefix="/carrito")
    app.register_blueprint(orders_bp, url_prefix="/pedidos")
    app.register_blueprint(payments_bp, url_prefix="/pagos")
    app.register_blueprint(webhooks_bp, url_prefix="/webhooks")


def _register_cli_commands(app: Flask) -> None:
    """Registra comandos CLI personalizados."""

    @app.cli.command("seed")
    def seed_command():
        """Puebla la BD con datos de prueba idempotentes."""
        from app.services.seed import seed_database
        seed_database()
        app.logger.info("Seed completado.")

    @app.cli.command("expire-orders")
    def expire_orders_command():
        """Expira pedidos pendientes vencidos y devuelve stock."""
        from app.services.orders import expire_pending_orders
        count = expire_pending_orders()
        app.logger.info(f"Pedidos expirados: {count}")

    @app.cli.command("reconcile-payments")
    def reconcile_payments_command():
        """Reconcilia pagos pendientes consultando a Mercado Pago."""
        from app.services.mercadopago import reconcile_pending_payments
        count = reconcile_pending_payments()
        app.logger.info(f"Pagos reconciliados: {count}")

    @app.cli.command("assign-test-sellers")
    def assign_test_sellers_command():
        """Asigna vendedores de prueba de MP a empresas sin credenciales (solo sandbox)."""
        from app.services.mp_accounts import load_test_sellers, validate_sellers_vs_buyer, assign_test_seller
        from app.models.company import Company

        if not app.config.get("MP_SANDBOX", True):
            app.logger.warning("assign-test-sellers: solo disponible en modo sandbox (MP_SANDBOX=True)")
            return

        try:
            validate_sellers_vs_buyer()
            sellers = load_test_sellers()
            app.logger.info(f"Pool de vendedores de prueba cargado: {len(sellers)} vendedores")

            companies_without_creds = Company.query.filter(
                (Company.mp_seller_user_id.is_(None)) | (Company.mp_seller_user_id == "")
            ).all()

            if not companies_without_creds:
                app.logger.info("Todas las empresas ya tienen credenciales asignadas.")
                return

            assigned = 0
            for company in companies_without_creds:
                try:
                    assign_test_seller(company)
                    assigned += 1
                except Exception as e:
                    app.logger.error(f"Error asignando vendedor a Company {company.id} ({company.name}): {e}")

            db.session.commit()
            app.logger.info(f"Vendedores de prueba asignados a {assigned} empresas.")
        except Exception as e:
            app.logger.exception("Error en assign-test-sellers")
            raise

    @app.cli.command("check-mp-setup")
    def check_mp_setup_command():
        """Verifica configuración de Mercado Pago (sandbox) y reporta en español."""
        from app.services.mp_accounts import load_test_sellers, get_test_buyer_user_id, find_company_by_seller_user_id
        from app.models.company import Company
        import requests

        sandbox = app.config.get("MP_SANDBOX", True)
        if not sandbox:
            print("⚠ MP_SANDBOX=False (modo producción). Este comando es para sandbox.")
            return

        print("=" * 60)
        print("VERIFICACION DE CONFIGURACION MERCADO PAGO (SANDBOX)")
        print("=" * 60)

        # a) Variables de .env presentes y MP_SANDBOX=True
        print("\n1) Variables de entorno (.env):")
        required_vars = {
            "MP_SANDBOX": "True",
            "MP_TEST_BUYER_EMAIL": "(email del comprador de prueba)",
            "MP_TEST_BUYER_USER_ID": "(user_id del comprador de prueba)",
            "MP_TEST_SELLERS_FILE": "mp_test_sellers.json",
            "PUBLIC_BASE_URL": "(URL publica para webhooks, ej. https://xxx.ngrok-free.app)",
        }
        all_ok = True
        for var, expected in required_vars.items():
            value = app.config.get(var, "")
            if value:
                display = value if var != "MP_TEST_SELLERS_FILE" else value
                print(f"   [OK] {var} = {display}")
            else:
                print(f"   [FAIL] {var} = NO CONFIGURADO (esperado: {expected})")
                all_ok = False

        # MP_SANDBOX explícitamente True
        mp_sandbox = app.config.get("MP_SANDBOX", True)
        if mp_sandbox is True or str(mp_sandbox).lower() in ("1", "true", "yes", "on"):
            print("   [OK] MP_SANDBOX = True")
        else:
            print("   [FAIL] MP_SANDBOX no es True")
            all_ok = False

        # b) mp_test_sellers.json existe y es válido
        print("\n2) Archivo mp_test_sellers.json:")
        sellers = []
        try:
            sellers = load_test_sellers()
            print(f"   [OK] Archivo encontrado y valido: {len(sellers)} vendedor(es)")
            for s in sellers:
                print(f"      - {s.label} (user_id={s.user_id})")
        except Exception as e:
            print(f"   [FAIL] Error cargando vendedores: {e}")
            all_ok = False

        # c) Ningún vendedor tiene el mismo user_id que el comprador
        print("\n3) Validacion comprador vs vendedores:")
        try:
            buyer_id = get_test_buyer_user_id()
            print(f"   Comprador de prueba user_id = {buyer_id}")
            conflict = False
            for s in sellers:
                if s.user_id == buyer_id:
                    print(f"   [FAIL] CONFLICTO: Vendedor '{s.label}' tiene mismo user_id que el comprador ({buyer_id})")
                    conflict = True
            if not conflict:
                print("   [OK] Ningun vendedor coincide con el comprador")
        except Exception as e:
            print(f"   [FAIL] Error validando: {e}")
            all_ok = False

        # d) Cuántas empresas tienen y no tienen credenciales
        print("\n4) Empresas y credenciales MP:")
        total_companies = Company.query.count()
        with_creds = Company.query.filter(
            Company.mp_seller_user_id.isnot(None),
            Company.mp_seller_user_id != ""
        ).count()
        without_creds = total_companies - with_creds
        print(f"   Total empresas: {total_companies}")
        print(f"   Con credenciales: {with_creds}")
        print(f"   Sin credenciales: {without_creds}")
        if without_creds > 0:
            print("   [INFO] Ejecutá 'flask assign-test-sellers' para asignar")

        # e) Para cada vendedor, GET /users/me con access_token
        print("\n5) Validacion de tokens de vendedores (API /users/me):")
        if not sellers:
            print("   (sin vendedores para validar)")
        else:
            for s in sellers:
                token_ok = False
                returned_id = None
                try:
                    resp = requests.get(
                        "https://api.mercadopago.com/users/me",
                        headers={"Authorization": f"Bearer {s.access_token}"},
                        timeout=10
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        returned_id = str(data.get("id", ""))
                        if returned_id == s.user_id:
                            print(f"   [OK] {s.label} (user_id={s.user_id}): token VALIDO, id coincide")
                            token_ok = True
                        else:
                            print(f"   [WARN] {s.label} (user_id={s.user_id}): token VALIDO pero id devuelto es {returned_id} (NO COINCIDE)")
                    else:
                        print(f"   [FAIL] {s.label} (user_id={s.user_id}): token INVALIDO (HTTP {resp.status_code})")
                except requests.exceptions.RequestException as e:
                    print(f"   [INFO] {s.label} (user_id={s.user_id}): sin red / error de conexion ({type(e).__name__})")
                except Exception as e:
                    print(f"   [FAIL] {s.label} (user_id={s.user_id}): error inesperado ({type(e).__name__}: {e})")

        print("\n" + "=" * 60)
        if all_ok:
            print("[OK] CONFIGURACION OK")
        else:
            print("[WARN] HAY PROBLEMAS DE CONFIGURACION (ver arriba)")
        print("=" * 60)


def _register_error_handlers(app: Flask) -> None:
    """Registra handlers para errores HTTP."""

    @app.errorhandler(403)
    def forbidden(e):
        app.logger.warning(f"403 Forbidden: {request.path} - User: {getattr(request, 'user', 'anon')}")
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()
        app.logger.exception(f"500 Internal Server Error: {request.path}")
        return render_template("errors/500.html"), 500

    @app.errorhandler(429)
    def ratelimit_exceeded(e):
        return render_template("errors/429.html", retry_after=e.retry_after), 429


def _configure_logging(app: Flask) -> None:
    """Configura logging estructurado."""
    if not app.debug and not app.testing:
        # Log a archivo en producción
        if not os.path.exists("logs"):
            os.mkdir("logs")
        file_handler = RotatingFileHandler(
            "logs/b2b_b2c.log", maxBytes=10240, backupCount=10
        )
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]"
            )
        )
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
    else:
        # En desarrollo, log a consola con nivel DEBUG
        app.logger.setLevel(logging.DEBUG)


def _register_template_context(app: Flask) -> None:
    """Registra variables y funciones globales para templates."""

    @app.context_processor
    def inject_globals():
        from app.config import config_by_name
        config = config_by_name.get(app.config.get("ENV", "default"), config_by_name["default"])
        return {
            "APP_NAME": "B2B_B2C",
            "CURRENCY": app.config["CURRENCY"],
            "MIN_QTY_COMPANY": app.config["MIN_QTY_COMPANY"],
            "MIN_QTY_CLIENT": app.config["MIN_QTY_CLIENT"],
        }


def _register_request_hooks(app: Flask) -> None:
    """Registra hooks de request/response."""

    @app.before_request
    def ensure_csrf_on_forms():
        # El CSRF ya está activo globalmente via csrf.init_app
        # Este hook es placeholder para validaciones extra si se necesitan
        pass

    @app.after_request
    def add_security_headers(response):
        # Cabeceras de seguridad básicas
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Referrer-Policy: strict-origin-when-cross-origin es un buen balance
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response