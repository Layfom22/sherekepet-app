import pytest
from datetime import date, time, timedelta
from app.core.models import Clinica
from app.clinic.models import Cliente, Mascota, AtencionClinica, Cita
from app.follow_up.models import MedicationPlan, DoseTracking
from app.core.security import create_access_token
from app.core.timezone import get_lima_now
from app.follow_up.routes import extraer_detalle_receta


def test_extraer_detalle_receta():
    """Valida la función helper que extrae los datos de prescripción médica."""
    texto = "Prescripción Médica: Amoxicilina 500mg | Frecuencia: Cada 8 horas | Cantidad/Dosis: 1 pastilla"
    receta, resto = extraer_detalle_receta(texto)
    assert receta is not None
    assert receta["medicamento"] == "Amoxicilina 500mg"
    assert receta["frecuencia"] == "Cada 8 horas"
    assert receta["cantidad"] == "1 pastilla"
    assert resto is None

    # Con emoji y texto complementario
    texto_con_resto = "Control post operatorio.\n💊 Prescripción Médica: Meloxicam 1mg | Frecuencia: Cada 24 horas | Cantidad/Dosis: media tableta\nTomar con alimentos."
    receta2, resto2 = extraer_detalle_receta(texto_con_resto)
    assert receta2 is not None
    assert receta2["medicamento"] == "Meloxicam 1mg"
    assert receta2["frecuencia"] == "Cada 24 horas"
    assert receta2["cantidad"] == "media tableta"
    assert "Control post operatorio" in resto2
    assert "Tomar con alimentos" in resto2


def test_visibilidad_receta_en_carnet_dueño(client, db_session):
    """
    Tarea 1: En la vista del Carnet (/portal/carnet/{id}), dentro del historial de atenciones,
    se renderiza claramente la receta con nombre de medicamento, y badge resaltado con cantidad y frecuencia.
    """
    clinica = Clinica(nombre="Vet Care Lima", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    cliente = Cliente(
        clinica_id=clinica.id,
        dni="12345678",
        nombre_completo="Ana Torres"
    )
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        nombre="Bobby",
        especie="Canino",
        raza="Golden Retriever"
    )
    db_session.add(mascota)
    db_session.flush()

    # Registrar atención clínica con receta
    tratamiento_texto = "💊 Prescripción Médica: Amoxicilina 500mg | Frecuencia: Cada 8 horas | Cantidad/Dosis: 1 pastilla\nAdministrar por 7 días seguidos."
    atencion = AtencionClinica(
        clinica_id=clinica.id,
        mascota_id=mascota.id,
        tipo_atencion="CONSULTA",
        motivo="Infección leve en la piel",
        diagnostico="Dermatitis bacteriana superficial",
        tratamiento=tratamiento_texto
    )
    db_session.add(atencion)
    db_session.commit()

    token = create_access_token(data={"sub": str(cliente.id), "role": "client"})
    client.cookies.set("client_token", token)

    resp = client.get(f"/portal/carnet/{mascota.id}")
    assert resp.status_code == 200
    html = resp.text

    # Validar que los campos estructurados de la receta se renderizan
    assert "Prescripción Médica" in html or "Receta" in html
    assert "Amoxicilina 500mg" in html
    assert "1 pastilla" in html
    assert "Cada 8 horas" in html
    assert "Administrar por 7 días seguidos" in html


