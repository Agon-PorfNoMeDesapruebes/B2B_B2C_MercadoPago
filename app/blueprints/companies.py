"""
Blueprint de empresas - B2B_B2C.

Rutas: /empresas (listado), /empresas/<id> (apartado público),
       /mi-empresa (panel del dueño)
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models.company import Company
from app.models.product import Product
from app.forms.company import CompanyEditForm, ProductForm

companies_bp = Blueprint("companies", __name__, url_prefix="/empresas")


@companies_bp.route("/")
def list_companies():
    """Listado público de empresas (tarjetas con preview de productos)."""
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "").strip()

    query = Company.query.order_by(Company.created_at.desc())
    if q:
        query = query.filter(Company.name.ilike(f"%{q}%"))

    pagination = query.paginate(page=page, per_page=12, error_out=False)

    # Para cada empresa, traer 4 productos activos para preview
    companies_with_preview = []
    for company in pagination.items:
        preview_products = Product.query.filter_by(
            company_id=company.id, is_active=True
        ).limit(4).all()
        companies_with_preview.append({
            "company": company,
            "preview_products": preview_products,
        })

    return render_template(
        "companies/list.html",
        companies_data=companies_with_preview,
        pagination=pagination,
        search_query=q,
    )


@companies_bp.route("/<int:company_id>")
def view_company(company_id):
    """Apartado de empresa - vista pública con grilla de productos paginada."""
    company = db.session.get(Company, company_id)
    if not company:
        abort(404)

    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "").strip()

    products_query = Product.query.filter_by(company_id=company.id, is_active=True)
    if q:
        products_query = products_query.filter(
            db.or_(Product.name.ilike(f"%{q}%"), Product.description.ilike(f"%{q}%"))
        )
    products_query = products_query.order_by(Product.created_at.desc())

    pagination = products_query.paginate(page=page, per_page=12, error_out=False)

    # Flag para template: ¿es el dueño?
    es_dueno = current_user.is_authenticated and current_user.is_empresa and current_user.company and current_user.company.id == company.id

    return render_template(
        "companies/view.html",
        company=company,
        products=pagination,
        search_query=q,
        es_dueno=es_dueno,
    )


@companies_bp.route("/mi-empresa", methods=["GET", "POST"])
@login_required
def my_company():
    """Panel 'Mi empresa' - solo para dueño. Edita datos de empresa + CRUD productos."""
    if not current_user.is_empresa or not current_user.company:
        abort(403)

    company = current_user.company
    form = CompanyEditForm(obj=company, current_company=company)

    if form.validate_on_submit():
        form.populate_obj(company)
        db.session.commit()
        flash("Datos de la empresa actualizados.", "success")
        return redirect(url_for("companies.my_company"))

    # CRUD productos se maneja en templates con forms separados (AJAX o POST clásico)
    # Aquí solo pasamos el form de empresa y la paginación de productos
    page = request.args.get("page", 1, type=int)
    products_pagination = Product.query.filter_by(company_id=company.id).order_by(
        Product.created_at.desc()
    ).paginate(page=page, per_page=10, error_out=False)

    return render_template(
        "companies/my_company.html",
        company=company,
        form=form,
        products=products_pagination,
    )


# --- CRUD Productos (dueño only) ---

@companies_bp.route("/mi-empresa/productos/nuevo", methods=["GET", "POST"])
@login_required
def new_product():
    if not current_user.is_empresa or not current_user.company:
        abort(403)

    form = ProductForm()
    if form.validate_on_submit():
        from decimal import Decimal
        product = Product(
            company_id=current_user.company.id,
            name=form.name.data.strip(),
            description=form.description.data.strip() if form.description.data else "",
            price=Decimal(str(form.price.data)),
            stock=form.stock.data,
            image_url=form.image_url.data.strip() if form.image_url.data else "",
            is_active=True,
        )
        db.session.add(product)
        db.session.commit()
        flash("Producto creado.", "success")
        return redirect(url_for("companies.my_company"))
    return render_template("companies/product_form.html", form=form, action="nuevo")


@companies_bp.route("/mi-empresa/productos/<int:product_id>/editar", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    if not current_user.is_empresa or not current_user.company:
        abort(403)

    product = db.session.get(Product, product_id)
    if not product or product.company_id != current_user.company.id:
        abort(404)

    form = ProductForm(obj=product)
    # Set expected stock for atomic update
    form.expected_stock.data = str(product.stock)
    
    if form.validate_on_submit():
        from decimal import Decimal
        
        # Atomic stock update: stock = stock + (new - expected)
        expected_stock = int(form.expected_stock.data)
        new_stock = form.stock.data
        delta = new_stock - expected_stock
        
        if delta != 0:
            # Atomic update: stock = stock + delta WHERE stock >= 0
            result = db.session.execute(
                db.text(
                    "UPDATE products SET stock = stock + :delta "
                    "WHERE id = :pid AND stock + :delta >= 0 AND is_active = 1"
                ),
                {"delta": delta, "pid": product.id},
            )
            if result.rowcount == 0:
                flash("Stock insuficiente para la operación.", "error")
                return render_template("companies/product_form.html", form=form, action="editar", product=product)
            db.session.flush()  # Refresh product stock
        
        product.name = form.name.data.strip()
        product.description = form.description.data.strip() if form.description.data else ""
        product.price = Decimal(str(form.price.data))
        product.stock = form.stock.data
        product.image_url = form.image_url.data.strip() if form.image_url.data else ""
        db.session.commit()
        flash("Producto actualizado.", "success")
        return redirect(url_for("companies.my_company"))
    return render_template("companies/product_form.html", form=form, action="editar", product=product)


@companies_bp.route("/mi-empresa/productos/<int:product_id>/toggle", methods=["POST"])
@login_required
def toggle_product(product_id):
    """Activar/desactivar (borrado lógico)."""
    if not current_user.is_empresa or not current_user.company:
        abort(403)

    product = db.session.get(Product, product_id)
    if not product or product.company_id != current_user.company.id:
        abort(404)

    product.is_active = not product.is_active
    db.session.commit()
    flash(f"Producto {'activado' if product.is_active else 'desactivado'}.", "success")
    return redirect(url_for("companies.my_company"))