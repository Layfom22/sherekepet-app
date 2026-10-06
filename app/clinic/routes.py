import base64
import urllib.parse
from datetime import date, time, timedelta
import json
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status, Body, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session

from app.core.timezone import get_lima_now
from app.core.security import decode_access_token, hash_password
from app.database import get_db
from app.services.email_service import enviar_alerta_paciente
from app.auth.service import AuthService
from app.auth.schemas import (
    VetLoginRequest,
    VetRegisterRequest,
    AsistenteCreateRequest,
    ClinicaConfiguracionUpdate
)
import uuid
from app.core.config import settings
from app.core.models import Clinica, PagoSuscripcion
from app.clinic.models import (
    Especie,
    Raza,
    Cliente,
    Mascota,
    Veterinario,
    AtencionClinica,
    RegistroVacuna,
    SeguimientoNotificacion,
    Cita,
    HorarioAtencion,
    Producto,
    ServicioBano
)
from app.core.storage import upload_image_to_r2
from app.clinic.schemas import (
    ReniecResponse,
    EspecieConRazas,
    PacienteRapidoRequest,
    PacienteRapidoResponse,
    ClienteSummary,
    MascotaSummary,
    AtencionCreateRequest,
    AtencionResponse,
    ProductoItem,
    ProductoCreateRequest,
    ProductoUpdateRequest,
    ServicioBanoItem,
    ServicioBanoCreateRequest,
    ProductoStockUpdateRequest,
    SeguimientoUpdateResponse,
    LogoUploadResponse,
    MascotaFotoResponse,
    DiaHorarioItem,
    HorariosConfigRequest,
    HorariosConfigResponse
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


def obtener_veterinario_actual(request: Request, db: Session) -> Optional[Veterinario]:
    """
    Obtiene el usuario en sesión (Veterinario ADMIN o ASISTENTE) a partir de la cookie vet_token
    o del header Authorization Bearer.
    """
    token = request.cookies.get("vet_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]

    if not token:
        return None

    payload = decode_access_token(token)
    if not payload or payload.get("role") == "client":
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    try:
        vet = db.query(Veterinario).filter(
            Veterinario.id == int(user_id),
            Veterinario.is_deleted == False
        ).first()
        if vet:
            if vet.email and vet.email.strip().lower() == "roggerjjj@gmail.com":
                if vet.rol != "SUPER_ADMIN" or not getattr(vet, "is_superadmin", False):
                    vet.rol = "SUPER_ADMIN"
                    vet.is_superadmin = True
                    db.commit()
                    db.refresh(vet)
            elif vet.rol in ["VET", "VETERINARIO"]:
                vet.rol = "ADMIN"
                db.commit()
                db.refresh(vet)
            try:
                hoy = get_lima_now().date()
                vet.citas_pendientes_count = db.query(Cita).filter(
                    Cita.clinica_id == vet.clinica_id,
                    Cita.is_deleted == False,
                    Cita.estado == "PENDIENTE",
                    Cita.fecha >= hoy
                ).count()
            except Exception:
                vet.citas_pendientes_count = 0
        return vet
    except Exception:
        return None


def require_current_vet(
    request: Request,
    db: Session = Depends(get_db)
) -> Veterinario:
    """
    Dependencia estricta para endpoints de clínica:
    1. Bloquea tokens de rol 'client' con 403 Forbidden.
    2. Exige un token válido de veterinario ('vet_token' o Bearer) y retorna el Veterinario activo.
    """
    verificar_acceso_veterinario(request)
    vet = obtener_veterinario_actual(request, db)
    if not vet:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida. Inicie sesión en el panel veterinario."
        )
    if not vet.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Su cuenta de veterinario se encuentra desactivada."
        )
    return vet


# ==========================================
# 1. ENDPOINTS DE API REST
# ==========================================

