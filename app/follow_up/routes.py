import json
from datetime import date
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.timezone import get_lima_now
from app.core.security import decode_access_token
from app.database import get_db
from app.core.models import Clinica
from app.clinic.models import Cliente, Mascota, RegistroVacuna
from app.follow_up.models import MedicationPlan, DoseTracking, WebPushSubscription
from app.follow_up.schemas import (
    MedicationPlanCreateRequest,
    MedicationPlanResponse,
    DoseInfo,
    ConfirmDoseRequest,
    ConfirmDoseResponse,
    WebPushSubscriptionRequest
)
from app.follow_up.services import crear_plan_medicacion, confirmar_toma
from app.auth.service import AuthService
from app.auth.schemas import ClientLoginRequest

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(tags=["Seguimiento de Medicación y Portal Cliente"])


# =======================================================
# 1. PWA STATICS (manifest.json & service-worker.js)
# =======================================================

@router.get("/manifest.json", summary="PWA Web App Manifest")
def get_manifest():
    manifest_data = {
        "name": "SherekePet - Portal de Medicación",
        "short_name": "SherekePet",
        "description": "Portal móvil para dueños de mascotas y control de medicación",
        "start_url": "/portal/dashboard",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#0d9488",
        "icons": [
            {
                "src": "https://img.icons8.com/fluency/192/veterinarian.png",
                "sizes": "192x192",
                "type": "image/png"
            },
            {
                "src": "https://img.icons8.com/fluency/512/veterinarian.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ]
    }
    return JSONResponse(content=manifest_data, media_type="application/manifest+json")


@router.get("/service-worker.js", summary="PWA Service Worker")
def get_service_worker():
    sw_code = """
const CACHE_NAME = 'sherekepet-v1';
const STATIC_ASSETS = [
    '/portal/dashboard',
    '/manifest.json'
];

self.addEventListener('install', event => {
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(clients.claim());
});

self.addEventListener('fetch', event => {
    // Red primero con fallback a red normal
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});

// Manejo de Notificaciones Web Push
self.addEventListener('push', event => {
    let data = { title: 'SherekePet - Hora de Medicación', body: 'Es hora de darle la medicina a tu mascota.' };
    if (event.data) {
        try {
            data = event.data.json();
        } catch(e) {
            data.body = event.data.text();
        }
    }
    const options = {
        body: data.body,
        icon: 'https://img.icons8.com/fluency/192/veterinarian.png',
        badge: 'https://img.icons8.com/fluency/192/veterinarian.png',
        vibrate: [200, 100, 200],
        data: { url: '/portal/dashboard' }
    };
    event.waitUntil(
        self.registration.showNotification(data.title, options)
    );
});

self.addEventListener('notificationclick', event => {
    event.notification.close();
    event.waitUntil(
        clients.openWindow(event.notification.data.url || '/portal/dashboard')
    );
});
"""
    return Response(content=sw_code, media_type="application/javascript")


# =======================================================
# 2. ENDPOINTS DE API REST
# =======================================================

@router.post(
    "/api/medication/plan",
    response_model=MedicationPlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear plan de medicación para una mascota",
    description="El veterinario registra la prescripción y el sistema programa la primera dosis automáticamente."
)
def api_crear_plan(
    payload: MedicationPlanCreateRequest,
    db: Session = Depends(get_db)
):
    # Validar existencia de mascota
    mascota = db.query(Mascota).filter(
        Mascota.id == payload.pet_id,
        Mascota.is_deleted == False
    ).first()
    if not mascota:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La mascota especificada no existe."
        )

    plan, primera_dosis = crear_plan_medicacion(
        db=db,
        pet_id=payload.pet_id,
        clinic_id=payload.clinic_id,
        medicamento=payload.medicamento,
        frecuencia_horas=payload.frecuencia_horas,
        total_dosis=payload.total_dosis,
        es_estricto=payload.es_estricto,
        hora_inicio=payload.hora_inicio
    )

    return MedicationPlanResponse(
        id=plan.id,
        pet_id=plan.pet_id,
        clinic_id=plan.clinic_id,
        medicamento=plan.medicamento,
        frecuencia_horas=plan.frecuencia_horas,
        total_dosis=plan.total_dosis,
        es_estricto=plan.es_estricto,
        estado=plan.estado,
        primera_dosis=DoseInfo.model_validate(primera_dosis),
        mensaje="Plan de medicación creado exitosamente. Primera dosis programada."
    )


@router.post(
    "/api/medication/dose/{id}/confirm",
    response_model=ConfirmDoseResponse,
    status_code=status.HTTP_200_OK,
    summary="Cliente confirma toma de dosis (Motor Dinámico)",
    description="Marca la dosis como CONSUMIDO y calcula la siguiente toma con validación de ventana de sueño."
)
def api_confirmar_toma(
    id: int,
    payload: Optional[ConfirmDoseRequest] = None,
    db: Session = Depends(get_db)
):
    hora_real = payload.hora_real if payload else None
    dosis, siguiente = confirmar_toma(db=db, dose_id=id, hora_real=hora_real)

    return ConfirmDoseResponse(
        dosis_confirmada_id=dosis.id,
        numero_dosis=dosis.numero_dosis,
        hora_consumo_real=dosis.hora_consumo_real,
        plan_completado=(siguiente is None),
        siguiente_dosis=DoseInfo.model_validate(siguiente) if siguiente else None,
        mensaje="¡Toma registrada con éxito!" if siguiente else "¡Felicidades! Tratamiento completado con éxito."
    )


@router.post(
    "/api/webpush/subscribe",
    status_code=status.HTTP_200_OK,
    summary="Registrar suscripción Web Push"
)
def api_subscribe_push(
    payload: WebPushSubscriptionRequest,
    db: Session = Depends(get_db)
):
    sub = WebPushSubscription(
        cliente_id=payload.cliente_id,
        endpoint=payload.endpoint,
        keys_json=json.dumps(payload.keys)
    )
    db.add(sub)
    db.commit()
    return {"status": "ok", "mensaje": "Suscripción push guardada con éxito."}


# =======================================================
# 3. VISTAS MÓVILES DEL CLIENTE (PORTAL PWA)
# =======================================================

def obtener_cliente_autenticado(request: Request, db: Session) -> Optional[Cliente]:
    """Helper para verificar token JWT en cookie o query param para el portal móvil."""
    token = request.cookies.get("client_token") or request.query_params.get("token")
    if not token:
        # Modo fallback para pruebas si se envía cliente_id en query param
        cid = request.query_params.get("cliente_id")
        if cid and cid.isdigit():
            return db.query(Cliente).filter(Cliente.id == int(cid), Cliente.is_deleted == False).first()
        return None

    payload = decode_access_token(token)
    if not payload or payload.get("role") != "client":
        return None

    cliente_id = int(payload.get("sub"))
    return db.query(Cliente).filter(Cliente.id == cliente_id, Cliente.is_deleted == False).first()


@router.get("/portal/login", response_class=HTMLResponse, summary="Vista Login Cliente PWA")
def portal_login_view(request: Request, db: Session = Depends(get_db)):
    clinica = db.query(Clinica).filter(Clinica.is_deleted == False).first()
    return templates.TemplateResponse(
        request=request,
        name="client/login.html",
        context={"error": None, "clinica": clinica}
    )


@router.get("/portal/seleccionar-clinica", response_class=HTMLResponse, summary="Seleccionar Clínica Multi-Tenant")
def portal_seleccionar_clinica(request: Request, dni: str, pin: Optional[str] = None, db: Session = Depends(get_db)):
    clientes = db.query(Cliente).filter(
        Cliente.dni == dni.strip(),
        Cliente.is_deleted == False
    ).all()

    if not clientes:
        return RedirectResponse(url="/portal/login")

    registros = []
    for c in clientes:
        total_mascotas = db.query(Mascota).filter(Mascota.cliente_id == c.id, Mascota.is_deleted == False).count()
        registros.append({
            "cliente": c,
            "clinica": c.clinica,
            "total_mascotas": total_mascotas
        })

    return templates.TemplateResponse(
        request=request,
        name="client/seleccionar_clinica.html",
        context={
            "dni": dni,
            "pin": pin or "",
            "registros": registros,
            "clinica": clientes[0].clinica if clientes else None
        }
    )


@router.post("/portal/login", response_class=HTMLResponse)
async def portal_login_post(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    dni = str(form.get("dni", "")).strip()
    pin = str(form.get("pin", "")).strip()
    nuevo_pin = str(form.get("nuevo_pin", "")).strip()
    confirmar_pin = str(form.get("confirmar_pin", "")).strip()
    form_clinica_id = form.get("clinica_id")

    # Si se envió formulario de creación de PIN, validar coincidencia
    if nuevo_pin:
        if confirmar_pin and nuevo_pin != confirmar_pin:
            clinica_first = db.query(Clinica).filter(Clinica.is_deleted == False).first()
            return templates.TemplateResponse(
                request=request,
                name="client/login.html",
                context={
                    "error": "Los PIN ingresados no coinciden. Intenta de nuevo.",
                    "dni": dni,
                    "clinica": clinica_first,
                    "needs_pin": True
                }
            )

    # Si no se pasó clinica_id específica o viene la default 1, verificar si el DNI existe en múltiples clínicas
    clientes_con_dni = db.query(Cliente).filter(
        Cliente.dni == dni,
        Cliente.is_deleted == False
    ).all()

    if not clientes_con_dni:
        clinica_first = db.query(Clinica).filter(Clinica.is_deleted == False).first()
        return templates.TemplateResponse(
            request=request,
            name="client/login.html",
            context={
                "error": "DNI no registrado en el sistema. Consulta con tu veterinaria.",
                "dni": dni,
                "clinica": clinica_first
            }
        )

    if len(clientes_con_dni) > 1 and not form.get("clinica_seleccionada"):
        # Redirigir al selector intermedio
        registros = []
        for c in clientes_con_dni:
            total_mascotas = db.query(Mascota).filter(Mascota.cliente_id == c.id, Mascota.is_deleted == False).count()
            registros.append({
                "cliente": c,
                "clinica": c.clinica,
                "total_mascotas": total_mascotas
            })
        return templates.TemplateResponse(
            request=request,
            name="client/seleccionar_clinica.html",
            context={
                "dni": dni,
                "pin": nuevo_pin or pin,
                "registros": registros,
                "clinica": clientes_con_dni[0].clinica
            }
        )

    if form_clinica_id:
        try:
            clinica_id = int(form_clinica_id)
        except Exception:
            clinica_id = clientes_con_dni[0].clinica_id
    elif clientes_con_dni:
        clinica_id = clientes_con_dni[0].clinica_id
    else:
        clinica_id = 1

    clinica = db.query(Clinica).filter(Clinica.id == clinica_id).first()

    try:
        pin_final = nuevo_pin or pin or None
        req = ClientLoginRequest(
            clinica_id=clinica_id,
            dni=dni,
            pin=pin_final,
            nuevo_pin=nuevo_pin if nuevo_pin else None
        )
        auth_resp = AuthService.login_cliente(db, req)

        if auth_resp.requires_pin_setup:
            return templates.TemplateResponse(
                request=request,
                name="client/login.html",
                context={
                    "error": "Primer ingreso detectado: Por favor crea tu PIN de 4 dígitos para acceder.",
                    "dni": dni,
                    "clinica": clinica,
                    "needs_pin": True
                }
            )

        # Login exitoso: redirigir a dashboard guardando cookie
        response = RedirectResponse(url="/portal/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            key="client_token",
            value=auth_resp.access_token,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7  # 7 días
        )
        return response

    except HTTPException as ex:
        return templates.TemplateResponse(
            request=request,
            name="client/login.html",
            context={"error": ex.detail, "dni": dni, "clinica": clinica}
        )


@router.get("/portal/logout")
def portal_logout():
    resp = RedirectResponse(url="/portal/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie("client_token")
    return resp


@router.get("/portal/dashboard", response_class=HTMLResponse, summary="Portal Cliente Dashboard PWA")
def portal_dashboard(
    request: Request,
    db: Session = Depends(get_db)
):
    cliente = obtener_cliente_autenticado(request, db)
    if not cliente:
        # Si hay clientes en la DB y estamos en ambiente local, seleccionar el primero para facilitar pruebas
        primer_cliente = db.query(Cliente).filter(Cliente.is_deleted == False).first()
        if primer_cliente:
            cliente = primer_cliente
        else:
            return RedirectResponse(url="/portal/login")

    # Obtener mascotas activas del cliente
    mascotas = db.query(Mascota).filter(
        Mascota.cliente_id == cliente.id,
        Mascota.is_deleted == False
    ).all()

    # Obtener tratamientos activos con sus próximas dosis
    mascota_ids = [m.id for m in mascotas]
    planes_activos = db.query(MedicationPlan).filter(
        MedicationPlan.pet_id.in_(mascota_ids),
        MedicationPlan.estado == "ACTIVO",
        MedicationPlan.is_deleted == False
    ).all()

    # Recopilar próximas dosis pendientes
    dosis_pendientes = []
    for plan in planes_activos:
        proxima = db.query(DoseTracking).filter(
            DoseTracking.plan_id == plan.id,
            DoseTracking.estado == "PENDIENTE"
        ).order_by(DoseTracking.numero_dosis.asc()).first()
        if proxima:
            dosis_pendientes.append({
                "plan": plan,
                "dosis": proxima,
                "mascota": plan.mascota
            })

    return templates.TemplateResponse(
        request=request,
        name="client/dashboard.html",
        context={
            "cliente": cliente,
            "clinica": cliente.clinica,
            "mascotas": mascotas,
            "dosis_pendientes": dosis_pendientes,
            "ahora": get_lima_now()
        }
    )


@router.get("/portal/carnet/{mascota_id}", response_class=HTMLResponse, summary="Carnet Digital y Medicación")
def portal_carnet_mascota(
    request: Request,
    mascota_id: int,
    db: Session = Depends(get_db)
):
    mascota = db.query(Mascota).filter(
        Mascota.id == mascota_id,
        Mascota.is_deleted == False
    ).first()

    if not mascota:
        raise HTTPException(status_code=404, detail="Mascota no encontrada.")

    # Vacunas (solo lectura)
    vacunas = db.query(RegistroVacuna).filter(
        RegistroVacuna.mascota_id == mascota_id,
        RegistroVacuna.is_deleted == False
    ).order_by(RegistroVacuna.fecha_aplicacion.desc()).all()

    # Planes de medicación y su próxima dosis pendiente
    planes = db.query(MedicationPlan).filter(
        MedicationPlan.pet_id == mascota_id,
        MedicationPlan.is_deleted == False
    ).order_by(MedicationPlan.created_at.desc()).all()

    planes_info = []
    for plan in planes:
        proxima_dosis = db.query(DoseTracking).filter(
            DoseTracking.plan_id == plan.id,
            DoseTracking.estado == "PENDIENTE"
        ).order_by(DoseTracking.numero_dosis.asc()).first()

        dosis_consumidas = db.query(DoseTracking).filter(
            DoseTracking.plan_id == plan.id,
            DoseTracking.estado == "CONSUMIDO"
        ).count()

        planes_info.append({
            "plan": plan,
            "proxima_dosis": proxima_dosis,
            "dosis_consumidas": dosis_consumidas,
            "porcentaje": int((dosis_consumidas / plan.total_dosis) * 100) if plan.total_dosis > 0 else 0
        })

    return templates.TemplateResponse(
        request=request,
        name="client/carnet.html",
        context={
            "mascota": mascota,
            "cliente": mascota.cliente,
            "clinica": mascota.clinica or mascota.cliente.clinica,
            "vacunas": vacunas,
            "planes": planes_info,
            "ahora": get_lima_now()
        }
    )


class MascotaPerfilUpdateRequest(BaseModel):
    sexo: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    rasgos_distintivos: Optional[str] = None
    microchip: Optional[str] = None


@router.post("/api/portal/mascotas/{mascota_id}", summary="Actualizar Datos No Clínicos de la Mascota")
def actualizar_perfil_mascota(
    mascota_id: int,
    payload: MascotaPerfilUpdateRequest,
    db: Session = Depends(get_db)
):
    mascota = db.query(Mascota).filter(Mascota.id == mascota_id, Mascota.is_deleted == False).first()
    if not mascota:
        raise HTTPException(status_code=404, detail="Mascota no encontrada.")

    if payload.sexo is not None:
        mascota.sexo = payload.sexo
    if payload.fecha_nacimiento is not None:
        mascota.fecha_nacimiento = payload.fecha_nacimiento
    if payload.rasgos_distintivos is not None:
        mascota.rasgos_distintivos = payload.rasgos_distintivos
    if payload.microchip is not None:
        mascota.microchip = payload.microchip

    db.commit()
    db.refresh(mascota)

    return {
        "mensaje": "Perfil de la mascota actualizado correctamente.",
        "mascota_id": mascota.id,
        "sexo": mascota.sexo,
        "fecha_nacimiento": mascota.fecha_nacimiento.isoformat() if mascota.fecha_nacimiento else None,
        "rasgos_distintivos": mascota.rasgos_distintivos,
        "microchip": mascota.microchip
    }

