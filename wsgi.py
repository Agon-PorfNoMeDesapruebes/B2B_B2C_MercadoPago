"""
Entry point WSGI para producción (gunicorn, uwsgi, etc.).

Uso:
    gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app
"""

import os
from app import create_app

config_name = os.environ.get("FLASK_ENV", "production")
app = create_app(config_name)

if __name__ == "__main__":
    # Solo para desarrollo directo: python wsgi.py
    app.run(host="0.0.0.0", port=5000, debug=True)