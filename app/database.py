from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.engine import Engine

from app.core.config import settings
from app.core.models import Base, Clinica
from app.clinic.models import Veterinario, Cliente, Mascota

# Configuración del Engine de Base de Datos
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True
)

# Activar claves foráneas en SQLite
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if settings.DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_db() -> Generator[Session, None, None]:
    """Dependency para inyección de sesiones SQLAlchemy con manejo seguro."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Inicialización segura de la base de datos.
    Crea las tablas asegurando sentencias 'IF NOT EXISTS' para evitar bloqueos
    e inconsistencias en ejecuciones concurrentes o reinicios de la aplicación.
    """
    # Base.metadata.create_all ejecuta DDL con validación previa de existencia (checkfirst=True)
    # y sentencias seguras compatibles con SQLite y PostgreSQL.
    Base.metadata.create_all(bind=engine, checkfirst=True)
