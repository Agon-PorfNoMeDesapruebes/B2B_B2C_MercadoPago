"""
Servicio de gestión de cuentas de prueba de Mercado Pago - B2B_B2C.

En modo sandbox (MP_SANDBOX=True), cada Company cobra con su propia cuenta VENDEDORA de prueba
y todos los compradores pagan como la cuenta COMPRADORA de prueba.

En producción (MP_SANDBOX=False) se usan las credenciales globales de config.
"""

import json
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from flask import current_app
from app.models.company import Company


@dataclass
class TestSeller:
    """Vendedor de prueba del pool."""
    label: str
    user_id: str
    access_token: str
    public_key: str
    webhook_secret: str
    assigned_count: int = 0  # Para round-robin


# Cache del pool de vendedores
_test_sellers_cache: list[TestSeller] | None = None
_buyer_user_id: str | None = None


def _reset_cache_for_testing() -> None:
    """Resetea el cache global (solo para tests)."""
    global _test_sellers_cache, _buyer_user_id
    _test_sellers_cache = None
    _buyer_user_id = None


def load_test_sellers() -> list[TestSeller]:
    """
    Lee el JSON del pool de vendedores de prueba y valida campos.

    El archivo se configura con MP_TEST_SELLERS_FILE en .env.
    Formato esperado:
    [
        {"label": "Vendedor", "user_id": "3735930282", "access_token": "...", "public_key": "...", "webhook_secret": "..."},
        ...
    ]

    Returns:
        list[TestSeller]: Lista de vendedores válidos.

    Raises:
        RuntimeError: Si el archivo no existe, JSON inválido, o campos faltantes.
    """
    global _test_sellers_cache

    if _test_sellers_cache is not None:
        return _test_sellers_cache

    sellers_file = current_app.config.get("MP_TEST_SELLERS_FILE")
    if not sellers_file:
        raise RuntimeError("MP_TEST_SELLERS_FILE no configurado en .env")

    path = Path(sellers_file)
    if not path.is_absolute():
        # Resolver relativo a la raíz del proyecto (donde está .env)
        base_dir = Path(current_app.root_path).parent
        path = base_dir / sellers_file

    if not path.exists():
        raise RuntimeError(f"Archivo de vendedores de prueba no encontrado: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON inválido en {path}: {e}")

    if not isinstance(data, list) or not data:
        raise RuntimeError("El pool de vendedores debe ser una lista no vacía")

    required_fields = {"label", "user_id", "access_token", "public_key", "webhook_secret"}
    sellers = []

    for idx, item in enumerate(data):
        missing = required_fields - set(item.keys())
        if missing:
            raise RuntimeError(f"Vendedor #{idx} ({item.get('label', '?')}) faltan campos: {missing}")

        # Validar que no sean strings vacíos
        for field in required_fields:
            if not item[field] or not str(item[field]).strip():
                raise RuntimeError(f"Vendedor #{idx} ({item.get('label', '?')}) campo '{field}' vacío")

        sellers.append(TestSeller(
            label=str(item["label"]).strip(),
            user_id=str(item["user_id"]).strip(),
            access_token=str(item["access_token"]).strip(),
            public_key=str(item["public_key"]).strip(),
            webhook_secret=str(item["webhook_secret"]).strip(),
        ))

    _test_sellers_cache = sellers
    return sellers


def get_test_buyer_user_id() -> str:
    """
    Obtiene el user_id del comprador de prueba desde .env (MP_TEST_BUYER_USER_ID).
    Se usa para validar que ningún vendedor sea la misma cuenta que el comprador.
    """
    global _buyer_user_id
    if _buyer_user_id is None:
        _buyer_user_id = current_app.config.get("MP_TEST_BUYER_USER_ID", "").strip()
        if not _buyer_user_id:
            raise RuntimeError("MP_TEST_BUYER_USER_ID no configurado en .env")
    return _buyer_user_id


def validate_sellers_vs_buyer() -> None:
    """
    Valida al arrancar que ningún vendedor del pool sea la misma cuenta que el comprador.
    Mercado Pago no permite que una cuenta se pague a sí misma.

    Raises:
        RuntimeError: Si algún vendedor tiene el mismo user_id que el comprador.
    """
    if not current_app.config.get("MP_SANDBOX", True):
        return  # Solo en sandbox

    buyer_id = get_test_buyer_user_id()
    sellers = load_test_sellers()

    for seller in sellers:
        if seller.user_id == buyer_id:
            raise RuntimeError(
                f"El vendedor de prueba '{seller.label}' (user_id={seller.user_id}) "
                f"es la misma cuenta que el comprador de prueba (user_id={buyer_id}). "
                f"Mercado Pago no permite que una cuenta se pague a sí misma."
            )


