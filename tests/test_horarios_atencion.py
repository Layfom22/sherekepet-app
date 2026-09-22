import pytest
from datetime import date, time, timedelta
from app.core.models import Clinica
from app.clinic.models import Veterinario, Cliente, Mascota, Cita, HorarioAtencion
from app.core.security import create_access_token


def test_obtener_horarios_default(client, db_session):
    """
    Verifica que al consultar GET /api/clinic/horarios por primera vez,
    el sistema inicialice los 7 días de la semana con la plantilla por defecto.
    """
    clinica = Clinica(nombre="Vet Test Horarios", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    vet = Veterinario(
        clinica_id=clinica.id,
        nombre="Dr. Horarios",
        email="dr.horarios@test.com",
        rol="ADMIN",
        is_verified=True,
        is_active=True
    )
    db_session.add(vet)
    db_session.commit()

    token = create_access_token({
        "sub": str(vet.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "ADMIN",
        "email": vet.email
    })
    client.cookies.set("vet_token", token)

    resp = client.get("/api/clinic/horarios")
    assert resp.status_code == 200
    data = resp.json()

    assert data["intervalo_minutos"] == 30
    assert len(data["dias"]) == 7

    # Lunes (0) activo por defecto
    lunes = next(d for d in data["dias"] if d["dia_semana"] == 0)
    assert lunes["activo"] is True
    assert lunes["hora_inicio_1"] == "08:30"
    assert lunes["hora_fin_1"] == "13:00"
    assert lunes["hora_inicio_2"] == "14:00"
    assert lunes["hora_fin_2"] == "18:00"

    # Domingo (6) activo por defecto en la plantilla inicial hasta personalización
    domingo = next(d for d in data["dias"] if d["dia_semana"] == 6)
    assert domingo["activo"] is True


def test_actualizar_horarios_veterinario(client, db_session):
    """
    Verifica que el veterinario pueda actualizar sus días, turnos e intervalo de citas.
    """
    clinica = Clinica(nombre="Vet Update Horarios", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    vet = Veterinario(
        clinica_id=clinica.id,
        nombre="Dra. Update",
        email="dra.update@test.com",
        rol="ADMIN",
        is_verified=True,
        is_active=True
    )
    db_session.add(vet)
    db_session.commit()

    token = create_access_token({
        "sub": str(vet.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "ADMIN",
        "email": vet.email
    })
    client.cookies.set("vet_token", token)

    # Modificar para que Lunes sea continuo de 08:00 a 14:00 (sin turno tarde) y duración 20 min
    dias_payload = [
        {
            "dia_semana": 0,
            "activo": True,
            "hora_inicio_1": "08:00",
            "hora_fin_1": "14:00",
            "hora_inicio_2": None,
            "hora_fin_2": None,
            "intervalo_minutos": 20
        }
    ]
    for d in range(1, 7):
        dias_payload.append({
            "dia_semana": d,
            "activo": False,
            "hora_inicio_1": "09:00",
            "hora_fin_1": "13:00",
            "hora_inicio_2": None,
            "hora_fin_2": None,
            "intervalo_minutos": 20
        })

    resp = client.put("/api/clinic/horarios", json={
        "intervalo_minutos": 20,
        "dias": dias_payload
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["intervalo_minutos"] == 20

    lunes = next(d for d in data["dias"] if d["dia_semana"] == 0)
    assert lunes["hora_inicio_1"] == "08:00"
    assert lunes["hora_fin_1"] == "14:00"
    assert lunes["hora_inicio_2"] is None


def test_disponibilidad_respeta_receso_y_turnos(client, db_session):
    """
    Verifica que la disponibilidad en el portal NO ofrezca slots durante el refrigerio/almuerzo
    y genere slots dinámicos calculados con el intervalo configurado.
    """
    clinica = Clinica(nombre="Vet Receso Test", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    vet = Veterinario(
        clinica_id=clinica.id,
        nombre="Dr. Receso",
        email="dr.receso@test.com",
        rol="ADMIN",
        is_verified=True,
        is_active=True
    )
    db_session.add(vet)
    db_session.flush()

    # Configuramos Lunes: T1=09:00-13:00, T2=15:00-18:00 (Almuerzo 13:00 - 15:00)
    # y Domingo inactivo
    for d in range(7):
        h = HorarioAtencion(
            clinica_id=clinica.id,
            dia_semana=d,
            activo=(d != 6),  # Domingo inactivo
            hora_inicio_1=time(9, 0),
            hora_fin_1=time(13, 0),
            hora_inicio_2=time(15, 0) if d == 0 else None,
            hora_fin_2=time(18, 0) if d == 0 else None,
            intervalo_minutos=30
        )
        db_session.add(h)
    db_session.commit()

    # Próximo lunes
    hoy = date.today()
    dias_hasta_lunes = (0 - hoy.weekday()) % 7
    if dias_hasta_lunes <= 0:
        dias_hasta_lunes += 7
    proximo_lunes = hoy + timedelta(days=dias_hasta_lunes)

    resp = client.get(f"/api/portal/clinica/{clinica.id}/disponibilidad?fecha={proximo_lunes.isoformat()}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["hay_disponibilidad"] is True
    disponibles = data["horas_disponibles"]

    # Slots de la mañana deben estar presentes
    assert "09:00" in disponibles
    assert "09:30" in disponibles
    assert "12:00" in disponibles
    assert "12:30" in disponibles

    # A la 1:00 PM (13:00) y en la hora de almuerzo NO debe haber slots
    assert "13:00" not in disponibles
    assert "13:30" not in disponibles
    assert "14:00" not in disponibles
    assert "14:30" not in disponibles

    # Slots de la tarde deben estar presentes
    assert "15:00" in disponibles
    assert "15:30" in disponibles
    assert "17:00" in disponibles
    assert "17:30" in disponibles
    assert "18:00" not in disponibles  # 18:00 es hora fin


def test_disponibilidad_dia_no_laborable(client, db_session):
    """
    Verifica que en un día marcado como no laborable (ej. Domingo) no se ofrezcan horas disponibles.
    """
    clinica = Clinica(nombre="Vet Domingo Cerrado", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    for d in range(7):
        db_session.add(HorarioAtencion(
            clinica_id=clinica.id,
            dia_semana=d,
            activo=(d != 6),
            hora_inicio_1=time(9, 0),
            hora_fin_1=time(13, 0),
            intervalo_minutos=30
        ))
    db_session.commit()

    hoy = date.today()
    dias_hasta_domingo = (6 - hoy.weekday()) % 7
    if dias_hasta_domingo <= 0:
        dias_hasta_domingo += 7
    proximo_domingo = hoy + timedelta(days=dias_hasta_domingo)

    resp = client.get(f"/api/portal/clinica/{clinica.id}/disponibilidad?fecha={proximo_domingo.isoformat()}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["hay_disponibilidad"] is False
    assert len(data["horas_disponibles"]) == 0
    assert "no atiende" in data["mensaje"].lower()


def test_agendamiento_portal_valida_horarios_atencion(client, db_session):
    """
    Verifica que al agendar una cita desde el portal:
    - Se rechace si la hora cae en hora de almuerzo o fuera de turno (400 Bad Request).
    - Se acepte si cae dentro de los turnos válidos (201 Created).
    """
    clinica = Clinica(nombre="Vet Agendamiento Strict", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    # Horario: Lunes T1: 09:00 - 13:00, T2: 15:00 - 18:00
    for d in range(7):
        db_session.add(HorarioAtencion(
            clinica_id=clinica.id,
            dia_semana=d,
            activo=True,
            hora_inicio_1=time(9, 0),
            hora_fin_1=time(13, 0),
            hora_inicio_2=time(15, 0),
            hora_fin_2=time(18, 0),
            intervalo_minutos=30
        ))

    cliente = Cliente(clinica_id=clinica.id, dni="11223344", nombre_completo="Carlos Dueño")
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(clinica_id=clinica.id, cliente_id=cliente.id, nombre="Toby", especie="Canino")
    db_session.add(mascota)
    db_session.commit()

    token_cliente = create_access_token({
        "sub": str(cliente.id),
        "dni": cliente.dni,
        "clinica_id": clinica.id,
        "role": "client"
    })
    client.cookies.set("client_token", token_cliente)

    # Próximo lunes
    hoy = date.today()
    dias_hasta_lunes = (0 - hoy.weekday()) % 7
    if dias_hasta_lunes <= 0:
        dias_hasta_lunes += 7
    proximo_lunes = hoy + timedelta(days=dias_hasta_lunes)

    # 1. Intento de agendar a la 1:00 PM (13:00) -> DEBE RECHAZARSE (hora de refrigerio)
    resp_receso = client.post("/api/portal/citas", json={
        "clinica_id": clinica.id,
        "mascota_id": mascota.id,
        "fecha": proximo_lunes.isoformat(),
        "hora": "13:00",
        "motivo": "Consulta fuera de turno"
    })
    assert resp_receso.status_code == 400
    assert "turnos de atención" in resp_receso.json()["detail"].lower()

    # 2. Intento de agendar en turno válido (10:00 AM) -> DEBE ACEPTARSE
    resp_valido = client.post("/api/portal/citas", json={
        "clinica_id": clinica.id,
        "mascota_id": mascota.id,
        "fecha": proximo_lunes.isoformat(),
        "hora": "10:00",
        "motivo": "Consulta médica de rutina"
    })
    assert resp_valido.status_code == 201
    assert resp_valido.json()["cita"]["hora"] == "10:00"


def test_muro_contencion_horarios_cliente(client, db_session):
    """
    Verifica que un cliente no pueda modificar ni acceder a los endpoints administrativos de horarios.
    """
    clinica = Clinica(nombre="Vet Muro Horarios", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    cliente = Cliente(clinica_id=clinica.id, dni="99001122", nombre_completo="Cliente Invasor")
    db_session.add(cliente)
    db_session.commit()

    token_cliente = create_access_token({
        "sub": str(cliente.id),
        "dni": cliente.dni,
        "clinica_id": clinica.id,
        "role": "client"
    })
    client.cookies.set("client_token", token_cliente)

    resp_get = client.get("/api/clinic/horarios")
    assert resp_get.status_code == 403

    resp_put = client.put("/api/clinic/horarios", json={"intervalo_minutos": 30, "dias": []})
    assert resp_put.status_code == 403
