import base64
from datetime import date, timedelta
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.core.timezone import get_lima_now
from app.core.security import decode_access_token
from app.database import get_db
from app.core.models import Clinica
from app.clinic.models import (
    Especie,
    Raza,
    Cliente,
    Mascota,
    Veterinario,
    AtencionClinica,
    RegistroVacuna,
    SeguimientoNotificacion
)
from app.clinic.schemas import (
    ReniecResponse,
    EspecieConRazas,
    PacienteRapidoRequest,
    PacienteRapidoResponse,
    ClienteSummary,
    MascotaSummary,
    AtencionCreateRequest,
    AtencionResponse,
    SeguimientoUpdateResponse,
    LogoUploadResponse
)
from app.clinic.services.reniec_service import consultar_dni_reniec
from app.clinic.services.whatsapp_service import generar_enlace_whatsapp

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(tags=["Clínica"])


# ==========================================
# 0. MURO DE CONTENCIÓN: SEGURIDAD POR ROLES
# ==========================================

def verificar_acceso_veterinario(request: Request) -> None:
    """
    Muro de Contención: Impide que usuarios con rol 'client' accedan
    al panel operativo o APIs administrativas de la clínica.
    """
    token = request.cookies.get("client_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]

    if token:
        payload = decode_access_token(token)
        if payload and payload.get("role") == "client":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso denegado: Los clientes solo tienen autorización para acceder a su portal de mascotas (/portal)."
            )


# ==========================================
# 1. ENDPOINTS DE API REST
# ==========================================

