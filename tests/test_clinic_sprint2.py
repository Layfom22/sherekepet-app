from datetime import date, timedelta
from unittest.mock import patch, AsyncMock
import pytest

from app.clinic.models import Cliente, Mascota, AtencionClinica, RegistroVacuna, SeguimientoNotificacion, Veterinario
from app.core.security import create_access_token
from app.clinic.services.whatsapp_service import normalizar_telefono_peru, generar_enlace_whatsapp


def test_whatsapp_service_normalization():
    """Verifica la normalización de números peruanos y la generación de enlaces wa.me."""
    assert normalizar_telefono_peru("987654321") == "51987654321"
    assert normalizar_telefono_peru("+51 987 654 321") == "51987654321"
    assert normalizar_telefono_peru("51987654321") == "51987654321"

    enlace = generar_enlace_whatsapp("987654321", "¡Hola! Tu mascota tiene cita.")
    assert "https://wa.me/51987654321?text=" in enlace
    assert "%C2%A1Hola%21" in enlace or "Hola" in enlace


def test_reniec_endpoint_mock(client):
    """Verifica el proxy de RENIEC mockeando el servicio para evitar consumo de cuota externa en tests."""
    mock_data = {
        "dni": "72345678",
        "nombres": "JUAN CARLOS",
        "apellido_paterno": "PEREZ",
        "apellido_materno": "GARCIA",
        "nombre_completo": "JUAN CARLOS PEREZ GARCIA"
    }

    with patch("app.clinic.routes.consultar_dni_reniec", new_callable=AsyncMock) as mock_reniec:
        mock_reniec.return_value = mock_data
        response = client.get("/api/reniec/dni/72345678")
        assert response.status_code == 200
        json_data = response.json()
        assert json_data["dni"] == "72345678"
        assert json_data["nombre_completo"] == "JUAN CARLOS PEREZ GARCIA"


