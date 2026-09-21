import pytest
from datetime import date, time, datetime, timedelta
from app.core.models import Clinica
from app.clinic.models import Veterinario, Cliente, Mascota, Cita
from app.core.security import create_access_token, hash_pin


def test_dni_reutilizacion_global_paciente_rapido(client, db_session):
    """
    1. Unificación Global (DNI):
    Si se registra un paciente con un DNI existente, el sistema DEBE reutilizar ese cliente_id
    y no crear registros duplicados de cliente.
    """
    clinica1 = Clinica(nombre="Veterinaria Norte", zona_horaria="America/Lima", plan_activo="solo")
    clinica2 = Clinica(nombre="Veterinaria Sur", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add_all([clinica1, clinica2])
    db_session.flush()

    # Registro en Clínica 1
    payload1 = {
        "clinica_id": clinica1.id,
        "dni": "44556677",
        "nombre_completo": "Juan Pérez",
        "telefono": "987654321",
        "mascota_nombre": "Firulais",
        "mascota_especie": "Canino",
        "mascota_raza": "Mestizo",
        "foto_url": "https://r2.sherekepet.com/firulais.webp"
    }
    resp1 = client.post("/api/clinic/pacientes", json=payload1)
    assert resp1.status_code == 201
    data1 = resp1.json()
    cliente_id_1 = data1["cliente"]["id"]
    assert data1["mascota"]["foto_url"] == "https://r2.sherekepet.com/firulais.webp"

    # Registro en Clínica 2 con el MISMO DNI
    payload2 = {
        "clinica_id": clinica2.id,
        "dni": "44556677",
        "nombre_completo": "Juan Carlos Pérez",  # Actualiza o mantiene
        "telefono": "999888777",
        "mascota_nombre": "Michi",
        "mascota_especie": "Felino",
        "mascota_raza": "Siamés"
    }
    resp2 = client.post("/api/clinic/pacientes", json=payload2)
    assert resp2.status_code == 201
    data2 = resp2.json()
    cliente_id_2 = data2["cliente"]["id"]

    # DEBE ser el mismo cliente_id
    assert cliente_id_1 == cliente_id_2

    # Verificar que en base de datos solo existe UN cliente con ese DNI
    clientes_dni = db_session.query(Cliente).filter(Cliente.dni == "44556677").all()
    assert len(clientes_dni) == 1
    assert len(clientes_dni[0].mascotas) == 2


def test_portal_dashboard_filtra_por_dni(client, db_session):
    """
    En /portal/dashboard, se listan todas las mascotas asociadas al DNI del cliente logueado,
    incluso si fueron atendidas en diferentes clínicas.
    """
    clinica1 = Clinica(nombre="Vet 1", zona_horaria="America/Lima", plan_activo="solo")
    clinica2 = Clinica(nombre="Vet 2", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add_all([clinica1, clinica2])
    db_session.flush()

    cliente = Cliente(
        clinica_id=clinica1.id,
        dni="88776655",
        nombre_completo="María Rodriguez",
        pin_hash=hash_pin("1234"),
        telefono="912345678"
    )
    db_session.add(cliente)
    db_session.flush()

    mascota1 = Mascota(clinica_id=clinica1.id, cliente_id=cliente.id, nombre="Luna", especie="Canino")
    mascota2 = Mascota(clinica_id=clinica2.id, cliente_id=cliente.id, nombre="Sol", especie="Felino")
    db_session.add_all([mascota1, mascota2])
    db_session.commit()

    # Sin cookie -> Redirige a /portal/login (nunca filtra datos de otro cliente)
    resp_unauth = client.get("/portal/dashboard", follow_redirects=False)
    assert resp_unauth.status_code == 303
    assert resp_unauth.headers["location"] == "/portal/login"

    token = create_access_token({
        "sub": str(cliente.id),
        "dni": cliente.dni,
        "clinica_id": clinica1.id,
        "role": "client"
    })
    client.cookies.set("client_token", token)

    resp = client.get("/portal/dashboard")
    assert resp.status_code == 200
    assert "Luna" in resp.text
    assert "Sol" in resp.text


def test_disponibilidad_citas_y_fallback(client, db_session):
    """
    Verifica el endpoint GET /api/portal/clinica/{id}/disponibilidad:
    - Retorna slots disponibles y ocupados.
    - Cuando se ocupan todos los slots o no hay disponibilidad, activa los datos para el fallback de urgencia.
    """
    clinica = Clinica(
        nombre="Clínica Central",
        telefono="+51 987654321",
        zona_horaria="America/Lima",
        plan_activo="solo"
    )
    db_session.add(clinica)
    db_session.flush()

    cliente = Cliente(clinica_id=clinica.id, dni="11223344", nombre_completo="Ana López")
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(clinica_id=clinica.id, cliente_id=cliente.id, nombre="Bobby", especie="Canino")
    db_session.add(mascota)
    db_session.flush()

    # Fecha futura para evitar que slots pasados sean filtrados por 'hoy'
    fecha_futura = (date.today() + timedelta(days=5)).isoformat()

    # Cita existente a las 09:00
    cita = Cita(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        mascota_id=mascota.id,
        fecha=date.fromisoformat(fecha_futura),
        hora=time(9, 0),
        motivo="Vacuna séxtuple",
        estado="CONFIRMADA"
    )
    db_session.add(cita)
    db_session.commit()

    token = create_access_token({
        "sub": str(cliente.id),
        "dni": cliente.dni,
        "clinica_id": clinica.id,
        "role": "client"
    })
    client.cookies.set("client_token", token)

    resp = client.get(f"/api/portal/clinica/{clinica.id}/disponibilidad?fecha={fecha_futura}")
    assert resp.status_code == 200
    data = resp.json()
    assert "09:00" in data["horas_ocupadas"]
    assert "09:00" not in data["horas_disponibles"]
    assert "08:30" in data["horas_disponibles"]
    assert data["contacto_emergencia"] == "+51 987654321"


def test_agendar_confirmar_cancelar_cita(client, db_session):
    """
    Prueba el ciclo de vida de una Cita:
    1. Agendamiento desde el Portal del Dueño (POST /api/portal/citas).
    2. Colisión de horario (409 Conflict).
    3. Confirmación por el Veterinario (PUT /api/clinic/citas/{id}/confirmar).
    4. Cancelación por el Veterinario (PUT /api/clinic/citas/{id}/cancelar).
    """
    clinica = Clinica(nombre="Vet San Miguel", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    vet = Veterinario(
        clinica_id=clinica.id,
        nombre="Dr. Veterinario",
        email="vet@sanmiguel.com",
        rol="VET",
        is_verified=True,
        is_active=True
    )
    db_session.add(vet)

    cliente = Cliente(clinica_id=clinica.id, dni="99887766", nombre_completo="Pedro")
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(clinica_id=clinica.id, cliente_id=cliente.id, nombre="Rex", especie="Canino")
    db_session.add(mascota)
    db_session.commit()

    fecha_str = (date.today() + timedelta(days=2)).isoformat()

    # 1. Agendamiento desde el portal
    client_token = create_access_token({
        "sub": str(cliente.id),
        "dni": cliente.dni,
        "clinica_id": clinica.id,
        "role": "client"
    })
    client.cookies.set("client_token", client_token)

    payload = {
        "clinica_id": clinica.id,
        "mascota_id": mascota.id,
        "fecha": fecha_str,
        "hora": "10:30",
        "motivo": "Revisión general"
    }

    resp = client.post("/api/portal/citas", json=payload)
    assert resp.status_code == 201
    cita_data = resp.json()
    assert cita_data["cita"]["estado"] == "PENDIENTE"
    cita_id = cita_data["cita"]["id"]

    # 2. Intento de agendar la MISMA hora (Colisión)
    resp_colision = client.post("/api/portal/citas", json=payload)
    assert resp_colision.status_code == 409

    # 3. Confirmar Cita desde vista Veterinario
    client.cookies.delete("client_token")
    vet_token = create_access_token({
        "sub": str(vet.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "VET",
        "email": vet.email
    })
    client.cookies.set("vet_token", vet_token)

    resp_conf = client.put(f"/api/clinic/citas/{cita_id}/confirmar")
    assert resp_conf.status_code == 200
    assert resp_conf.json()["estado"] == "CONFIRMADA"

    # 4. Cancelar Cita
    resp_canc = client.put(f"/api/clinic/citas/{cita_id}/cancelar")
    assert resp_canc.status_code == 200
    assert resp_canc.json()["estado"] == "CANCELADA"


def test_agenda_vista_veterinario(client, db_session):
    """
    Verifica que GET /agenda renderiza correctamente la vista cronológica de citas para el veterinario.
    """
    clinica = Clinica(nombre="Vet Miraflores", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    vet = Veterinario(
        clinica_id=clinica.id,
        nombre="Dra. Miraflores",
        email="dra@miraflores.com",
        rol="ADMIN",
        is_verified=True,
        is_active=True
    )
    db_session.add(vet)
    db_session.commit()

    vet_token = create_access_token({
        "sub": str(vet.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "ADMIN",
        "email": vet.email
    })
    client.cookies.set("vet_token", vet_token)

    resp = client.get("/agenda")
    assert resp.status_code == 200
    assert "Agenda de Citas" in resp.text
    assert "inputFechaAgenda" in resp.text
    assert "Total Citas" in resp.text


def test_ficha_mascota_reubicacion_pin_tarjeta_dueno(client, db_session):
    """
    2. Reubicación del PIN (Owner-Centric):
    - La vista de paciente (/pacientes/{id}) muestra una tarjeta exclusiva de 'Datos del Propietario'.
    - El botón 'Restablecer PIN' reside en la tarjeta del dueño y actúa sobre cliente_id.
    - Se verifica el endpoint POST /api/clinic/clientes/{cliente_id}/reset-pin.
    """
    clinica = Clinica(nombre="Vet San Borja", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    vet = Veterinario(
        clinica_id=clinica.id,
        nombre="Dr. San Borja",
        email="dr@sanborja.com",
        rol="ADMIN",
        is_verified=True,
        is_active=True
    )
    db_session.add(vet)

    cliente = Cliente(
        clinica_id=clinica.id,
        dni="12348765",
        nombre_completo="Roberto Gomez",
        telefono="955443322",
        pin_hash=hash_pin("9999")
    )
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        nombre="Pelusa",
        especie="Felino"
    )
    db_session.add(mascota)
    db_session.commit()

    vet_token = create_access_token({
        "sub": str(vet.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "ADMIN",
        "email": vet.email
    })
    client.cookies.set("vet_token", vet_token)

    # 1. Verificar render de ficha clínica
    resp = client.get(f"/pacientes/{mascota.id}")
    assert resp.status_code == 200
    assert "Datos del Propietario" in resp.text
    assert f"resetearPinCliente({cliente.id})" in resp.text
    assert "Restablecer PIN" in resp.text

    # 2. Ejecutar reset de PIN
    reset_resp = client.post(f"/api/clinic/clientes/{cliente.id}/reset-pin")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["cliente_id"] == cliente.id

    # 3. Verificar en BD que el pin_hash se limpió (exigirá crear uno nuevo en PWA)
    db_session.refresh(cliente)
    assert cliente.pin_hash is None