@router.get(
    "/api/reniec/dni/{dni}",
    response_model=ReniecResponse,
    status_code=status.HTTP_200_OK,
    summary="Consulta de DNI en RENIEC",
    description="Proxy seguro hacia apis.net.pe con Bearer token y validación de 8 dígitos.",
    dependencies=[Depends(require_current_vet)]
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


@router.get(
    "/api/catalogos/especies/{especie_id}/razas",
    summary="Listado de Razas por Especie",
    description="Retorna el listado de razas correspondientes a una especie."
)
def get_razas_por_especie(especie_id: int, db: Session = Depends(get_db)):
    razas = db.query(Raza).filter(
        Raza.especie_id == especie_id
    ).order_by(Raza.nombre.asc()).all()
    return [{"id": r.id, "nombre": r.nombre, "especie_id": r.especie_id} for r in razas]


@router.post(
    "/api/clinic/logo",
    response_model=LogoUploadResponse,
    summary="Subir Logo de la Clínica",
    description="Permite al Administrador de la clínica subir el logo a Cloudflare R2 y actualizar Clinica.logo_url."
)
async def upload_logo_clinica(
    request: Request,
    file: UploadFile = File(...),
    clinica_id: int = Form(1),
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    if current_user.rol == "ASISTENTE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Los asistentes no tienen autorización para cambiar el logo de la clínica."
        )

    target_clinica_id = clinica_id if getattr(current_user, "is_superadmin", False) else current_user.clinica_id
    clinica = db.query(Clinica).filter(Clinica.id == target_clinica_id, Clinica.is_deleted == False).first()
    if not clinica:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clínica no encontrada.")

    tipos_validos = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    content_type = (file.content_type or "image/webp").lower()
    if content_type not in tipos_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de imagen inválido. Solo se admiten PNG, JPEG, WEBP y GIF (SVG no permitido por seguridad)."
        )

    contenido = await file.read()
    if len(contenido) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo excede el tamaño máximo permitido (10MB)."
        )

    try:
        logo_url = await upload_image_to_r2(
            file_bytes=contenido,
            filename=file.filename or "logo.webp",
            folder="logos",
            content_type=content_type
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    clinica.logo_url = logo_url
    db.commit()

    return LogoUploadResponse(
        mensaje="Logo de la clínica actualizado correctamente.",
        logo_url=logo_url,
        logo_b64=logo_url
    )


@router.put(
    "/api/clinic/configuracion",
    summary="Actualizar Configuración de Marca Blanca de la Clínica",
    description="Permite al Administrador de la clínica editar el nombre legal y nombre comercial de su veterinaria."
)
def actualizar_configuracion_clinica(
    payload: ClinicaConfiguracionUpdate,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    if not current_user or current_user.rol == "ASISTENTE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Los asistentes no tienen autorización para editar la configuración de la clínica."
        )

    # Normalizar automáticamente rol de veterinarios titulares
    if current_user.rol in ["VET", "VETERINARIO"]:
        current_user.rol = "ADMIN"
        db.commit()

    clinica = db.query(Clinica).filter(
        Clinica.id == current_user.clinica_id,
        Clinica.is_deleted == False
    ).first()

    if not clinica:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clínica no encontrada.")

    clinica.nombre = payload.nombre.strip()
    clinica.nombre_comercial = payload.nombre_comercial.strip() if payload.nombre_comercial else None
    db.commit()
    db.refresh(clinica)

    return {
        "mensaje": "Configuración guardada exitosamente.",
        "clinica": {
            "id": clinica.id,
            "nombre": clinica.nombre,
            "nombre_comercial": clinica.nombre_comercial,
            "nombre_mostrado": clinica.nombre_mostrado,
            "logo_url": clinica.logo_url
        }
    }


# ==========================================
# HORARIOS Y TURNOS DE ATENCIÓN DE LA CLÍNICA
# ==========================================

DIAS_SEMANA_NOMBRES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def obtener_o_inicializar_horarios(clinica_id: int, db: Session) -> List[HorarioAtencion]:
    """
    Retorna los 7 registros de horarios de atención (Lunes a Domingo) para la clínica.
    Si la clínica no tiene horarios configurados aún, inicializa la plantilla por defecto:
    - Lun - Vie: 09:00 - 13:00 y 15:00 - 18:00 (activo=True)
    - Sáb: 09:00 - 13:00 (activo=True)
    - Dom: Inactivo (activo=False)
    """
    horarios = db.query(HorarioAtencion).filter(
        HorarioAtencion.clinica_id == clinica_id,
        HorarioAtencion.is_deleted == False
    ).order_by(HorarioAtencion.dia_semana.asc()).all()

    if len(horarios) == 7:
        return horarios

    dias_existentes = {h.dia_semana: h for h in horarios}
    horarios_nuevos = []
    for d in range(7):
        if d in dias_existentes:
            continue
        h = HorarioAtencion(
            clinica_id=clinica_id,
            dia_semana=d,
            activo=True,
            hora_inicio_1=time(8, 30),
            hora_fin_1=time(13, 0),
            hora_inicio_2=time(14, 0) if d < 6 else None,
            hora_fin_2=time(18, 0) if d < 6 else None,
            intervalo_minutos=30
        )
        db.add(h)
        horarios_nuevos.append(h)

    if horarios_nuevos:
        db.commit()

    return db.query(HorarioAtencion).filter(
        HorarioAtencion.clinica_id == clinica_id,
        HorarioAtencion.is_deleted == False
    ).order_by(HorarioAtencion.dia_semana.asc()).all()


@router.get(
    "/api/clinic/horarios",
    response_model=HorariosConfigResponse,
    summary="Obtener Horarios de Atención de la Clínica"
)
def get_horarios_clinica(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = current_user.clinica_id

    horarios = obtener_o_inicializar_horarios(target_clinica_id, db)
    intervalo = horarios[0].intervalo_minutos if horarios else 30

    dias_response = []
    for h in horarios:
        dias_response.append(DiaHorarioItem(
            dia_semana=h.dia_semana,
            dia_nombre=DIAS_SEMANA_NOMBRES[h.dia_semana],
            activo=h.activo,
            hora_inicio_1=h.hora_inicio_1.strftime("%H:%M") if h.hora_inicio_1 else "09:00",
            hora_fin_1=h.hora_fin_1.strftime("%H:%M") if h.hora_fin_1 else "13:00",
            hora_inicio_2=h.hora_inicio_2.strftime("%H:%M") if h.hora_inicio_2 else None,
            hora_fin_2=h.hora_fin_2.strftime("%H:%M") if h.hora_fin_2 else None,
            intervalo_minutos=h.intervalo_minutos
        ))

    return HorariosConfigResponse(
        mensaje="Horarios obtenidos correctamente.",
        intervalo_minutos=intervalo,
        dias=dias_response
    )


@router.put(
    "/api/clinic/horarios",
    response_model=HorariosConfigResponse,
    summary="Guardar o Actualizar Horarios de Atención de la Clínica"
)
def update_horarios_clinica(
    payload: HorariosConfigRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = current_user.clinica_id

    # Asegurar que existan los 7 registros
    horarios_actuales = {h.dia_semana: h for h in obtener_o_inicializar_horarios(target_clinica_id, db)}

    def parse_time(val: Optional[str]) -> Optional[time]:
        if not val or not val.strip():
            return None
        partes = val.strip().split(":")
        return time(int(partes[0]), int(partes[1]))

    for item in payload.dias:
        if item.dia_semana in horarios_actuales:
            h = horarios_actuales[item.dia_semana]
            h.activo = item.activo
            h.intervalo_minutos = payload.intervalo_minutos

            t1_ini = parse_time(item.hora_inicio_1) or time(9, 0)
            t1_fin = parse_time(item.hora_fin_1) or time(13, 0)
            h.hora_inicio_1 = t1_ini
            h.hora_fin_1 = t1_fin

            h.hora_inicio_2 = parse_time(item.hora_inicio_2)
            h.hora_fin_2 = parse_time(item.hora_fin_2)

    db.commit()

    # Recargar para respuesta
    horarios_actualizados = obtener_o_inicializar_horarios(target_clinica_id, db)
    dias_response = []
    for h in horarios_actualizados:
        dias_response.append(DiaHorarioItem(
            dia_semana=h.dia_semana,
            dia_nombre=DIAS_SEMANA_NOMBRES[h.dia_semana],
            activo=h.activo,
            hora_inicio_1=h.hora_inicio_1.strftime("%H:%M") if h.hora_inicio_1 else "09:00",
            hora_fin_1=h.hora_fin_1.strftime("%H:%M") if h.hora_fin_1 else "13:00",
            hora_inicio_2=h.hora_inicio_2.strftime("%H:%M") if h.hora_inicio_2 else None,
            hora_fin_2=h.hora_fin_2.strftime("%H:%M") if h.hora_fin_2 else None,
            intervalo_minutos=h.intervalo_minutos
        ))

    return HorariosConfigResponse(
        mensaje="Horarios de atención guardados exitosamente.",
        intervalo_minutos=payload.intervalo_minutos,
        dias=dias_response
    )


# ==========================================
# MINI-ERP: SERVICIOS DE BAÑO E INVENTARIO
# ==========================================

def obtener_o_inicializar_servicios_bano(clinica_id: int, db: Session) -> List[ServicioBano]:
    """Obtiene los servicios de baño de la clínica o inicializa los 3 tipos por defecto con inventario."""
    servicios = db.query(ServicioBano).filter(
        ServicioBano.clinica_id == clinica_id,
        ServicioBano.is_deleted == False
    ).order_by(ServicioBano.id.asc()).all()

    if not servicios:
        # 1. Crear productos estándar de shampoo si no existen
        shampoo_neutro = db.query(Producto).filter(
            Producto.clinica_id == clinica_id,
            Producto.nombre.ilike("%Shampoo Básico%"),
            Producto.is_deleted == False
        ).first()
        if not shampoo_neutro:
            shampoo_neutro = Producto(
                clinica_id=clinica_id,
                nombre="Shampoo Básico Neutro",
                tipo="Champú",
                controlar_stock=True,
                stock_actual=2500.0,
                unidad_medida="ml",
                stock_minimo=250.0,
                precio_costo=35.0,
                precio_venta=0.0
            )
            db.add(shampoo_neutro)
            db.flush()

        shampoo_hipo = db.query(Producto).filter(
            Producto.clinica_id == clinica_id,
            Producto.nombre.ilike("%Hipoalergénico%"),
            Producto.is_deleted == False
        ).first()
        if not shampoo_hipo:
            shampoo_hipo = Producto(
                clinica_id=clinica_id,
                nombre="Shampoo Hipoalergénico Avena",
                tipo="Champú",
                controlar_stock=True,
                stock_actual=1500.0,
                unidad_medida="ml",
                stock_minimo=200.0,
                precio_costo=50.0,
                precio_venta=0.0
            )
            db.add(shampoo_hipo)
            db.flush()

        shampoo_med = db.query(Producto).filter(
            Producto.clinica_id == clinica_id,
            Producto.nombre.ilike("%Medicado%"),
            Producto.is_deleted == False
        ).first()
        if not shampoo_med:
            shampoo_med = Producto(
                clinica_id=clinica_id,
                nombre="Shampoo Medicado Clorhexidina",
                tipo="Champú",
                controlar_stock=True,
                stock_actual=1200.0,
                unidad_medida="ml",
                stock_minimo=150.0,
                precio_costo=65.0,
                precio_venta=0.0
            )
            db.add(shampoo_med)
            db.flush()

        # 2. Crear los 3 servicios estándar
        s1 = ServicioBano(
            clinica_id=clinica_id,
            nombre="Baño Normal / Básico",
            descripcion="Baño relajante con shampoo neutro, secado y cepillado",
            precio=35.0,
            producto_id=shampoo_neutro.id,
            cantidad_consumo=50.0,
            activo=True
        )
        s2 = ServicioBano(
            clinica_id=clinica_id,
            nombre="Baño Hipoalergénico",
            descripcion="Para pieles sensibles o atópicas con extracto de avena",
            precio=50.0,
            producto_id=shampoo_hipo.id,
            cantidad_consumo=50.0,
            activo=True
        )
        s3 = ServicioBano(
            clinica_id=clinica_id,
            nombre="Baño Medicado",
            descripcion="Tratamiento dérmico antiséptico y fungicida",
            precio=65.0,
            producto_id=shampoo_med.id,
            cantidad_consumo=50.0,
            activo=True
        )
        db.add_all([s1, s2, s3])
        db.commit()

        servicios = db.query(ServicioBano).filter(
            ServicioBano.clinica_id == clinica_id,
            ServicioBano.is_deleted == False
        ).order_by(ServicioBano.id.asc()).all()

    return servicios


@router.get(
    "/api/clinic/servicios-bano",
    response_model=List[ServicioBanoItem],
    summary="Listar Servicios de Baño y Consumo de Insumos"
)
def get_servicios_bano(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = current_user.clinica_id

    servicios = obtener_o_inicializar_servicios_bano(target_clinica_id, db)
    resultado = []
    for s in servicios:
        item = ServicioBanoItem(
            id=s.id,
            clinica_id=s.clinica_id,
            nombre=s.nombre,
            precio=s.precio,
            producto_id=s.producto_id,
            cantidad_consumo=s.cantidad_consumo,
            activo=s.activo,
            producto_nombre=s.producto.nombre if s.producto else None,
            stock_actual=s.producto.stock_actual if s.producto else None,
            unidad_medida=s.producto.unidad_medida if s.producto else None
        )
        resultado.append(item)
    return resultado


@router.post(
    "/api/clinic/servicios-bano",
    response_model=ServicioBanoItem,
    status_code=status.HTTP_201_CREATED,
    summary="Crear o Registrar Tipo de Baño"
)
def create_servicio_bano(
    payload: ServicioBanoCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = payload.clinica_id if getattr(current_user, "is_superadmin", False) else current_user.clinica_id

    sb = ServicioBano(
        clinica_id=target_clinica_id,
        nombre=payload.nombre.strip(),
        precio=payload.precio,
        producto_id=payload.producto_id,
        cantidad_consumo=payload.cantidad_consumo,
        activo=payload.activo
    )
    db.add(sb)
    db.commit()
    db.refresh(sb)

    return ServicioBanoItem(
        id=sb.id,
        clinica_id=sb.clinica_id,
        nombre=sb.nombre,
        precio=sb.precio,
        producto_id=sb.producto_id,
        cantidad_consumo=sb.cantidad_consumo,
        activo=sb.activo,
        producto_nombre=sb.producto.nombre if sb.producto else None,
        stock_actual=sb.producto.stock_actual if sb.producto else None,
        unidad_medida=sb.producto.unidad_medida if sb.producto else None
    )


@router.get("/productos", response_class=HTMLResponse, summary="Módulo Mis Productos e Inventario de la Clínica")
def vista_mis_productos(
    request: Request,
    db: Session = Depends(get_db)
):
    verificar_acceso_veterinario(request)
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    target_clinica_id = current_user.clinica_id
    clinica = db.query(Clinica).filter(Clinica.id == target_clinica_id, Clinica.is_deleted == False).first()

    # Asegurar que se inicialicen los insumos base si la clínica es nueva
    obtener_o_inicializar_servicios_bano(target_clinica_id, db)

    productos = db.query(Producto).filter(
        Producto.clinica_id == target_clinica_id,
        Producto.is_deleted == False
    ).order_by(Producto.tipo.asc(), Producto.nombre.asc()).all()

    hoy = get_lima_now().date()
    total_citas_pendientes = db.query(Cita).filter(
        Cita.clinica_id == target_clinica_id,
        Cita.is_deleted == False,
        func.upper(Cita.estado) == "PENDIENTE",
        Cita.fecha >= hoy
    ).count()

    return templates.TemplateResponse(
        request=request,
        name="clinic/productos.html",
        context={
            "clinica": clinica,
            "current_user": current_user,
            "productos": productos,
            "citas_pendientes_count": total_citas_pendientes
        }
    )


@router.get(
    "/api/clinic/productos",
    response_model=List[ProductoItem],
    summary="Listar Productos e Insumos de Inventario"
)
def get_productos_inventario(
    request: Request,
    tipo: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = current_user.clinica_id

    # Asegurar que se inicialicen los insumos por defecto si la clínica es nueva
    obtener_o_inicializar_servicios_bano(target_clinica_id, db)

    query = db.query(Producto).filter(
        Producto.clinica_id == target_clinica_id,
        Producto.is_deleted == False
    )
    if tipo and tipo.strip():
        query = query.filter(func.lower(Producto.tipo) == tipo.strip().lower())

    productos = query.order_by(Producto.nombre.asc()).all()

    return [ProductoItem.model_validate(p) for p in productos]


@router.post(
    "/api/clinic/productos",
    response_model=ProductoItem,
    status_code=status.HTTP_201_CREATED,
    summary="Crear Nuevo Producto en el Inventario del Veterinario"
)
def crear_producto_inventario(
    payload: ProductoCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = current_user.clinica_id

    nombre_limpio = payload.nombre.strip()
    if not nombre_limpio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre del producto es obligatorio."
        )

    usa_stock = bool(payload.controlar_stock)
    nuevo_prod = Producto(
        clinica_id=target_clinica_id,
        nombre=nombre_limpio,
        tipo=(payload.tipo or "Medicina").strip(),
        codigo=payload.codigo.strip() if payload.codigo else None,
        controlar_stock=usa_stock,
        stock_actual=payload.stock_actual if usa_stock else 0.0,
        unidad_medida=(payload.unidad_medida or "unidades").strip(),
        stock_minimo=payload.stock_minimo if usa_stock else 0.0,
        precio_costo=payload.precio_costo,
        precio_venta=payload.precio_venta
    )
    db.add(nuevo_prod)
    db.commit()
    db.refresh(nuevo_prod)
    return ProductoItem.model_validate(nuevo_prod)


@router.put(
    "/api/clinic/productos/{producto_id}",
    response_model=ProductoItem,
    summary="Actualizar Datos de un Producto del Veterinario"
)
def actualizar_producto_inventario(
    producto_id: int,
    payload: ProductoUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = current_user.clinica_id

    prod = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.clinica_id == target_clinica_id,
        Producto.is_deleted == False
    ).first()

    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado en esta clínica."
        )

    if payload.nombre is not None and payload.nombre.strip():
        prod.nombre = payload.nombre.strip()
    if payload.tipo is not None and payload.tipo.strip():
        prod.tipo = payload.tipo.strip()
    if payload.codigo is not None:
        prod.codigo = payload.codigo.strip() or None
    if payload.controlar_stock is not None:
        prod.controlar_stock = payload.controlar_stock
        if not payload.controlar_stock:
            prod.stock_actual = 0.0
            prod.stock_minimo = 0.0
    if payload.stock_actual is not None and prod.controlar_stock:
        prod.stock_actual = payload.stock_actual
    if payload.unidad_medida is not None and payload.unidad_medida.strip():
        prod.unidad_medida = payload.unidad_medida.strip()
    if payload.stock_minimo is not None and prod.controlar_stock:
        prod.stock_minimo = payload.stock_minimo
    if payload.precio_costo is not None:
        prod.precio_costo = payload.precio_costo
    if payload.precio_venta is not None:
        prod.precio_venta = payload.precio_venta

    db.commit()
    db.refresh(prod)
    return ProductoItem.model_validate(prod)


@router.delete(
    "/api/clinic/productos/{producto_id}",
    summary="Eliminar Producto del Inventario del Veterinario"
)
def eliminar_producto_inventario(
    producto_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = current_user.clinica_id

    prod = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.clinica_id == target_clinica_id,
        Producto.is_deleted == False
    ).first()

    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado en esta clínica."
        )

    prod.is_deleted = True
    db.commit()
    return {"mensaje": "Producto eliminado correctamente.", "id": producto_id}


@router.put(
    "/api/clinic/productos/{producto_id}/stock",
    response_model=ProductoItem,
    summary="Actualizar o Reabastecer Stock de un Producto"
)
def update_stock_producto(
    producto_id: int,
    payload: ProductoStockUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = current_user.clinica_id

    prod = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.clinica_id == target_clinica_id,
        Producto.is_deleted == False
    ).first()

    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado en esta clínica."
        )

    prod.stock_actual = payload.stock_actual
    if payload.stock_minimo is not None:
        prod.stock_minimo = payload.stock_minimo
    if payload.unidad_medida:
        prod.unidad_medida = payload.unidad_medida.strip()

    db.commit()
    db.refresh(prod)
    return ProductoItem.model_validate(prod)


class VeterinarioPerfilUpdate(BaseModel):
    nombre: Optional[str] = None
    email: Optional[str] = None
    foto_perfil: Optional[str] = None


@router.put(
    "/api/clinic/perfil",
    summary="Actualizar Perfil del Veterinario",
    description="Permite al veterinario actualizar su nombre, correo y foto de perfil."
)
def actualizar_perfil_veterinario(
    payload: VeterinarioPerfilUpdate,
    request: Request,
    db: Session = Depends(get_db)
):
    verificar_acceso_veterinario(request)
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autorizado.")

    if current_user.rol in ["VET", "VETERINARIO"]:
        current_user.rol = "ADMIN"

    if payload.nombre is not None and payload.nombre.strip():
        current_user.nombre = payload.nombre.strip()
    if payload.email is not None and payload.email.strip():
        email_limpio = payload.email.strip().lower()
        otro = db.query(Veterinario).filter(
            Veterinario.email == email_limpio,
            Veterinario.id != current_user.id,
            Veterinario.is_deleted == False
        ).first()
        if otro:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El correo ya se encuentra registrado por otro usuario.")
        current_user.email = email_limpio
    if payload.foto_perfil is not None:
        current_user.foto_perfil = payload.foto_perfil.strip() or None

    db.commit()
    db.refresh(current_user)

    return {
        "mensaje": "Perfil actualizado exitosamente.",
        "veterinario": {
            "id": current_user.id,
            "nombre": current_user.nombre,
            "email": current_user.email,
            "foto_perfil": current_user.foto_perfil,
            "rol": current_user.rol
        }
    }


@router.post(
    "/api/clinic/perfil/foto",
    summary="Subir Foto de Perfil del Veterinario",
    description="Sube la foto del veterinario a Cloudflare R2 y actualiza Veterinario.foto_perfil."
)
async def upload_foto_veterinario(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    tipos_validos = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    content_type = (file.content_type or "image/webp").lower()
    if content_type not in tipos_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de imagen inválido. Solo se admiten PNG, JPEG, WEBP y GIF (SVG no permitido por seguridad)."
        )

    contenido = await file.read()
    if len(contenido) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo excede el tamaño máximo permitido (10MB)."
        )

    try:
        foto_url = await upload_image_to_r2(
            file_bytes=contenido,
            filename=file.filename or f"vet_{current_user.id}.webp",
            folder="veterinarios",
            content_type=content_type
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    current_user.foto_perfil = foto_url
    db.commit()
    db.refresh(current_user)

    return {
        "mensaje": "Foto de perfil actualizada correctamente.",
        "foto_perfil": foto_url
    }


@router.get(
    "/api/clinic/buscar-dni/{dni}",
    summary="Búsqueda Global de Pacientes por DNI (Cross-Tenant Inteligente)",
    description="Busca un cliente por DNI en toda la red SherekePet y retorna sus mascotas registradas sin historial médico."
)
def buscar_cliente_global_por_dni(
    dni: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    dni_limpio = dni.strip()
    if not dni_limpio or len(dni_limpio) < 4 or len(dni_limpio) > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El documento debe tener entre 4 y 20 caracteres.")

    target_clinica_id = current_user.clinica_id

    clientes = db.query(Cliente).filter(
        Cliente.dni == dni_limpio,
        Cliente.is_deleted == False
    ).order_by(Cliente.created_at.desc()).all()

    if not clientes:
        return {
            "encontrado": False,
            "mensaje": "DNI no encontrado en la red SherekePet."
        }

    cliente = next((c for c in clientes if c.clinica_id == target_clinica_id), clientes[0])

    mascotas_raw = db.query(Mascota).join(Cliente).filter(
        Cliente.dni == dni_limpio,
        Cliente.is_deleted == False,
        Mascota.is_deleted == False
    ).order_by(Mascota.created_at.desc()).all()

    mascotas_por_nombre = {}
    for m in mascotas_raw:
        clave_nom = m.nombre.strip().lower()
        if clave_nom not in mascotas_por_nombre:
            mascotas_por_nombre[clave_nom] = []
        mascotas_por_nombre[clave_nom].append(m)

    mascotas = []
    for clave_nom, lista in mascotas_por_nombre.items():
        local = next((item for item in lista if item.clinica_id == target_clinica_id), None)
        principal = local or lista[0]
        mascotas.append(principal)

    return {
        "encontrado": True,
        "cliente": {
            "id": cliente.id,
            "dni": cliente.dni,
            "nombre_completo": cliente.nombre_completo or f"{cliente.nombres or ''} {cliente.apellido_paterno or ''}".strip(),
            "telefono": cliente.telefono,
            "clinica_id": cliente.clinica_id
        },
        "mascotas": [
            {
                "id": m.id,
                "nombre": m.nombre,
                "especie": m.especie,
                "raza": m.raza,
                "peso": m.peso,
                "sexo": m.sexo,
                "foto_url": m.foto_url,
                "clinica_id": m.clinica_id
            }
            for m in mascotas
        ]
    }


def _asegurar_mascota_local_clinica(
    db: Session,
    mascota_id: int,
    target_clinica_id: int
) -> Optional[Mascota]:
    """
    Asegura que una mascota (creada por el dueño en el Portal o en otra sede)
    tenga su ficha y propietario vinculados en `target_clinica_id`, actualizando
    cualquier cita de esta clínica para apuntar a la ficha local.
    """
    mascota_original = db.query(Mascota).filter(
        Mascota.id == mascota_id,
        Mascota.is_deleted == False
    ).first()
    if not mascota_original:
        return None

    if mascota_original.clinica_id == target_clinica_id:
        return mascota_original

    cliente_original = mascota_original.cliente
    cliente_local = db.query(Cliente).filter(
        Cliente.clinica_id == target_clinica_id,
        Cliente.dni == cliente_original.dni,
        Cliente.is_deleted == False
    ).first()

    if not cliente_local:
        cliente_local = Cliente(
            clinica_id=target_clinica_id,
            dni=cliente_original.dni,
            nombre_completo=cliente_original.nombre_completo,
            telefono=cliente_original.telefono,
            email=cliente_original.email,
            nombres=cliente_original.nombres,
            apellido_paterno=cliente_original.apellido_paterno,
            apellido_materno=cliente_original.apellido_materno,
            pin_hash=cliente_original.pin_hash
        )
        db.add(cliente_local)
        db.flush()

    mascota_local = db.query(Mascota).filter(
        Mascota.clinica_id == target_clinica_id,
        Mascota.cliente_id == cliente_local.id,
        func.lower(func.trim(Mascota.nombre)) == mascota_original.nombre.strip().lower(),
        Mascota.is_deleted == False
    ).first()

    if not mascota_local:
        mascota_local = Mascota(
            clinica_id=target_clinica_id,
            cliente_id=cliente_local.id,
            especie_id=mascota_original.especie_id,
            raza_id=mascota_original.raza_id,
            nombre=mascota_original.nombre,
            especie=mascota_original.especie,
            raza=mascota_original.raza,
            sexo=mascota_original.sexo,
            fecha_nacimiento=mascota_original.fecha_nacimiento,
            peso=mascota_original.peso,
            foto_url=mascota_original.foto_url,
            rasgos_distintivos=mascota_original.rasgos_distintivos,
            alergias=mascota_original.alergias,
            tiene_alergias=mascota_original.tiene_alergias,
            detalle_alergias=mascota_original.detalle_alergias,
            condiciones_previas=mascota_original.condiciones_previas
        )
        db.add(mascota_local)
        db.flush()

    # Actualizar citas de esta clínica que apuntaban al ID externo para que apunten a la ficha local
    citas_ext = db.query(Cita).filter(
        Cita.clinica_id == target_clinica_id,
        Cita.mascota_id == mascota_original.id,
        Cita.is_deleted == False
    ).all()
    for c_item in citas_ext:
        c_item.mascota_id = mascota_local.id
        c_item.cliente_id = cliente_local.id

    db.commit()
    db.refresh(mascota_local)
    return mascota_local


@router.post(
    "/api/clinic/vincular-mascota/{mascota_id}",
    summary="Vincular Mascota Existente a Clínica Actual",
    description="Asocia una mascota existente de la red a la clínica actual del veterinario para abrir su ficha médica."
)
def vincular_mascota_a_clinica(
    mascota_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = current_user.clinica_id

    mascota_local = _asegurar_mascota_local_clinica(db, mascota_id, target_clinica_id)
    if not mascota_local:
        raise HTTPException(status_code=404, detail="Mascota no encontrada.")

    return {
        "mensaje": "Mascota vinculada exitosamente a su clínica.",
        "mascota_id": mascota_local.id
    }


@router.post(
    "/api/mascotas/{mascota_id}/foto",
    response_model=MascotaFotoResponse,
    summary="Subir Foto de la Mascota (Cloudflare R2)",
    description="Sube la foto de la mascota a Cloudflare R2 y actualiza Mascota.foto_url."
)
async def upload_foto_mascota(
    mascota_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    query = db.query(Mascota).filter(Mascota.id == mascota_id, Mascota.is_deleted == False)
    if not getattr(current_user, "is_superadmin", False):
        query = query.filter(Mascota.clinica_id == current_user.clinica_id)
    mascota = query.first()
    if not mascota:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mascota no encontrada en esta clínica.")

    tipos_validos = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    content_type = (file.content_type or "image/webp").lower()
    if content_type not in tipos_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de imagen inválido. Solo se admiten PNG, JPEG, WEBP y GIF (SVG no permitido por seguridad)."
        )

    contenido = await file.read()
    if len(contenido) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo excede el tamaño máximo permitido (10MB)."
        )

    try:
        foto_url = await upload_image_to_r2(
            file_bytes=contenido,
            filename=file.filename or f"mascota_{mascota_id}.webp",
            folder="mascotas",
            content_type=content_type
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    mascota.foto_url = foto_url
    db.commit()

    return MascotaFotoResponse(
        mensaje="Foto de la mascota actualizada correctamente.",
        mascota_id=mascota.id,
        foto_url=foto_url
    )


@router.post(
    "/api/clinic/upload-foto",
    summary="Subir foto temporal de mascota",
    description="Permite subir una foto de mascota antes de crear el registro clínico."
)
async def upload_foto_clinica_temp(
    file: UploadFile = File(...),
    current_user: Veterinario = Depends(require_current_vet)
):
    tipos_validos = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    content_type = (file.content_type or "image/webp").lower()
    if content_type not in tipos_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de imagen inválido. Solo se admiten PNG, JPEG, WEBP y GIF (SVG no permitido por seguridad)."
        )

    contenido = await file.read()
    if len(contenido) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo excede el tamaño máximo permitido (10MB)."
        )

    try:
        foto_url = await upload_image_to_r2(
            file_bytes=contenido,
            filename=file.filename or "mascota.webp",
            folder="mascotas",
            content_type=content_type
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    return {"foto_url": foto_url}


@router.post(
    "/api/clinic/pacientes",
    response_model=PacienteRapidoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registro de Paciente y Dueño (Unificación Global por DNI)",
    description="Crea o reutiliza globalmente el Cliente por DNI y registra su Mascota."
)
@router.post(
    "/api/clinic/paciente-rapido",
    response_model=PacienteRapidoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registro rápido de Paciente y Dueño (Cero Fricción)",
    description="Crea o actualiza el Cliente y registra su Mascota con catálogos y ficha médica en una sola transacción."
)
def registrar_paciente_rapido(
    payload: PacienteRapidoRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = payload.clinica_id if getattr(current_user, "is_superadmin", False) else current_user.clinica_id

    # 1. Verificar si la clínica existe
    clinica = db.query(Clinica).filter(
        Clinica.id == target_clinica_id,
        Clinica.is_deleted == False
    ).first()
    if not clinica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La clínica especificada no existe o fue dada de baja."
        )

    # 2. Unificación Global por DNI: Buscar primero en la clínica actual, y si no, en toda la red SherekePet
    cliente = db.query(Cliente).filter(
        Cliente.clinica_id == target_clinica_id,
        Cliente.dni == payload.dni,
        Cliente.is_deleted == False
    ).first()

    if not cliente:
        # Búsqueda global por DNI para evitar duplicación entre clínicas
        cliente = db.query(Cliente).filter(
            Cliente.dni == payload.dni,
            Cliente.is_deleted == False
        ).first()

    nombre_completo = payload.nombre_completo
    if not nombre_completo:
        partes = [p.strip() for p in (payload.nombres, payload.apellido_paterno, payload.apellido_materno) if p]
        nombre_completo = " ".join(partes) if partes else None

    if not cliente:
        cliente = Cliente(
            clinica_id=target_clinica_id,
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
        # Si ya existe el cliente en la red, actualizar datos de contacto si fueron provistos
        if nombre_completo and nombre_completo.strip():
            cliente.nombre_completo = nombre_completo.strip()
        if payload.telefono and payload.telefono.strip():
            cliente.telefono = payload.telefono.strip()
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

    # 4. Registrar o Actualizar Mascota en la clínica actual (evitando duplicidad sin robar mascotas de otra clínica)
    nombre_mascota_limpio = payload.mascota_nombre.strip()
    mascota_existente = db.query(Mascota).join(Cliente).filter(
        Mascota.clinica_id == target_clinica_id,
        Cliente.dni == payload.dni.strip(),
        Cliente.is_deleted == False,
        func.lower(func.trim(Mascota.nombre)) == nombre_mascota_limpio.lower(),
        Mascota.is_deleted == False
    ).first()

    if mascota_existente:
        mascota_existente.clinica_id = target_clinica_id
        mascota_existente.cliente_id = cliente.id
        if payload.especie_id:
            mascota_existente.especie_id = payload.especie_id
        if payload.raza_id:
            mascota_existente.raza_id = payload.raza_id
        if nombre_especie:
            mascota_existente.especie = nombre_especie
        if nombre_raza:
            mascota_existente.raza = nombre_raza
        if payload.mascota_peso:
            mascota_existente.peso = payload.mascota_peso
        if payload.fecha_nacimiento:
            mascota_existente.fecha_nacimiento = payload.fecha_nacimiento
        if payload.foto_url:
            mascota_existente.foto_url = payload.foto_url
        if payload.tiene_alergias:
            mascota_existente.tiene_alergias = True
            mascota_existente.detalle_alergias = payload.detalle_alergias
        if payload.condiciones_previas:
            mascota_existente.condiciones_previas = payload.condiciones_previas.strip()
        db.commit()
        db.refresh(cliente)
        db.refresh(mascota_existente)
        mascota = mascota_existente
    else:
        mascota = Mascota(
            clinica_id=target_clinica_id,
            cliente_id=cliente.id,
            especie_id=payload.especie_id,
            raza_id=payload.raza_id,
            nombre=nombre_mascota_limpio,
            especie=nombre_especie,
            raza=nombre_raza,
            peso=payload.mascota_peso,
            fecha_nacimiento=payload.fecha_nacimiento,
            foto_url=payload.foto_url,
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


def _notificar_sugerencia_bano_dueno(
    db: Session,
    background_tasks: Optional[BackgroundTasks],
    mascota: Mascota,
    clinica_id: int,
    fecha_sugerida: date,
    hora_obj: time
) -> None:
    """Envía notificación por correo y Web Push al dueño cuando el veterinario sugiere un próximo baño."""
    cliente = mascota.cliente
    if not cliente:
        return

    clinica = db.query(Clinica).filter(Clinica.id == clinica_id).first()
    clinica_nombre = (clinica.nombre_comercial or clinica.nombre) if clinica else "Veterinaria SherekePet"
    cliente_nombre = cliente.nombre_completo or f"DNI {cliente.dni}"
    fecha_str = fecha_sugerida.strftime("%d/%m/%Y")
    hora_str = hora_obj.strftime("%I:%M %p")

    email_destino = (cliente.email or "").strip()
    if not email_destino and cliente.dni:
        otro_cli = db.query(Cliente).filter(
            Cliente.dni == cliente.dni,
            Cliente.email.isnot(None),
            Cliente.email != "",
            Cliente.is_deleted == False
        ).first()
        if otro_cli and otro_cli.email:
            email_destino = otro_cli.email.strip()

    if email_destino:
        from app.core.email import send_bath_suggestion_email
        if background_tasks:
            background_tasks.add_task(
                send_bath_suggestion_email,
                email_destino,
                cliente_nombre,
                mascota.nombre,
                fecha_str,
                hora_str,
                clinica_nombre
            )
        else:
            try:
                send_bath_suggestion_email(
                    email_destino,
                    cliente_nombre,
                    mascota.nombre,
                    fecha_str,
                    hora_str,
                    clinica_nombre
                )
            except Exception:
                pass


@router.post(
    "/api/clinic/atenciones",
    response_model=AtencionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar Atención Clínica y Digitalización de Vacunas",
    description="Guarda la atención médica. Si es 'VACUNACION', guarda la vacuna con sus enfermedades cubiertas y genera el seguimiento."
)
def registrar_atencion(
    payload: AtencionCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = payload.clinica_id if getattr(current_user, "is_superadmin", False) else current_user.clinica_id
    if not getattr(current_user, "is_superadmin", False) and payload.clinica_id != current_user.clinica_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para registrar atenciones en otra clínica."
        )

    mascota = db.query(Mascota).filter(
        Mascota.id == payload.mascota_id,
        Mascota.clinica_id == target_clinica_id,
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

    vet_id_efectivo = payload.veterinario_id if getattr(current_user, "is_superadmin", False) else current_user.id

    atencion = AtencionClinica(
        clinica_id=target_clinica_id,
        mascota_id=payload.mascota_id,
        veterinario_id=vet_id_efectivo,
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
    cita_sugerida_id = None
    enfermedades_lista = payload.enfermedades_cubiertas

    # Lógica para VACUNACION
    if payload.tipo_atencion == "VACUNACION":
        tipo_vacuna = payload.tipo_vacuna or "Vacuna General"
        fecha_aplicacion = payload.fecha_aplicacion or get_lima_now().date()
        fecha_refuerzo = payload.fecha_proximo_refuerzo or (fecha_aplicacion + timedelta(days=365))

        enfermedades_json = json.dumps(enfermedades_lista, ensure_ascii=False) if enfermedades_lista else None

        vacuna = RegistroVacuna(
            clinica_id=target_clinica_id,
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
            clinica_id=target_clinica_id,
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

    # Lógica para Prescripción Médica / Receta (Validación Estricta)
    plan_medicacion_id = None
    if payload.receta_medicamento and payload.receta_medicamento.strip():
        med_nombre = payload.receta_medicamento.strip()
        frec_texto = (payload.receta_frecuencia or "").strip()
        dosis_texto = (payload.receta_dosis or "").strip()

        detalle_receta = f"💊 Prescripción Médica: {med_nombre} | Frecuencia: {frec_texto} | Cantidad/Dosis: {dosis_texto}"
        if atencion.tratamiento:
            atencion.tratamiento = f"{atencion.tratamiento}\n{detalle_receta}"
        else:
            atencion.tratamiento = detalle_receta

        try:
            from app.follow_up.services import crear_plan_medicacion
            frec_h = payload.receta_frecuencia_horas or 8
            tot_d = payload.receta_total_dosis or 10
            plan_obj, _ = crear_plan_medicacion(
                db=db,
                pet_id=mascota.id,
                clinic_id=target_clinica_id,
                medicamento=med_nombre,
                frecuencia_horas=frec_h,
                total_dosis=tot_d,
                es_estricto=False,
                hora_inicio=get_lima_now()
            )
            plan_medicacion_id = plan_obj.id
        except Exception as e:
            logger.warning(f"No se pudo crear el plan de medicación automático: {e}")

    # Lógica para Descuento de Inventario y Sugerencia de Próximo Baño en Grooming / Baños (Mini-ERP)
    stock_descontado = None
    insumo_nombre = None
    stock_restante = None

    if payload.tipo_atencion == "GROOMING":
        servicio_bano = None
        if payload.servicio_bano_id:
            servicio_bano = db.query(ServicioBano).filter(
                ServicioBano.id == payload.servicio_bano_id,
                ServicioBano.clinica_id == target_clinica_id,
                ServicioBano.is_deleted == False
            ).first()

        if not servicio_bano:
            # Buscar el servicio de baño por defecto o primer activo
            servicio_bano = db.query(ServicioBano).filter(
                ServicioBano.clinica_id == target_clinica_id,
                ServicioBano.activo == True,
                ServicioBano.is_deleted == False
            ).first()

        if servicio_bano and servicio_bano.producto_id:
            producto = db.query(Producto).filter(
                Producto.id == servicio_bano.producto_id,
                Producto.clinica_id == target_clinica_id,
                Producto.is_deleted == False
            ).first()
            if producto:
                consumo = servicio_bano.cantidad_consumo or 50.0
                producto.stock_actual = max(0.0, round(float(producto.stock_actual) - float(consumo), 2))
                stock_descontado = consumo
                insumo_nombre = producto.nombre
                stock_restante = producto.stock_actual
                db.flush()

        # Si el veterinario sugirió una próxima fecha de baño directamente en el formulario
        if payload.fecha_proximo_bano:
            hora_sug_obj = time(10, 0)
            if payload.hora_proximo_bano and ":" in payload.hora_proximo_bano:
                try:
                    partes_h = payload.hora_proximo_bano.strip().split(":")
                    hora_sug_obj = time(int(partes_h[0]), int(partes_h[1]))
                except Exception:
                    hora_sug_obj = time(10, 0)

            cita_sugerida = Cita(
                clinica_id=target_clinica_id,
                cliente_id=mascota.cliente_id,
                mascota_id=mascota.id,
                fecha=payload.fecha_proximo_bano,
                hora=hora_sug_obj,
                motivo="Próximo Baño y Grooming (Sugerido)",
                estado="SUGERIDA"
            )
            db.add(cita_sugerida)
            db.flush()
            cita_sugerida_id = cita_sugerida.id

            dueno_nom = (mascota.cliente.nombre_completo if mascota.cliente else None) or "Estimado(a) cliente"
            fecha_bano_str = payload.fecha_proximo_bano.strftime("%d/%m/%Y")
            msg_bano = (
                f"Hola {dueno_nom}, te saludamos de tu veterinaria. "
                f"Te sugerimos programar el próximo baño de {mascota.nombre} para el día {fecha_bano_str}. "
                f"Puedes confirmar tu hora en tu Portal SherekePet o respondiendo a este mensaje."
            )
            seg_bano = SeguimientoNotificacion(
                clinica_id=target_clinica_id,
                cliente_id=mascota.cliente_id,
                mascota_id=mascota.id,
                tipo="PROXIMO_BANO",
                fecha_programada=payload.fecha_proximo_bano,
                mensaje_plantilla=msg_bano,
                estado="PENDIENTE"
            )
            db.add(seg_bano)
            db.flush()
            seguimiento_id = seg_bano.id

    elif payload.tipo_atencion == "VACUNACION" and payload.tipo_vacuna:
        prod_vacuna = db.query(Producto).filter(
            Producto.clinica_id == target_clinica_id,
            func.lower(Producto.nombre) == payload.tipo_vacuna.strip().lower(),
            Producto.is_deleted == False
        ).first()
        if prod_vacuna and prod_vacuna.controlar_stock and prod_vacuna.stock_actual > 0:
            prod_vacuna.stock_actual = max(0.0, round(float(prod_vacuna.stock_actual) - 1.0, 2))
            stock_descontado = 1.0
            insumo_nombre = prod_vacuna.nombre
            stock_restante = prod_vacuna.stock_actual
            db.flush()

    if payload.receta_medicamento and payload.receta_medicamento.strip():
        prod_med = db.query(Producto).filter(
            Producto.clinica_id == target_clinica_id,
            func.lower(Producto.nombre) == payload.receta_medicamento.strip().lower(),
            Producto.is_deleted == False
        ).first()
        if prod_med and prod_med.controlar_stock and prod_med.stock_actual > 0:
            prod_med.stock_actual = max(0.0, round(float(prod_med.stock_actual) - 1.0, 2))
            if stock_descontado is None:
                stock_descontado = 1.0
                insumo_nombre = prod_med.nombre
                stock_restante = prod_med.stock_actual
            db.flush()

    # Marcar automáticamente como ATENDIDA la cita asociada (o las citas activas de hoy para esta mascota)
    hoy_lima = get_lima_now().date()
    if payload.cita_id:
        cita_asociada = db.query(Cita).filter(
            Cita.id == payload.cita_id,
            Cita.clinica_id == target_clinica_id,
            Cita.is_deleted == False
        ).first()
        if cita_asociada:
            cita_asociada.estado = "ATENDIDA"
            cita_asociada.mascota_id = mascota.id
            cita_asociada.cliente_id = mascota.cliente_id

    citas_hoy_mascota = db.query(Cita).join(Mascota, Cita.mascota_id == Mascota.id).join(Cliente, Cita.cliente_id == Cliente.id).filter(
        Cita.clinica_id == target_clinica_id,
        Cita.fecha == hoy_lima,
        Cita.is_deleted == False,
        func.upper(Cita.estado).in_(["PENDIENTE", "CONFIRMADA"]),
        or_(
            Cita.mascota_id == mascota.id,
            and_(
                Cliente.dni == mascota.cliente.dni,
                func.lower(func.trim(Mascota.nombre)) == mascota.nombre.strip().lower()
            )
        )
    ).all()
    for c_hoy in citas_hoy_mascota:
        c_hoy.estado = "ATENDIDA"
        c_hoy.mascota_id = mascota.id
        c_hoy.cliente_id = mascota.cliente_id

    db.commit()

    if payload.tipo_atencion == "GROOMING" and payload.fecha_proximo_bano and cita_sugerida_id:
        hora_notif = time(10, 0)
        if payload.hora_proximo_bano and ":" in payload.hora_proximo_bano:
            try:
                ph = payload.hora_proximo_bano.strip().split(":")
                hora_notif = time(int(ph[0]), int(ph[1]))
            except Exception:
                pass
        _notificar_sugerencia_bano_dueno(
            db=db,
            background_tasks=background_tasks,
            mascota=mascota,
            clinica_id=target_clinica_id,
            fecha_sugerida=payload.fecha_proximo_bano,
            hora_obj=hora_notif
        )

    return AtencionResponse(
        id=atencion.id,
        tipo_atencion=atencion.tipo_atencion,
        motivo=atencion.motivo,
        mascota_id=atencion.mascota_id,
        vacuna_id=vacuna_id,
        seguimiento_id=seguimiento_id,
        cita_sugerida_id=cita_sugerida_id,
        enfermedades_cubiertas=enfermedades_lista,
        plan_medicacion_id=plan_medicacion_id,
        stock_descontado=stock_descontado,
        insumo_nombre=insumo_nombre,
        stock_restante=stock_restante,
        mensaje="Atención registrada correctamente."
    )


@router.patch(
    "/api/clinic/seguimientos/{id}/marcar-enviado",
    response_model=SeguimientoUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Marcar recordatorio como ENVIADO",
    description="Actualiza el estado de la notificación a 'ENVIADO'."
)
def marcar_seguimiento_enviado(
    id: int,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    query = db.query(SeguimientoNotificacion).filter(
        SeguimientoNotificacion.id == id,
        SeguimientoNotificacion.is_deleted == False
    )
    if not getattr(current_user, "is_superadmin", False):
        query = query.filter(SeguimientoNotificacion.clinica_id == current_user.clinica_id)
    seguimiento = query.first()

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


@router.patch(
    "/api/clinic/clientes/{cliente_id}/reset-pin",
    status_code=status.HTTP_200_OK,
    summary="Restablecer PIN de Cliente / Dueño",
    description="Asigna cliente.pin_hash = None para que se le pida crear uno nuevo en su próximo acceso."
)
@router.post(
    "/api/clinic/clientes/{cliente_id}/reset-pin",
    status_code=status.HTTP_200_OK,
    summary="Restablecer PIN de Cliente / Dueño (Alias POST)",
    description="Asigna cliente.pin_hash = None para que se le pida crear uno nuevo en su próximo acceso."
)
def resetear_pin_cliente(
    cliente_id: int,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    cliente = db.query(Cliente).filter(
        Cliente.id == cliente_id,
        Cliente.is_deleted == False
    ).first()

    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cliente no encontrado."
        )

    if not getattr(current_user, "is_superadmin", False) and cliente.clinica_id != current_user.clinica_id:
        # Verificar si la clínica tiene una mascota o cliente vinculado con este mismo DNI
        tiene_vinculo = db.query(Mascota).join(Cliente).filter(
            Mascota.clinica_id == current_user.clinica_id,
            Cliente.dni == cliente.dni,
            Mascota.is_deleted == False
        ).first() is not None
        if not tiene_vinculo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cliente no encontrado en esta clínica."
            )

    cliente.pin_hash = None
    if cliente.dni:
        otros_registros = db.query(Cliente).filter(
            Cliente.dni == cliente.dni,
            Cliente.is_deleted == False
        ).all()
        for reg in otros_registros:
            reg.pin_hash = None

    db.commit()
    db.refresh(cliente)

    return {
        "status": "ok",
        "mensaje": "El PIN del cliente ha sido restablecido a None exitosamente.",
        "cliente_id": cliente.id,
        "pin_hash": cliente.pin_hash
    }


# ==========================================
# 2. VISTAS HTML PÚBLICAS Y DE SESIÓN (VETERINARIO)
# ==========================================

@router.get("/planes", response_class=HTMLResponse, summary="Vista Pública de Planes y Qué Ofrecemos")
@router.get("/precios", response_class=HTMLResponse, summary="Alias de Vista Pública de Planes y Precios")
def vista_planes_publica(request: Request, db: Session = Depends(get_db)):
    current_user = obtener_veterinario_actual(request, db)
    return templates.TemplateResponse(
        request=request,
        name="planes.html",
        context={"current_user": current_user}
    )


@router.get("/login", response_class=HTMLResponse, summary="Vista Login Veterinario")
def vista_login_veterinario(request: Request, error: Optional[str] = None, db: Session = Depends(get_db)):
    current_user = obtener_veterinario_actual(request, db)
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={"error": error, "email": ""}
    )


@router.post("/login", response_class=HTMLResponse)
async def procesar_login_veterinario(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", "")).strip()

    try:
        req = VetLoginRequest(email=email, password=password)
        auth_resp = AuthService.login_veterinario(db, req)

        response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            key="vet_token",
            value=auth_resp.access_token,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7
        )
        return response
    except HTTPException as ex:
        # Si la cuenta no está verificada, redirigir a la pantalla de verificación OTP
        if ex.status_code == 403 and ("verificada" in str(ex.detail).lower() or "otp" in str(ex.detail).lower()):
            return RedirectResponse(
                url=f"/verificar?email={urllib.parse.quote(email)}&error={urllib.parse.quote(ex.detail)}",
                status_code=status.HTTP_303_SEE_OTHER
            )
        return templates.TemplateResponse(
            request=request,
            name="landing.html",
            context={"error": ex.detail, "email": email}
        )
    except Exception as ex:
        db.rollback()
        error_msg = "Error al iniciar sesión."
        if hasattr(ex, "errors"):
            try:
                error_msg = ex.errors()[0].get("msg", str(ex))
            except Exception:
                error_msg = str(ex)
        else:
            error_msg = str(ex)
        return templates.TemplateResponse(
            request=request,
            name="landing.html",
            context={"error": error_msg, "email": email}
        )


@router.get("/registro", response_class=HTMLResponse, summary="Vista Registro Veterinario")
def vista_registro_veterinario(request: Request, error: Optional[str] = None, db: Session = Depends(get_db)):
    current_user = obtener_veterinario_actual(request, db)
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request=request,
        name="clinic/registro.html",
        context={"error": error}
    )


@router.post("/registro", response_class=HTMLResponse)
async def procesar_registro_veterinario(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    nombre = str(form.get("nombre", "")).strip()
    nombre_clinica = str(form.get("nombre_clinica", "")).strip()
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", "")).strip()
    password_confirm = form.get("password_confirm")
    acepta_terminos = form.get("acepta_terminos")

    # Validación de coincidencia de contraseña (Repetir contraseña)
    if password_confirm is not None and str(password_confirm).strip() != password:
        return templates.TemplateResponse(
            request=request,
            name="clinic/registro.html",
            context={
                "error": "Las contraseñas no coinciden. Por favor asegúrate de repetirla exactamente igual.",
                "nombre": nombre,
                "nombre_clinica": nombre_clinica,
                "email": email
            }
        )

    # El checkbox es estrictamente obligatorio en el formulario HTML (required).
    # Si viene explícitamente desmarcado o rechazado ("false", "0", "no"):
    if acepta_terminos is not None and str(acepta_terminos).strip().lower() in ("false", "0", "off", "no"):
        return templates.TemplateResponse(
            request=request,
            name="clinic/registro.html",
            context={
                "error": "Debes leer y aceptar los Términos y Condiciones y la Política de Privacidad para registrar tu clínica.",
                "nombre": nombre,
                "nombre_clinica": nombre_clinica,
                "email": email
            }
        )

    try:
        req = VetRegisterRequest(
            nombre=nombre,
            nombre_clinica=nombre_clinica,
            email=email,
            password=password
        )
        auth_resp = AuthService.register_veterinario(db, req)

        # Redirigir a pantalla de verificación OTP indicando que revise su bandeja
        response = RedirectResponse(
            url=f"/verificar?email={urllib.parse.quote(email)}&mensaje=Cuenta+creada.+Ingresa+el+código+de+6+dígitos+enviado+a+tu+correo.",
            status_code=status.HTTP_303_SEE_OTHER
        )
        response.set_cookie(
            key="vet_token",
            value=auth_resp.access_token,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7
        )
        return response
    except HTTPException as ex:
        return templates.TemplateResponse(
            request=request,
            name="clinic/registro.html",
            context={
                "error": ex.detail,
                "nombre": nombre,
                "nombre_clinica": nombre_clinica,
                "email": email
            }
        )
    except Exception as ex:
        db.rollback()
        error_msg = "Error al registrar la cuenta."
        if hasattr(ex, "errors"):
            try:
                first_err = ex.errors()[0]
                loc = " -> ".join([str(l) for l in first_err.get("loc", [])])
                msg = first_err.get("msg", "")
                error_msg = f"{loc}: {msg}" if loc else msg
            except Exception:
                error_msg = str(ex)
        else:
            error_msg = str(ex)

        return templates.TemplateResponse(
            request=request,
            name="clinic/registro.html",
            context={
                "error": error_msg,
                "nombre": nombre,
                "nombre_clinica": nombre_clinica,
                "email": email
            }
        )


@router.get("/verificar", response_class=HTMLResponse, summary="Vista Verificación OTP")
def vista_verificar_otp(
    request: Request,
    email: Optional[str] = None,
    error: Optional[str] = None,
    mensaje: Optional[str] = None
):
    return templates.TemplateResponse(
        request=request,
        name="clinic/verificar.html",
        context={
            "email": email or "",
            "error": error,
            "mensaje": mensaje
        }
    )


@router.post("/verificar", response_class=HTMLResponse)
async def procesar_verificar_otp(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    otp_code = str(form.get("otp_code", "")).strip()

    try:
        auth_resp = AuthService.verificar_otp(db, email=email, otp_code=otp_code)
        response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            key="vet_token",
            value=auth_resp.access_token,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7
        )
        return response
    except HTTPException as ex:
        return templates.TemplateResponse(
            request=request,
            name="clinic/verificar.html",
            context={
                "email": email,
                "error": ex.detail,
                "mensaje": None
            }
        )
    except Exception as ex:
        db.rollback()
        return templates.TemplateResponse(
            request=request,
            name="clinic/verificar.html",
            context={
                "email": email,
                "error": str(ex),
                "mensaje": None
            }
        )


@router.post(
    "/api/clinic/asistentes",
    summary="Crear Usuario de Asistente (1 por clínica)",
    description="Permite al Administrador de la clínica crear un usuario con rol ASISTENTE vinculado a su misma clínica."
)
def crear_asistente_clinica(
    payload: AsistenteCreateRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autorizado.")
    if current_user.rol not in ("ADMIN", "SUPER_ADMIN") and not getattr(current_user, "is_superadmin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el Administrador de la clínica puede gestionar el equipo.")

    # 1. Validar límite de 1 asistente por clínica
    asistentes_actuales = db.query(Veterinario).filter(
        Veterinario.clinica_id == current_user.clinica_id,
        Veterinario.rol == "ASISTENTE",
        Veterinario.is_deleted == False
    ).count()

    if asistentes_actuales >= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu clínica ya cuenta con el límite de 1 asistente permitido en este plan."
        )

    # 2. Validar que el username no esté en uso
    clean_username = payload.username.strip().lower()
    existente = db.query(Veterinario).filter(
        (Veterinario.username == clean_username) | (Veterinario.email == clean_username),
        Veterinario.is_deleted == False
    ).first()
    if existente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de usuario ya está registrado en la plataforma. Elige otro."
        )

    # 3. Crear asistente sin requerir correo ni OTP
    nuevo_asistente = Veterinario(
        clinica_id=current_user.clinica_id,
        username=clean_username,
        nombre=payload.nombre.strip() if payload.nombre else clean_username,
        password_hash=hash_password(payload.password),
        rol="ASISTENTE",
        is_active=True,
        is_verified=True
    )
    db.add(nuevo_asistente)
    db.commit()
    db.refresh(nuevo_asistente)

    return {
        "mensaje": "Asistente creado exitosamente.",
        "asistente": {
            "id": nuevo_asistente.id,
            "username": nuevo_asistente.username,
            "nombre": nuevo_asistente.nombre,
            "rol": nuevo_asistente.rol
        }
    }


@router.delete(
    "/api/clinic/asistentes/{asistente_id}",
    summary="Eliminar Asistente de la Clínica"
)
def eliminar_asistente_clinica(
    asistente_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    if not current_user or (current_user.rol not in ("ADMIN", "SUPER_ADMIN") and not getattr(current_user, "is_superadmin", False)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acción no autorizada. Requiere rol ADMIN.")

    asistente = db.query(Veterinario).filter(
        Veterinario.id == asistente_id,
        Veterinario.clinica_id == current_user.clinica_id,
        Veterinario.rol == "ASISTENTE",
        Veterinario.is_deleted == False
    ).first()

    if not asistente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asistente no encontrado.")

    asistente.soft_delete()
    db.commit()

    return {"mensaje": "Cuenta de asistente eliminada correctamente."}


@router.get("/logout", summary="Cerrar Sesión Veterinario")
def logout_veterinario():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("vet_token")
    return response


# ==========================================
# 3. VISTAS HTML JINJA2 (PANEL VETERINARIO)
# ==========================================

@router.get("/dashboard", response_class=HTMLResponse, summary="Vista Dashboard Veterinario")
def vista_dashboard(
    request: Request,
    q: Optional[str] = None,
    clinica_id: int = 1,
    db: Session = Depends(get_db)
):
    verificar_acceso_veterinario(request)
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    target_clinica_id = current_user.clinica_id

    clinica = db.query(Clinica).filter(Clinica.id == target_clinica_id, Clinica.is_deleted == False).first()
    if not clinica:
        clinica = Clinica(
            id=target_clinica_id,
            nombre="Clínica Veterinaria SherekePet",
            zona_horaria="America/Lima",
            plan_activo="solo"
        )
        db.add(clinica)
        db.commit()
        db.refresh(clinica)

    hoy = get_lima_now().date()

    # Cálculo dinámico de periodo de prueba basado en trial_ends_at (ajustable por SuperAdmin)
    if clinica.estado_suscripcion_normalizado == "ACTIVE":
        dias_restantes_prueba = None
    elif clinica.trial_ends_at:
        dias_restantes_prueba = clinica.dias_restantes_trial
    else:
        dias_transcurridos = (hoy - clinica.created_at.date()).days if clinica.created_at else 0
        dias_restantes_prueba = max(0, 14 - dias_transcurridos)

    # Asistente de la clínica (si existe)
    asistente = db.query(Veterinario).filter(
        Veterinario.clinica_id == target_clinica_id,
        Veterinario.rol == "ASISTENTE",
        Veterinario.is_deleted == False
    ).first()

    # KPI 1: Atenciones de hoy
    citas_hoy = db.query(AtencionClinica).filter(
        AtencionClinica.clinica_id == target_clinica_id,
        AtencionClinica.is_deleted == False,
        func.date(AtencionClinica.created_at) == hoy
    ).count()

    # KPI 2: Refuerzos pendientes para hoy o vencidos
    refuerzos_pendientes_hoy = db.query(SeguimientoNotificacion).filter(
        SeguimientoNotificacion.clinica_id == target_clinica_id,
        SeguimientoNotificacion.is_deleted == False,
        SeguimientoNotificacion.estado == "PENDIENTE",
        SeguimientoNotificacion.fecha_programada <= hoy
    ).count()

    # KPI 3: Total pacientes registrados
    total_pacientes = db.query(Mascota).filter(
        Mascota.clinica_id == target_clinica_id,
        Mascota.is_deleted == False
    ).count()

    # Lista de seguimientos pendientes
    seguimientos_query = db.query(SeguimientoNotificacion).filter(
        SeguimientoNotificacion.clinica_id == target_clinica_id,
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
            Mascota.clinica_id == target_clinica_id,
            Mascota.is_deleted == False,
            or_(
                Mascota.nombre.ilike(termino),
                Cliente.dni.ilike(termino),
                Cliente.nombre_completo.ilike(termino),
                Cliente.telefono.ilike(termino)
            )
        ).limit(10).all()

    # KPI Citas: Solicitudes de Citas Pendientes de Confirmación (Hoy y a futuro)
    citas_pendientes_query = db.query(Cita).filter(
        Cita.clinica_id == target_clinica_id,
        Cita.is_deleted == False,
        Cita.estado == "PENDIENTE",
        Cita.fecha >= hoy
    ).order_by(Cita.fecha.asc(), Cita.hora.asc()).all()

    total_citas_pendientes = len(citas_pendientes_query)

    citas_pendientes_agrupadas = {}
    for c in citas_pendientes_query:
        fecha_str = c.fecha.strftime("%Y-%m-%d")
        if fecha_str not in citas_pendientes_agrupadas:
            if c.fecha == hoy:
                etiqueta = "HOY"
                badge_class = "bg-rose-100 text-rose-800 border-rose-300"
            elif c.fecha == hoy + timedelta(days=1):
                etiqueta = "MAÑANA (" + c.fecha.strftime("%d/%m") + ")"
                badge_class = "bg-amber-100 text-amber-800 border-amber-300"
            else:
                etiqueta = c.fecha.strftime("%d/%m/%Y")
                badge_class = "bg-indigo-50 text-indigo-800 border-indigo-200"

            citas_pendientes_agrupadas[fecha_str] = {
                "fecha": c.fecha,
                "fecha_str": fecha_str,
                "etiqueta": etiqueta,
                "badge_class": badge_class,
                "citas": []
            }

        telefono = c.cliente.telefono or ""
        enlace_wa = generar_enlace_whatsapp(
            telefono,
            f"Hola {c.cliente.nombre_completo or ''}, te saludamos de {clinica.nombre}. Hemos recibido tu solicitud de cita para {c.mascota.nombre} el día {c.fecha.strftime('%d/%m/%Y')} a las {c.hora.strftime('%I:%M %p')}. Motivo: {c.motivo}."
        )
        citas_pendientes_agrupadas[fecha_str]["citas"].append({
            "cita": c,
            "enlace_whatsapp": enlace_wa
        })

    citas_pendientes_por_fecha = list(citas_pendientes_agrupadas.values())

    return templates.TemplateResponse(
        request=request,
        name="clinic/dashboard.html",
        context={
            "clinica": clinica,
            "current_user": current_user,
            "dias_restantes_prueba": dias_restantes_prueba,
            "asistente": asistente,
            "citas_hoy": citas_hoy,
            "refuerzos_pendientes_hoy": refuerzos_pendientes_hoy,
            "total_pacientes": total_pacientes,
            "citas_pendientes_count": total_citas_pendientes,
            "citas_pendientes_por_fecha": citas_pendientes_por_fecha,
            "seguimientos": seguimientos_con_wa,
            "busqueda": q,
            "resultados_busqueda": resultados_busqueda,
            "hoy": hoy
        }
    )


@router.get("/pacientes", response_class=HTMLResponse, summary="Directorio de Pacientes y Dueños de la Clínica")
def vista_lista_pacientes(
    request: Request,
    q: Optional[str] = None,
    clinica_id: int = 1,
    db: Session = Depends(get_db)
):
    verificar_acceso_veterinario(request)
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    target_clinica_id = current_user.clinica_id

    clinica = db.query(Clinica).filter(Clinica.id == target_clinica_id, Clinica.is_deleted == False).first()

    # 1. Obtener clientes vinculados a esta clínica (registrados directamente, con mascotas o con citas agendadas)
    clientes_raw = db.query(Cliente).filter(
        Cliente.is_deleted == False,
        or_(
            Cliente.clinica_id == target_clinica_id,
            Cliente.id.in_(
                db.query(Mascota.cliente_id).filter(
                    Mascota.clinica_id == target_clinica_id,
                    Mascota.is_deleted == False
                )
            ),
            Cliente.id.in_(
                db.query(Cita.cliente_id).filter(
                    Cita.clinica_id == target_clinica_id,
                    Cita.is_deleted == False
                )
            )
        )
    ).order_by(Cliente.created_at.desc()).all()

    # Unificar por DNI para evitar duplicidad de dueños
    dnis_vistos = set()
    propietarios_unicos = []
    for c in clientes_raw:
        if c.dni not in dnis_vistos:
            dnis_vistos.add(c.dni)
            propietarios_unicos.append(c)

    # 2. Para cada dueño, agrupar todas sus mascotas (indiferentemente de si han sido atendidas en esta clínica o registradas en el portal)
    termino = q.strip().lower() if q and q.strip() else None
    propietarios_data = []

    for c in propietarios_unicos:
        # Todas las mascotas vinculadas a este DNI unificado
        mascotas_query = db.query(Mascota).join(Cliente).filter(
            Cliente.dni == c.dni,
            Cliente.is_deleted == False,
            Mascota.is_deleted == False
        ).order_by(Mascota.created_at.desc()).all()

        mascotas_por_nombre = {}
        for m in mascotas_query:
            clave_nom = m.nombre.strip().lower()
            if clave_nom not in mascotas_por_nombre:
                mascotas_por_nombre[clave_nom] = []
            mascotas_por_nombre[clave_nom].append(m)

        todas_mascotas = []
        for clave_nom, lista_instancias in mascotas_por_nombre.items():
            # 1. Priorizar la instancia que pertenece a la clínica actual
            local = next((inst for inst in lista_instancias if inst.clinica_id == target_clinica_id), None)
            if local:
                principal = local
            else:
                # 2. Si no hay instancia local, seleccionar la más completa
                principal = sorted(
                    lista_instancias,
                    key=lambda item: (
                        1 if item.foto_url else 0,
                        1 if item.fecha_nacimiento else 0,
                        1 if (item.peso and item.peso > 0) else 0,
                        item.id
                    ),
                    reverse=True
                )[0]

            # 3. Enriquecer datos de la mascota principal con atributos de las otras instancias si le faltan
            for otra in lista_instancias:
                if otra.id == principal.id:
                    continue
                if not principal.foto_url and otra.foto_url:
                    principal.foto_url = otra.foto_url
                if not principal.fecha_nacimiento and otra.fecha_nacimiento:
                    principal.fecha_nacimiento = otra.fecha_nacimiento
                if (not principal.peso or principal.peso <= 0) and (otra.peso and otra.peso > 0):
                    principal.peso = otra.peso
                if not principal.raza and otra.raza:
                    principal.raza = otra.raza
                if not principal.sexo and otra.sexo:
                    principal.sexo = otra.sexo
                if not principal.tiene_alergias and otra.tiene_alergias:
                    principal.tiene_alergias = otra.tiene_alergias
                    principal.detalle_alergias = otra.detalle_alergias or principal.detalle_alergias

            todas_mascotas.append(principal)

        todas_mascotas.sort(key=lambda item: item.nombre.lower())

        if not todas_mascotas:
            continue

        if termino:
            dueno_coincide = (
                (c.nombre_completo and termino in c.nombre_completo.lower()) or
                (c.dni and termino in c.dni.lower()) or
                (c.telefono and termino in c.telefono.lower())
            )
            if dueno_coincide:
                mascotas_a_mostrar = todas_mascotas
            else:
                mascotas_a_mostrar = [
                    m for m in todas_mascotas
                    if (termino in m.nombre.lower() or
                        (m.especie and termino in m.especie.lower()) or
                        (m.raza and termino in m.raza.lower()))
                ]
            if not mascotas_a_mostrar:
                continue
        else:
            mascotas_a_mostrar = todas_mascotas

        propietarios_data.append({
            "cliente": c,
            "mascotas": mascotas_a_mostrar,
            "total_mascotas": len(todas_mascotas)
        })

    # Lista plana para compatibilidad con tests y utilidades
    pacientes_planos = [m for p in propietarios_data for m in p["mascotas"]]

    return templates.TemplateResponse(
        request=request,
        name="clinic/pacientes_list.html",
        context={
            "clinica": clinica,
            "current_user": current_user,
            "propietarios": propietarios_data,
            "pacientes": pacientes_planos,
            "busqueda": q or "",
            "total_propietarios": len(propietarios_data),
            "total_pacientes": len(pacientes_planos)
        }
    )


@router.get("/pacientes/nuevo", response_class=HTMLResponse, summary="Formulario Registro Rápido")
def vista_nuevo_paciente(
    request: Request,
    clinica_id: int = 1,
    db: Session = Depends(get_db)
):
    verificar_acceso_veterinario(request)
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    target_clinica_id = current_user.clinica_id

    clinica = db.query(Clinica).filter(Clinica.id == target_clinica_id).first()
    especies = db.query(Especie).order_by(Especie.nombre.asc()).all()

    return templates.TemplateResponse(
        request=request,
        name="clinic/paciente_form.html",
        context={
            "clinica": clinica,
            "current_user": current_user,
            "clinica_id": target_clinica_id,
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
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    target_clinica_id = current_user.clinica_id

    # 1. Buscar si la mascota pertenece directamente a la clínica actual
    mascota = db.query(Mascota).filter(
        Mascota.id == mascota_id,
        Mascota.is_deleted == False,
        Mascota.clinica_id == target_clinica_id
    ).first()

    # 2. Si no pertenece a esta clínica, verificar si ya tiene ficha local o si proviene de una cita en esta clínica
    if not mascota:
        mascota_externa = db.query(Mascota).filter(
            Mascota.id == mascota_id,
            Mascota.is_deleted == False
        ).first()

        if mascota_externa and mascota_externa.cliente and mascota_externa.cliente.dni:
            qs = f"?{request.url.query}" if request.url.query else ""
            mascota_local = db.query(Mascota).join(Cliente).filter(
                Cliente.dni == mascota_externa.cliente.dni,
                Mascota.clinica_id == target_clinica_id,
                func.lower(func.trim(Mascota.nombre)) == mascota_externa.nombre.strip().lower(),
                Mascota.is_deleted == False
            ).first()

            if mascota_local:
                return RedirectResponse(url=f"/pacientes/{mascota_local.id}{qs}", status_code=status.HTTP_302_FOUND)

            # Solo auto-vincular si la mascota realmente tiene una cita agendada en esta clínica
            tiene_cita_en_clinica = db.query(Cita).filter(
                Cita.clinica_id == target_clinica_id,
                Cita.mascota_id == mascota_externa.id,
                Cita.is_deleted == False
            ).first() is not None

            if tiene_cita_en_clinica:
                mascota_vinculada = _asegurar_mascota_local_clinica(db, mascota_externa.id, target_clinica_id)
                if mascota_vinculada:
                    return RedirectResponse(url=f"/pacientes/{mascota_vinculada.id}{qs}", status_code=status.HTTP_302_FOUND)

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
            "current_user": current_user,
            "atenciones": atenciones,
            "vacunas": vacunas_con_wa,
            "hoy": hoy
        }
    )


@router.get("/configuracion", response_class=HTMLResponse, summary="Vista Configuración de Marca Blanca")
def vista_configuracion_clinica(
    request: Request,
    db: Session = Depends(get_db)
):
    verificar_acceso_veterinario(request)
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    if current_user.rol in ["VET", "VETERINARIO"]:
        current_user.rol = "ADMIN"
        db.commit()
        db.refresh(current_user)

    target_clinica_id = current_user.clinica_id

    clinica = db.query(Clinica).filter(
        Clinica.id == target_clinica_id,
        Clinica.is_deleted == False
    ).first()

    if not clinica:
        clinica = Clinica(
            id=target_clinica_id,
            nombre="Clínica Veterinaria SherekePet",
            zona_horaria="America/Lima",
            plan_activo="solo"
        )
        db.add(clinica)
        db.commit()
        db.refresh(clinica)

    return templates.TemplateResponse(
        request=request,
        name="clinic/settings.html",
        context={
            "clinica": clinica,
            "current_user": current_user,
            "nombre_comercial": clinica.nombre_comercial or ""
        }
    )


@router.get("/configuracion/facturacion", response_class=HTMLResponse, summary="Vista de Facturación y Suscripción SaaS")
def vista_facturacion_clinica(
    request: Request,
    alerta: Optional[str] = None,
    mensaje: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Vista de Facturación y Planes SaaS: Muestra Plan Emprendedor (S/ 49.00 / mes),
    días restantes del Trial de 14 días, Periodo de Gracia (3 días), alerta roja de Suscripción Expirada,
    pasarela Mercado Pago, modal de Yape/Plin con subida de comprobante e historial de pagos.
    """
    verificar_acceso_veterinario(request)
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    target_clinica_id = current_user.clinica_id
    clinica = db.query(Clinica).filter(
        Clinica.id == target_clinica_id,
        Clinica.is_deleted == False
    ).first()

    if not clinica:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    expirado = not clinica.tiene_suscripcion_activa
    dias_restantes = clinica.dias_restantes_trial
    en_trial = (clinica.estado_suscripcion or "").upper() == "TRIAL"
    en_gracia = clinica.en_periodo_gracia
    dias_gracia = clinica.dias_gracia_restantes
    dias_suscripcion = clinica.dias_restantes_suscripcion

    historial_pagos = db.query(PagoSuscripcion).filter(
        PagoSuscripcion.clinica_id == clinica.id
    ).order_by(PagoSuscripcion.created_at.desc()).limit(20).all()

    pago_pendiente = next(
        (p for p in historial_pagos if (p.estado or "").upper() == "PENDIENTE_REVISION"),
        None
    )

    return templates.TemplateResponse(
        request=request,
        name="clinic/billing.html",
        context={
            "clinica": clinica,
            "current_user": current_user,
            "expirado": expirado,
            "dias_restantes": dias_restantes,
            "en_trial": en_trial,
            "en_gracia": en_gracia,
            "dias_gracia": dias_gracia,
            "dias_suscripcion": dias_suscripcion,
            "historial_pagos": historial_pagos,
            "pago_pendiente": pago_pendiente,
            "yape_titular": settings.YAPE_PLIN_TITULAR,
            "yape_numero": settings.YAPE_PLIN_NUMERO,
            "yape_qr_url": settings.YAPE_PLIN_QR_URL,
            "mp_enabled": bool(settings.MP_ENABLED),
            "mp_configured": bool(settings.MP_ENABLED and settings.MP_ACCESS_TOKEN),
            "alerta": alerta,
            "mensaje": mensaje
        }
    )


def _aplicar_activacion_30_dias(
    db: Session,
    clinica: Clinica,
    metodo_pago: str = "MERCADOPAGO",
    referencia_operacion: Optional[str] = None,
    notas: Optional[str] = None
) -> PagoSuscripcion:
    """Activa o extiende por 30 días la suscripción del Plan Emprendedor y registra el pago aprobado."""
    ahora = get_lima_now()
    base_inicio = ahora
    if clinica.subscription_ends_at:
        s_end = clinica.subscription_ends_at
        if s_end.tzinfo is None:
            s_end = s_end.replace(tzinfo=ahora.tzinfo)
        if s_end > ahora:
            base_inicio = s_end

    nuevo_fin = base_inicio + timedelta(days=30)
    clinica.estado_suscripcion = "ACTIVO"
    clinica.plan_activo = "emprendedor"
    clinica.subscription_ends_at = nuevo_fin
    clinica.trial_ends_at = nuevo_fin

    ref_final = referencia_operacion or f"MP-{uuid.uuid4().hex[:8].upper()}"
    pago = PagoSuscripcion(
        clinica_id=clinica.id,
        monto="49.00",
        moneda="PEN",
        metodo_pago=metodo_pago,
        referencia_operacion=ref_final,
        estado="APROBADO",
        notas=notas or "Suscripción mensual Plan Emprendedor (30 días)",
        periodo_inicio=ahora,
        periodo_fin=nuevo_fin
    )
    db.add(pago)
    db.commit()
    db.refresh(clinica)
    db.refresh(pago)
    return pago


@router.post("/configuracion/facturacion/activar", response_class=HTMLResponse, summary="Activar Suscripción Plan Emprendedor")
def activar_plan_emprendedor(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Activa la suscripción del Plan Emprendedor (S/ 49.00/mes) por 30 días pasando el estado a ACTIVO
    y desbloqueando inmediatamente todas las operaciones de la clínica.
    Si MP_ENABLED y MP_ACCESS_TOKEN están configurados en producción, redirige al Checkout Pro de Mercado Pago.
    """
    verificar_acceso_veterinario(request)
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    clinica = db.query(Clinica).filter(
        Clinica.id == current_user.clinica_id,
        Clinica.is_deleted == False
    ).first()

    if not clinica:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    # Si Mercado Pago está habilitado y hay token configurado, crear preferencia Checkout Pro real
    if settings.MP_ENABLED and settings.MP_ACCESS_TOKEN and settings.MP_ACCESS_TOKEN.strip():
        try:
            import httpx
            base_url = str(request.base_url).rstrip("/")
            forwarded_proto = request.headers.get("x-forwarded-proto", "")
            if (forwarded_proto == "https" or "onrender.com" in base_url or "sherekepet.com" in base_url) and base_url.startswith("http://"):
                base_url = "https://" + base_url[len("http://"):]

            mp_payload = {
                "items": [
                    {
                        "id": f"plan-emprendedor-{clinica.id}",
                        "title": f"SherekePet - Plan Emprendedor Mensual ({clinica.nombre_mostrado})",
                        "description": "Suscripción SaaS Veterinario por 30 días",
                        "quantity": 1,
                        "currency_id": "PEN",
                        "unit_price": 49.00
                    }
                ],
                "external_reference": str(clinica.id),
                "back_urls": {
                    "success": f"{base_url}/configuracion/facturacion/retorno-mp",
                    "failure": f"{base_url}/configuracion/facturacion?alerta=pago_fallido",
                    "pending": f"{base_url}/configuracion/facturacion?mensaje=Tu+pago+está+en+proceso+de+validación."
                },
                "notification_url": f"{base_url}/api/billing/webhook/mercadopago"
            }
            if base_url.startswith("https://"):
                mp_payload["auto_return"] = "approved"

            resp = httpx.post(
                "https://api.mercadopago.com/checkout/preferences",
                headers={
                    "Authorization": f"Bearer {settings.MP_ACCESS_TOKEN.strip()}",
                    "Content-Type": "application/json"
                },
                json=mp_payload,
                timeout=10.0
            )
            if resp.status_code in (200, 201):
                mp_data = resp.json()
                init_point = mp_data.get("init_point") or mp_data.get("sandbox_init_point")
                if init_point:
                    return RedirectResponse(url=init_point, status_code=status.HTTP_303_SEE_OTHER)
        except Exception:
            pass

    # Modo directo / sandbox cuando aún no se configura MP_ACCESS_TOKEN
    _aplicar_activacion_30_dias(
        db=db,
        clinica=clinica,
        metodo_pago="MERCADOPAGO",
        notas="Activación Plan Emprendedor (30 días)"
    )

    return RedirectResponse(
        url="/configuracion/facturacion?mensaje=¡Plan+Emprendedor+(S/+49.00/mes)+activado+con+éxito!+Tu+clínica+cuenta+con+acceso+total+por+30+días.",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/configuracion/facturacion/retorno-mp", response_class=HTMLResponse, summary="Retorno desde Mercado Pago Checkout Pro")
def retorno_mercadopago(
    request: Request,
    status_mp: Optional[str] = None,
    collection_status: Optional[str] = None,
    payment_id: Optional[str] = None,
    external_reference: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Procesa el retorno de Mercado Pago Checkout Pro verificando que el pago
    realmente exista y esté aprobado antes de activar los 30 días.
    """
    verificar_acceso_veterinario(request)
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    estado_pago = (status_mp or collection_status or request.query_params.get("status") or "").lower()
    if estado_pago == "approved" and payment_id:
        clinica = db.query(Clinica).filter(
            Clinica.id == current_user.clinica_id,
            Clinica.is_deleted == False
        ).first()
        if clinica:
            # 1. Verificar si el webhook ya aprobó este payment_id para esta clínica
            existente = db.query(PagoSuscripcion).filter(
                PagoSuscripcion.clinica_id == clinica.id,
                PagoSuscripcion.referencia_operacion == str(payment_id),
                PagoSuscripcion.estado == "APROBADO"
            ).first()
            if existente:
                return RedirectResponse(
                    url="/configuracion/facturacion?mensaje=¡Pago+confirmado+vía+Mercado+Pago!+Tu+Plan+Emprendedor+está+activo+por+30+días.",
                    status_code=status.HTTP_303_SEE_OTHER
                )

            # 2. Verificar directamente contra la API de Mercado Pago (nunca confiar solo en query params)
            if settings.MP_ACCESS_TOKEN and settings.MP_ACCESS_TOKEN.strip():
                try:
                    import httpx
                    resp = httpx.get(
                        f"https://api.mercadopago.com/v1/payments/{payment_id}",
                        headers={"Authorization": f"Bearer {settings.MP_ACCESS_TOKEN.strip()}"},
                        timeout=8.0
                    )
                    if resp.status_code == 200:
                        info = resp.json()
                        mp_status = str(info.get("status") or "").lower()
                        mp_ext_ref = str(info.get("external_reference") or "")
                        if mp_status == "approved" and mp_ext_ref == str(clinica.id):
                            _aplicar_activacion_30_dias(
                                db=db,
                                clinica=clinica,
                                metodo_pago="MERCADOPAGO",
                                referencia_operacion=str(payment_id),
                                notas="Pago automático verificado vía API Mercado Pago"
                            )
                            return RedirectResponse(
                                url="/configuracion/facturacion?mensaje=¡Pago+confirmado+vía+Mercado+Pago!+Tu+Plan+Emprendedor+está+activo+por+30+días.",
                                status_code=status.HTTP_303_SEE_OTHER
                            )
                except Exception:
                    pass

    return RedirectResponse(
        url="/configuracion/facturacion?alerta=El+pago+no+pudo+ser+verificado+o+sigue+pendiente.",
        status_code=status.HTTP_303_SEE_OTHER
    )


def _verificar_firma_webhook_mp(request: Request, payment_id: Optional[str]) -> bool:
    """
    Valida la firma HMAC-SHA256 de Mercado Pago (header x-signature) o el token x-webhook-secret.
    """
    import hmac
    import hashlib

    secret = (settings.MP_WEBHOOK_SECRET or "").strip()
    if not secret:
        return False

    # 1. Soporte directo por header x-webhook-secret (para pruebas / integraciones internas)
    custom_header = (request.headers.get("x-webhook-secret") or "").strip()
    if custom_header and hmac.compare_digest(custom_header, secret):
        return True

    # 2. Formato oficial de Mercado Pago: x-signature: ts=...,v1=...
    x_sig = request.headers.get("x-signature") or ""
    x_req_id = request.headers.get("x-request-id") or ""
    if not x_sig:
        return False

    partes = {}
    for item in x_sig.split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            partes[k.strip()] = v.strip()

    ts = partes.get("ts")
    v1 = partes.get("v1")
    if not ts or not v1:
        return False

    data_id = str(payment_id or request.query_params.get("data.id") or "")
    manifest = f"id:{data_id};request-id:{x_req_id};ts:{ts};"
    expected = hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


@router.post("/api/billing/webhook/mercadopago", summary="Webhook Automático de Mercado Pago")
async def webhook_mercadopago(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Recibe notificaciones IPN/Webhook de Mercado Pago.
    Exige verificación criptográfica de firma (MP_WEBHOOK_SECRET) o validación directa
    del payment_id contra la API oficial de Mercado Pago (MP_ACCESS_TOKEN).
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    topic = body.get("type") or body.get("topic") or request.query_params.get("type") or request.query_params.get("topic")
    data_obj = body.get("data") or {}
    payment_id = data_obj.get("id") or request.query_params.get("data.id") or body.get("id")

    firma_valida = _verificar_firma_webhook_mp(request, str(payment_id) if payment_id else None)
    if settings.MP_WEBHOOK_SECRET and settings.MP_WEBHOOK_SECRET.strip() and not firma_valida:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firma de webhook de Mercado Pago inválida."
        )

    external_ref = None
    payment_status = None

    # Si tenemos MP_ACCESS_TOKEN y payment_id, consultar la fuente de verdad en la API de Mercado Pago
    if payment_id and settings.MP_ACCESS_TOKEN and settings.MP_ACCESS_TOKEN.strip():
        try:
            import httpx
            resp = httpx.get(
                f"https://api.mercadopago.com/v1/payments/{payment_id}",
                headers={"Authorization": f"Bearer {settings.MP_ACCESS_TOKEN.strip()}"},
                timeout=8.0
            )
            if resp.status_code == 200:
                info = resp.json()
                external_ref = info.get("external_reference")
                payment_status = info.get("status")
        except Exception:
            pass
    elif firma_valida:
        # Solo si la firma HMAC del webhook fue validada criptográficamente aceptamos el payload firmado
        external_ref = body.get("external_reference") or data_obj.get("external_reference")
        payment_status = body.get("status") or data_obj.get("status")
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook no verificado: configure MP_WEBHOOK_SECRET o MP_ACCESS_TOKEN."
        )

    if external_ref and str(payment_status or "").lower() == "approved":
        try:
            clinica_id = int(external_ref)
        except (ValueError, TypeError):
            clinica_id = None

        if clinica_id:
            clinica = db.query(Clinica).filter(Clinica.id == clinica_id, Clinica.is_deleted == False).first()
            if clinica:
                ref_str = str(payment_id) if payment_id else f"MP-WH-{uuid.uuid4().hex[:8].upper()}"
                ya_procesado = db.query(PagoSuscripcion).filter(
                    PagoSuscripcion.referencia_operacion == ref_str,
                    PagoSuscripcion.estado == "APROBADO"
                ).first()
                if not ya_procesado:
                    _aplicar_activacion_30_dias(
                        db=db,
                        clinica=clinica,
                        metodo_pago="MERCADOPAGO",
                        referencia_operacion=ref_str,
                        notas="Renovación automática vía Webhook Mercado Pago"
                    )
                return {"status": "ok", "clinica_id": clinica.id, "estado_suscripcion": clinica.estado_suscripcion}

    return {"status": "ignored", "topic": topic}


@router.post("/api/billing/reportar-pago", summary="Reportar Pago Yape/Plin con Comprobante en Plataforma")
async def reportar_pago_yape_plin(
    request: Request,
    background_tasks: BackgroundTasks,
    metodo_pago: str = Form("YAPE_PLIN"),
    referencia_operacion: str = Form(...),
    notas: Optional[str] = Form(None),
    comprobante: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """
    Permite a la clínica informar su pago por Yape, Plin o Transferencia directamente en la plataforma
    (sin depender de WhatsApp), adjuntando el N° de operación y opcionalmente la captura de pantalla.
    Notifica por correo al SuperAdmin y queda listo para aprobación en 1 clic desde /admin.
    """
    verificar_acceso_veterinario(request)
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autorizado.")

    clinica = db.query(Clinica).filter(
        Clinica.id == current_user.clinica_id,
        Clinica.is_deleted == False
    ).first()
    if not clinica:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clínica no encontrada.")

    ref_limpia = (referencia_operacion or "").strip()
    if not ref_limpia:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El número de operación es obligatorio.")

    comprobante_url = None
    if comprobante and comprobante.filename:
        contenido = await comprobante.read()
        if len(contenido) > 10 * 1024 * 1024:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La imagen excede los 10MB.")
        if len(contenido) > 0:
            try:
                comprobante_url = await upload_image_to_r2(
                    file_bytes=contenido,
                    filename=comprobante.filename or f"voucher_{clinica.id}_{uuid.uuid4().hex[:6]}.webp",
                    folder="comprobantes",
                    content_type=comprobante.content_type or "image/webp"
                )
            except ValueError as ve:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    metodo_norm = (metodo_pago or "YAPE_PLIN").strip().upper()
    nuevo_pago = PagoSuscripcion(
        clinica_id=clinica.id,
        monto="49.00",
        moneda="PEN",
        metodo_pago=metodo_norm,
        referencia_operacion=ref_limpia,
        comprobante_url=comprobante_url,
        estado="PENDIENTE_REVISION",
        notas=(notas or "").strip() or f"Pago reportado por {current_user.nombre or current_user.email}"
    )
    db.add(nuevo_pago)
    db.commit()
    db.refresh(nuevo_pago)

    # Notificar por correo electrónico al SuperAdmin en segundo plano
    try:
        from app.core.email import send_payment_report_notification_email
        background_tasks.add_task(
            send_payment_report_notification_email,
            clinica.nombre_mostrado,
            clinica.id,
            current_user.email or "sin-correo@sherekepet.com",
            metodo_norm,
            ref_limpia,
            "49.00",
            comprobante_url or ""
        )
    except Exception:
        pass

    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return {
            "status": "ok",
            "mensaje": "Comprobante enviado con éxito. Validaremos tu operación en breve.",
            "pago_id": nuevo_pago.id,
            "estado": nuevo_pago.estado,
            "comprobante_url": nuevo_pago.comprobante_url
        }

    return RedirectResponse(
        url="/configuracion/facturacion?mensaje=¡Comprobante+recibido+con+éxito!+Nuestro+equipo+validará+tu+operación+y+activará+tus+30+días+en+breve.",
        status_code=status.HTTP_303_SEE_OTHER
    )


# ==========================================
# 6. AGENDA Y CITAS VETERINARIAS
# ==========================================

@router.get("/agenda", response_class=HTMLResponse, summary="Vista Agenda de Citas del Veterinario")
def vista_agenda_citas(
    request: Request,
    fecha: Optional[str] = None,
    db: Session = Depends(get_db)
):
    verificar_acceso_veterinario(request)
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    target_clinica_id = current_user.clinica_id

    clinica = db.query(Clinica).filter(Clinica.id == target_clinica_id, Clinica.is_deleted == False).first()

    hoy = get_lima_now().date()
    fecha_filtro = hoy
    if fecha and fecha.strip():
        try:
            fecha_filtro = date.fromisoformat(fecha.strip())
        except Exception:
            fecha_filtro = hoy

    # Citas de la fecha seleccionada en la clínica
    citas_raw = db.query(Cita).filter(
        Cita.clinica_id == target_clinica_id,
        Cita.fecha == fecha_filtro,
        Cita.is_deleted == False
    ).order_by(Cita.hora.asc()).all()

    # Ordenar: primero las citas activas (PENDIENTE, CONFIRMADA) por hora, y debajo las ya ATENDIDAS o CANCELADAS
    def _prioridad_estado_cita(cita_obj: Cita) -> int:
        est = (cita_obj.estado or "").upper()
        if est in ("PENDIENTE", "CONFIRMADA"):
            return 0
        if est in ("ATENDIDA", "ATENDIDO", "COMPLETADA"):
            return 1
        return 2

    citas = sorted(citas_raw, key=lambda item: (_prioridad_estado_cita(item), item.hora))

    total_hoy = len(citas)
    total_pendientes = sum(1 for c in citas if (c.estado or "").upper() == "PENDIENTE")
    total_confirmadas = sum(1 for c in citas if (c.estado or "").upper() == "CONFIRMADA")
    total_atendidas = sum(1 for c in citas if (c.estado or "").upper() in ("ATENDIDA", "ATENDIDO", "COMPLETADA"))
    total_canceladas = sum(1 for c in citas if (c.estado or "").upper() == "CANCELADA")

    # Citas pendientes en OTRAS fechas futuras para alertar al veterinario
    otras_fechas_query = db.query(Cita).filter(
        Cita.clinica_id == target_clinica_id,
        Cita.is_deleted == False,
        func.upper(Cita.estado) == "PENDIENTE",
        Cita.fecha != fecha_filtro,
        Cita.fecha >= hoy
    ).order_by(Cita.fecha.asc()).all()

    resumen_otras_fechas = {}
    for c in otras_fechas_query:
        f_str = c.fecha.strftime("%Y-%m-%d")
        if f_str not in resumen_otras_fechas:
            if c.fecha == hoy + timedelta(days=1):
                lbl = "Mañana (" + c.fecha.strftime("%d/%m") + ")"
            else:
                lbl = c.fecha.strftime("%d/%m/%Y")
            resumen_otras_fechas[f_str] = {
                "fecha_str": f_str,
                "label": lbl,
                "cantidad": 0
            }
        resumen_otras_fechas[f_str]["cantidad"] += 1

    total_pendientes_global = db.query(Cita).filter(
        Cita.clinica_id == target_clinica_id,
        Cita.is_deleted == False,
        func.upper(Cita.estado) == "PENDIENTE",
        Cita.fecha >= hoy
    ).count()

    # Próximas 15 a 20 citas futuras (solo PENDIENTE y CONFIRMADA; las ya ATENDIDAS desaparecen de la cola)
    proximas_citas = db.query(Cita).filter(
        Cita.clinica_id == target_clinica_id,
        Cita.is_deleted == False,
        Cita.fecha >= hoy,
        func.upper(Cita.estado).in_(["PENDIENTE", "CONFIRMADA"])
    ).order_by(Cita.fecha.asc(), Cita.hora.asc()).limit(20).all()

    return templates.TemplateResponse(
        request=request,
        name="clinic/agenda.html",
        context={
            "clinica": clinica,
            "current_user": current_user,
            "citas": citas,
            "proximas_citas": proximas_citas,
            "fecha_seleccionada": fecha_filtro,
            "hoy": hoy,
            "total_hoy": total_hoy,
            "total_pendientes": total_pendientes,
            "total_confirmadas": total_confirmadas,
            "total_atendidas": total_atendidas,
            "total_canceladas": total_canceladas,
            "otras_fechas_pendientes": list(resumen_otras_fechas.values()),
            "citas_pendientes_count": total_pendientes_global
        }
    )


@router.put(
    "/api/clinic/citas/{cita_id}/confirmar",
    summary="Confirmar Cita Agendada (Clínica)",
    description="Actualiza el estado de la cita a Confirmada garantizando la integridad relacional de clinica_id y mascota_id."
)
@router.put(
    "/api/citas/{cita_id}/confirmar",
    summary="Confirmar Cita Agendada",
    description="Actualiza el estado de la cita a Confirmada garantizando la integridad relacional de clinica_id y mascota_id."
)
def confirmar_cita_veterinario(
    cita_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    payload: Optional[dict] = Body(default=None),
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    # Buscar la cita por su ID primario asegurando que pertenezca a la clínica del veterinario
    query = db.query(Cita).filter(
        Cita.id == cita_id,
        Cita.is_deleted == False
    )
    if not getattr(current_user, "is_superadmin", False):
        query = query.filter(Cita.clinica_id == current_user.clinica_id)

    cita = query.first()

    if not cita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cita no encontrada.")

    # Guardar explícitamente los IDs de relación para evitar que queden NULL en la transacción
    # (Solución Caso 'Agujero Negro': asegurar que clinica_id y mascota_id jamás se anulen)
    original_clinica_id = cita.clinica_id
    original_mascota_id = cita.mascota_id
    original_cliente_id = cita.cliente_id

    # Si la mascota fue registrada por el dueño en el Portal (otra clinica_id), vincularla automáticamente a esta clínica
    if original_mascota_id and original_clinica_id:
        mascota_local = _asegurar_mascota_local_clinica(db, original_mascota_id, original_clinica_id)
        if mascota_local:
            original_mascota_id = mascota_local.id
            original_cliente_id = mascota_local.cliente_id

    # Actualizar estado a 'Confirmada'
    cita.estado = "Confirmada"

    # Blindaje de integridad relacional: restaurar llaves si fueron alteradas
    if cita.clinica_id is None or cita.clinica_id <= 0:
        cita.clinica_id = original_clinica_id
    if cita.mascota_id is None or cita.mascota_id <= 0:
        cita.mascota_id = original_mascota_id
    if cita.cliente_id is None or cita.cliente_id <= 0:
        cita.cliente_id = original_cliente_id

    db.commit()
    db.refresh(cita)

    # Inyección en segundo plano (BackgroundTasks) para envío de correo transaccional sin retrasar respuesta HTTP
    destinatario_email = None
    if payload and isinstance(payload, dict):
        destinatario_email = payload.get("destinatario_email") or payload.get("email")
    if not destinatario_email:
        destinatario_email = request.query_params.get("destinatario_email") or request.query_params.get("email")
    if not destinatario_email and cita.cliente:
        destinatario_email = getattr(cita.cliente, "email", None)
        if not destinatario_email and cita.cliente.dni:
            otro_cli = db.query(Cliente).filter(
                Cliente.dni == cita.cliente.dni,
                Cliente.email.isnot(None),
                Cliente.email != "",
                Cliente.is_deleted == False
            ).first()
            if otro_cli:
                destinatario_email = otro_cli.email

    if destinatario_email:
        background_tasks.add_task(enviar_alerta_paciente, cita.id, destinatario_email)

    return {
        "mensaje": "Cita confirmada exitosamente.",
        "cita_id": cita.id,
        "id": cita.id,
        "estado": cita.estado,
        "clinica_id": cita.clinica_id,
        "mascota_id": cita.mascota_id,
        "cliente_id": cita.cliente_id
    }


@router.put(
    "/api/clinic/citas/{cita_id}/atendida",
    summary="Marcar Cita como Atendida",
    description="Actualiza el estado de la cita a ATENDIDA y asegura la ficha local de la mascota."
)
def marcar_cita_atendida_veterinario(
    cita_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = current_user.clinica_id

    cita = db.query(Cita).filter(
        Cita.id == cita_id,
        Cita.clinica_id == target_clinica_id,
        Cita.is_deleted == False
    ).first()

    if not cita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cita no encontrada.")

    if cita.mascota_id:
        mascota_local = _asegurar_mascota_local_clinica(db, cita.mascota_id, target_clinica_id)
        if mascota_local:
            cita.mascota_id = mascota_local.id
            cita.cliente_id = mascota_local.cliente_id

    cita.estado = "ATENDIDA"
    db.commit()
    db.refresh(cita)

    return {
        "mensaje": "Cita marcada como atendida.",
        "cita_id": cita.id,
        "mascota_id": cita.mascota_id,
        "estado": cita.estado
    }


@router.put(
    "/api/citas/{id}/confirmar",
    summary="Confirmar Cita Agendada (Alias id)",
    description="Actualiza el estado de la cita a Confirmada garantizando la integridad relacional de clinica_id y mascota_id."
)
def confirmar_cita_alias_id(
    id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    payload: Optional[dict] = Body(default=None),
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    return confirmar_cita_veterinario(
        cita_id=id,
        request=request,
        background_tasks=background_tasks,
        payload=payload,
        db=db,
        current_user=current_user
    )


@router.put(
    "/api/clinic/citas/{cita_id}/cancelar",
    summary="Cancelar Cita Agendada",
    description="Actualiza el estado de la cita a CANCELADA."
)
def cancelar_cita_veterinario(
    cita_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = current_user.clinica_id

    cita = db.query(Cita).filter(
        Cita.id == cita_id,
        Cita.clinica_id == target_clinica_id,
        Cita.is_deleted == False
    ).first()

    if not cita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cita no encontrada.")

    cita.estado = "CANCELADA"
    db.commit()
    db.refresh(cita)

    return {
        "mensaje": "Cita cancelada.",
        "cita_id": cita.id,
        "estado": cita.estado
    }


class CitaCreateVetRequest(BaseModel):
    clinica_id: Optional[int] = None
    cliente_id: Optional[int] = None
    mascota_id: int
    fecha: date
    hora: str
    motivo: str = "Próximo Baño y Grooming (Recurrencia)"
    estado: str = "CONFIRMADA"


@router.post(
    "/api/clinic/citas",
    summary="Registrar Cita desde el Panel del Veterinario"
)
def crear_cita_veterinario(
    payload: CitaCreateVetRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_current_vet)
):
    target_clinica_id = (payload.clinica_id or current_user.clinica_id) if getattr(current_user, "is_superadmin", False) else current_user.clinica_id

    mascota = db.query(Mascota).filter(
        Mascota.id == payload.mascota_id,
        Mascota.clinica_id == target_clinica_id,
        Mascota.is_deleted == False
    ).first()
    if not mascota:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mascota no encontrada en esta clínica."
        )

    resolved_cliente_id = payload.cliente_id or mascota.cliente_id

    # Parse hora "HH:MM"
    partes = payload.hora.strip().split(":")
    hora_obj = time(int(partes[0]), int(partes[1]))

    cita = Cita(
        clinica_id=target_clinica_id,
        cliente_id=resolved_cliente_id,
        mascota_id=payload.mascota_id,
        fecha=payload.fecha,
        hora=hora_obj,
        motivo=payload.motivo,
        estado=payload.estado
    )
    db.add(cita)

    if (payload.estado or "").upper() == "SUGERIDA":
        dueno_nom = (mascota.cliente.nombre_completo if mascota.cliente else None) or "Estimado(a) cliente"
        fecha_bano_str = payload.fecha.strftime("%d/%m/%Y")
        msg_bano = (
            f"Hola {dueno_nom}, te saludamos de tu veterinaria. "
            f"Te sugerimos programar el próximo baño de {mascota.nombre} para el día {fecha_bano_str}. "
            f"Puedes confirmar tu hora en tu Portal SherekePet o respondiendo a este mensaje."
        )
        seg_bano = SeguimientoNotificacion(
            clinica_id=target_clinica_id,
            cliente_id=resolved_cliente_id,
            mascota_id=mascota.id,
            tipo="PROXIMO_BANO",
            fecha_programada=payload.fecha,
            mensaje_plantilla=msg_bano,
            estado="PENDIENTE"
        )
        db.add(seg_bano)

    db.commit()
    db.refresh(cita)

    if (payload.estado or "").upper() == "SUGERIDA":
        _notificar_sugerencia_bano_dueno(
            db=db,
            background_tasks=background_tasks,
            mascota=mascota,
            clinica_id=target_clinica_id,
            fecha_sugerida=payload.fecha,
            hora_obj=hora_obj
        )

    return {
        "mensaje": "Cita agendada exitosamente.",
        "cita_id": cita.id,
        "fecha": str(cita.fecha),
        "hora": cita.hora.strftime("%H:%M"),
        "estado": cita.estado
    }



