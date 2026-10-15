import pytest
from datetime import date, time, timedelta
from app.core.models import Clinica
from app.clinic.models import Cliente, Mascota, Cita, Veterinario, HorarioAtencion
from app.core.security import create_access_token, hash_password
from app.core.timezone import get_lima_now


def test_portal_dueno_reprogramar_cita_exitosamente(client, db_session):
    """El dueño de la mascota puede reprogramar su propia cita desde el portal."""
    clinica = Clinica(nombre="Vet Amigos", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    # Horarios de atención activos
    for d in range(7):
        h = HorarioAtencion(
            clinica_id=clinica.id,
            dia_semana=d,
            activo=True,
            hora_inicio_1=time(8, 0),
            hora_fin_1=time(18, 0),
            intervalo_minutos=30
        )
        db_session.add(h)
    db_session.flush()

    cliente = Cliente(
        clinica_id=clinica.id,
        dni="44556677",
        nombre_completo="Carlos Dueño",
        email="carlos@example.com"
    )
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        nombre="Firulais",
        especie="Canino"
    )
    db_session.add(mascota)
    db_session.flush()

    fecha_hoy = get_lima_now().date()
    fecha_futura = fecha_hoy + timedelta(days=2)
    fecha_reprogramada = fecha_hoy + timedelta(days=4)

    cita = Cita(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        mascota_id=mascota.id,
        fecha=fecha_futura,
        hora=time(10, 0),
        motivo="Vacunación Anual",
        estado="CONFIRMADA"
    )
    db_session.add(cita)
    db_session.commit()
    db_session.refresh(cita)

    # Autenticar al dueño
    token_cliente = create_access_token(data={"sub": str(cliente.id), "role": "client"})
    client.cookies.set("client_token", token_cliente)

    # Reprogramar cita
    payload = {
        "fecha": str(fecha_reprogramada),
        "hora": "11:30",
        "motivo": "Vacunación y corte de uñas"
    }
    resp = client.put(f"/api/portal/citas/{cita.id}", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    assert data["cita"]["fecha"] == str(fecha_reprogramada)
    assert data["cita"]["hora"] == "11:30"
    assert data["cita"]["motivo"] == "Vacunación y corte de uñas"

    # Verificar en la base de datos que se actualizó y pasó a PENDIENTE
    db_session.refresh(cita)
    assert cita.fecha == fecha_reprogramada
    assert cita.hora == time(11, 30)
    assert cita.motivo == "Vacunación y corte de uñas"
    assert cita.estado == "PENDIENTE"


def test_portal_dueno_cancelar_cita_exitosamente(client, db_session):
    """El dueño de la mascota puede cancelar su propia cita desde el portal."""
    clinica = Clinica(nombre="Vet Amigos 2", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    cliente = Cliente(
        clinica_id=clinica.id,
        dni="88776655",
        nombre_completo="Maria Propietaria",
        email="maria@example.com"
    )
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        nombre="Mishi",
        especie="Felino"
    )
    db_session.add(mascota)
    db_session.flush()

    fecha_hoy = get_lima_now().date()
    fecha_futura = fecha_hoy + timedelta(days=3)

    cita = Cita(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        mascota_id=mascota.id,
        fecha=fecha_futura,
        hora=time(14, 0),
        motivo="Chequeo general",
        estado="PENDIENTE"
    )
    db_session.add(cita)
    db_session.commit()
    db_session.refresh(cita)

    token_cliente = create_access_token(data={"sub": str(cliente.id), "role": "client"})
    client.cookies.set("client_token", token_cliente)

    # Cancelar cita vía POST
    resp = client.post(f"/api/portal/citas/{cita.id}/cancelar")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    assert "cancelada" in data["mensaje"].lower()

    # Verificar en la base de datos
    db_session.refresh(cita)
    assert cita.estado == "CANCELADA"
    assert cita.is_deleted is True


def test_portal_proteccion_idor_otro_dueno_no_puede_editar_o_cancelar(client, db_session):
    """Un dueño no puede editar o cancelar citas de otro dueño (BOLA/IDOR protection)."""
    clinica = Clinica(nombre="Vet IDOR Guard", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    cliente_a = Cliente(clinica_id=clinica.id, dni="11111111", nombre_completo="Cliente Legitimo")
    cliente_b = Cliente(clinica_id=clinica.id, dni="22222222", nombre_completo="Cliente Atacante")
    db_session.add_all([cliente_a, cliente_b])
    db_session.flush()

    mascota_a = Mascota(clinica_id=clinica.id, cliente_id=cliente_a.id, nombre="Perro A", especie="Canino")
    db_session.add(mascota_a)
    db_session.flush()

    fecha_futura = get_lima_now().date() + timedelta(days=2)
    cita_a = Cita(
        clinica_id=clinica.id,
        cliente_id=cliente_a.id,
        mascota_id=mascota_a.id,
        fecha=fecha_futura,
        hora=time(10, 0),
        motivo="Consulta",
        estado="CONFIRMADA"
    )
    db_session.add(cita_a)
    db_session.commit()

    # Loguearse como cliente B
    token_b = create_access_token(data={"sub": str(cliente_b.id), "role": "client"})
    client.cookies.set("client_token", token_b)

    # Intentar editar cita de A
    resp_put = client.put(f"/api/portal/citas/{cita_a.id}", json={"fecha": str(fecha_futura), "hora": "11:00", "motivo": "Hack"})
    assert resp_put.status_code == 404

    # Intentar cancelar cita de A
    resp_del = client.post(f"/api/portal/citas/{cita_a.id}/cancelar")
    assert resp_del.status_code == 404

    # Verificar que la cita de A sigue intacta
    db_session.refresh(cita_a)
    assert cita_a.estado == "CONFIRMADA"
    assert cita_a.is_deleted is False


def test_veterinario_agenda_y_cancela_cita_con_notificaciones(client, db_session):
    """
    Cuando el veterinario agenda una cita desde la clínica, queda disponible en /api/portal/citas/estado
    y al cancelarla se actualiza correctamente.
    """
    clinica = Clinica(nombre="Vet Notif Clinic", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    vet = Veterinario(
        clinica_id=clinica.id,
        email="vet@example.com",
        password_hash=hash_password("admin123"),
        nombre="Dr. House",
        rol="ADMIN",
        is_active=True,
        is_verified=True
    )
    db_session.add(vet)
    db_session.flush()

    cliente = Cliente(
        clinica_id=clinica.id,
        dni="99887766",
        nombre_completo="Juan Perez",
        telefono="999888777",
        email="juan@example.com"
    )
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        nombre="Rocky",
        especie="Canino"
    )
    db_session.add(mascota)
    db_session.commit()

    # 1. Login del veterinario
    token_vet = create_access_token(data={"sub": str(vet.id), "role": "veterinario", "clinica_id": clinica.id})
    client.cookies.set("vet_token", token_vet)

    # 2. Veterinario agenda cita para el cliente existente
    fecha_futura = get_lima_now().date() + timedelta(days=1)
    payload_vet = {
        "mascota_id": mascota.id,
        "fecha": str(fecha_futura),
        "hora": "15:00",
        "motivo": "Control Dermatológico",
        "estado": "CONFIRMADA",
        "enviar_email": True
    }
    resp_crear = client.post("/api/clinic/citas", json=payload_vet)
    assert resp_crear.status_code == 200, resp_crear.text
    cita_id = resp_crear.json()["cita_id"]

    # 3. Consultar desde el portal del cliente que la cita aparece inmediatamente
    token_cliente = create_access_token(data={"sub": str(cliente.id), "role": "client"})
    client.cookies.clear()
    client.cookies.set("client_token", token_cliente)

    resp_portal = client.get("/api/portal/citas/estado")
    assert resp_portal.status_code == 200
    citas_portal = resp_portal.json()["citas"]
    cita_en_portal = next((c for c in citas_portal if c["id"] == cita_id), None)
    assert cita_en_portal is not None
    assert cita_en_portal["mascota"] == "Rocky"
    assert cita_en_portal["motivo"] == "Control Dermatológico"
    assert cita_en_portal["estado"] == "CONFIRMADA"

    # 4. Veterinario cancela la cita
    client.cookies.clear()
    client.cookies.set("vet_token", token_vet)
    resp_cancel = client.put(f"/api/clinic/citas/{cita_id}/cancelar")
    assert resp_cancel.status_code == 200
    assert resp_cancel.json()["estado"] == "CANCELADA"
