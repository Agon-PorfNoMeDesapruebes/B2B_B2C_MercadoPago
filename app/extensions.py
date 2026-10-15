"""
Extensiones Flask centralizadas.

Inicializa todas las extensiones fuera de la factory para evitar imports circulares.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


# SQLAlchemy 2.x
db = SQLAlchemy()

# Flask-Login
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Por favor, iniciá sesión para acceder a esta página."
login_manager.login_message_category = "warning"

# Flask-WTF CSRF
csrf = CSRFProtect()

# Flask-Migrate (Alembic)
migrate = Migrate()

# Flask-Limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute"],
    storage_uri="memory://",
    strategy="fixed-window",
)