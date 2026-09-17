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
    3. Botón 'Editar Perfil' de la mascota sin bloque de titular redundante.
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

    # 3. Separación de entidades: Botón Editar Perfil de mascota sin bloque 'Titular'
    assert 'id="btnEditarPerfil"' in html
    assert "Editar Perfil" in html
    assert "Titular:" not in html

    # 4. Selector de tema claro / oscuro y clases dinámicas
    assert 'id="btnTemaOscuro"' in html
    assert 'id="btnTemaClaro"' in html
    assert "cambiarTemaDni('oscuro')" in html
    assert "cambiarTemaDni('claro')" in html
    assert 'id="dni-card"' in html
    assert "transition-colors duration-300" in html


def test_alergias_accesibles_en_carnet(client, db_session):
    """Verifica accesibilidad de la alerta de alergias en carnet."""
    clinica = Clinica(nombre="Vet Alergias", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    cliente = Cliente(clinica_id=clinica.id, dni="11223344", pin_hash=hash_pin("1111"))
    db_session.add(cliente)
    db_session.flush()

    # Mascota CON alergias
    m1 = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        nombre="Alergico",
        especie="Canino",
        tiene_alergias=True,
        detalle_alergias="Penicilina y polen"
    )
    # Mascota SIN alergias
    m2 = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        nombre="Sano",
        especie="Felino",
        tiene_alergias=False,
        detalle_alergias=None
    )
    db_session.add_all([m1, m2])
    db_session.commit()

    token = create_access_token({"sub": str(cliente.id), "clinica_id": clinica.id, "role": "client", "dni": cliente.dni})
    client.cookies.set("client_token", token)

    # 1. Con alergias: clases de accesibilidad aplicadas
    resp1 = client.get(f"/portal/carnet/{m1.id}")
    assert resp1.status_code == 200
    assert "bg-rose-50 text-rose-700 border border-rose-200" in resp1.text
    assert "Penicilina y polen" in resp1.text

    # 2. Sin alergias: la alerta está oculta
    resp2 = client.get(f"/portal/carnet/{m2.id}")
    assert resp2.status_code == 200
    assert "bg-rose-50 text-rose-700" not in resp2.text


def test_portal_perfil_dueno_update(client, db_session):
    """Verifica la edición del perfil del dueño mediante PUT /api/portal/perfil."""
    clinica = Clinica(nombre="Vet Centro", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    cliente = Cliente(
        clinica_id=clinica.id,
        dni="77665544",
        nombre_completo="Carlos Dueño Original",
        telefono="999888777",
        pin_hash=hash_pin("4321")
    )
    db_session.add(cliente)
    db_session.commit()

    token = create_access_token({"sub": str(cliente.id), "clinica_id": clinica.id, "role": "client", "dni": cliente.dni})
    client.cookies.set("client_token", token)

    # Editar datos
    resp = client.put("/api/portal/perfil", json={
        "nombre_completo": "Carlos Alberto Modificado",
        "telefono": "911222333"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["nombre_completo"] == "Carlos Alberto Modificado"
    assert data["telefono"] == "911222333"

    # Verificar reflejo en dashboard
    resp_dash = client.get("/portal/dashboard")
    assert resp_dash.status_code == 200
    assert "Carlos Alberto Modificado" in resp_dash.text
    assert "911222333" in resp_dash.text
    assert "77665544" in resp_dash.text
    assert "Mi Perfil" in resp_dash.text


def test_autonomia_registro_y_busqueda_veterinario(client, db_session):
    """
    Regla de Negocio:
    1. El dueño registra una nueva mascota de forma autónoma (POST /api/portal/mascotas).
    2. El dueño puede editar el nombre y señas de su mascota (POST /api/portal/mascotas/{id}).
    3. Cuando el veterinario busca el DNI en /pacientes, devuelve TODAS las mascotas y permite abrir la ficha clínica.
    """
    clinica = Clinica(nombre="Vet San Miguel", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    # Veterinario de la clínica
    vet = Veterinario(
        clinica_id=clinica.id,
        email="vet.sanmiguel@example.com",
        password_hash=hash_password("VetPass123!"),
        rol="ADMIN",
        nombre="Dr. Miguel"
    )
    db_session.add(vet)
    db_session.flush()

    # Dueño con 1 mascota registrada en clínica
    cliente = Cliente(
        clinica_id=clinica.id,
        dni="12345099",
        nombre_completo="María Elena Fuentes",
        pin_hash=hash_pin("1234")
    )
    db_session.add(cliente)
    db_session.flush()

    m_clinica = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        nombre="Bobby Clínico",
        especie="Canino"
    )
    db_session.add(m_clinica)
    db_session.commit()

    # 1. Dueño se autentica y registra una segunda mascota autónomamente
    token_cliente = create_access_token({"sub": str(cliente.id), "clinica_id": clinica.id, "role": "client", "dni": cliente.dni})
    client.cookies.set("client_token", token_cliente)

    resp_crear = client.post("/api/portal/mascotas", json={
        "nombre": "Michi Autónomo",
        "especie": "Felino",
        "raza": "Angora",
        "sexo": "Hembra",
        "rasgos_distintivos": "Mancha en la patita"
    })
    assert resp_crear.status_code == 201
    nueva_m_data = resp_crear.json()
    nueva_m_id = nueva_m_data["mascota_id"]
    assert nueva_m_data["nombre"] == "Michi Autónomo"
    assert nueva_m_data["especie"] == "Felino"

    # 2. Dueño edita los datos de Michi Autónomo
    resp_edit = client.post(f"/api/portal/mascotas/{nueva_m_id}", json={
        "nombre": "Michi Estrella",
        "sexo": "Hembra",
        "rasgos_distintivos": "Mancha en la patita y collar violeta"
    })
    assert resp_edit.status_code == 200
    assert resp_edit.json()["nombre"] == "Michi Estrella"

    # 3. El veterinario ingresa y busca al dueño por DNI en /pacientes
    client.cookies.clear()
    token_vet = create_access_token({"sub": str(vet.id), "clinica_id": clinica.id, "rol": "ADMIN", "email": vet.email})
    client.cookies.set("vet_token", token_vet)

    resp_busqueda = client.get("/pacientes?q=12345099")
    assert resp_busqueda.status_code == 200
    # Ambas mascotas (la de clínica y la creada autónomamente por el dueño) deben figurar
    assert "Bobby Clínico" in resp_busqueda.text
    assert "Michi Estrella" in resp_busqueda.text

    # 4. El veterinario abre la ficha clínica de la nueva mascota para registrar atenciones
    resp_ficha = client.get(f"/pacientes/{nueva_m_id}")
    assert resp_ficha.status_code == 200
    assert "Michi Estrella" in resp_ficha.text
    assert "María Elena Fuentes" in resp_ficha.text