@router.get(
    "/api/reniec/dni/{dni}",
    response_model=ReniecResponse,
    status_code=status.HTTP_200_OK,
    summary="Consulta de DNI en RENIEC",
    description="Proxy seguro hacia apis.net.pe con Bearer token y validación de 8 dígitos.",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
async def get_reniec_dni(dni: str):
    datos = await consultar_dni_reniec(dni)
    return ReniecResponse(**datos)


@router.get(
    "/api/clinic/catalogo",
    response_model=List[EspecieConRazas],
    summary="Catálogo de Especies y Razas",
    description="Retorna las especies con sus respectivas razas para autocompletado reactivo.",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def get_catalogo_especies(db: Session = Depends(get_db)):
    return db.query(Especie).order_by(Especie.nombre.asc()).all()


@router.post(
    "/api/clinic/logo",
    response_model=LogoUploadResponse,
    summary="Subir Logo de la Clínica (Base64)",
    description="Carga imagen del logo, la convierte a Base64 con data URI y la guarda en la clínica.",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
async def upload_logo_clinica(
    file: UploadFile = File(...),
    clinica_id: int = Form(1),
    db: Session = Depends(get_db)
):
    clinica = db.query(Clinica).filter(Clinica.id == clinica_id, Clinica.is_deleted == False).first()
    if not clinica:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clínica no encontrada.")

    tipos_validos = {"image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"}
    content_type = file.content_type or "image/png"
    if content_type not in tipos_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de imagen inválido. Solo se admiten PNG, JPEG, WEBP y SVG."
        )

    contenido = await file.read()
    if len(contenido) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo excede el tamaño máximo permitido (5MB)."
        )

    b64_encoded = base64.b64encode(contenido).decode("utf-8")
    data_uri = f"data:{content_type};base64,{b64_encoded}"

    clinica.logo_b64 = data_uri
    db.commit()

    return LogoUploadResponse(
        mensaje="Logo de la clínica actualizado correctamente.",
        logo_b64=data_uri
    )


@router.post(
    "/api/clinic/paciente-rapido",
    response_model=PacienteRapidoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registro rápido de Paciente y Dueño (Cero Fricción)",
    description="Crea o actualiza el Cliente y registra su Mascota con catálogos y ficha médica en una sola transacción.",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def registrar_paciente_rapido(
    payload: PacienteRapidoRequest,
    db: Session = Depends(get_db)
):
    # 1. Verificar si la clínica existe
    clinica = db.query(Clinica).filter(
        Clinica.id == payload.clinica_id,
        Clinica.is_deleted == False
    ).first()
    if not clinica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La clínica especificada no existe o fue dada de baja."
        )

    # 2. Buscar o crear Cliente
    cliente = db.query(Cliente).filter(
        Cliente.clinica_id == payload.clinica_id,
        Cliente.dni == payload.dni,
        Cliente.is_deleted == False
    ).first()

    nombre_completo = payload.nombre_completo
    if not nombre_completo:
        partes = [p.strip() for p in (payload.nombres, payload.apellido_paterno, payload.apellido_materno) if p]
        nombre_completo = " ".join(partes) if partes else None

    if not cliente:
        cliente = Cliente(
            clinica_id=payload.clinica_id,
            dni=payload.dni,
            nombres=payload.nombres,
            apellido_paterno=payload.apellido_paterno,
            apellido_materno=payload.apellido_materno,
            nombre_completo=nombre_completo,
            telefono=payload.telefono,
            pin_hash=None
        )
        db.add(cliente)
        db.flush()
    else:
        if not cliente.nombre_completo and nombre_completo:
            cliente.nombre_completo = nombre_completo
        if not cliente.telefono and payload.telefono:
            cliente.telefono = payload.telefono
        db.flush()

    # 3. Resolver nombres de Especie y Raza desde Catálogo si se enviaron IDs
    nombre_especie = payload.mascota_especie or "Canino"
    if payload.especie_id:
        esp_obj = db.query(Especie).filter(Especie.id == payload.especie_id).first()
        if esp_obj:
            nombre_especie = esp_obj.nombre

    nombre_raza = payload.mascota_raza
    if payload.raza_id:
        raza_obj = db.query(Raza).filter(Raza.id == payload.raza_id).first()
        if raza_obj:
            nombre_raza = raza_obj.nombre

    alergias_legado = payload.detalle_alergias if payload.tiene_alergias else payload.mascota_alergias

    # 4. Registrar Mascota
    mascota = Mascota(
        clinica_id=payload.clinica_id,
        cliente_id=cliente.id,
        especie_id=payload.especie_id,
        raza_id=payload.raza_id,
        nombre=payload.mascota_nombre.strip(),
        especie=nombre_especie,
        raza=nombre_raza,
        peso=payload.mascota_peso,
        tiene_alergias=payload.tiene_alergias,
        detalle_alergias=payload.detalle_alergias if payload.tiene_alergias else None,
        condiciones_previas=payload.condiciones_previas.strip() if payload.condiciones_previas else None,
        alergias=alergias_legado
    )
    db.add(mascota)
    db.commit()
    db.refresh(cliente)
    db.refresh(mascota)

    return PacienteRapidoResponse(
        mensaje="Paciente y dueño registrados con éxito.",
        cliente=ClienteSummary.model_validate(cliente),
        mascota=MascotaSummary.model_validate(mascota)
    )


@router.post(
    "/api/clinic/atenciones",
    response_model=AtencionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar Atención Clínica y Digitalización de Vacunas",
    description="Guarda la atención médica. Si es 'VACUNACION', guarda la vacuna con sus enfermedades cubiertas y genera el seguimiento.",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def registrar_atencion(
    payload: AtencionCreateRequest,
    db: Session = Depends(get_db)
):
    mascota = db.query(Mascota).filter(
        Mascota.id == payload.mascota_id,
        Mascota.clinica_id == payload.clinica_id,
        Mascota.is_deleted == False
    ).first()

    if not mascota:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La mascota especificada no existe en esta clínica."
        )

    # Actualizar peso actual de la mascota si se proporcionó
    if payload.peso_actual_kg is not None:
        mascota.peso = payload.peso_actual_kg

    atencion = AtencionClinica(
        clinica_id=payload.clinica_id,
        mascota_id=payload.mascota_id,
        veterinario_id=payload.veterinario_id,
        tipo_atencion=payload.tipo_atencion,
        motivo=payload.motivo,
        diagnostico=payload.diagnostico,
        tratamiento=payload.tratamiento,
        peso_actual_kg=payload.peso_actual_kg
    )
    db.add(atencion)
    db.flush()

    vacuna_id = None
    seguimiento_id = None
    enfermedades_lista = payload.enfermedades_cubiertas

    # Lógica para VACUNACION
    if payload.tipo_atencion == "VACUNACION":
        tipo_vacuna = payload.tipo_vacuna or "Vacuna General"
        fecha_aplicacion = payload.fecha_aplicacion or get_lima_now().date()
        fecha_refuerzo = payload.fecha_proximo_refuerzo or (fecha_aplicacion + timedelta(days=365))

        enfermedades_json = json.dumps(enfermedades_lista, ensure_ascii=False) if enfermedades_lista else None

        vacuna = RegistroVacuna(
            clinica_id=payload.clinica_id,
            mascota_id=mascota.id,
            atencion_id=atencion.id,
            tipo_vacuna=tipo_vacuna,
            marca_lote=payload.marca_lote,
            fecha_aplicacion=fecha_aplicacion,
            fecha_proximo_refuerzo=fecha_refuerzo,
            estado="VIGENTE",
            enfermedades_cubiertas=enfermedades_json
        )
        db.add(vacuna)
        db.flush()
        vacuna_id = vacuna.id

        # Crear fila automática de Seguimiento / Recordatorio
        cliente = mascota.cliente
        dueno_nombre = cliente.nombre_completo or "Estimado(a) cliente"
        fecha_str = fecha_refuerzo.strftime("%d/%m/%Y")
        mensaje = (
            f"Hola {dueno_nombre}, te saludamos de SherekePet. "
            f"Te recordamos que a tu mascota {mascota.nombre} le corresponde su refuerzo de la vacuna "
            f"{tipo_vacuna} el día {fecha_str}. ¡Responde a este mensaje para agendar su cita!"
        )

        seguimiento = SeguimientoNotificacion(
            clinica_id=payload.clinica_id,
            cliente_id=mascota.cliente_id,
            mascota_id=mascota.id,
            tipo="REFUERZO_VACUNA",
            fecha_programada=fecha_refuerzo,
            mensaje_plantilla=mensaje,
            estado="PENDIENTE"
        )
        db.add(seguimiento)
        db.flush()
        seguimiento_id = seguimiento.id

    db.commit()

    return AtencionResponse(
        id=atencion.id,
        tipo_atencion=atencion.tipo_atencion,
        motivo=atencion.motivo,
        mascota_id=atencion.mascota_id,
        vacuna_id=vacuna_id,
        seguimiento_id=seguimiento_id,
        enfermedades_cubiertas=enfermedades_lista,
        mensaje="Atención registrada correctamente."
    )


@router.patch(
    "/api/clinic/seguimientos/{id}/marcar-enviado",
    response_model=SeguimientoUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Marcar recordatorio como ENVIADO",
    description="Actualiza el estado de la notificación a 'ENVIADO'.",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def marcar_seguimiento_enviado(
    id: int,
    db: Session = Depends(get_db)
):
    seguimiento = db.query(SeguimientoNotificacion).filter(
        SeguimientoNotificacion.id == id,
        SeguimientoNotificacion.is_deleted == False
    ).first()

    if not seguimiento:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seguimiento de notificación no encontrado."
        )

    seguimiento.estado = "ENVIADO"
    db.commit()

    return SeguimientoUpdateResponse(
        id=seguimiento.id,
        estado="ENVIADO",
        mensaje="Seguimiento marcado como enviado correctamente."
    )


# ==========================================
# 2. VISTAS HTML JINJA2 (PANEL VETERINARIO)
# ==========================================

@router.get("/dashboard", response_class=HTMLResponse, summary="Vista Dashboard Veterinario")
def vista_dashboard(
    request: Request,
    q: Optional[str] = None,
    clinica_id: int = 1,
    db: Session = Depends(get_db)
):
    verificar_acceso_veterinario(request)

    clinica = db.query(Clinica).filter(Clinica.id == clinica_id, Clinica.is_deleted == False).first()
    if not clinica:
        clinica = Clinica(
            id=1,
            nombre="Clínica Veterinaria SherekePet",
            zona_horaria="America/Lima",
            plan_activo="solo"
        )
        db.add(clinica)
        db.commit()
        db.refresh(clinica)

    hoy = get_lima_now().date()

    # KPI 1: Atenciones de hoy
    citas_hoy = db.query(AtencionClinica).filter(
        AtencionClinica.clinica_id == clinica_id,
        AtencionClinica.is_deleted == False,
        func.date(AtencionClinica.created_at) == hoy
    ).count()

    # KPI 2: Refuerzos pendientes para hoy o vencidos
    refuerzos_pendientes_hoy = db.query(SeguimientoNotificacion).filter(
        SeguimientoNotificacion.clinica_id == clinica_id,
        SeguimientoNotificacion.is_deleted == False,
        SeguimientoNotificacion.estado == "PENDIENTE",
        SeguimientoNotificacion.fecha_programada <= hoy
    ).count()

    # KPI 3: Total pacientes registrados
    total_pacientes = db.query(Mascota).filter(
        Mascota.clinica_id == clinica_id,
        Mascota.is_deleted == False
    ).count()

    # Lista de seguimientos pendientes
    seguimientos_query = db.query(SeguimientoNotificacion).filter(
        SeguimientoNotificacion.clinica_id == clinica_id,
        SeguimientoNotificacion.is_deleted == False,
        SeguimientoNotificacion.estado == "PENDIENTE"
    ).order_by(SeguimientoNotificacion.fecha_programada.asc()).limit(15).all()

    seguimientos_con_wa = []
    for s in seguimientos_query:
        telefono = s.cliente.telefono or ""
        enlace_wa = generar_enlace_whatsapp(telefono, s.mensaje_plantilla)
        seguimientos_con_wa.append({
            "id": s.id,
            "tipo": s.tipo,
            "fecha_programada": s.fecha_programada,
            "estado": s.estado,
            "cliente_nombre": s.cliente.nombre_completo or f"DNI {s.cliente.dni}",
            "cliente_telefono": s.cliente.telefono or "Sin teléfono",
            "mascota_nombre": s.mascota.nombre,
            "mascota_id": s.mascota.id,
            "mensaje_plantilla": s.mensaje_plantilla,
            "enlace_whatsapp": enlace_wa
        })

    # Resultados de búsqueda rápida
    resultados_busqueda = []
    if q and q.strip():
        termino = f"%{q.strip()}%"
        resultados_busqueda = db.query(Mascota).join(Cliente).filter(
            Mascota.clinica_id == clinica_id,
            Mascota.is_deleted == False,
            or_(
                Mascota.nombre.ilike(termino),
                Cliente.dni.ilike(termino),
                Cliente.nombre_completo.ilike(termino),
                Cliente.telefono.ilike(termino)
            )
        ).limit(10).all()

    return templates.TemplateResponse(
        request=request,
        name="clinic/dashboard.html",
        context={
            "clinica": clinica,
            "citas_hoy": citas_hoy,
            "refuerzos_pendientes_hoy": refuerzos_pendientes_hoy,
            "total_pacientes": total_pacientes,
            "seguimientos": seguimientos_con_wa,
            "busqueda": q,
            "resultados_busqueda": resultados_busqueda,
            "hoy": hoy
        }
    )


@router.get("/pacientes/nuevo", response_class=HTMLResponse, summary="Formulario Registro Rápido")
def vista_nuevo_paciente(
    request: Request,
    clinica_id: int = 1,
    db: Session = Depends(get_db)
):
    verificar_acceso_veterinario(request)
    clinica = db.query(Clinica).filter(Clinica.id == clinica_id).first()
    especies = db.query(Especie).order_by(Especie.nombre.asc()).all()

    return templates.TemplateResponse(
        request=request,
        name="clinic/paciente_form.html",
        context={
            "clinica": clinica,
            "clinica_id": clinica_id,
            "especies": especies
        }
    )


@router.get("/pacientes/{mascota_id}", response_class=HTMLResponse, summary="Ficha Clínica de la Mascota")
def vista_ficha_mascota(
    request: Request,
    mascota_id: int,
    db: Session = Depends(get_db)
):
    verificar_acceso_veterinario(request)

    mascota = db.query(Mascota).filter(
        Mascota.id == mascota_id,
        Mascota.is_deleted == False
    ).first()

    if not mascota:
        raise HTTPException(status_code=404, detail="Mascota no encontrada.")

    # Atenciones ordenadas descendente por fecha
    atenciones = db.query(AtencionClinica).filter(
        AtencionClinica.mascota_id == mascota_id,
        AtencionClinica.is_deleted == False
    ).order_by(AtencionClinica.created_at.desc()).all()

    # Carnet de vacunas
    vacunas = db.query(RegistroVacuna).filter(
        RegistroVacuna.mascota_id == mascota_id,
        RegistroVacuna.is_deleted == False
    ).order_by(RegistroVacuna.fecha_aplicacion.desc()).all()

    # Deserializar enfermedades cubiertas y preparar WhatsApp
    vacunas_con_wa = []
    hoy = get_lima_now().date()
    for v in vacunas:
        enfermedades = []
        if v.enfermedades_cubiertas:
            try:
                enfermedades = json.loads(v.enfermedades_cubiertas)
            except Exception:
                enfermedades = [v.enfermedades_cubiertas]

        mensaje_refuerzo = (
            f"Hola {mascota.cliente.nombre_completo or 'Estimado(a)'}, te escribimos de SherekePet. "
            f"A tu mascota {mascota.nombre} le corresponde su refuerzo de {v.tipo_vacuna} el {v.fecha_proximo_refuerzo.strftime('%d/%m/%Y')}."
        )
        enlace_wa = generar_enlace_whatsapp(mascota.cliente.telefono or "", mensaje_refuerzo)
        vacunas_con_wa.append({
            "vacuna": v,
            "enfermedades": enfermedades,
            "enlace_whatsapp": enlace_wa,
            "esta_vencida": v.fecha_proximo_refuerzo < hoy
        })

    return templates.TemplateResponse(
        request=request,
        name="clinic/ficha_mascota.html",
        context={
            "mascota": mascota,
            "cliente": mascota.cliente,
            "atenciones": atenciones,
            "vacunas": vacunas_con_wa,
            "hoy": hoy
        }
    )
