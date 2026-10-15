"""
Servicio de autenticación - B2B_B2C.

Registro atómico de usuario + empresa.
"""

from app.extensions import db
from app.models.user import User, AccountType
from app.models.company import Company


def register_user_with_company(
    username: str,
    email: str,
    password: str,
    company_name: str,
    cuit: str,
    description: str = "",
) -> User:
    """
    Crea User (account_type=EMPRESA) + Company en una sola transacción.

    En sandbox, intenta asignar vendedor de prueba de MP a la Company.
    Si el pool no está disponible, registra warning y continúa sin credenciales.

    Args:
        username: Nombre de usuario único.
        email: Email único (normalizado a minúsculas).
        password: Contraseña en texto plano (min 8 chars validado en form).
        company_name: Nombre único de la empresa.
        cuit: CUIT válido (11 dígitos).
        description: Descripción opcional.

    Returns:
        User: El usuario creado (ya en sesión, pendiente commit).

    Raises:
        ValueError: Si hay conflictos de unicidad.
    """
    # Normalizar
    email = email.lower().strip()
    username = username.strip()
    company_name = company_name.strip()
    cuit = Company.normalize_cuit(cuit)

    # Verificar unicidad (doble chequeo por si race condition)
    if User.get_by_username(username):
        raise ValueError("Nombre de usuario ya en uso.")
    if User.get_by_email(email):
        raise ValueError("Email ya registrado.")
    if Company.query.filter_by(name=company_name).first():
        raise ValueError("Nombre de empresa ya en uso.")
    if Company.query.filter_by(tax_id=cuit).first():
        raise ValueError("CUIT ya registrado.")

    # Crear usuario
    user = User.create_user(
        username=username,
        email=email,
        password=password,
        account_type=AccountType.EMPRESA,
    )

    # Crear empresa
    company = Company.create_for_owner(
        owner=user,
        name=company_name,
        tax_id=cuit,
        description=description,
    )

    db.session.add(user)
    db.session.add(company)
    db.session.flush()  # Para tener company.id antes de asignar vendedor

    # Asignación automática de vendedor de prueba (solo sandbox)
    try:
        from flask import current_app
        if current_app and current_app.config.get("MP_SANDBOX", True):
            from app.services.mp_accounts import assign_test_seller, load_test_sellers
            try:
                # Validar pool disponible antes de asignar
                load_test_sellers()
                assign_test_seller(company)
            except RuntimeError as e:
                # Pool no disponible o error de configuración: warning y seguir sin credenciales
                current_app.logger.warning(f"Registro empresa {company.name}: no se asignó vendedor de prueba MP: {e}")
    except Exception as e:
        # Cualquier otro error inesperado: warning y seguir
        from flask import current_app
        if current_app:
            current_app.logger.warning(f"Registro empresa {company.name}: error inesperado asignando vendedor MP: {e}")

    # El commit lo maneja el caller (blueprint)
    return user