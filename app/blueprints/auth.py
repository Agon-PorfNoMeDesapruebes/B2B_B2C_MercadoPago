"""
Blueprint de autenticación - B2B_B2C.

Rutas: /auth/registrar/eleccion, /auth/registrar/empresa, /auth/registrar/cliente,
       /auth/login, /auth/logout
"""

from urllib.parse import urlparse
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user, login_user, logout_user, login_required
from app.extensions import db, limiter
from app.forms.auth import LoginForm, RegisterEmpresaForm, RegisterClienteForm
from app.models.user import User, AccountType
from app.models.company import Company
from app.services.auth import register_user_with_company

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _safe_redirect_target(default="main.dashboard"):
    """
    Valida y devuelve target seguro para redirect.
    
    Solo permite URLs relativas (sin netloc) para prevenir open redirect.
    """
    target = request.args.get("next") or request.form.get("next")
    if target:
        parsed = urlparse(target)
        if not parsed.netloc and parsed.path.startswith("/"):
            return target
    return url_for(default)


@auth_bp.route("/registrar/eleccion")
def register_choice():
    """Pantalla inicial: ¿Sos empresa o cliente?"""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("auth/register_choice.html")


@auth_bp.route("/registrar/empresa", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def register_empresa():
    """Registro de cuenta EMPRESA (crea User + Company)."""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = RegisterEmpresaForm(formdata=request.form if request.method == "POST" else None)
    if form.validate_on_submit():
        try:
            user = register_user_with_company(
                username=form.username.data,
                email=form.email.data,
                password=form.password.data,
                company_name=form.company_name.data,
                cuit=form.cuit.data,
                description=form.description.data or "",
            )
            db.session.commit()
            login_user(user)
            flash("¡Empresa creada! Bienvenido a tu panel.", "success")
            return redirect(_safe_redirect_target())
        except Exception as e:
            db.session.rollback()
            flash("Error al crear la cuenta. Intentá de nuevo.", "error")
    return render_template("auth/register_empresa.html", form=form)


@auth_bp.route("/registrar/cliente", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def register_cliente():
    """Registro de cuenta CLIENTE (solo User)."""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = RegisterClienteForm(formdata=request.form if request.method == "POST" else None)
    if form.validate_on_submit():
        try:
            user = User.create_user(
                username=form.username.data,
                email=form.email.data,
                password=form.password.data,
                account_type=AccountType.CLIENTE,
            )
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("¡Cuenta creada! Bienvenido.", "success")
            return redirect(_safe_redirect_target())
        except Exception:
            db.session.rollback()
            flash("Error al crear la cuenta. Intentá de nuevo.", "error")
    return render_template("auth/register_cliente.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    """Inicio de sesión con rate limiting."""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm(formdata=request.form if request.method == "POST" else None)
    if form.validate_on_submit():
        user = User.get_by_email(form.email.data)
        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash("Esta cuenta está desactivada.", "error")
                return render_template("auth/login.html", form=form)
            login_user(user, remember=form.remember.data)
            flash(f"¡Hola, {user.username}!", "success")
            return redirect(_safe_redirect_target())
        else:
            # Mensaje genérico para no revelar si el email existe
            flash("Credenciales inválidas.", "error")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """Cierre de sesión por POST + limpieza total de sesión."""
    from flask import session
    logout_user()
    session.clear()
    flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("auth.login"))