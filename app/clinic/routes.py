import base64
import urllib.parse
from datetime import date, time, timedelta
import json
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.core.timezone import get_lima_now
from app.core.security import decode_access_token, hash_password
from app.database import get_db
from app.auth.service import AuthService
from app.auth.schemas import (
    VetLoginRequest,
    VetRegisterRequest,
    AsistenteCreateRequest,
    ClinicaConfiguracionUpdate
)
from app.core.models import Clinica
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
            if vet.rol in ["VET", "VETERINARIO"]:
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
    description="Permite al Administrador de la clínica subir el logo a Cloudflare R2 y actualizar Clinica.logo_url.",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
async def upload_logo_clinica(
    request: Request,
    file: UploadFile = File(...),
    clinica_id: int = Form(1),
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    if current_user and current_user.rol == "ASISTENTE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Los asistentes no tienen autorización para cambiar el logo de la clínica."
        )

    target_clinica_id = current_user.clinica_id if current_user else clinica_id
    clinica = db.query(Clinica).filter(Clinica.id == target_clinica_id, Clinica.is_deleted == False).first()
    if not clinica:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clínica no encontrada.")

    tipos_validos = {"image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"}
    content_type = file.content_type or "image/webp"
    if content_type not in tipos_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de imagen inválido. Solo se admiten PNG, JPEG, WEBP y SVG."
        )

    contenido = await file.read()
    if len(contenido) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo excede el tamaño máximo permitido (10MB)."
        )

    logo_url = await upload_image_to_r2(
        file_bytes=contenido,
        filename=file.filename or "logo.webp",
        folder="logos",
        content_type=content_type
    )

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
    summary="Obtener Horarios de Atención de la Clínica",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def get_horarios_clinica(
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    target_clinica_id = current_user.clinica_id if current_user else 1

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
    summary="Guardar o Actualizar Horarios de Atención de la Clínica",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def update_horarios_clinica(
    payload: HorariosConfigRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    target_clinica_id = current_user.clinica_id if current_user else 1

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
    summary="Listar Servicios de Baño y Consumo de Insumos",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def get_servicios_bano(
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    target_clinica_id = current_user.clinica_id if current_user else 1

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
    summary="Crear o Registrar Tipo de Baño",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def create_servicio_bano(
    payload: ServicioBanoCreateRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    target_clinica_id = current_user.clinica_id if current_user else payload.clinica_id

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


@router.get(
    "/api/clinic/productos",
    response_model=List[ProductoItem],
    summary="Listar Productos e Insumos de Inventario",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def get_productos_inventario(
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    target_clinica_id = current_user.clinica_id if current_user else 1

    # Asegurar que se inicialicen los insumos por defecto si la clínica es nueva
    obtener_o_inicializar_servicios_bano(target_clinica_id, db)

    productos = db.query(Producto).filter(
        Producto.clinica_id == target_clinica_id,
        Producto.is_deleted == False
    ).order_by(Producto.nombre.asc()).all()

    return [ProductoItem.model_validate(p) for p in productos]


@router.put(
    "/api/clinic/productos/{producto_id}/stock",
    response_model=ProductoItem,
    summary="Actualizar o Reabastecer Stock de un Producto",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def update_stock_producto(
    producto_id: int,
    payload: ProductoStockUpdateRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    target_clinica_id = current_user.clinica_id if current_user else 1

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
    db: Session = Depends(get_db)
):
    verificar_acceso_veterinario(request)
    current_user = obtener_veterinario_actual(request, db)
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autorizado.")

    tipos_validos = {"image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"}
    content_type = file.content_type or "image/webp"
    if content_type not in tipos_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de imagen inválido. Solo se admiten PNG, JPEG y WEBP."
        )

    contenido = await file.read()
    if len(contenido) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo excede el tamaño máximo permitido (10MB)."
        )

    foto_url = await upload_image_to_r2(
        file_bytes=contenido,
        filename=file.filename or f"vet_{current_user.id}.webp",
        folder="veterinarios",
        content_type=content_type
    )

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
    db: Session = Depends(get_db)
):
    verificar_acceso_veterinario(request)
    dni_limpio = dni.strip()
    if not dni_limpio or len(dni_limpio) < 4 or len(dni_limpio) > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El documento debe tener entre 4 y 20 caracteres.")

    cliente = db.query(Cliente).filter(
        Cliente.dni == dni_limpio,
        Cliente.is_deleted == False
    ).first()

    if not cliente:
        return {
            "encontrado": False,
            "mensaje": "DNI no encontrado en la red SherekePet."
        }

    mascotas = db.query(Mascota).filter(
        Mascota.cliente_id == cliente.id,
        Mascota.is_deleted == False
    ).order_by(Mascota.created_at.desc()).all()

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


@router.post(
    "/api/clinic/vincular-mascota/{mascota_id}",
    summary="Vincular Mascota Existente a Clínica Actual",
    description="Asocia una mascota existente de la red a la clínica actual del veterinario para abrir su ficha médica."
)
def vincular_mascota_a_clinica(
    mascota_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    verificar_acceso_veterinario(request)
    current_user = obtener_veterinario_actual(request, db)
    target_clinica_id = current_user.clinica_id if current_user else 1

    mascota_original = db.query(Mascota).filter(
        Mascota.id == mascota_id,
        Mascota.is_deleted == False
    ).first()
    if not mascota_original:
        raise HTTPException(status_code=404, detail="Mascota no encontrada.")

    # Si ya pertenece a la clínica actual, retornar id directo
    if mascota_original.clinica_id == target_clinica_id:
        return {
            "mensaje": "Mascota ya asociada a su clínica.",
            "mascota_id": mascota_original.id
        }

    # Asegurar cliente en la clínica local
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
            nombres=cliente_original.nombres,
            apellido_paterno=cliente_original.apellido_paterno,
            apellido_materno=cliente_original.apellido_materno
        )
        db.add(cliente_local)
        db.flush()

    nueva_mascota = Mascota(
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
        detalle_alergias=mascota_original.detalle_alergias
    )
    db.add(nueva_mascota)
    db.commit()
    db.refresh(nueva_mascota)

    return {
        "mensaje": "Mascota vinculada exitosamente a su clínica.",
        "mascota_id": nueva_mascota.id
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
    db: Session = Depends(get_db)
):
    mascota = db.query(Mascota).filter(Mascota.id == mascota_id, Mascota.is_deleted == False).first()
    if not mascota:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mascota no encontrada.")

    tipos_validos = {"image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"}
    content_type = file.content_type or "image/webp"
    if content_type not in tipos_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de imagen inválido. Solo se admiten PNG, JPEG y WEBP."
        )

    contenido = await file.read()
    if len(contenido) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo excede el tamaño máximo permitido (10MB)."
        )

    foto_url = await upload_image_to_r2(
        file_bytes=contenido,
        filename=file.filename or f"mascota_{mascota_id}.webp",
        folder="mascotas",
        content_type=content_type
    )

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
    description="Permite subir una foto de mascota antes de crear el registro clínico.",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
async def upload_foto_clinica_temp(
    file: UploadFile = File(...)
):
    tipos_validos = {"image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"}
    content_type = file.content_type or "image/webp"
    if content_type not in tipos_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de imagen inválido. Solo se admiten PNG, JPEG y WEBP."
        )

    contenido = await file.read()
    if len(contenido) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo excede el tamaño máximo permitido (10MB)."
        )

    foto_url = await upload_image_to_r2(
        file_bytes=contenido,
        filename=file.filename or "mascota.webp",
        folder="mascotas",
        content_type=content_type
    )

    return {"foto_url": foto_url}



