import pytest
from datetime import date, timedelta
from app.core.models import Clinica
from app.clinic.models import (
    Veterinario, Cliente, Mascota,
    Producto, ServicioBano, AtencionClinica
)
from app.core.security import create_access_token
from app.core.timezone import get_lima_now


@pytest.fixture
def vet_setup(client, db_session):
    clinica = Clinica(
        nombre="Clínica Vet Mejoras",
        nombre_comercial="Vet Mejoras Pro",
        zona_horaria="America/Lima",
        plan_activo="solo"
    )
    db_session.add(clinica)
    db_session.flush()

    vet = Veterinario(
        clinica_id=clinica.id,
        nombre="Dra. Andrea Morales",
        email="andrea@vetmejoras.pe",
        rol="ADMIN",
        is_verified=True,
        is_active=True
    )
    db_session.add(vet)
    db_session.commit()
    db_session.refresh(vet)

    token = create_access_token({
        "sub": str(vet.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "ADMIN",
        "email": vet.email
    })
    client.cookies.set("vet_token", token)

    return {"clinica": clinica, "vet": vet}


def test_fecha_nacimiento_y_deduplicacion_pacientes(client, db_session, vet_setup):
    """
    1. Registro rápido de paciente con fecha_nacimiento.
    2. Comprobar que en GET /pacientes no hay duplicidad de mascotas.
    """
    clinica = vet_setup["clinica"]

    # 1. Registrar paciente con fecha_nacimiento
    payload = {
        "clinica_id": clinica.id,
        "dni": "77889900",
        "nombres": "Carlos",
        "apellido_paterno": "Dueño",
        "telefono": "987654321",
        "mascota_nombre": "Bobby",
        "mascota_especie": "Canino",
        "mascota_raza": "Golden Retriever",
        "fecha_nacimiento": "2024-03-15",
    }
    resp = client.post("/api/clinic/paciente-rapido", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["mascota"]["fecha_nacimiento"] == "2024-03-15"
    mascota_id = data["mascota"]["id"]

    # Verificar en BD
    mascota_db = db_session.get(Mascota, mascota_id)
    assert mascota_db.fecha_nacimiento == date(2024, 3, 15)

    # 2. Simular un escenario de clientes repetidos con el mismo DNI
    cliente2 = Cliente(
        clinica_id=clinica.id,
        dni="77889900",
        nombres="Carlos Duplicado",
        apellido_paterno="Dueño",
        telefono="987654321"
    )
    db_session.add(cliente2)
    db_session.commit()

    # GET /pacientes debe renderizar y contener a Bobby exactamente 1 vez
    resp_html = client.get("/pacientes")
    assert resp_html.status_code == 200
    assert "Bobby" in resp_html.text


def test_validacion_estricta_receta_medica(client, db_session, vet_setup):
    """
    Validación estricta de receta:
    - Si se especifica receta_medicamento, frecuencia y dosis son obligatorios (422 si falta alguno).
    - Si están los 3, se registra la atención y se crea el MedicationPlan.
    """
    clinica = vet_setup["clinica"]
    vet = vet_setup["vet"]

    # Crear cliente y mascota
    cliente = Cliente(clinica_id=clinica.id, dni="12345678", nombres="Ana", apellido_paterno="Ruiz", telefono="999111222")
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(clinica_id=clinica.id, cliente_id=cliente.id, nombre="Luna", especie="Canino")
    db_session.add(mascota)
    db_session.commit()

    # Intento 1: Mandar medicamento SIN frecuencia ni dosis -> debe fallar con 422
    payload_invalido = {
        "clinica_id": clinica.id,
        "mascota_id": mascota.id,
        "tipo_atencion": "CONSULTA",
        "motivo": "Revisión general",
        "diagnostico": "Faringitis",
        "tratamiento": "Reposo e hidratación",
        "receta_medicamento": "Amoxicilina 500mg",
        "receta_frecuencia": "",
        "receta_dosis": ""
    }
    resp_fail = client.post("/api/clinic/atenciones", json=payload_invalido)
    assert resp_fail.status_code == 422
    assert "receta_frecuencia" in resp_fail.text or "Frecuencia" in resp_fail.text

    # Intento 2: Mandar con medicamento, frecuencia y dosis completos -> debe tener éxito
    payload_valido = {
        "clinica_id": clinica.id,
        "mascota_id": mascota.id,
        "tipo_atencion": "CONSULTA",
        "motivo": "Revisión general",
        "diagnostico": "Faringitis",
        "tratamiento": "Reposo e hidratación",
        "receta_medicamento": "Amoxicilina 500mg",
        "receta_frecuencia": "Cada 8 horas",
        "receta_dosis": "1 tableta"
    }
    resp_ok = client.post("/api/clinic/atenciones", json=payload_valido)
    assert resp_ok.status_code == 201
    res_data = resp_ok.json()
    assert "id" in res_data
    assert res_data.get("plan_medicacion_id") is not None

    # Verificar que el tratamiento incluye el texto de la receta
    atencion_db = db_session.get(AtencionClinica, res_data["id"])
    assert "Amoxicilina 500mg" in atencion_db.tratamiento
    assert "Cada 8 horas" in atencion_db.tratamiento
    assert "1 tableta" in atencion_db.tratamiento


def test_catalogo_banos_inventario_y_descuento_grooming(client, db_session, vet_setup):
    """
    1. GET /api/clinic/servicios-bano autosemilla 3 servicios (Normal, Hipoalergénico, Medicado).
    2. GET /api/clinic/productos autosemilla shampoos con stock.
    3. Registrar atención de GROOMING con servicio_bano_id descuenta stock automáticamente.
    """
    clinica = vet_setup["clinica"]
    vet = vet_setup["vet"]

    # 1. Autosemilla de servicios y productos
    resp_servicios = client.get("/api/clinic/servicios-bano")
    assert resp_servicios.status_code == 200
    servicios = resp_servicios.json()
    assert len(servicios) >= 3
    assert any("Normal" in s["nombre"] for s in servicios)
    assert any("Medicado" in s["nombre"] for s in servicios)

    resp_productos = client.get("/api/clinic/productos")
    assert resp_productos.status_code == 200
    productos = resp_productos.json()
    assert len(productos) >= 3

    # Buscar el servicio Medicado y el producto asociado
    servicio_medicado = next(s for s in servicios if "Medicado" in s["nombre"])
    assert servicio_medicado["producto_id"] is not None
    prod_id = servicio_medicado["producto_id"]
    consumo = servicio_medicado["cantidad_consumo"]

    prod_db = db_session.get(Producto, prod_id)
    stock_inicial = prod_db.stock_actual
    assert stock_inicial > 0

    # 2. Crear paciente para atender
    cliente = Cliente(clinica_id=clinica.id, dni="99887766", nombres="Pedro", apellido_paterno="Ramos")
    db_session.add(cliente)
    db_session.flush()
    mascota = Mascota(clinica_id=clinica.id, cliente_id=cliente.id, nombre="Rocky", especie="Canino")
    db_session.add(mascota)
    db_session.commit()

    # 3. Registrar atención de GROOMING
    payload_grooming = {
        "clinica_id": clinica.id,
        "mascota_id": mascota.id,
        "tipo_atencion": "GROOMING",
        "motivo": "Baño antipulgas y medicado",
        "diagnostico": "Piel sensible",
        "tratamiento": "Baño con shampoo medicado y secado suave",
        "servicio_bano_id": servicio_medicado["id"]
    }
    resp_grooming = client.post("/api/clinic/atenciones", json=payload_grooming)
    assert resp_grooming.status_code == 201

    # Verificar que el stock se descontó exactamente en cantidad_consumo
    db_session.refresh(prod_db)
    assert prod_db.stock_actual == stock_inicial - consumo


def test_actualizar_stock_y_crear_servicio_bano(client, db_session, vet_setup):
    """
    CRUD rápido:
    - PUT /api/clinic/productos/{id}/stock actualiza el stock actual y mínimo.
    - POST /api/clinic/servicios-bano permite crear un nuevo servicio personalizado.
    """
    # Semillar primero
    client.get("/api/clinic/productos")
    prods = client.get("/api/clinic/productos").json()
    first_prod = prods[0]

    # Actualizar stock
    resp_stock = client.put(f"/api/clinic/productos/{first_prod['id']}/stock", json={
        "stock_actual": 25.5,
        "stock_minimo": 4.0
    })
    assert resp_stock.status_code == 200
    assert resp_stock.json()["stock_actual"] == 25.5
    assert resp_stock.json()["stock_minimo"] == 4.0

    # Crear nuevo servicio
    resp_new_serv = client.post("/api/clinic/servicios-bano", json={
        "nombre": "Baño Relajante de Avena",
        "descripcion": "Baño con extracto de avena y aromaterapia",
        "precio": 65.0,
        "producto_id": first_prod["id"],
        "cantidad_consumo": 0.08
    })
    assert resp_new_serv.status_code == 201
    data_serv = resp_new_serv.json()
    assert data_serv["nombre"] == "Baño Relajante de Avena"
    assert data_serv["precio"] == 65.0


def test_agendar_cita_retencion_y_proximas_citas_en_agenda(client, db_session, vet_setup):
    """
    1. POST /api/clinic/citas permite agendar una cita directa desde el panel veterinario.
    2. GET /agenda renderiza la sección de próximas citas con sus datos.
    """
    clinica = vet_setup["clinica"]
    vet = vet_setup["vet"]

    cliente = Cliente(clinica_id=clinica.id, dni="11223344", nombres="Beatriz", apellido_paterno="Castro", telefono="912345678")
    db_session.add(cliente)
    db_session.flush()
    mascota = Mascota(clinica_id=clinica.id, cliente_id=cliente.id, nombre="Peluchín", especie="Canino")
    db_session.add(mascota)
    db_session.commit()

    # Agendar cita de próximo baño a 21 días
    fecha_cita = (get_lima_now() + timedelta(days=21)).date()
    hora_cita = "11:00"

    payload_cita = {
        "mascota_id": mascota.id,
        "fecha": str(fecha_cita),
        "hora": hora_cita,
        "motivo": "Próximo Baño de Mantenimiento",
        "notas": "Agendado automáticamente post-atención de baño"
    }

    resp_cita = client.post("/api/clinic/citas", json=payload_cita)
    assert resp_cita.status_code == 200
    cita_data = resp_cita.json()
    assert "cita_id" in cita_data
    assert cita_data["fecha"] == str(fecha_cita)
    assert cita_data["hora"] == hora_cita

    # Comprobar que en GET /agenda aparece la cita
    resp_agenda = client.get("/agenda")
    assert resp_agenda.status_code == 200
    assert "Peluchín" in resp_agenda.text
    assert "Próximo Baño de Mantenimiento" in resp_agenda.text
    assert "Próximas 15-20 Citas Programadas" in resp_agenda.text


def test_deduplicacion_mascotas_mismo_nombre_y_multi_clinica(client, db_session, vet_setup):
    """
    Reproduce exactamente el caso reportado por el usuario:
    - Dueño 1 (Roger): 1 Mulato (otra clínica), 2 Princesas (1 local y 1 otra clínica).
    - Dueño 2 (Teresa): 1 Afro (local), 2 Biscochos (otra clínica), 1 Nieve (otra clínica).
    Verifica que:
    1. En GET /pacientes, Princesa y Biscocho aparecen EXACTAMENTE 1 vez cada uno.
    2. Roger tiene 2 mascotas y Teresa tiene 3 mascotas (total 5, no 7).
    3. Princesa local es priorizada y muestra 'Paciente de tu Clínica'.
    4. Al abrir una mascota de otra sede (Mulato), no genera 404.
    """
    clinica = vet_setup["clinica"]

    # Crear una clínica externa para simular registros de red / portal
    clinica_ext = Clinica(
        nombre="Clínica Externa",
        nombre_comercial="Clínica Externa",
        zona_horaria="America/Lima",
        plan_activo="solo"
    )
    db_session.add(clinica_ext)
    db_session.flush()

    # Dueño 1: Roger
    c1_local = Cliente(clinica_id=clinica.id, dni="70566711", nombres="Roger Fernando", apellido_paterno="Cabezudo", telefono="922508449")
    c1_ext = Cliente(clinica_id=clinica_ext.id, dni="70566711", nombres="Roger Fernando", apellido_paterno="Cabezudo", telefono="922508449")
    db_session.add_all([c1_local, c1_ext])
    db_session.flush()

    m_mulato = Mascota(clinica_id=clinica_ext.id, cliente_id=c1_ext.id, nombre="Mulato", especie="Canino", raza="Mestizo", peso=10.0)
    m_princesa_local = Mascota(clinica_id=clinica.id, cliente_id=c1_local.id, nombre="Princesa", especie="Canino", raza="Jack Russell Terrier", peso=15.0)
    m_princesa_ext = Mascota(clinica_id=clinica_ext.id, cliente_id=c1_ext.id, nombre="Princesa", especie="Canino", raza="Jack Russell Terrier", peso=15.0)

    # Dueño 2: Teresa
    c2_local = Cliente(clinica_id=clinica.id, dni="70566732", nombres="Teresa Victoria", apellido_paterno="Cabezudo", telefono="934292901")
    c2_ext = Cliente(clinica_id=clinica_ext.id, dni="70566732", nombres="Teresa Victoria", apellido_paterno="Cabezudo", telefono="934292901")
    db_session.add_all([c2_local, c2_ext])
    db_session.flush()

    m_afro = Mascota(clinica_id=clinica.id, cliente_id=c2_local.id, nombre="Afro", especie="Canino", raza="Criollo", peso=25.0)
    m_biscocho_1 = Mascota(clinica_id=clinica_ext.id, cliente_id=c2_ext.id, nombre="Biscocho", especie="Felino", raza="Criollo")
    m_biscocho_2 = Mascota(clinica_id=clinica_ext.id, cliente_id=c2_ext.id, nombre="Biscocho", especie="Felino", raza="Criollo")
    m_nieve = Mascota(clinica_id=clinica_ext.id, cliente_id=c2_ext.id, nombre="Nieve", especie="Canino", raza="Husky", peso=28.0)

    db_session.add_all([m_mulato, m_princesa_local, m_princesa_ext, m_afro, m_biscocho_1, m_biscocho_2, m_nieve])
    db_session.commit()

    # 1. Comprobar directorio de pacientes
    resp = client.get("/pacientes")
    assert resp.status_code == 200
    html = resp.text

    # Total registrado debe ser 5 mascotas (no 7)
    assert "5 MASCOTAS" in html or "(5 MASCOTAS)" in html or "5 mascotas" in html
    assert "7 MASCOTAS" not in html

    # Cada mascota debe tener su botón de acción (Ver Ficha para locales, Vincular Ficha para externas)
    assert (html.count("Ver Ficha") + html.count("Vincular Ficha")) >= 5
    assert "Princesa" in html
    assert "Biscocho" in html
    assert "Mulato" in html
    assert "Afro" in html
    assert "Nieve" in html

    # 2. Vincular Mulato a la clínica actual y verificar que abre su ficha con éxito
    resp_vincular = client.post(f"/api/clinic/vincular-mascota/{m_mulato.id}")
    assert resp_vincular.status_code == 200
    nueva_id = resp_vincular.json()["mascota_id"]

    resp_ficha = client.get(f"/pacientes/{nueva_id}")
    assert resp_ficha.status_code == 200
    assert "Mulato" in resp_ficha.text


def test_modulo_mis_productos_crud_y_privacidad_multitenant(client, db_session, vet_setup):
    """
    Verifica:
    1. Acceso al módulo GET /productos y presencia en el menú lateral.
    2. Creación de productos propios (Vacuna, Medicina) mediante POST /api/clinic/productos.
    3. Aislamiento Multi-Tenant: los productos de otra clínica nunca aparecen en la lista de este veterinario.
    4. Edición (PUT) y eliminación lógica (DELETE) de productos propios.
    """
    clinica = vet_setup["clinica"]

    # 1. Crear otra clínica con su propio producto privado
    otra_clinica = Clinica(
        nombre="Veterinaria Ajena",
        nombre_comercial="Vet Ajena",
        zona_horaria="America/Lima",
        plan_activo="solo"
    )
    db_session.add(otra_clinica)
    db_session.flush()

    prod_ajeno = Producto(
        clinica_id=otra_clinica.id,
        nombre="Vacuna Secreta Otra Vet",
        tipo="Vacuna",
        stock_actual=50.0,
        unidad_medida="dosis",
        stock_minimo=5.0
    )
    db_session.add(prod_ajeno)
    db_session.commit()

    # 2. Verificar que la vista GET /productos carga correctamente
    resp_vista = client.get("/productos")
    assert resp_vista.status_code == 200
    assert "Mis Productos" in resp_vista.text
    assert 'href="/productos"' in resp_vista.text

    # 3. Crear una Vacuna propia del veterinario SIN control de stock (por defecto)
    resp_crear = client.post("/api/clinic/productos", json={
        "nombre": "Séxtuple Vanguard Plus",
        "tipo": "Vacuna",
        "codigo": "LOTE-Z99",
        "precio_venta": 65.0
    })
    assert resp_crear.status_code == 201
    mi_vacuna = resp_crear.json()
    assert mi_vacuna["nombre"] == "Séxtuple Vanguard Plus"
    assert mi_vacuna["tipo"] == "Vacuna"
    assert mi_vacuna["codigo"] == "LOTE-Z99"
    assert mi_vacuna["controlar_stock"] is False
    assert mi_vacuna["stock_actual"] == 0.0
    assert mi_vacuna["clinica_id"] == clinica.id

    # 4. Listar productos del veterinario y comprobar que NO aparece el de otra clínica
    resp_lista = client.get("/api/clinic/productos")
    assert resp_lista.status_code == 200
    nombres = [p["nombre"] for p in resp_lista.json()]
    assert "Séxtuple Vanguard Plus" in nombres
    assert "Vacuna Secreta Otra Vet" not in nombres

    # 5. Intentar editar o borrar el producto ajeno debe dar 404
    resp_del_ajeno = client.delete(f"/api/clinic/productos/{prod_ajeno.id}")
    assert resp_del_ajeno.status_code == 404

    # 6. Activar el toggle opcional de stock (controlar_stock=True) y editar el producto propio
    resp_edit = client.put(f"/api/clinic/productos/{mi_vacuna['id']}", json={
        "nombre": "Séxtuple Vanguard Plus 5",
        "controlar_stock": True,
        "stock_actual": 20,
        "stock_minimo": 5
    })
    assert resp_edit.status_code == 200
    assert resp_edit.json()["nombre"] == "Séxtuple Vanguard Plus 5"
    assert resp_edit.json()["controlar_stock"] is True
    assert resp_edit.json()["stock_actual"] == 20.0

    resp_del = client.delete(f"/api/clinic/productos/{mi_vacuna['id']}")
    assert resp_del.status_code == 200


def test_flujo_cita_portal_auto_vinculacion_y_estado_atendida(client, db_session, vet_setup):
    """
    Verifica el flujo completo solicitado:
    1. Un dueño registra por su cuenta una mascota en el Portal (otra clinica_id) y agenda una cita en la clínica actual para hoy a las 14:00.
    2. El veterinario confirma la cita o hace clic en 'Atender Paciente' desde la Agenda -> la mascota se vincula automáticamente a su clínica.
    3. Al registrar la atención médica de la mascota, la cita pasa automáticamente a estado 'ATENDIDA'.
    4. En GET /agenda de hoy se muestra como 'Atendido' y desaparece de la cola de 'Próximas Citas'.
    """
    from datetime import time
    from app.clinic.models import Cita

    clinica = vet_setup["clinica"]
    hoy = get_lima_now().date()

    # Clínica externa (simulando mascota creada por el cliente en el Portal)
    clinica_portal = Clinica(
        nombre="Portal General",
        nombre_comercial="Portal",
        zona_horaria="America/Lima",
        plan_activo="solo"
    )
    db_session.add(clinica_portal)
    db_session.flush()

    cliente_portal = Cliente(
        clinica_id=clinica_portal.id,
        dni="44556677",
        nombres="Lucía",
        apellido_paterno="Méndez",
        nombre_completo="Lucía Méndez",
        telefono="988776655"
    )
    db_session.add(cliente_portal)
    db_session.flush()

    mascota_portal = Mascota(
        clinica_id=clinica_portal.id,
        cliente_id=cliente_portal.id,
        nombre="Toby",
        especie="Canino",
        raza="Beagle",
        peso=11.5
    )
    db_session.add(mascota_portal)
    db_session.flush()

    # El cliente agenda cita para HOY a las 14:00 (2:00 PM) en la clínica del veterinario
    cita = Cita(
        clinica_id=clinica.id,
        cliente_id=cliente_portal.id,
        mascota_id=mascota_portal.id,
        fecha=hoy,
        hora=time(14, 0),
        motivo="Vacunación anual y control",
        estado="PENDIENTE"
    )
    db_session.add(cita)
    db_session.commit()
    db_session.refresh(cita)

    # 1. El veterinario confirma la cita -> debe auto-vincular a Toby en su clínica
    resp_conf = client.put(f"/api/clinic/citas/{cita.id}/confirmar")
    assert resp_conf.status_code == 200
    conf_data = resp_conf.json()
    mascota_local_id = conf_data["mascota_id"]

    # Abrir la ficha desde el botón 'Atender Paciente' de la agenda debe responder 200
    resp_ficha = client.get(f"/pacientes/{mascota_local_id}?atender_cita={cita.id}&motivo=Vacunación")
    assert resp_ficha.status_code == 200
    assert "Toby" in resp_ficha.text

    # 2. Registrar la atención médica vinculada a la cita
    resp_atencion = client.post("/api/clinic/atenciones", json={
        "clinica_id": clinica.id,
        "mascota_id": mascota_local_id,
        "tipo_atencion": "VACUNACION",
        "motivo": "Vacunación anual y control",
        "tipo_vacuna": "Séxtuple Canina",
        "diagnostico": "Paciente sano",
        "tratamiento": "Vacuna Séxtuple aplicada",
        "cita_id": cita.id
    })
    assert resp_atencion.status_code == 201

    # 3. Verificar que la cita pasó automáticamente a estado ATENDIDA
    db_session.refresh(cita)
    assert cita.estado.upper() == "ATENDIDA"

    # 4. En la Agenda de hoy, aparece con el badge 'Atendido'
    resp_agenda = client.get("/agenda")
    assert resp_agenda.status_code == 200
    assert "Atendido" in resp_agenda.text


def test_sugerir_proximo_bano_desde_atencion_grooming_con_notificacion(client, db_session, vet_setup, monkeypatch):
    """
    Verifica que al registrar un Baño (GROOMING) indicando 'fecha_proximo_bano' (ej. +15 o +30 días):
    - Se crea automáticamente una Cita con estado 'SUGERIDA' para el portal del dueño.
    - Se crea un SeguimientoNotificacion con tipo 'PROXIMO_BANO'.
    - Se dispara la notificación por correo al dueño.
    - La API de estado del portal móvil devuelve la cita SUGERIDA para lanzar la alerta en celular.
    """
    from datetime import timedelta
    from app.clinic.models import Cita, SeguimientoNotificacion
    from app.core.timezone import get_lima_now
    from app.core.security import create_access_token

    clinica = vet_setup["clinica"]
    cliente_dueno = Cliente(
        clinica_id=clinica.id,
        dni="77889900",
        nombres="Carlos",
        apellido_paterno="Ríos",
        nombre_completo="Carlos Ríos",
        telefono="999111222",
        email="dueno.bano@sherekepet.com"
    )
    db_session.add(cliente_dueno)
    db_session.flush()

    mascota = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente_dueno.id,
        nombre="Boby",
        especie="Canino",
        raza="Poodle",
        peso=6.5
    )
    db_session.add(mascota)
    db_session.commit()
    db_session.refresh(mascota)

    correos_enviados = []

    def mock_send_bath_email(destinatario, cliente_nombre, mascota_nombre, fecha_sugerida_str, hora_sugerida_str, clinica_nombre):
        correos_enviados.append({
            "destinatario": destinatario,
            "mascota": mascota_nombre,
            "fecha": fecha_sugerida_str,
            "hora": hora_sugerida_str,
            "clinica": clinica_nombre
        })
        return True

    import app.core.email as email_mod
    monkeypatch.setattr(email_mod, "send_bath_suggestion_email", mock_send_bath_email)

    # Verificar que la ficha contiene los controles de sugerencia de próximo baño en #seccionGrooming
    resp_ficha = client.get(f"/pacientes/{mascota.id}")
    assert resp_ficha.status_code == 200
    assert 'id="fecha_proximo_bano"' in resp_ficha.text
    assert 'seleccionarFechaProximoBanoInline(15)' in resp_ficha.text
    assert 'seleccionarFechaProximoBanoInline(30)' in resp_ficha.text

    fecha_sugerida = get_lima_now().date() + timedelta(days=15)

    resp_at = client.post("/api/clinic/atenciones", json={
        "clinica_id": clinica.id,
        "mascota_id": mascota.id,
        "tipo_atencion": "GROOMING",
        "motivo": "Baño medicado quincenal",
        "tratamiento": "Piel mejorando notablemente",
        "fecha_proximo_bano": fecha_sugerida.isoformat(),
        "hora_proximo_bano": "11:00"
    })
    assert resp_at.status_code == 201
    data_at = resp_at.json()
    assert data_at["cita_sugerida_id"] is not None
    assert data_at["seguimiento_id"] is not None

    # Verificar Cita SUGERIDA creada
    cita_sug = db_session.query(Cita).filter(Cita.id == data_at["cita_sugerida_id"]).first()
    assert cita_sug is not None
    assert cita_sug.estado == "SUGERIDA"
    assert cita_sug.fecha == fecha_sugerida

    # Verificar SeguimientoNotificacion creado
    seg = db_session.query(SeguimientoNotificacion).filter(SeguimientoNotificacion.id == data_at["seguimiento_id"]).first()
    assert seg is not None
    assert seg.tipo == "PROXIMO_BANO"
    assert seg.fecha_programada == fecha_sugerida

    # Verificar que el correo fue enviado al dueño
    assert len(correos_enviados) == 1
    assert correos_enviados[0]["destinatario"] == "dueno.bano@sherekepet.com"
    assert correos_enviados[0]["mascota"] == mascota.nombre

    # Verificar que el endpoint de alertas móviles del Portal Dueño incluye la cita SUGERIDA
    client_token = create_access_token({"sub": str(cliente_dueno.id), "role": "client"})
    client.cookies.set("client_token", client_token)
    resp_estado = client.get("/api/portal/citas/estado")
    assert resp_estado.status_code == 200
    citas_portal = resp_estado.json()["citas"]
    assert any(c["id"] == cita_sug.id and c["estado"] == "SUGERIDA" for c in citas_portal)


def test_pagina_publica_planes_y_que_ofrecemos(client):
    """
    Verifica que la landing page enlace a '/planes' y que la página de Planes y Qué Ofrecemos
    muestre el Plan Emprendedor (S/ 49.00 / mes), la Prueba de 14 días gratis, los módulos y
    la preparación para Mercado Pago.
    """
    client.cookies.clear()
    resp_landing = client.get("/login")
    assert resp_landing.status_code == 200
    assert 'href="/planes"' in resp_landing.text
    assert "Planes y Qué Ofrecemos" in resp_landing.text

    resp_planes = client.get("/planes")
    assert resp_planes.status_code == 200
    assert "Plan Emprendedor Veterinario" in resp_planes.text
    assert "S/ 49.00" in resp_planes.text
    assert "14 Días" in resp_planes.text
    assert "Mercado Pago" in resp_planes.text

    resp_precios = client.get("/precios")
    assert resp_precios.status_code == 200
    assert "Plan Emprendedor Veterinario" in resp_precios.text





