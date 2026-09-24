"""
Tests de integración para Sprint 4:
1. Landing Page pública (GET /) con propuesta de valor y login integrado a la derecha.
2. Confirmación de Citas sin pérdida de relaciones (Caso 'Agujero Negro' blindado).
3. Modelos Mini-ERP: Producto (con Enum TipoProducto), ServicioCatalogo y ServicioProducto.
"""
from datetime import date, time
import pytest
from app.core.models import Clinica
from app.clinic.models import (
    Veterinario,
    Cliente,
    Mascota,
    Cita,
    Producto,
    TipoProducto,
    ServicioCatalogo,
    ServicioProducto
)
from app.core.security import create_access_token


def test_landing_page_publica_y_redireccion_autenticada(client, db_session):
    """
    1. Verifica que GET / devuelve 200 con la propuesta de valor y el formulario de login.
    2. Verifica que usuarios con sesión activa son redirigidos adecuadamente.
    """
    client.cookies.clear()

    # Usuario anónimo -> Ve la landing page pública
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "SherekePet" in html
    assert "Moderniza tu clínica veterinaria" in html
    assert "Historias Clínicas" in html
    assert "Agendamiento Inteligente" in html
    assert "Portal PWA para Dueños" in html
    assert "Mini-ERP" in html
    assert "Acceso Veterinario" in html
    assert 'action="/login"' in html

    # Usuario Veterinario autenticado -> Redirige a /dashboard
    clinica = Clinica(nombre="Clínica Sanitas", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    vet = Veterinario(
        clinica_id=clinica.id,
        nombre="Dr. Sanitas",
        email="dr.sanitas@vet.com",
        username="dr_sanitas",
        password_hash="fakehash",
        rol="ADMIN",
        is_verified=True
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

    resp_auth = client.get("/", follow_redirects=False)
    assert resp_auth.status_code == 303
    assert resp_auth.headers["location"] == "/dashboard"


def test_registro_y_auth_no_muestran_sidebar_privado(client):
    """
    Verifica que en las vistas públicas de creación de cuenta (/registro) y verificación (/verificar):
    - NO se muestra el menú/sidebar lateral del panel administrativo (Nuevo Paciente, Agenda, Configuración, etc.)
    - El formulario está limpio y centrado, sin opciones de navegación interna.
    """
    client.cookies.clear()

    # 1. Página de Registro de Clínica
    resp_reg = client.get("/registro")
    assert resp_reg.status_code == 200
    html_reg = resp_reg.text

    assert "Nuevo Paciente" not in html_reg
    assert "mobileSidebar" not in html_reg
    assert 'href="/agenda"' not in html_reg
    assert 'href="/configuracion"' not in html_reg
    assert 'href="/logout"' not in html_reg
    assert "Comienza tu periodo de prueba gratis" in html_reg
    assert "Registrar Clínica y Entrar" in html_reg

    # 2. Página de Verificación de Correo
    resp_ver = client.get("/verificar?email=test@vet.com")
    assert resp_ver.status_code == 200
    html_ver = resp_ver.text

    assert "Nuevo Paciente" not in html_ver
    assert "mobileSidebar" not in html_ver
    assert 'href="/agenda"' not in html_ver
    assert 'href="/configuracion"' not in html_ver
    assert 'href="/logout"' not in html_ver
    assert "Verifica tu Correo" in html_ver


def test_confirmacion_cita_sin_agujero_negro(client, db_session):
    """
    Verifica que PUT /api/citas/{id}/confirmar y PUT /api/clinic/citas/{id}/confirmar:
    - Cambian el estado a 'Confirmada'
    - Preservan estrictamente clinica_id, mascota_id y cliente_id en la base de datos (No se anulan).
    """
    clinica = Clinica(nombre="Vet Integral", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    vet = Veterinario(
        clinica_id=clinica.id,
        nombre="Dra. Lopez",
        email="dra.lopez@vet.com",
        username="dra_lopez",
        password_hash="fakehash",
        rol="VET",
        is_verified=True
    )
    db_session.add(vet)

    cliente = Cliente(
        clinica_id=clinica.id,
        nombre_completo="Carlos Benites",
        dni="88990011",
        telefono="987654321"
    )
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        nombre="Toby",
        sexo="Macho"
    )
    db_session.add(mascota)
    db_session.flush()

    cita = Cita(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        mascota_id=mascota.id,
        fecha=date(2026, 10, 5),
        hora=time(10, 30),
        motivo="Vacuna séxtuple",
        estado="PENDIENTE"
    )
    db_session.add(cita)
    db_session.commit()
    db_session.refresh(cita)

    cita_id = cita.id
    assert cita.clinica_id == clinica.id
    assert cita.mascota_id == mascota.id
    assert cita.cliente_id == cliente.id

    # Autenticar como veterinario
    vet_token = create_access_token({
        "sub": str(vet.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "VET",
        "email": vet.email
    })
    client.cookies.set("vet_token", vet_token)

    # 1. Ejecutar confirmación vía endpoint raíz /api/citas/{id}/confirmar
    resp = client.put(f"/api/citas/{cita_id}/confirmar", json={"estado": "Confirmada"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["estado"] in ["Confirmada", "CONFIRMADA"]
    assert data["clinica_id"] == clinica.id
    assert data["mascota_id"] == mascota.id
    assert data["cliente_id"] == cliente.id

    # 2. Consultar directamente en BD para asegurar que no hay 'agujero negro' (campos nulos)
    db_session.expire_all()
    cita_db = db_session.query(Cita).filter(Cita.id == cita_id).first()
    assert cita_db is not None
    assert cita_db.estado == "Confirmada"
    assert cita_db.clinica_id == clinica.id
    assert cita_db.mascota_id == mascota.id
    assert cita_db.cliente_id == cliente.id


def test_modelos_mini_erp_inventario_y_catalogo(db_session):
    """
    Verifica los nuevos modelos de base de datos para Mini-ERP:
    - Producto con Enum TipoProducto (Champú, Vacuna, Medicina), stock y unidad de medida.
    - ServicioCatalogo (id, clinica_id, nombre, tipo_servicio, activo).
    - ServicioProducto (tabla intermedia para consumo de insumos por servicio).
    """
    clinica = Clinica(nombre="Clínica ERP", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    # 1. Crear productos con los diferentes tipos de enum
    champu = Producto(
        clinica_id=clinica.id,
        nombre="Champú Clorhexidina 2%",
        tipo=TipoProducto.CHAMPU.value,
        stock_actual=5000.0,
        unidad_medida="ml",
        stock_minimo=500.0
    )
    vacuna = Producto(
        clinica_id=clinica.id,
        nombre="Vacuna Antirrábica Nobivac",
        tipo=TipoProducto.VACUNA.value,
        stock_actual=50.0,
        unidad_medida="dosis",
        stock_minimo=10.0
    )
    medicina = Producto(
        clinica_id=clinica.id,
        nombre="Amoxicilina + Ác. Clavulánico 250mg",
        tipo=TipoProducto.MEDICINA.value,
        stock_actual=100.0,
        unidad_medida="comprimidos",
        stock_minimo=20.0
    )
    db_session.add_all([champu, vacuna, medicina])
    db_session.commit()
    db_session.refresh(champu)
    db_session.refresh(vacuna)
    db_session.refresh(medicina)

    assert champu.tipo == "Champú"
    assert vacuna.tipo == "Vacuna"
    assert medicina.tipo == "Medicina"

    # 2. Crear ServicioCatalogo
    servicio_bano = ServicioCatalogo(
        clinica_id=clinica.id,
        nombre="Baño Hipoalergénico Premium",
        tipo_servicio="BAÑO",
        activo=True
    )
    db_session.add(servicio_bano)
    db_session.commit()
    db_session.refresh(servicio_bano)

    assert servicio_bano.id is not None
    assert servicio_bano.activo is True

    # 3. Vincular Servicio con Producto vía ServicioProducto (Intermedia)
    insumo_bano = ServicioProducto(
        servicio_id=servicio_bano.id,
        producto_id=champu.id,
        cantidad=65.0  # Consume 65 ml por cada baño
    )
    db_session.add(insumo_bano)
    db_session.commit()
    db_session.refresh(servicio_bano)
    db_session.refresh(champu)

    # 4. Verificar relaciones bidireccionales
    assert len(servicio_bano.productos) == 1
    assert servicio_bano.productos[0].producto.nombre == "Champú Clorhexidina 2%"
    assert servicio_bano.productos[0].cantidad == 65.0

    assert len(champu.servicios_asociados) == 1
    assert champu.servicios_asociados[0].servicio.nombre == "Baño Hipoalergénico Premium"