@router.post(
    "/api/clinic/pacientes",
    response_model=PacienteRapidoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registro de Paciente y Dueño (Unificación Global por DNI)",
    description="Crea o reutiliza globalmente el Cliente por DNI y registra su Mascota.",
    dependencies=[Depends(verificar_acceso_veterinario)]
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
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    target_clinica_id = current_user.clinica_id if current_user else payload.clinica_id

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

    # 4. Registrar Mascota (con foto_url si se envió)
    mascota = Mascota(
        clinica_id=target_clinica_id,
        cliente_id=cliente.id,
        especie_id=payload.especie_id,
        raza_id=payload.raza_id,
        nombre=payload.mascota_nombre.strip(),
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
                clinic_id=payload.clinica_id,
                medicamento=med_nombre,
                frecuencia_horas=frec_h,
                total_dosis=tot_d,
                es_estricto=False,
                hora_inicio=get_lima_now()
            )
            plan_medicacion_id = plan_obj.id
        except Exception as e:
            logger.warning(f"No se pudo crear el plan de medicación automático: {e}")

    # Lógica para Descuento de Inventario en Grooming / Baños (Mini-ERP)
    stock_descontado = None
    insumo_nombre = None
    stock_restante = None

    if payload.tipo_atencion == "GROOMING":
        servicio_bano = None
        if payload.servicio_bano_id:
            servicio_bano = db.query(ServicioBano).filter(
                ServicioBano.id == payload.servicio_bano_id,
                ServicioBano.clinica_id == payload.clinica_id,
                ServicioBano.is_deleted == False
            ).first()

        if not servicio_bano:
            # Buscar el servicio de baño por defecto o primer activo
            servicio_bano = db.query(ServicioBano).filter(
                ServicioBano.clinica_id == payload.clinica_id,
                ServicioBano.activo == True,
                ServicioBano.is_deleted == False
            ).first()

        if servicio_bano and servicio_bano.producto_id:
            producto = db.query(Producto).filter(
                Producto.id == servicio_bano.producto_id,
                Producto.clinica_id == payload.clinica_id,
                Producto.is_deleted == False
            ).first()
            if producto:
                consumo = servicio_bano.cantidad_consumo or 50.0
                producto.stock_actual = max(0.0, round(float(producto.stock_actual) - float(consumo), 2))
                stock_descontado = consumo
                insumo_nombre = producto.nombre
                stock_restante = producto.stock_actual
                db.flush()

    db.commit()

    return AtencionResponse(
        id=atencion.id,
        tipo_atencion=atencion.tipo_atencion,
        motivo=atencion.motivo,
        mascota_id=atencion.mascota_id,
        vacuna_id=vacuna_id,
        seguimiento_id=seguimiento_id,
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


@router.patch(
    "/api/clinic/clientes/{cliente_id}/reset-pin",
    status_code=status.HTTP_200_OK,
    summary="Restablecer PIN de Cliente / Dueño",
    description="Asigna cliente.pin_hash = None para que se le pida crear uno nuevo en su próximo acceso.",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
@router.post(
    "/api/clinic/clientes/{cliente_id}/reset-pin",
    status_code=status.HTTP_200_OK,
    summary="Restablecer PIN de Cliente / Dueño (Alias POST)",
    description="Asigna cliente.pin_hash = None para que se le pida crear uno nuevo en su próximo acceso.",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def resetear_pin_cliente(
    cliente_id: int,
    db: Session = Depends(get_db)
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

    cliente.pin_hash = None
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

@router.get("/login", response_class=HTMLResponse, summary="Vista Login Veterinario")
def vista_login_veterinario(request: Request, error: Optional[str] = None, db: Session = Depends(get_db)):
    current_user = obtener_veterinario_actual(request, db)
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request=request,
        name="clinic/login.html",
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
            name="clinic/login.html",
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
            name="clinic/login.html",
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
    if current_user.rol != "ADMIN":
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
    if not current_user or current_user.rol != "ADMIN":
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

    # Cálculo dinámico de periodo de prueba (14 días desde clinica.created_at)
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

    # 1. Obtener clientes vinculados a esta clínica (registrados directamente o con mascotas/atenciones)
    clientes_raw = db.query(Cliente).filter(
        Cliente.is_deleted == False,
        or_(
            Cliente.clinica_id == target_clinica_id,
            Cliente.id.in_(
                db.query(Mascota.cliente_id).filter(
                    Mascota.clinica_id == target_clinica_id,
                    Mascota.is_deleted == False
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
        # Todas las mascotas vinculadas a este DNI unificado (deduplicadas por Mascota.id)
        mascotas_query = db.query(Mascota).join(Cliente).filter(
            Cliente.dni == c.dni,
            Mascota.is_deleted == False
        ).order_by(Mascota.nombre.asc()).all()

        mascotas_dict = {}
        for m in mascotas_query:
            if m.id not in mascotas_dict:
                mascotas_dict[m.id] = m
        todas_mascotas = list(mascotas_dict.values())

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

    mascota_query = db.query(Mascota).filter(
        Mascota.id == mascota_id,
        Mascota.is_deleted == False,
        Mascota.clinica_id == current_user.clinica_id
    )

    mascota = mascota_query.first()

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
    citas = db.query(Cita).filter(
        Cita.clinica_id == target_clinica_id,
        Cita.fecha == fecha_filtro,
        Cita.is_deleted == False
    ).order_by(Cita.hora.asc()).all()

    total_hoy = len(citas)
    total_pendientes = sum(1 for c in citas if c.estado == "PENDIENTE")
    total_confirmadas = sum(1 for c in citas if c.estado == "CONFIRMADA")
    total_canceladas = sum(1 for c in citas if c.estado == "CANCELADA")

    # Citas pendientes en OTRAS fechas futuras para alertar al veterinario
    otras_fechas_query = db.query(Cita).filter(
        Cita.clinica_id == target_clinica_id,
        Cita.is_deleted == False,
        Cita.estado == "PENDIENTE",
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
        Cita.estado == "PENDIENTE",
        Cita.fecha >= hoy
    ).count()

    # Próximas 15 a 20 citas futuras (ordenadas cronológicamente para panel avanzado)
    proximas_citas = db.query(Cita).filter(
        Cita.clinica_id == target_clinica_id,
        Cita.is_deleted == False,
        Cita.fecha >= hoy,
        Cita.estado.in_(["PENDIENTE", "CONFIRMADA"])
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
            "total_canceladas": total_canceladas,
            "otras_fechas_pendientes": list(resumen_otras_fechas.values()),
            "citas_pendientes_count": total_pendientes_global
        }
    )


@router.put(
    "/api/clinic/citas/{cita_id}/confirmar",
    summary="Confirmar Cita Agendada",
    description="Actualiza el estado de la cita a CONFIRMADA.",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def confirmar_cita_veterinario(
    cita_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    target_clinica_id = current_user.clinica_id if current_user else 1

    cita = db.query(Cita).filter(
        Cita.id == cita_id,
        Cita.clinica_id == target_clinica_id,
        Cita.is_deleted == False
    ).first()

    if not cita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cita no encontrada.")

    cita.estado = "CONFIRMADA"
    db.commit()
    db.refresh(cita)

    return {
        "mensaje": "Cita confirmada exitosamente.",
        "cita_id": cita.id,
        "estado": cita.estado
    }


@router.put(
    "/api/clinic/citas/{cita_id}/cancelar",
    summary="Cancelar Cita Agendada",
    description="Actualiza el estado de la cita a CANCELADA.",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def cancelar_cita_veterinario(
    cita_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    target_clinica_id = current_user.clinica_id if current_user else 1

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
    summary="Registrar Cita desde el Panel del Veterinario",
    dependencies=[Depends(verificar_acceso_veterinario)]
)
def crear_cita_veterinario(
    payload: CitaCreateVetRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = obtener_veterinario_actual(request, db)
    target_clinica_id = current_user.clinica_id if current_user else (payload.clinica_id or 1)

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
    db.commit()
    db.refresh(cita)

    return {
        "mensaje": "Cita agendada exitosamente.",
        "cita_id": cita.id,
        "fecha": str(cita.fecha),
        "hora": cita.hora.strftime("%H:%M"),
        "estado": cita.estado
    }


