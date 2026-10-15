"""
Blueprint principal - B2B_B2C.

Rutas: / (inicio), /dashboard, /tema (POST para sincronizar tema)
"""

from flask import Blueprint, render_template, request, jsonify, session
from flask_login import login_required, current_user

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Landing page pública."""
    return render_template("index.html")


@main_bp.route("/dashboard")
@login_required
def dashboard():
    """Panel principal según tipo de cuenta."""
    from app.services.reports import get_dashboard_metrics
    metrics = get_dashboard_metrics(current_user)

    # Últimos pedidos para mostrar en dashboard
    from app.models.order import Order, OrderStatus
    if current_user.is_empresa and current_user.company:
        recent_orders = Order.query.filter_by(
            company_id=current_user.company.id
        ).order_by(Order.created_at.desc()).limit(5).all()
    else:
        recent_orders = Order.query.filter_by(
            buyer_id=current_user.id
        ).order_by(Order.created_at.desc()).limit(5).all()

    if current_user.is_empresa:
        return render_template("dashboard_empresa.html", metrics=metrics, recent_orders=recent_orders)
    return render_template("dashboard_cliente.html", metrics=metrics, recent_orders=recent_orders)


@main_bp.route("/tema", methods=["POST"])
def set_theme():
    """Endpoint para sincronizar preferencia de tema en sesión (SSR opcional)."""
    data = request.get_json(silent=True) or {}
    theme = data.get("theme")
    if theme in ("light", "dark"):
        session["theme"] = theme
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 400


@main_bp.route("/health")
def health():
    """Health check para load balancers / monitoreo."""
    return jsonify({"status": "ok", "service": "b2b_b2c"})