"""
Tipos de datos personalizados - B2B_B2C.

Incluye UTCDateTime: TypeDecorator que garantiza datetimes timezone-aware en UTC.
"""

from datetime import datetime, timezone
from sqlalchemy import DateTime, TypeDecorator


class UTCDateTime(TypeDecorator):
    """
    TypeDecorator para datetime con timezone UTC.

    - Guarda en UTC (naive en BD, pero representando UTC)
    - Devuelve siempre datetime aware con tzinfo=UTC
    - Compatible con SQLite, PostgreSQL, MySQL
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Convierte a naive UTC antes de guardar."""
        if value is None:
            return None
        if value.tzinfo is None:
            # Asumimos que naive = UTC
            return value
        # Convertir a UTC y quitar tzinfo
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        """Convierte a aware UTC al leer."""
        if value is None:
            return None
        if value.tzinfo is None:
            # Asumimos que naive en BD = UTC
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)