def assign_test_seller(company: Company) -> TestSeller:
    """
    Asigna a una Company sin credenciales el vendedor de prueba menos usado (round-robin).

    Si hay más empresas que vendedores, se comparten (se documenta esta limitación).
    La asignación es persistente: guarda los campos en la Company.

    Args:
        company: Company a la que asignar credenciales.

    Returns:
        TestSeller: El vendedor asignado.

    Raises:
        RuntimeError: Si la empresa ya tiene credenciales o no hay vendedores disponibles.
    """
    if company.mp_seller_user_id:
        # Ya tiene credenciales asignadas, buscar el seller correspondiente
        sellers = load_test_sellers()
        for seller in sellers:
            if seller.user_id == company.mp_seller_user_id:
                return seller
        # Si no se encuentra en el pool actual, reasignar
        current_app.logger.warning(f"Company {company.id} tiene mp_seller_user_id={company.mp_seller_user_id} "
                                   f"pero no está en el pool actual; reasignando")

    sellers = load_test_sellers()
    if not sellers:
        raise RuntimeError("No hay vendedores de prueba disponibles en el pool")

    # Round-robin: elegir el con menor assigned_count
    # Nota: assigned_count es en memoria; para persistencia real se necesitaría un campo en BD.
    # Como workaround, contamos cuántas empresas ya usan cada seller.
    from app.extensions import db
    seller_usage = {}
    for s in sellers:
        count = Company.query.filter_by(mp_seller_user_id=s.user_id).count()
        seller_usage[s.user_id] = count

    # Elegir el menos usado
    chosen = min(sellers, key=lambda s: seller_usage.get(s.user_id, 0))

    # Asignar a la company
    company.mp_seller_user_id = chosen.user_id
    company.mp_access_token = chosen.access_token
    company.mp_public_key = chosen.public_key
    company.mp_webhook_secret = chosen.webhook_secret
    db.session.add(company)
    db.session.flush()

    current_app.logger.info(f"Asignado vendedor de prueba '{chosen.label}' (user_id={chosen.user_id}) "
                            f"a Company {company.id} ({company.name})")

    return chosen


def get_mp_credentials(order: "Order") -> tuple[str, str]:
    """
    Obtiene las credenciales de Mercado Pago para un pedido.

    En sandbox: devuelve (access_token, public_key) de order.company.
    Si la empresa no tiene credenciales, intenta asignarlas (lazy assignment) y hace commit.
    En producción: devuelve las globales (MP_ACCESS_TOKEN, MP_PUBLIC_KEY).

    Args:
        order: Pedido del cual obtener las credenciales (via order.company).

    Returns:
        tuple: (access_token, public_key)

    Raises:
        RuntimeError: En sandbox si la empresa no tiene credenciales y no se pudieron asignar.
    """
    from app.config import config_by_name
    # Usar config de la app actual
    sandbox = current_app.config.get("MP_SANDBOX", True)

    if not sandbox:
        # Producción: credenciales globales
        access_token = current_app.config.get("MP_ACCESS_TOKEN", "")
        public_key = current_app.config.get("MP_PUBLIC_KEY", "")
        if not access_token or not public_key:
            raise RuntimeError("Credenciales globales de MP no configuradas (MP_ACCESS_TOKEN, MP_PUBLIC_KEY)")
        return access_token, public_key

    # Sandbox: credenciales por empresa
    company = order.company
    if not company:
        raise RuntimeError("Pedido sin empresa asociada")

    if not company.mp_access_token or not company.mp_public_key:
        # Lazy assignment: intentar asignar vendedor de prueba ahora
        try:
            from app.extensions import db
            from app.services.mp_accounts import assign_test_seller, load_test_sellers
            load_test_sellers()  # Valida que el pool existe
            assign_test_seller(company)
            db.session.commit()
            current_app.logger.info(f"Lazy assignment: vendedor de prueba asignado a Company {company.id} ({company.name})")
        except RuntimeError as e:
            # Pool no disponible o error de configuración
            current_app.logger.error(f"Lazy assignment falló para Company {company.id}: {e}")
            raise RuntimeError(
                f"La empresa '{company.name}' (id={company.id}) no tiene credenciales de prueba asignadas "
                f"y no se pudieron asignar automáticamente: {e}. "
                f"Ejecutá 'flask assign-test-sellers' o asigná manualmente."
            )
        except Exception as e:
            # Cualquier otro error inesperado
            current_app.logger.exception(f"Lazy assignment error inesperado para Company {company.id}")
            raise RuntimeError(
                f"La empresa '{company.name}' (id={company.id}) no tiene credenciales de prueba asignadas "
                f"y ocurrió un error inesperado al intentar asignarlas: {e}"
            )

    return company.mp_access_token, company.mp_public_key


def get_payer_email(order: "Order", form_email: str) -> str:
    """
    Obtiene el email del pagador para enviar a Mercado Pago.

    En sandbox:
      - Si MP_FORCE_TEST_BUYER_EMAIL=True (default): devuelve MP_TEST_BUYER_EMAIL.
      - Si MP_FORCE_TEST_BUYER_EMAIL=False: usa el email del formulario.
    En producción: devuelve el email del formulario.

    Args:
        order: Pedido (para contexto).
        form_email: Email que ingresó el usuario en el formulario.

    Returns:
        str: Email a usar en el pago.
    """
    sandbox = current_app.config.get("MP_SANDBOX", True)

    if not sandbox:
        return form_email.strip() if form_email else ""

    # Sandbox: comportamiento configurable
    force_test_buyer = current_app.config.get("MP_FORCE_TEST_BUYER_EMAIL", True)
    if force_test_buyer:
        buyer_email = current_app.config.get("MP_TEST_BUYER_EMAIL", "").strip()
        if not buyer_email:
            raise RuntimeError("MP_TEST_BUYER_EMAIL no configurado en .env")
        return buyer_email
    else:
        return form_email.strip() if form_email else ""


def get_webhook_secret_for_seller(seller_user_id: str) -> str | None:
    """
    Busca el webhook_secret del vendedor por su user_id en el pool.

    Args:
        seller_user_id: User ID del vendedor en Mercado Pago.

    Returns:
        str o None: El webhook_secret si se encuentra, None si no.
    """
    sellers = load_test_sellers()
    for seller in sellers:
        if seller.user_id == seller_user_id:
            return seller.webhook_secret
    return None


def find_company_by_seller_user_id(seller_user_id: str) -> Company | None:
    """
    Busca una Company por el mp_seller_user_id (user_id del vendedor en MP).

    Args:
        seller_user_id: User ID del vendedor en Mercado Pago.

    Returns:
        Company o None.
    """
    return Company.query.filter_by(mp_seller_user_id=seller_user_id).first()