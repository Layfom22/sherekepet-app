import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.core.models import Base, Clinica
from app.clinic.models import Veterinario, Cliente, Mascota
from app.database import get_db
from app.main import app

# Configuración de base de datos en memoria para pruebas
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Crea un esquema fresco y una sesión para cada test."""
    Base.metadata.create_all(bind=engine, checkfirst=True)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Cliente de prueba de FastAPI con sobreescritura de get_db."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def test_clinica(db_session):
    """Fixture de una clínica activa para tests multi-tenant."""
    clinica = Clinica(
        nombre="Veterinaria San Francisco",
        zona_horaria="America/Lima",
        plan_activo="solo"
    )
    db_session.add(clinica)
    db_session.commit()
    db_session.refresh(clinica)
    return clinica
