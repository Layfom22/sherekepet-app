import pytest
from app.core.models import Clinica
from app.clinic.models import Veterinario, Cliente, Mascota
from app.core.security import create_access_token, hash_pin, hash_password


def test_actualizar_configuracion_marca_blanca(client, db_session):
    """
    1. Configuración de Marca Blanca:
    - PUT /api/clinic/configuracion permite al ADMIN guardar nombre y nombre_comercial.
    - Clinica.nombre_mostrado retorna el nombre_comercial.
    """
    clinica = Clinica(
        nombre="Veterinaria San Borja S.A.C.",
        nombre_comercial="San Borja Pet Clinic",
        zona_horaria="America/Lima",
        plan_activo="solo"
    )
    db_session.add(clinica)
    db_session.flush()

    admin = Veterinario(
        clinica_id=clinica.id,
        nombre="Dr. Administrador",
        email="admin@sanborja.com",
        rol="ADMIN",
        is_verified=True,
        is_active=True
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    token = create_access_token({
        "sub": str(admin.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "ADMIN",
        "email": admin.email
    })
    client.cookies.set("vet_token", token)

    # Actualizar configuración
    update_payload = {
        "nombre": "Clínica Veterinaria San Borja Central",
        "nombre_comercial": "San Borja Pet Care & Spa"
    }
    resp = client.put("/api/clinic/configuracion", json=update_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["clinica"]["nombre"] == "Clínica Veterinaria San Borja Central"
    assert data["clinica"]["nombre_comercial"] == "San Borja Pet Care & Spa"
    assert data["clinica"]["nombre_mostrado"] == "San Borja Pet Care & Spa"

    # Verificar en BD
    db_session.refresh(clinica)
    assert clinica.nombre == "Clínica Veterinaria San Borja Central"
    assert clinica.nombre_comercial == "San Borja Pet Care & Spa"
    assert clinica.nombre_mostrado == "San Borja Pet Care & Spa"


def test_asistente_cannot_update_configuracion(client, db_session):
    """
    Un usuario con rol ASISTENTE no puede modificar la configuración de la clínica.
    """
    clinica = Clinica(nombre="Vet Test", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    asistente = Veterinario(
        clinica_id=clinica.id,
        username="asistente_test",
        nombre="Asistente Test",
        rol="ASISTENTE",
        is_verified=True,
        is_active=True
    )
    db_session.add(asistente)
    db_session.commit()

    token = create_access_token({
        "sub": str(asistente.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "ASISTENTE",
        "username": asistente.username
    })
    client.cookies.set("vet_token", token)

    resp = client.put("/api/clinic/configuracion", json={"nombre": "Hack", "nombre_comercial": "Hack"})
    assert resp.status_code == 403


def test_vista_configuracion_render(client, db_session):
    """
    GET /configuracion renderiza la vista settings.html con el formulario y mockup.
    """
    clinica = Clinica(nombre="Clínica Sur", nombre_comercial="Sur Vet", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    admin = Veterinario(clinica_id=clinica.id, nombre="Dr. Sur", email="sur@vet.com", rol="ADMIN", is_verified=True)
    db_session.add(admin)
    db_session.commit()

    token = create_access_token({
        "sub": str(admin.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "ADMIN",
        "email": admin.email
    })
    client.cookies.set("vet_token", token)

    resp = client.get("/configuracion")
    assert resp.status_code == 200
    assert "Marca Blanca" in resp.text
    assert "Sur Vet" in resp.text
    assert "Clínica Sur" in resp.text


def test_check_dni_endpoint(client, db_session):
    """
    2. Endpoint POST /api/portal/check-dni:
    - Retorna exists: false si no existe.
    - Retorna exists: true, needs_pin: true si pin_hash es nulo.
    - Retorna exists: true, needs_pin: false si ya cuenta con pin_hash.
    """
    # 1. DNI inexistente
    resp_no = client.post("/api/portal/check-dni", json={"dni": "99999999"})
    assert resp_no.status_code == 200
    data_no = resp_no.json()
    assert data_no["exists"] is False
    assert data_no["needs_pin"] is False

    # 2. Cliente sin PIN (primer ingreso)
    clinica = Clinica(nombre="Vet Norte", nombre_comercial="Norte Vet Pets", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    c_sin_pin = Cliente(
        clinica_id=clinica.id,
        dni="77665544",
        nombre_completo="María Rodríguez",
        pin_hash=None
    )
    db_session.add(c_sin_pin)
    db_session.commit()

    resp_sin_pin = client.post("/api/portal/check-dni", json={"dni": "77665544"})
    assert resp_sin_pin.status_code == 200
    data_sin = resp_sin_pin.json()
    assert data_sin["exists"] is True
    assert data_sin["needs_pin"] is True
    assert data_sin["nombre"] == "María Rodríguez"
    assert data_sin["clinica_nombre"] == "Norte Vet Pets"

    # 3. Cliente con PIN ya creado
    c_con_pin = Cliente(
        clinica_id=clinica.id,
        dni="11223344",
        nombre_completo="Jorge Gómez",
        pin_hash=hash_pin("4321")
    )
    db_session.add(c_con_pin)
    db_session.commit()

    resp_con_pin = client.post("/api/portal/check-dni", json={"dni": "11223344"})
    assert resp_con_pin.status_code == 200
    data_con = resp_con_pin.json()
    assert data_con["exists"] is True
    assert data_con["needs_pin"] is False
    assert data_con["nombre"] == "Jorge Gómez"


def test_first_time_login_with_pin_creation_single_step(client, db_session):
    """
    Login PWA en 1 paso para nuevo PIN:
    - Cliente sin PIN envía nuevo_pin y confirmar_pin.
    - Se encripta el PIN, se guarda en BD y se retorna el JWT con cookie.
    - No exige volver a iniciar sesión.
    """
    clinica = Clinica(nombre="Clínica Los Pinos", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    cliente = Cliente(
        clinica_id=clinica.id,
        dni="88990011",
        nombre_completo="Lucía Fernández",
        pin_hash=None
    )
    db_session.add(cliente)
    db_session.commit()
    db_session.refresh(cliente)

    # 1. Error si no coinciden
    bad_match = client.post("/portal/login", data={
        "dni": "88990011",
        "nuevo_pin": "1234",
        "confirmar_pin": "5678",
        "clinica_id": str(clinica.id)
    })
    assert bad_match.status_code == 200
    assert "no coinciden" in bad_match.text

    # 2. Creación exitosa en un solo paso
    login_post = client.post("/portal/login", data={
        "dni": "88990011",
        "nuevo_pin": "1234",
        "confirmar_pin": "1234",
        "clinica_id": str(clinica.id)
    }, follow_redirects=False)

    assert login_post.status_code == 303
    assert login_post.headers["location"] == "/portal/dashboard"
    assert "client_token" in login_post.cookies

    # Verificar que el PIN quedó guardado en BD
    db_session.refresh(cliente)
    assert cliente.pin_hash is not None

    # 3. Siguiente login con el PIN recién creado
    client.cookies.clear()
    login_segundo = client.post("/portal/login", data={
        "dni": "88990011",
        "pin": "1234",
        "clinica_id": str(clinica.id)
    }, follow_redirects=False)
    assert login_segundo.status_code == 303
    assert login_segundo.headers["location"] == "/portal/dashboard"


def test_pwa_brand_reflection_in_portal(client, db_session):
    """
    Verifica que el nombre comercial y logo aparezcan en el header del portal del cliente.
    """
    clinica = Clinica(
        nombre="Razón Social Veterinaria Perú S.A.",
        nombre_comercial="Happy Pets 24 Horas",
        logo_url="https://example.com/happypets.png",
        zona_horaria="America/Lima",
        plan_activo="solo"
    )
    db_session.add(clinica)
    db_session.flush()

    cliente = Cliente(
        clinica_id=clinica.id,
        dni="44332211",
        nombre_completo="Carla Morales",
        pin_hash=hash_pin("9999")
    )
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        nombre="Peluchín",
        especie="Felino",
        raza="Siamés"
    )
    db_session.add(mascota)
    db_session.commit()

    token = create_access_token({
        "sub": str(cliente.id),
        "clinica_id": clinica.id,
        "role": "client",
        "dni": cliente.dni
    })
    client.cookies.set("client_token", token)

    # 1. En Dashboard PWA
    resp_dash = client.get("/portal/dashboard")
    assert resp_dash.status_code == 200
    assert "Happy Pets 24 Horas" in resp_dash.text
    assert "https://example.com/happypets.png" in resp_dash.text

    # 2. En Carnet Digital PWA
    resp_carnet = client.get(f"/portal/carnet/{mascota.id}")
    assert resp_carnet.status_code == 200
    assert "Happy Pets 24 Horas" in resp_carnet.text


def test_dni_mascota_ui_features(client, db_session):
    """
    Verifica los requerimientos de UI/UX del DNI de Mascota:
    1. Header limpio con 'Veterinaria:' y 'Portal de mi Mascota'.
    2. Badge ID con whitespace-nowrap y shrink-0.
    3. Modo privacidad de DNI con data-dni y función toggle.
    4. Alternador de Tema Claro / Oscuro con botones y transición.
    """
    clinica = Clinica(
        nombre="Clínica San Lucas",
        nombre_comercial="San Lucas Pets",
        zona_horaria="America/Lima",
        plan_activo="solo"
    )
    db_session.add(clinica)
    db_session.flush()

    cliente = Cliente(
        clinica_id=clinica.id,
        dni="87654321",
        nombre_completo="Juan Pérez",
        pin_hash=hash_pin("1234")
    )
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        nombre="Firulais",
        especie="Canino",
        raza="Golden Retriever"
    )
    db_session.add(mascota)
    db_session.commit()

    token = create_access_token({
        "sub": str(cliente.id),
        "clinica_id": clinica.id,
        "role": "client",
        "dni": cliente.dni
    })
    client.cookies.set("client_token", token)

    resp = client.get(f"/portal/carnet/{mascota.id}")
    assert resp.status_code == 200
    html = resp.text

    # 1. Header con respiro visual y nombre comercial
    assert "Veterinaria:" in html
    assert "San Lucas Pets" in html
    assert "Portal de mi Mascota" in html

    # 2. Badge de ID nunca cortado
    assert 'id="dniIdBadge"' in html
    assert "whitespace-nowrap" in html
    assert "shrink-0" in html

    # 3. Modo Privacidad DNI
    assert 'id="btnTogglePrivacidad"' in html
    assert 'onclick="togglePrivacidadDni()"' in html
    assert 'data-dni="87654321"' in html
    assert "togglePrivacidadDni" in html

    # 4. Selector de tema claro / oscuro y clases dinámicas
    assert 'id="btnTemaOscuro"' in html
    assert 'id="btnTemaClaro"' in html
    assert "cambiarTemaDni('oscuro')" in html
    assert "cambiarTemaDni('claro')" in html
    assert 'id="dni-card"' in html
    assert "transition-colors duration-300" in html
    assert "cambiarTemaDni" in html