def test_paciente_rapido_single_transaction(client, test_clinica, db_session):
    """Verifica el registro atómico de Dueño y Mascota (Registro Cero Fricción)."""
    payload = {
        "clinica_id": test_clinica.id,
        "dni": "70112233",
        "nombres": "CARLOS",
        "apellido_paterno": "QUISPE",
        "apellido_materno": "ROJAS",
        "nombre_completo": "CARLOS QUISPE ROJAS",
        "telefono": "987111222",
        "mascota_nombre": "Rocky",
        "mascota_especie": "Canino",
        "mascota_raza": "Bulldog Francés",
        "mascota_peso": 12.4,
        "mascota_alergias": "Pollo"
    }

    response = client.post("/api/clinic/paciente-rapido", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["cliente"]["dni"] == "70112233"
    assert data["cliente"]["nombre_completo"] == "CARLOS QUISPE ROJAS"
    assert data["mascota"]["nombre"] == "Rocky"
    assert data["mascota"]["peso"] == 12.4
    assert data["mascota"]["alergias"] == "Pollo"

    # Verificar en base de datos
    mascota_db = db_session.query(Mascota).filter(Mascota.nombre == "Rocky").first()
    assert mascota_db is not None
    assert mascota_db.cliente.dni == "70112233"
    assert mascota_db.cliente.pin_hash is None  # Debe ser None para que aplique flujo Sprint 1


def test_atencion_clinica_general(client, test_clinica, db_session):
    """Verifica el registro de una atención de tipo CONSULTA y actualización de peso."""
    cliente = Cliente(clinica_id=test_clinica.id, dni="11223344", nombre_completo="Ana Maria")
    db_session.add(cliente)
    db_session.commit()

    mascota = Mascota(
        clinica_id=test_clinica.id,
        cliente_id=cliente.id,
        nombre="Pelusa",
        especie="Felino",
        peso=3.5
    )
    db_session.add(mascota)
    db_session.commit()

    payload = {
        "clinica_id": test_clinica.id,
        "mascota_id": mascota.id,
        "tipo_atencion": "CONSULTA",
        "motivo": "Control estomacal",
        "diagnostico": "Gastroenteritis leve",
        "tratamiento": "Dieta blanda y probióticos",
        "peso_actual_kg": 3.8
    }

    response = client.post("/api/clinic/atenciones", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["tipo_atencion"] == "CONSULTA"
    assert data["vacuna_id"] is None
    assert data["seguimiento_id"] is None

    # Verificar actualización de peso en la mascota
    db_session.refresh(mascota)
    assert mascota.peso == 3.8


def test_atencion_vacunacion_automatic_tracking(client, test_clinica, db_session):
    """
    Verifica que si la atención es tipo 'VACUNACION', se crean automáticamente:
    1. El registro en sp_vacunas.
    2. La notificación en sp_seguimientos con la fecha del próximo refuerzo y mensaje personalizado.
    """
    cliente = Cliente(
        clinica_id=test_clinica.id,
        dni="88776655",
        nombre_completo="Roberto Gomez",
        telefono="944555666"
    )
    db_session.add(cliente)
    db_session.commit()

    mascota = Mascota(
        clinica_id=test_clinica.id,
        cliente_id=cliente.id,
        nombre="Max",
        especie="Canino",
        peso=15.0
    )
    db_session.add(mascota)
    db_session.commit()

    fecha_hoy = date.today()
    fecha_refuerzo = fecha_hoy + timedelta(days=21)

    payload = {
        "clinica_id": test_clinica.id,
        "mascota_id": mascota.id,
        "tipo_atencion": "VACUNACION",
        "motivo": "Primera dosis de Séxtuple",
        "tipo_vacuna": "Séxtuple Canina",
        "marca_lote": "Nobivac DHPPi Lote 982",
        "fecha_aplicacion": str(fecha_hoy),
        "fecha_proximo_refuerzo": str(fecha_refuerzo)
    }

    response = client.post("/api/clinic/atenciones", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["vacuna_id"] is not None
    assert data["seguimiento_id"] is not None

    # Validar Registro de Vacuna en DB
    vacuna = db_session.query(RegistroVacuna).filter(RegistroVacuna.id == data["vacuna_id"]).first()
    assert vacuna is not None
    assert vacuna.tipo_vacuna == "Séxtuple Canina"
    assert vacuna.fecha_proximo_refuerzo == fecha_refuerzo

    # Validar Seguimiento en DB
    seguimiento = db_session.query(SeguimientoNotificacion).filter(
        SeguimientoNotificacion.id == data["seguimiento_id"]
    ).first()
    assert seguimiento is not None
    assert seguimiento.tipo == "REFUERZO_VACUNA"
    assert seguimiento.fecha_programada == fecha_refuerzo
    assert seguimiento.estado == "PENDIENTE"
    assert "Roberto Gomez" in seguimiento.mensaje_plantilla
    assert "Séxtuple Canina" in seguimiento.mensaje_plantilla


def test_marcar_seguimiento_enviado(client, test_clinica, db_session):
    """Verifica cambiar el estado de seguimiento a ENVIADO."""
    cliente = Cliente(clinica_id=test_clinica.id, dni="99887766")
    db_session.add(cliente)
    db_session.commit()

    mascota = Mascota(clinica_id=test_clinica.id, cliente_id=cliente.id, nombre="Boby", especie="Canino")
    db_session.add(mascota)
    db_session.commit()

    seg = SeguimientoNotificacion(
        clinica_id=test_clinica.id,
        cliente_id=cliente.id,
        mascota_id=mascota.id,
        tipo="CONTROL_MEDICO",
        fecha_programada=date.today(),
        mensaje_plantilla="Control médico",
        estado="PENDIENTE"
    )
    db_session.add(seg)
    db_session.commit()

    resp = client.patch(f"/api/clinic/seguimientos/{seg.id}/marcar-enviado")
    assert resp.status_code == 200
    assert resp.json()["estado"] == "ENVIADO"

    db_session.refresh(seg)
    assert seg.estado == "ENVIADO"


def test_vistas_html_render(client, test_clinica, db_session):
    """Verifica que los endpoints HTML de Jinja2 rendericen correctamente con código 200."""
    vet = Veterinario(
        clinica_id=test_clinica.id,
        nombre="Dr. Sprint2",
        email="dr.sprint2@test.com",
        rol="ADMIN",
        is_verified=True,
        is_active=True
    )
    db_session.add(vet)
    db_session.commit()

    token = create_access_token({
        "sub": str(vet.id),
        "clinica_id": test_clinica.id,
        "role": "vet",
        "rol": "ADMIN",
        "email": vet.email
    })
    client.cookies.set("vet_token", token)

    cliente = Cliente(clinica_id=test_clinica.id, dni="12344321", nombre_completo="Maria Elena")
    db_session.add(cliente)
    db_session.commit()

    mascota = Mascota(
        clinica_id=test_clinica.id,
        cliente_id=cliente.id,
        nombre="Luna",
        especie="Felino"
    )
    db_session.add(mascota)
    db_session.commit()

    # 1. Dashboard
    resp_dashboard = client.get("/dashboard")
    assert resp_dashboard.status_code == 200
    assert "Panel del Veterinario" in resp_dashboard.text
    assert "WhatsApp 1-Clic" in resp_dashboard.text

    # 2. Formulario de nuevo paciente
    resp_form = client.get("/pacientes/nuevo")
    assert resp_form.status_code == 200
    assert "Registro Rápido de Paciente" in resp_form.text
    assert "RENIEC" in resp_form.text

    # 3. Ficha de la mascota
    resp_ficha = client.get(f"/pacientes/{mascota.id}")
    assert resp_ficha.status_code == 200
    assert "Luna" in resp_ficha.text
    assert "Carnet de Vacunas" in resp_ficha.text
    assert "Historial de Atenciones" in resp_ficha.text
