"""
Comando seed idempotente - B2B_B2C.

Crea datos de prueba: 3 empresas con productos, 1 cliente, 1 empresa compradora.
Uso: flask seed
"""

from decimal import Decimal
from app.extensions import db
from app.models.user import User, AccountType
from app.models.company import Company
from app.models.product import Product


def seed_database() -> None:
    """Puebla la BD con datos de prueba de forma idempotente."""

    # --- 1. Usuario CLIENTE de prueba ---
    cliente = User.get_by_email("cliente@test.com")
    if not cliente:
        cliente = User.create_user(
            username="cliente_test",
            email="cliente@test.com",
            password="cliente123",
            account_type=AccountType.CLIENTE,
        )
        db.session.add(cliente)
        print("[OK] Cliente de prueba creado")
    else:
        print("[OK] Cliente de prueba ya existe")

    # --- 2. Empresa COMPRADORA de prueba (para testear compras B2B) ---
    empresa_compradora_user = User.get_by_email("empresa_compradora@test.com")
    if not empresa_compradora_user:
        empresa_compradora_user = User.create_user(
            username="empresa_compradora",
            email="empresa_compradora@test.com",
            password="empresa123",
            account_type=AccountType.EMPRESA,
        )
        db.session.add(empresa_compradora_user)
        db.session.flush()

        empresa_compradora = Company.create_for_owner(
            owner=empresa_compradora_user,
            name="Empresa Compradora S.A.",
            tax_id="30712345671",  # CUIT válido (base 3071234567 + DV=1)
            description="Empresa de prueba para compras B2B",
        )
        db.session.add(empresa_compradora)
        print("[OK] Empresa compradora de prueba creada")
    else:
        print("[OK] Empresa compradora ya existe")

    # --- 3. Tres empresas VENDEDORAS con productos ---
    empresas_data = [
        {
            "username": "techstore",
            "email": "techstore@test.com",
            "password": "techstore123",
            "company_name": "TechStore Argentina",
            "cuit": "30711111113",  # CUIT válido (base 3071111111 + DV=3)
            "description": "Equipamiento informático, notebooks, periféricos y componentes.",
            "products": [
                {"name": "Laptop Gaming X1", "description": "Procesador i9, 32GB RAM, RTX 4080, 1TB SSD.", "price": Decimal("1200000.00"), "stock": 15},
                {"name": "Monitor 27\" 4K 144Hz", "description": "IPS, HDR400, G-Sync compatible.", "price": Decimal("450000.00"), "stock": 8},
                {"name": "Teclado Mecánico RGB Pro", "description": "Switches Cherry MX Brown, aluminio.", "price": Decimal("180000.00"), "stock": 25},
                {"name": "Mouse Gaming Ultraligero", "description": "59g, sensor 26K DPI, inalámbrico.", "price": Decimal("120000.00"), "stock": 30},
                {"name": "Auriculares 7.1 Surround", "description": "Cancelación de ruido, micrófono desmontable.", "price": Decimal("95000.00"), "stock": 12},
                {"name": "Webcam 4K Streaming", "description": "Auto-focus, HDR, micrófono dual.", "price": Decimal("150000.00"), "stock": 20},
            ],
        },
        {
            "username": "oficinasur",
            "email": "oficinasur@test.com",
            "password": "oficinasur123",
            "company_name": "OficinaSur S.R.L.",
            "cuit": "30722222229",  # CUIT válido (base 3072222222 + DV=9)
            "description": "Mobiliario y suministros de oficina.",
            "products": [
                {"name": "Silla Ergonómica Executive", "description": "Malla transpirable, soporte lumbar, brazos 4D.", "price": Decimal("380000.00"), "stock": 10},
                {"name": "Escritorio Sit-Stand 160cm", "description": "Eléctrico, memoria de 4 alturas, bambú.", "price": Decimal("520000.00"), "stock": 5},
                {"name": "Monitor Arm Doble", "description": "Gas spring, rotación 360°, hasta 32\".", "price": Decimal("85000.00"), "stock": 18},
                {"name": "Pack 10 Resmas A4 75gr", "description": "Papel multifunción, caja sellada.", "price": Decimal("45000.00"), "stock": 50},
                {"name": "Archivador Metálico 4 Cajones", "description": "Con llave, guías telescópicas.", "price": Decimal("120000.00"), "stock": 7},
            ],
        },
        {
            "username": "hogarconfort",
            "email": "hogarconfort@test.com",
            "password": "hogar123",
            "company_name": "HogarConfort",
            "cuit": "30733333339",  # CUIT válido (base 3073333333 + DV=9)
            "description": "Electrodomésticos y artículos para el hogar.",
            "products": [
                {"name": "Heladera No Frost 450L", "description": "Inverter, dispenser agua/hielo, clase A+++.", "price": Decimal("950000.00"), "stock": 4},
                {"name": "Lavarropas Carga Frontal 10kg", "description": "Inverter, 1400 RPM, vapor, WiFi.", "price": Decimal("780000.00"), "stock": 6},
                {"name": "Aire Acondicionado Split 4500 Frig", "description": "Inverter, frío/calor, WiFi, purificador.", "price": Decimal("520000.00"), "stock": 8},
                {"name": "Robot Aspiradora LiDAR", "description": "Mapeo láser, fregado, app, 5000 Pa.", "price": Decimal("380000.00"), "stock": 10},
                {"name": "Cafetera Superautomática", "description": "Molido fresco, 15 bar, pantalla táctil.", "price": Decimal("420000.00"), "stock": 5},
            ],
        },
    ]

    for emp_data in empresas_data:
        user = User.get_by_email(emp_data["email"])
        if not user:
            user = User.create_user(
                username=emp_data["username"],
                email=emp_data["email"],
                password=emp_data["password"],
                account_type=AccountType.EMPRESA,
            )
            db.session.add(user)
            db.session.flush()

            company = Company.create_for_owner(
                owner=user,
                name=emp_data["company_name"],
                tax_id=emp_data["cuit"],
                description=emp_data["description"],
            )
            db.session.add(company)
            db.session.flush()

            for prod_data in emp_data["products"]:
                # Verificar si ya existe (idempotente por nombre+empresa)
                existing = Product.query.filter_by(
                    company_id=company.id, name=prod_data["name"]
                ).first()
                if not existing:
                    product = Product.create_for_company(
                        company=company,
                        name=prod_data["name"],
                        price=prod_data["price"],
                        stock=prod_data["stock"],
                        description=prod_data["description"],
                    )
                    db.session.add(product)

            print(f"[OK] {emp_data['company_name']} creada con {len(emp_data['products'])} productos")
        else:
            print(f"[OK] {emp_data['company_name']} ya existe")

    # --- 4. Asignar vendedores de prueba de Mercado Pago (solo en sandbox) ---
    if db.session.get_bind().engine.url.get_backend_name() != "sqlite" or True:
        # En sandbox, asignar credenciales de prueba a las empresas vendedoras
        try:
            from flask import current_app
            if current_app and current_app.config.get("MP_SANDBOX", True):
                from app.services.mp_accounts import load_test_sellers, validate_sellers_vs_buyer, assign_test_seller
                try:
                    validate_sellers_vs_buyer()
                    sellers = load_test_sellers()
                    print(f"[OK] Pool de vendedores de prueba MP cargado: {len(sellers)} vendedores")
                    
                    # Asignar a todas las empresas (incluyendo la compradora, por si vende)
                    all_companies = Company.query.all()
                    assigned = 0
                    for company in all_companies:
                        if not company.mp_seller_user_id:
                            try:
                                assign_test_seller(company)
                                assigned += 1
                            except Exception as e:
                                print(f"[WARN] Error asignando vendedor a {company.name}: {e}")
                    
                    if assigned > 0:
                        db.session.commit()
                        print(f"[OK] Vendedores de prueba asignados a {assigned} empresas")
                    else:
                        print("[OK] Todas las empresas ya tenían credenciales asignadas")
                except RuntimeError as e:
                    print(f"[INFO] Saltando asignación de vendedores MP: {e}")
        except Exception as e:
            print(f"[WARN] No se pudieron asignar vendedores de prueba MP: {e}")

    db.session.commit()
    print("\n[OK] Seed completado exitosamente")
    print("   Credenciales de prueba:")
    print("   - Cliente: cliente@test.com / cliente123")
    print("   - Empresa compradora: empresa_compradora@test.com / empresa123")
    print("   - TechStore: techstore@test.com / techstore123")
    print("   - OficinaSur: oficinasur@test.com / oficinasur123")
    print("   - HogarConfort: hogarconfort@test.com / hogar123")