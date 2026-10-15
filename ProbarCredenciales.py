"""
Prueba rapida de credenciales de Mercado Pago, SIN pasar por tu app.

Uso (con el venv activado, desde cualquier carpeta):
    python probar_credenciales.py

Te pide Access Token y Public Key (no se ven al pegarlos, no se guardan),
crea un token de tarjeta de prueba (APRO) y hace un pago de $100.
Te dice si esas credenciales sirven o no, y por que.
"""
import getpass
import sys
import uuid

import requests

API = "https://api.mercadopago.com"
EMAIL_DEFECTO = "comprador.prueba@example.com"  # cualquiera, pero distinto al de tu cuenta de Mercado Pago


def mostrar_error(resp):
    try:
        data = resp.json()
    except ValueError:
        print(f"   Respuesta no JSON (HTTP {resp.status_code}): {resp.text[:200]}")
        return ""
    msg = data.get("message") or data.get("error") or ""
    causa = data.get("cause")
    print(f"   HTTP {resp.status_code} - {msg}")
    if causa:
        print(f"   Detalle: {causa}")
    return str(data)


def main():
    print("=" * 60)
    print("PRUEBA DE CREDENCIALES DE MERCADO PAGO")
    print("=" * 60)
    token = getpass.getpass("Access Token (no se ve al pegar): ").strip()
    public_key = getpass.getpass("Public Key (no se ve al pegar): ").strip()
    email = input(f"Email del pagador [{EMAIL_DEFECTO}]: ").strip() or EMAIL_DEFECTO

    if not token or not public_key:
        print("Faltan credenciales.")
        sys.exit(1)

    print(f"\nEl token termina en: ...{token[-10:]}  (ese numero final es el ID de la cuenta dueña)")
    auth = {"Authorization": f"Bearer {token}"}

    # Paso 0: quien es el dueño del token
    print("\n[0] Consultando de quien es el token (/users/me)...")
    try:
        r = requests.get(f"{API}/users/me", headers=auth, timeout=20)
    except requests.RequestException as e:
        print(f"   Sin conexion con Mercado Pago: {e}")
        sys.exit(1)
    if r.status_code == 200:
        d = r.json()
        print(f"   ID: {d.get('id')} | nickname: {d.get('nickname')} | pais: {d.get('site_id')}")
        print(f"   tipo: {d.get('user_type')} | tags: {d.get('tags')}")
    else:
        print("   El token NO es valido o no tiene permisos:")
        mostrar_error(r)
        sys.exit(1)

    # Paso 1: token de tarjeta (lo que hace el Brick en el navegador)
    print("\n[1] Creando token de tarjeta de prueba (Mastercard APRO)...")
    tarjeta = {
        "card_number": "5031755734530604",
        "security_code": "123",
        "expiration_month": 11,
        "expiration_year": 2030,
        "cardholder": {
            "name": "APRO",
            "identification": {"type": "DNI", "number": "12345678"},
        },
    }
    r = requests.post(
        f"{API}/v1/card_tokens", params={"public_key": public_key}, json=tarjeta, timeout=20
    )
    if r.status_code not in (200, 201):
        print("   No se pudo crear el token de tarjeta (la Public Key suele ser la culpable):")
        mostrar_error(r)
        sys.exit(1)
    card_token = r.json()["id"]
    print("   OK, token de tarjeta creado.")

    # Paso 2: el pago
    print("\n[2] Creando pago de prueba de $100...")
    pago = {
        "transaction_amount": 100,
        "token": card_token,
        "description": "Prueba de credenciales",
        "installments": 1,
        "payment_method_id": "master",
        "payer": {"email": email},
    }
    headers = dict(auth, **{"X-Idempotency-Key": str(uuid.uuid4())})
    r = requests.post(f"{API}/v1/payments", headers=headers, json=pago, timeout=30)
    print("\n" + "=" * 60)
    if r.status_code in (200, 201):
        d = r.json()
        print(f"RESULTADO: status={d.get('status')} detalle={d.get('status_detail')}")
        if d.get("status") == "approved":
            print("ESTAS CREDENCIALES SIRVEN. Usalas en mp_test_sellers.json.")
        else:
            print("El pago se creo pero no se aprobo; pasame esta salida.")
    else:
        cuerpo = mostrar_error(r)
        print("=" * 60)
        if "live credentials" in cuerpo.lower():
            print("Mercado Pago considera estas credenciales como de PRODUCCION")
            print("(no activadas). No sirven para pagar con tarjeta de prueba.")
            print("Proba con otras credenciales y volve a correr este script.")
        else:
            print("Fallo distinto. Pasame el mensaje de arriba.")
    print("=" * 60)


if __name__ == "__main__":
    main()