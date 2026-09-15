from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.core.timezone import LIMA_TZ
from app.clinic.models import Cliente, Mascota
from app.follow_up.models import MedicationPlan, DoseTracking
from app.follow_up.services import ajustar_ventana_sueno, confirmar_toma, crear_plan_medicacion


def test_ajustar_ventana_sueno_nocturno():
    """
    Verifica la regla de ventana de sueño:
    - Si cae a las 23:xx -> 07:00 AM del día siguiente.
    - Si cae entre 00:00 y 06:59 -> 07:00 AM del mismo día.
    - Si cae de día (ej: 14:00) -> no se modifica.
    """
    # 1. Caso 23:30
    hora_23 = datetime(2026, 9, 15, 23, 30, tzinfo=LIMA_TZ)
    ajustada_23 = ajustar_ventana_sueno(hora_23)
    assert ajustada_23.day == 16
    assert ajustada_23.hour == 7
    assert ajustada_23.minute == 0

    # 2. Caso 04:15 de la madrugada
    hora_04 = datetime(2026, 9, 15, 4, 15, tzinfo=LIMA_TZ)
    ajustada_04 = ajustar_ventana_sueno(hora_04)
    assert ajustada_04.day == 15
    assert ajustada_04.hour == 7
    assert ajustada_04.minute == 0

    # 3. Caso 14:00 (hora diurna)
    hora_dia = datetime(2026, 9, 15, 14, 0, tzinfo=LIMA_TZ)
    ajustada_dia = ajustar_ventana_sueno(hora_dia)
    assert ajustada_dia.day == 15
    assert ajustada_dia.hour == 14
    assert ajustada_dia.minute == 0


