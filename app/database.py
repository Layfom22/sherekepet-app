from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.engine import Engine

from app.core.config import settings
from app.core.models import Base, Clinica
from app.clinic.models import (
    Especie,
    Raza,
    Veterinario,
    Cliente,
    Mascota,
    AtencionClinica,
    RegistroVacuna,
    SeguimientoNotificacion,
    Cita,
    HorarioAtencion,
    Producto,
    ServicioBano
)
from app.follow_up.models import (
    MedicationPlan,
    DoseTracking,
    WebPushSubscription
)

# Configuración del Engine de Base de Datos
database_url = settings.DATABASE_URL
# Normalizar prefijo de Render 'postgres://' a 'postgresql://' compatible con SQLAlchemy
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

connect_args = {}
if database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    database_url,
    connect_args=connect_args,
    pool_pre_ping=True
)

# Activar claves foráneas en SQLite
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if database_url.startswith("sqlite"):
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


def run_auto_migrations(target_engine) -> None:
    """
    Verifica y agrega columnas faltantes en tablas existentes sin romper la base de datos.
    Indispensable para entornos de producción como Render (PostgreSQL) donde create_all()
    no modifica tablas ya existentes.
    """
    from sqlalchemy import text, inspect
    try:
        inspector = inspect(target_engine)
        tables = inspector.get_table_names()

        # 1. sp_clinicas
        if "sp_clinicas" in tables:
            cols = {c["name"] for c in inspector.get_columns("sp_clinicas")}
            with target_engine.begin() as conn:
                if "logo_url" not in cols:
                    conn.execute(text("ALTER TABLE sp_clinicas ADD COLUMN logo_url VARCHAR(500);"))
                if "logo_b64" not in cols:
                    conn.execute(text("ALTER TABLE sp_clinicas ADD COLUMN logo_b64 TEXT;"))
                if "nombre_comercial" not in cols:
                    conn.execute(text("ALTER TABLE sp_clinicas ADD COLUMN nombre_comercial VARCHAR(150);"))
                if "telefono" not in cols:
                    conn.execute(text("ALTER TABLE sp_clinicas ADD COLUMN telefono VARCHAR(50);"))

        # Crear sp_citas si no existe
        if "sp_citas" not in tables:
            Base.metadata.create_all(target_engine, tables=[Cita.__table__])

        # Crear sp_horarios_atencion si no existe
        if "sp_horarios_atencion" not in tables:
            Base.metadata.create_all(target_engine, tables=[HorarioAtencion.__table__])

        # Crear sp_productos si no existe
        if "sp_productos" not in tables:
            Base.metadata.create_all(target_engine, tables=[Producto.__table__])

        # Crear sp_servicios_bano si no existe
        if "sp_servicios_bano" not in tables:
            Base.metadata.create_all(target_engine, tables=[ServicioBano.__table__])

        # 2. sp_mascotas
        if "sp_mascotas" in tables:
            cols = {c["name"] for c in inspector.get_columns("sp_mascotas")}
            with target_engine.begin() as conn:
                if "foto_url" not in cols:
                    conn.execute(text("ALTER TABLE sp_mascotas ADD COLUMN foto_url VARCHAR(500);"))
                if "especie_id" not in cols:
                    conn.execute(text("ALTER TABLE sp_mascotas ADD COLUMN especie_id INTEGER;"))
                if "raza_id" not in cols:
                    conn.execute(text("ALTER TABLE sp_mascotas ADD COLUMN raza_id INTEGER;"))
                if "tiene_alergias" not in cols:
                    conn.execute(text("ALTER TABLE sp_mascotas ADD COLUMN tiene_alergias BOOLEAN DEFAULT FALSE;"))
                if "detalle_alergias" not in cols:
                    conn.execute(text("ALTER TABLE sp_mascotas ADD COLUMN detalle_alergias VARCHAR(255);"))
                if "condiciones_previas" not in cols:
                    conn.execute(text("ALTER TABLE sp_mascotas ADD COLUMN condiciones_previas TEXT;"))
                if "fecha_nacimiento" not in cols:
                    conn.execute(text("ALTER TABLE sp_mascotas ADD COLUMN fecha_nacimiento DATE;"))
                if "sexo" not in cols:
                    conn.execute(text("ALTER TABLE sp_mascotas ADD COLUMN sexo VARCHAR(20);"))
                if "rasgos_distintivos" not in cols:
                    conn.execute(text("ALTER TABLE sp_mascotas ADD COLUMN rasgos_distintivos VARCHAR(255);"))
                if "microchip" not in cols:
                    conn.execute(text("ALTER TABLE sp_mascotas ADD COLUMN microchip VARCHAR(50);"))

        # 3. sp_vacunas
        if "sp_vacunas" in tables:
            cols = {c["name"] for c in inspector.get_columns("sp_vacunas")}
            with target_engine.begin() as conn:
                if "enfermedades_cubiertas" not in cols:
                    conn.execute(text("ALTER TABLE sp_vacunas ADD COLUMN enfermedades_cubiertas TEXT;"))

        # 4. sp_veterinarios
        if "sp_veterinarios" in tables:
            cols = {c["name"] for c in inspector.get_columns("sp_veterinarios")}
            with target_engine.begin() as conn:
                if "password_hash" not in cols:
                    conn.execute(text("ALTER TABLE sp_veterinarios ADD COLUMN password_hash VARCHAR(255);"))
                if "nombre" not in cols:
                    conn.execute(text("ALTER TABLE sp_veterinarios ADD COLUMN nombre VARCHAR(255);"))
                if "google_id" not in cols:
                    conn.execute(text("ALTER TABLE sp_veterinarios ADD COLUMN google_id VARCHAR(255);"))
                if "username" not in cols:
                    conn.execute(text("ALTER TABLE sp_veterinarios ADD COLUMN username VARCHAR(100);"))
                if "is_verified" not in cols:
                    conn.execute(text("ALTER TABLE sp_veterinarios ADD COLUMN is_verified BOOLEAN DEFAULT FALSE;"))
                if "otp_code" not in cols:
                    conn.execute(text("ALTER TABLE sp_veterinarios ADD COLUMN otp_code VARCHAR(10);"))
                if "otp_expires_at" not in cols:
                    conn.execute(text("ALTER TABLE sp_veterinarios ADD COLUMN otp_expires_at TIMESTAMP WITH TIME ZONE;"))
                if "foto_perfil" not in cols:
                    conn.execute(text("ALTER TABLE sp_veterinarios ADD COLUMN foto_perfil VARCHAR(500);"))

        # Ampliar a TEXT en motores que lo soportan (PostgreSQL) para evitar truncamientos
        if not target_engine.url.drivername.startswith("sqlite"):
            with target_engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE sp_clinicas ALTER COLUMN logo_url TYPE TEXT;"))
                    conn.execute(text("ALTER TABLE sp_mascotas ALTER COLUMN foto_url TYPE TEXT;"))
                    conn.execute(text("ALTER TABLE sp_veterinarios ALTER COLUMN email DROP NOT NULL;"))
                except Exception:
                    pass

    except Exception as e:
        print(f"[WARN] Error durante auto-migraciones: {e}")


def init_db() -> None:
    """
    Inicialización segura de la base de datos.
    Crea las tablas asegurando sentencias 'IF NOT EXISTS' para evitar bloqueos
    e inconsistencias en ejecuciones concurrentes o reinicios de la aplicación.
    """
    # 1. Crear tablas nuevas si no existen
    Base.metadata.create_all(bind=engine, checkfirst=True)

    # 2. Auto-migrar columnas faltantes en tablas existentes (ej. en Render PostgreSQL)
    run_auto_migrations(engine)

    # 3. Inicializar datos de catálogos si no existen
    from seed_catalogos import seed_catalogos
    db = SessionLocal()
    try:
        seed_catalogos(db)
    except Exception as e:
        db.rollback()
    finally:
        db.close()
