from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.config import settings

LIMA_TZ = ZoneInfo(settings.DEFAULT_TIMEZONE)


def get_lima_now() -> datetime:
    """Retorna la fecha y hora actual en la zona horaria 'America/Lima'."""
    return datetime.now(LIMA_TZ)