def test_api_crear_plan_medicacion(client, test_clinica, db_session):
    """Verifica que el endpoint cree el plan y la primera dosis automáticamente."""
    cliente = Cliente(clinica_id=test_clinica.id, dni="12345678", nombre_completo="Luis")
    db_session.add(cliente)
    db_session.commit()

    mascota = Mascota(clinica_id=test_clinica.id, cliente_id=cliente.id, nombre="Toby", especie="Canino")
    db_session.add(mascota)
    db_session.commit()

    payload = {
        "pet_id": mascota.id,
        "clinic_id": test_clinica.id,
        "medicamento": "Amoxicilina 250mg",
        "frecuencia_horas": 8,
        "total_dosis": 6,
        "es_estricto": False
    }

    response = client.post("/api/medication/plan", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["medicamento"] == "Amoxicilina 250mg"
    assert data["estado"] == "ACTIVO"
    assert data["primera_dosis"] is not None
    assert data["primera_dosis"]["numero_dosis"] == 1
    assert data["primera_dosis"]["estado"] == "PENDIENTE"


def test_confirmar_toma_y_ventana_sueno(client, test_clinica, db_session):
    """
    Verifica que al confirmar una toma:
    - La dosis pasa a CONSUMIDO con hora_consumo_real.
    - Se programa la siguiente dosis con validación de ventana de sueño.
    """
    cliente = Cliente(clinica_id=test_clinica.id, dni="87654321", nombre_completo="Rosa")
    db_session.add(cliente)
    db_session.commit()

    mascota = Mascota(clinica_id=test_clinica.id, cliente_id=cliente.id, nombre="Milo", especie="Felino")
    db_session.add(mascota)
    db_session.commit()

    # Plan NO estricto: cada 8 horas
    plan, dosis1 = crear_plan_medicacion(
        db=db_session,
        pet_id=mascota.id,
        clinic_id=test_clinica.id,
        medicamento="Prednisona 5mg",
        frecuencia_horas=8,
        total_dosis=3,
        es_estricto=False
    )

    # Simular toma a las 15:30 (la siguiente cada 8h caería a las 23:30 en ventana de sueño)
    hora_toma = datetime(2026, 9, 15, 15, 30, tzinfo=LIMA_TZ)

    resp = client.post(
        f"/api/medication/dose/{dosis1.id}/confirm",
        json={"hora_real": hora_toma.isoformat()}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dosis_confirmada_id"] == dosis1.id
    assert data["plan_completado"] is False
    assert data["siguiente_dosis"] is not None
    assert data["siguiente_dosis"]["numero_dosis"] == 2

    # Verificar que la siguiente dosis se ajustó a las 07:00 AM del día 16 por ventana de sueño
    siguiente_hora = datetime.fromisoformat(data["siguiente_dosis"]["hora_programada"])
    assert siguiente_hora.hour == 7
    assert siguiente_hora.day == 16


def test_plan_estricto_sin_ajuste_sueno(client, test_clinica, db_session):
    """
    Verifica que un plan estricto (es_estricto=True) NO ajuste la hora nocturna.
    """
    cliente = Cliente(clinica_id=test_clinica.id, dni="11224466")
    db_session.add(cliente)
    db_session.commit()

    mascota = Mascota(clinica_id=test_clinica.id, cliente_id=cliente.id, nombre="Rex", especie="Canino")
    db_session.add(mascota)
    db_session.commit()

    # Plan ESTRICTO
    plan, dosis1 = crear_plan_medicacion(
        db=db_session,
        pet_id=mascota.id,
        clinic_id=test_clinica.id,
        medicamento="Antiepiléptico Fenobarbital",
        frecuencia_horas=8,
        total_dosis=5,
        es_estricto=True
    )

    hora_toma = datetime(2026, 9, 15, 15, 30, tzinfo=LIMA_TZ)
    resp = client.post(
        f"/api/medication/dose/{dosis1.id}/confirm",
        json={"hora_real": hora_toma.isoformat()}
    )
    assert resp.status_code == 200
    data = resp.json()

    # Debe conservarse exacta a las 23:30 porque es estricto
    siguiente_hora = datetime.fromisoformat(data["siguiente_dosis"]["hora_programada"])
    assert siguiente_hora.hour == 23
    assert siguiente_hora.minute == 30


def test_completar_ultima_dosis(client, test_clinica, db_session):
    """Verifica que al confirmar la última dosis el plan pase a COMPLETADO."""
    cliente = Cliente(clinica_id=test_clinica.id, dni="55443322")
    db_session.add(cliente)
    db_session.commit()

    mascota = Mascota(clinica_id=test_clinica.id, cliente_id=cliente.id, nombre="Lassie", especie="Canino")
    db_session.add(mascota)
    db_session.commit()

    # Plan de solo 1 dosis
    plan, dosis1 = crear_plan_medicacion(
        db=db_session,
        pet_id=mascota.id,
        clinic_id=test_clinica.id,
        medicamento="Antiparasitario Único",
        frecuencia_horas=24,
        total_dosis=1,
        es_estricto=False
    )

    resp = client.post(f"/api/medication/dose/{dosis1.id}/confirm", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan_completado"] is True
    assert data["siguiente_dosis"] is None

    db_session.refresh(plan)
    assert plan.estado == "COMPLETADO"


def test_pwa_statics(client):
    """Verifica la disponibilidad de manifest.json y service-worker.js."""
    resp_manifest = client.get("/manifest.json")
    assert resp_manifest.status_code == 200
    assert "SherekePet" in resp_manifest.json()["name"]

    resp_sw = client.get("/service-worker.js")
    assert resp_sw.status_code == 200
    assert "addEventListener" in resp_sw.text


def test_portal_vistas_moviles(client, test_clinica, db_session):
    """Verifica el renderizado de las vistas HTML del portal de clientes."""
    cliente = Cliente(clinica_id=test_clinica.id, dni="99001122", nombre_completo="Fernando")
    db_session.add(cliente)
    db_session.commit()

    mascota = Mascota(clinica_id=test_clinica.id, cliente_id=cliente.id, nombre="Chispita", especie="Canino")
    db_session.add(mascota)
    db_session.commit()

    # 1. Vista Login
    resp_login = client.get("/portal/login")
    assert resp_login.status_code == 200
    assert "Portal de Dueños" in resp_login.text

    # 2. Vista Dashboard
    resp_dash = client.get("/portal/dashboard")
    assert resp_dash.status_code == 200
    assert "Portal del Dueño" in resp_dash.text
    assert "Chispita" in resp_dash.text

    # 3. Vista Carnet
    resp_carnet = client.get(f"/portal/carnet/{mascota.id}")
    assert resp_carnet.status_code == 200
    assert "Chispita" in resp_carnet.text
    assert "Carnet Digital Móvil" in resp_carnet.text
    assert "Tratamientos Activos" in resp_carnet.text
