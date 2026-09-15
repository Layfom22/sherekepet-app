from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.models import Clinica
from app.clinic.models import Veterinario, Cliente, Mascota
from app.core.timezone import get_lima_now


def test_models_multi_tenant_and_relationships(db_session, test_clinica):
    """Verifica que los modelos operativos implementen clinica_id y sus relaciones."""
    # 1. Crear Veterinario asociado a la clínica
    vet = Veterinario(
        clinica_id=test_clinica.id,
        email="vet@sanfrancisco.pe",
        rol="veterinario"
    )
    db_session.add(vet)

    # 2. Crear Cliente asociado a la clínica
    cliente = Cliente(
        clinica_id=test_clinica.id,
        dni="72345678",
        telefono="987654321"
    )
    db_session.add(cliente)
    db_session.commit()
    db_session.refresh(cliente)

    # 3. Crear Mascota asociada a la clínica y al cliente
    mascota = Mascota(
        clinica_id=test_clinica.id,
        cliente_id=cliente.id,
        nombre="Firulais",
        especie="canino",
        raza="Labrador",
        peso=28.5
    )
    db_session.add(mascota)
    db_session.commit()

    # Validaciones
    assert vet.clinica_id == test_clinica.id
    assert cliente.clinica_id == test_clinica.id
    assert mascota.clinica_id == test_clinica.id
    assert mascota.cliente_id == cliente.id
    assert len(cliente.mascotas) == 1
    assert cliente.mascotas[0].nombre == "Firulais"


def test_timezone_america_lima():
    """Verifica que el helper de zona horaria retorne la hora en America/Lima (-05:00)."""
    now = get_lima_now()
    assert now.tzinfo is not None
    # America/Lima tiene un offset UTC de -05:00
    utc_offset = now.utcoffset().total_seconds()
    assert utc_offset == -5 * 3600


def test_soft_delete_functionality(db_session, test_clinica):
    """Verifica el comportamiento del mixin SoftDelete en todas las entidades."""
    cliente = Cliente(
        clinica_id=test_clinica.id,
        dni="12345678"
    )
    db_session.add(cliente)
    db_session.commit()
    db_session.refresh(cliente)

    assert cliente.is_deleted is False
    assert cliente.deleted_at is None

    # Ejecutar soft delete
    cliente.soft_delete()
    db_session.commit()
    db_session.refresh(cliente)

    assert cliente.is_deleted is True
    assert cliente.deleted_at is not None

    # Verificar que las consultas que filtran por is_deleted == False omiten el registro
    activos = db_session.query(Cliente).filter(
        Cliente.clinica_id == test_clinica.id,
        Cliente.is_deleted == False
    ).all()
    assert len(activos) == 0

    # Restaurar
    cliente.restore()
    db_session.commit()
    db_session.refresh(cliente)

    assert cliente.is_deleted is False
    assert cliente.deleted_at is None