def test_visibilidad_tratamientos_activos_con_badge(client, db_session):
    """
    Tarea 1: En la sección de Tratamientos Activos del Carnet, se muestra el badge
    con cantidad y frecuencia destacada (Ej: 1 dosis cada 8 horas).
    """
    clinica = Clinica(nombre="Vet Clinic", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    cliente = Cliente(clinica_id=clinica.id, dni="87654321", nombre_completo="Carlos Ruiz")
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(clinica_id=clinica.id, cliente_id=cliente.id, nombre="Rocky", especie="Canino")
    db_session.add(mascota)
    db_session.flush()

    plan = MedicationPlan(
        pet_id=mascota.id,
        clinic_id=clinica.id,
        medicamento="Cefalexina 300mg",
        frecuencia_horas=12,
        total_dosis=14,
        es_estricto=False,
        estado="ACTIVO"
    )
    db_session.add(plan)
    db_session.flush()

    dosis = DoseTracking(
        plan_id=plan.id,
        numero_dosis=1,
        hora_programada=get_lima_now() + timedelta(hours=2),
        estado="PENDIENTE"
    )
    db_session.add(dosis)
    db_session.commit()

    token = create_access_token(data={"sub": str(cliente.id), "role": "client"})
    client.cookies.set("client_token", token)

    resp = client.get(f"/portal/carnet/{mascota.id}")
    assert resp.status_code == 200
    html = resp.text

    assert "Cefalexina 300mg" in html
    assert "1 dosis cada 12 horas" in html
    assert "14 tomas programadas" in html


def test_tarjeta_notificacion_bano_sugerido_dashboard(client, db_session):
    """
    Tarea 2: Si el veterinario agendó un 'Próximo Baño' en estado sugerido,
    se muestra la tarjeta de notificación en el Dashboard del paciente:
    'Tienes una sugerencia de baño para [Nombre Mascota] el [Fecha]. ¿Deseas confirmar la hora?'
    """
    clinica = Clinica(nombre="Grooming & Spa Canino", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    cliente = Cliente(clinica_id=clinica.id, dni="99887766", nombre_completo="Lucía Morales")
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(clinica_id=clinica.id, cliente_id=cliente.id, nombre="Luna", especie="Canino")
    db_session.add(mascota)
    db_session.flush()

    fecha_sugerida = get_lima_now().date() + timedelta(days=21)
    cita_sugerida = Cita(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        mascota_id=mascota.id,
        fecha=fecha_sugerida,
        hora=time(10, 0),
        motivo="Próximo Baño y Grooming (Recurrencia)",
        estado="SUGERIDA"
    )
    db_session.add(cita_sugerida)
    db_session.commit()

    token = create_access_token(data={"sub": str(cliente.id), "role": "client"})
    client.cookies.set("client_token", token)

    resp = client.get("/portal/dashboard")
    assert resp.status_code == 200
    html = resp.text

    # Mensaje exacto de notificación requerido
    assert "Tienes una sugerencia de baño para" in html
    assert "Luna" in html
    assert fecha_sugerida.strftime("%d/%m/%Y") in html
    assert "¿Deseas confirmar la hora?" in html
    assert f"card-sugerencia-{cita_sugerida.id}" in html
    assert "Confirmar Hora" in html


def test_confirmar_y_descartar_cita_sugerida_desde_celular(client, db_session):
    """
    Tarea 2: Permite al paciente seleccionar la hora exacta y confirmar la cita sugerida
    directamente desde su celular vía POST /api/portal/citas/{cita_id}/confirmar.
    Y también descartar la sugerencia vía POST /api/portal/citas/{cita_id}/descartar.
    """
    clinica = Clinica(nombre="Pet Center", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    cliente = Cliente(clinica_id=clinica.id, dni="11223344", nombre_completo="Rodrigo Vega")
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(clinica_id=clinica.id, cliente_id=cliente.id, nombre="Toby", especie="Canino")
    db_session.add(mascota)
    db_session.flush()

    fecha_sugerida = get_lima_now().date() + timedelta(days=15)
    cita_sugerida = Cita(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        mascota_id=mascota.id,
        fecha=fecha_sugerida,
        hora=time(10, 0),
        motivo="Próximo Baño y Grooming (Recurrencia)",
        estado="SUGERIDA"
    )
    db_session.add(cita_sugerida)
    db_session.commit()

    token = create_access_token(data={"sub": str(cliente.id), "role": "client"})
    client.cookies.set("client_token", token)

    # 1. El paciente confirma seleccionando la hora exacta: 11:30
    payload_confirm = {"hora": "11:30"}
    resp = client.post(f"/api/portal/citas/{cita_sugerida.id}/confirmar", json=payload_confirm)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["cita"]["estado"] == "CONFIRMADA"

    # Verificar en base de datos
    db_session.expire_all()
    cita_db = db_session.query(Cita).filter(Cita.id == cita_sugerida.id).first()
    assert cita_db.estado == "CONFIRMADA"
    assert cita_db.hora == time(11, 30)

    # 2. Descartar una cita sugerida
    cita_sugerida_2 = Cita(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        mascota_id=mascota.id,
        fecha=fecha_sugerida + timedelta(days=5),
        hora=time(15, 0),
        motivo="Próximo Baño Quincenal",
        estado="SUGERIDA"
    )
    db_session.add(cita_sugerida_2)
    db_session.commit()

    resp_desc = client.post(f"/api/portal/citas/{cita_sugerida_2.id}/descartar")
    assert resp_desc.status_code == 200
    db_session.expire_all()
    cita_db2 = db_session.query(Cita).filter(Cita.id == cita_sugerida_2.id).first()
    assert cita_db2.estado == "CANCELADA"
