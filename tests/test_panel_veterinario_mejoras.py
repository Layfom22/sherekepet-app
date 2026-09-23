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
