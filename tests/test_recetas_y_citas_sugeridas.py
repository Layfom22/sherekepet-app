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


def test_deduplicacion_mascotas_dashboard_dueno(client, db_session):
    """
    Validar que si una mascota con el mismo nombre está registrada en dos veterinarias
    distintas (ej. CITYVET y RoyVetComercial) para el mismo dueño, en el Dashboard aparezca
    SOLO UNA VEZ y el contador de mascotas registradas sea 1.
    """
    c1 = Clinica(nombre="CITYVET", zona_horaria="America/Lima", plan_activo="solo")
    c2 = Clinica(nombre="RoyVetComercial", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add_all([c1, c2])
    db_session.flush()

    # Mismo dueño en ambas clínicas (DNI unificado)
    dueno1 = Cliente(clinica_id=c1.id, dni="70566731", nombre_completo="Roger Cabezudo")
    dueno2 = Cliente(clinica_id=c2.id, dni="70566731", nombre_completo="Roger Cabezudo")
    db_session.add_all([dueno1, dueno2])
    db_session.flush()

    # Princesa registrada en c1 y en c2
    m1 = Mascota(
        clinica_id=c1.id,
        cliente_id=dueno1.id,
        nombre="Princesa",
        especie="Canino",
        raza="Jack Russell Terrier",
        sexo="Hembra"
    )
    m2 = Mascota(
        clinica_id=c2.id,
        cliente_id=dueno2.id,
        nombre="Princesa",
        especie="Canino",
        raza="Jack Russell Terrier",
        sexo="Hembra",
        foto_url="https://r2.sherekepet.com/princesa.webp"
    )
    db_session.add_all([m1, m2])
    db_session.commit()

    token = create_access_token(data={"sub": str(dueno1.id), "role": "client"})
    client.cookies.set("client_token", token)

    resp = client.get("/portal/dashboard")
    assert resp.status_code == 200
    html = resp.text

    # Debe decir 1 mascota registrada (no 2)
    assert "1 mascota registrada" in html
    # Debe tener la foto de la instancia que la tiene
    assert "https://r2.sherekepet.com/princesa.webp" in html


def test_carnet_atenciones_agrupadas_por_veterinario_ordenadas(client, db_session):
    """
    Validar que en el carnet las atenciones de la mascota estén:
    1. Unificadas entre todas las clínicas donde se atendió (CITYVET y RoyVetComercial).
    2. Agrupadas por veterinario.
    3. Ordenadas por quién atendió la última vez (el más reciente aparece primero como Último Médico Tratante).
    """
    from app.clinic.models import Veterinario

    c1 = Clinica(nombre="CITYVET", zona_horaria="America/Lima", plan_activo="solo")
    c2 = Clinica(nombre="RoyVetComercial", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add_all([c1, c2])
    db_session.flush()

    dueno = Cliente(clinica_id=c1.id, dni="70566731", nombre_completo="Roger Cabezudo")
    db_session.add(dueno)
    db_session.flush()

    vet_antiguo = Veterinario(clinica_id=c1.id, nombre="Dr. Carlos CityVet", email="carlos@cityvet.pe")
    vet_reciente = Veterinario(clinica_id=c2.id, nombre="Dr. Roy RoyVet", email="roy@royvet.pe")
    db_session.add_all([vet_antiguo, vet_reciente])
    db_session.flush()

    m1 = Mascota(clinica_id=c1.id, cliente_id=dueno.id, nombre="Princesa", especie="Canino")
    m2 = Mascota(clinica_id=c2.id, cliente_id=dueno.id, nombre="Princesa", especie="Canino")
    db_session.add_all([m1, m2])
    db_session.flush()

    # Atención antigua con Dr. Carlos (hace 10 días)
    at1 = AtencionClinica(
        clinica_id=c1.id,
        mascota_id=m1.id,
        veterinario_id=vet_antiguo.id,
        tipo_atencion="CONSULTA",
        motivo="Vacuna y chequeo en CityVet",
        created_at=get_lima_now() - timedelta(days=10)
    )
    # Atención reciente con Dr. Roy (ayer)
    at2 = AtencionClinica(
        clinica_id=c2.id,
        mascota_id=m2.id,
        veterinario_id=vet_reciente.id,
        tipo_atencion="GROOMING",
        motivo="Baño medicado en RoyVet",
        created_at=get_lima_now() - timedelta(days=1)
    )
    db_session.add_all([at1, at2])
    db_session.commit()

    token = create_access_token(data={"sub": str(dueno.id), "role": "client"})
    client.cookies.set("client_token", token)

    # Entrar al carnet de m1 (debe ver atenciones de m1 y m2)
    resp = client.get(f"/portal/carnet/{m1.id}")
    assert resp.status_code == 200
    html = resp.text

    # Se muestran ambos veterinarios
    assert "Dr. Roy RoyVet" in html
    assert "Dr. Carlos CityVet" in html
    assert "2 atenciones" in html
    assert "2 médicos" in html

    # Dr. Roy fue el más reciente: debe tener el badge de "Último Médico Tratante"
    # Y debe aparecer ANTES en el HTML que Dr. Carlos
    pos_roy = html.find("Dr. Roy RoyVet")
    pos_carlos = html.find("Dr. Carlos CityVet")
    assert pos_roy != -1 and pos_carlos != -1
    assert pos_roy < pos_carlos, "Dr. Roy debe aparecer primero porque atendió más recientemente"
    assert "Último Médico Tratante" in html


def test_citas_pasadas_no_aparecen_en_proximas_citas_dashboard(client, db_session):
    """
    Validar que las citas cuya fecha ya pasó (ej. hace 8 días, como el 22 de septiembre)
    NO aparezcan en la sección 'Mis Próximas Citas' del Dashboard del dueño,
    mientras que las citas futuras sí aparezcan.
    """
    clinica = Clinica(nombre="RoyVetComercial", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    dueno = Cliente(clinica_id=clinica.id, dni="70566731", nombre_completo="Roger Cabezudo")
    db_session.add(dueno)
    db_session.flush()

    mascota = Mascota(clinica_id=clinica.id, cliente_id=dueno.id, nombre="Princesa", especie="Canino")
    db_session.add(mascota)
    db_session.flush()

    hoy = get_lima_now().date()
    cita_pasada = Cita(
        clinica_id=clinica.id,
        cliente_id=dueno.id,
        mascota_id=mascota.id,
        fecha=hoy - timedelta(days=8),
        hora=time(10, 0),
        motivo="Cita Pasada 22 Septiembre",
        estado="PENDIENTE"
    )
    cita_futura = Cita(
        clinica_id=clinica.id,
        cliente_id=dueno.id,
        mascota_id=mascota.id,
        fecha=hoy + timedelta(days=3),
        hora=time(16, 0),
        motivo="Control Futuro Vigente",
        estado="CONFIRMADA"
    )
    db_session.add_all([cita_pasada, cita_futura])
    db_session.commit()

    token = create_access_token(data={"sub": str(dueno.id), "role": "client"})
    client.cookies.set("client_token", token)

    resp = client.get("/portal/dashboard")
    assert resp.status_code == 200
    html = resp.text

    assert "Cita Pasada 22 Septiembre" not in html
    assert "Control Futuro Vigente" in html


def test_actualizar_correo_perfil_dueno_y_sincronizacion_dni(client, db_session):
    """
    Validar que el dueño pueda registrar/actualizar su correo electrónico en 'Editar Mi Perfil'
    (PUT /api/portal/perfil) y que se sincronice en todas las clínicas donde tenga el mismo DNI.
    """
    c1 = Clinica(nombre="CITYVET", zona_horaria="America/Lima", plan_activo="solo")
    c2 = Clinica(nombre="RoyVetComercial", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add_all([c1, c2])
    db_session.flush()

    dueno1 = Cliente(clinica_id=c1.id, dni="70566731", nombre_completo="Roger Cabezudo")
    dueno2 = Cliente(clinica_id=c2.id, dni="70566731", nombre_completo="Roger Cabezudo")
    db_session.add_all([dueno1, dueno2])
    db_session.commit()

    token = create_access_token(data={"sub": str(dueno1.id), "role": "client"})
    client.cookies.set("client_token", token)

    resp = client.put("/api/portal/perfil", json={
        "nombre_completo": "Roger Cabezudo",
        "telefono": "+51 999888777",
        "email": "roger.cabezudo@gmail.com"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "roger.cabezudo@gmail.com"

    db_session.expire_all()
    d1_db = db_session.query(Cliente).filter(Cliente.id == dueno1.id).first()
    d2_db = db_session.query(Cliente).filter(Cliente.id == dueno2.id).first()
    assert d1_db.email == "roger.cabezudo@gmail.com"
    assert d2_db.email == "roger.cabezudo@gmail.com"


def test_reprogramar_dosis_manana_y_noche(client, db_session):
    """
    Validar que para pastillas de 2 veces al día (Mañana y Noche) o cualquier tratamiento activo,
    el dueño pueda ajustar rápidamente la hora de la toma pendiente (ej. 08:00 Mañana o 20:00 Noche).
    """
    clinica = Clinica(nombre="RoyVet", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    dueno = Cliente(clinica_id=clinica.id, dni="70566731", nombre_completo="Roger Cabezudo", email="roger@test.com")
    db_session.add(dueno)
    db_session.flush()

    mascota = Mascota(clinica_id=clinica.id, cliente_id=dueno.id, nombre="Princesa", especie="Canino")
    db_session.add(mascota)
    db_session.flush()

    plan = MedicationPlan(
        pet_id=mascota.id,
        clinic_id=clinica.id,
        medicamento="Prednisolona 20mg",
        frecuencia_horas=12,
        total_dosis=10,
        es_estricto=False,
        estado="ACTIVO"
    )
    db_session.add(plan)
    db_session.flush()

    dosis = DoseTracking(
        plan_id=plan.id,
        numero_dosis=1,
        hora_programada=get_lima_now() + timedelta(hours=3),
        estado="PENDIENTE"
    )
    db_session.add(dosis)
    db_session.commit()

    token = create_access_token(data={"sub": str(dueno.id), "role": "client"})
    client.cookies.set("client_token", token)

    # Ajustar a turno Mañana (08:00)
    resp_manana = client.put(f"/api/medication/dose/{dosis.id}/reprogramar", json={"hora": "08:00"})
    assert resp_manana.status_code == 200
    data_m = resp_manana.json()
    assert data_m["turno"] == "Mañana"
    assert data_m["hora_formateada"] == "08:00 AM"

    # Ajustar a turno Noche (20:00)
    resp_noche = client.put(f"/api/medication/dose/{dosis.id}/reprogramar", json={"hora": "20:00"})
    assert resp_noche.status_code == 200
    data_n = resp_noche.json()
    assert data_n["turno"] == "Noche"
    assert data_n["hora_formateada"] == "08:00 PM"


def test_confirmacion_cita_veterinario_visible_y_notificada_en_portal_dueno(client, db_session):
    """
    Validar que:
    1. El header superior del portal sea neutral ('SherekePet &bull; Portal de Mascotas').
    2. Cuando el veterinario confirma una cita para hoy (guardando estado='Confirmada'),
       el portal del dueño la muestre con el banner de 'Cita Confirmada por Veterinario'
       y el endpoint de tiempo real /api/portal/citas/estado retorne estado='CONFIRMADA'.
    """
    from app.clinic.models import Veterinario

    clinica = Clinica(
        nombre="RoyVet S.A.C.",
        nombre_comercial="RoyVetComercial",
        zona_horaria="America/Lima",
        plan_activo="solo"
    )
    db_session.add(clinica)
    db_session.flush()

    vet = Veterinario(
        clinica_id=clinica.id,
        nombre="Dr. Roy",
        email="roy@royvet.com",
        rol="ADMIN",
        is_verified=True
    )
    dueno = Cliente(
        clinica_id=clinica.id,
        dni="70566731",
        nombre_completo="Roger Cabezudo",
        email="roggerjjj@hotmail.com"
    )
    db_session.add_all([vet, dueno])
    db_session.flush()

    mascota = Mascota(clinica_id=clinica.id, cliente_id=dueno.id, nombre="Princesa", especie="Canino")
    db_session.add(mascota)
    db_session.flush()

    hoy = get_lima_now().date()
    cita_hoy = Cita(
        clinica_id=clinica.id,
        cliente_id=dueno.id,
        mascota_id=mascota.id,
        fecha=hoy,
        hora=time(8, 30),
        motivo="Control general hoy",
        estado="PENDIENTE"
    )
    db_session.add(cita_hoy)
    db_session.commit()

    # 1. El veterinario confirma la cita desde su panel (/api/clinic/citas/{id}/confirmar)
    vet_token = create_access_token({
        "sub": str(vet.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "ADMIN",
        "email": vet.email
    })
    client.cookies.set("vet_token", vet_token)
    resp_vet = client.put(f"/api/clinic/citas/{cita_hoy.id}/confirmar", json={})
    assert resp_vet.status_code == 200
    assert resp_vet.json()["estado"] == "Confirmada"

    # 2. El dueño consulta su portal (/portal/dashboard) y el endpoint de tiempo real (/api/portal/citas/estado)
    client.cookies.clear()
    client_token = create_access_token(data={"sub": str(dueno.id), "role": "client"})
    client.cookies.set("client_token", client_token)

    resp_estado = client.get("/api/portal/citas/estado")
    assert resp_estado.status_code == 200
    citas_rt = resp_estado.json()["citas"]
    assert len(citas_rt) == 1
    assert citas_rt[0]["id"] == cita_hoy.id
    assert citas_rt[0]["estado"] == "CONFIRMADA"
    assert citas_rt[0]["es_hoy"] is True

    resp_dash = client.get("/portal/dashboard")
    assert resp_dash.status_code == 200
    html = resp_dash.text

    # Header neutral en la barra superior + Botón Actualizar página
    assert "SherekePet &bull; Portal de Mascotas" in html
    assert 'id="btnActualizarPaginaPortal"' in html
    # Tarjeta única y limpia de cita confirmada por el veterinario (sin banners redundantes)
    assert "alertaCitaRecienConfirmada" not in html
    assert "✓ Confirmada" in html
    assert "El veterinario aceptó y confirmó tu cita." in html
    # Banner y guía de instalación en pantalla de inicio del celular
    assert 'id="pwaInstallBanner"' in html
    assert 'id="modalGuiaInstalarPwa"' in html




