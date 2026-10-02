from datetime import timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.models import Clinica
from app.core.security import decode_access_token
from app.core.timezone import get_lima_now
from app.clinic.models import Veterinario, Mascota
from app.database import get_db
from app.admin.schemas import (
    AjustarDiasRequest,
    CambiarEstadoSuscripcionRequest,
    AdminClinicaItem,
    AdminUsuarioSummary,
)

templates = Jinja2Templates(directory="app/templates")


def require_superadmin(
    request: Request,
    db: Session = Depends(get_db)
) -> Veterinario:
    """
    Dependencia de seguridad estricta para el Panel SuperAdmin.
    1. Verifica que el usuario esté autenticado mediante cookie 'vet_token' o header 'Authorization: Bearer'.
    2. Valida que su rol sea 'SUPER_ADMIN' (o is_superadmin == True).
    Si no cumple, lanza HTTPException(status_code=403, detail="Acceso denegado. Privilegios insuficientes.").
    """
    token = request.cookies.get("vet_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Privilegios insuficientes."
        )

    payload = decode_access_token(token)
    if not payload or payload.get("role") == "client":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Privilegios insuficientes."
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Privilegios insuficientes."
        )

    try:
        vet_id = int(user_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Privilegios insuficientes."
        )

    vet = db.query(Veterinario).filter(
        Veterinario.id == vet_id,
        Veterinario.is_deleted == False,
        Veterinario.is_active == True
    ).first()

    if not vet:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Privilegios insuficientes."
        )

    # Garantizar semilla automática si es el correo maestro roggerjjj@gmail.com
    if vet.email and vet.email.strip().lower() == "roggerjjj@gmail.com":
        if vet.rol != "SUPER_ADMIN" or not getattr(vet, "is_superadmin", False):
            vet.rol = "SUPER_ADMIN"
            vet.is_superadmin = True
            db.commit()
            db.refresh(vet)

    es_superadmin = (
        vet.rol == "SUPER_ADMIN"
        or bool(getattr(vet, "is_superadmin", False))
    )
    if not es_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Privilegios insuficientes."
        )

    return vet


router = APIRouter(
    prefix="/admin",
    tags=["SuperAdmin"],
    dependencies=[Depends(require_superadmin)]
)


def _serializar_clinica_admin(clinica: Clinica, db: Session) -> dict:
    """Construye la estructura enriquecida de una clínica para el Panel SuperAdmin."""
    vets = [
        v for v in clinica.veterinarios
        if not v.is_deleted
    ]
    # Priorizar al titular (SUPER_ADMIN o ADMIN) como contacto principal
    titular = next(
        (v for v in vets if v.rol in ("SUPER_ADMIN", "ADMIN", "VETERINARIO", "VET")),
        vets[0] if vets else None
    )

    total_pacientes = db.query(Mascota).filter(
        Mascota.clinica_id == clinica.id,
        Mascota.is_deleted == False
    ).count()

    estado_norm = clinica.estado_suscripcion_normalizado
    dias_restantes = clinica.dias_restantes_trial

    usuarios_data = [
        {
            "id": v.id,
            "nombre": v.nombre or v.username or "Sin nombre",
            "email": v.email,
            "username": v.username,
            "rol": v.rol,
            "is_superadmin": bool(getattr(v, "is_superadmin", False) or v.rol == "SUPER_ADMIN"),
            "is_active": v.is_active
        }
        for v in vets
    ]

    return {
        "id": clinica.id,
        "nombre": clinica.nombre,
        "nombre_comercial": clinica.nombre_comercial,
        "nombre_mostrado": clinica.nombre_mostrado,
        "telefono": clinica.telefono,
        "email": titular.email if titular else None,
        "contacto_email": titular.email if titular else None,
        "contacto_nombre": (titular.nombre or titular.username) if titular else "Sin titular",
        "veterinario_id": titular.id if titular else None,
        "veterinario_rol": titular.rol if titular else None,
        "veterinario_is_superadmin": bool(
            titular and (getattr(titular, "is_superadmin", False) or titular.rol == "SUPER_ADMIN")
        ),
        "fecha_registro": clinica.created_at.strftime("%d/%m/%Y %H:%M") if clinica.created_at else None,
        "created_at": clinica.created_at.isoformat() if clinica.created_at else None,
        "estado_suscripcion": estado_norm,
        "trial_ends_at": clinica.trial_ends_at.isoformat() if clinica.trial_ends_at else None,
        "trial_ends_at_formatted": clinica.trial_ends_at.strftime("%d/%m/%Y") if clinica.trial_ends_at else "Sin fecha",
        "dias_restantes": dias_restantes,
        "plan_activo": clinica.plan_activo,
        "total_pacientes": total_pacientes,
        "usuarios": usuarios_data,
    }


@router.get(
    "",
    response_class=HTMLResponse,
    summary="Vista Principal del Panel SuperAdmin"
)
@router.get(
    "/dashboard",
    response_class=HTMLResponse,
    summary="Vista Dashboard del Panel SuperAdmin"
)
def vista_admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_superadmin)
):
    """Renderiza la interfaz protegida admin_dashboard.html para gestión SaaS y roles."""
    clinicas_db = db.query(Clinica).filter(
        Clinica.is_deleted == False
    ).order_by(Clinica.id.desc()).all()

    clinicas_data = [_serializar_clinica_admin(c, db) for c in clinicas_db]

    usuarios_db = db.query(Veterinario).filter(
        Veterinario.is_deleted == False
    ).order_by(Veterinario.id.asc()).all()

    kpis = {
        "total_clinicas": len(clinicas_data),
        "activas": sum(1 for c in clinicas_data if c["estado_suscripcion"] == "ACTIVE"),
        "en_trial": sum(1 for c in clinicas_data if c["estado_suscripcion"] == "TRIAL"),
        "expiradas": sum(1 for c in clinicas_data if c["estado_suscripcion"] == "EXPIRED"),
        "total_superadmins": sum(
            1 for u in usuarios_db if u.rol == "SUPER_ADMIN" or getattr(u, "is_superadmin", False)
        )
    }

    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={
            "current_user": current_user,
            "clinicas": clinicas_data,
            "usuarios": usuarios_db,
            "kpis": kpis
        }
    )


@router.get(
    "/clinicas",
    summary="Listar todas las clínicas (SuperAdmin)"
)
def listar_clinicas_admin(
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_superadmin)
):
    """
    Retorna la lista de todas las clínicas con sus datos de contacto,
    fecha de registro, estado de suscripción (TRIAL, ACTIVE, EXPIRED) y días restantes (trial_ends_at).
    """
    clinicas_db = db.query(Clinica).filter(
        Clinica.is_deleted == False
    ).order_by(Clinica.id.desc()).all()

    resultado = [_serializar_clinica_admin(c, db) for c in clinicas_db]

    if q and q.strip():
        termino = q.strip().lower()
        resultado = [
            c for c in resultado
            if termino in (c["nombre"] or "").lower()
            or termino in (c["nombre_comercial"] or "").lower()
            or termino in (c["contacto_email"] or "").lower()
            or termino in (c["contacto_nombre"] or "").lower()
            or termino in (c["telefono"] or "").lower()
            or termino in (c["estado_suscripcion"] or "").lower()
        ]

    return resultado


@router.post(
    "/clinicas/{id}/ajustar-dias",
    summary="Ajustar días de prueba (trial_ends_at) de una clínica"
)
def ajustar_dias_clinica(
    id: int,
    payload: AjustarDiasRequest,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_superadmin)
):
    """
    Modifica la columna trial_ends_at sumando o restando `dias_a_sumar`
    (entero, puede ser positivo o negativo) para extender o recortar el tiempo de prueba.
    """
    clinica = db.query(Clinica).filter(
        Clinica.id == id,
        Clinica.is_deleted == False
    ).first()

    if not clinica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clínica no encontrada."
        )

    ahora = get_lima_now()
    base_time = clinica.trial_ends_at or ahora
    if base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=ahora.tzinfo)

    nuevo_vencimiento = base_time + timedelta(days=int(payload.dias_a_sumar))
    clinica.trial_ends_at = nuevo_vencimiento

    # Si estaba marcada como EXPIRED/EXPIRADO y ahora tiene fecha futura, reactivar a TRIAL
    estado_actual = (clinica.estado_suscripcion or "").upper()
    if estado_actual in ("EXPIRED", "EXPIRADO") and nuevo_vencimiento > ahora:
        clinica.estado_suscripcion = "TRIAL"

    db.commit()
    db.refresh(clinica)

    datos_actualizados = _serializar_clinica_admin(clinica, db)
    accion_str = f"+{payload.dias_a_sumar}" if payload.dias_a_sumar >= 0 else str(payload.dias_a_sumar)

    return {
        "mensaje": f"Se ajustaron {accion_str} días a la clínica '{clinica.nombre_mostrado}'.",
        "clinica": datos_actualizados,
        "id": clinica.id,
        "trial_ends_at": datos_actualizados["trial_ends_at"],
        "dias_restantes": datos_actualizados["dias_restantes"],
        "estado_suscripcion": datos_actualizados["estado_suscripcion"]
    }


@router.post(
    "/clinicas/{id}/estado",
    summary="Cambiar estado de suscripción de una clínica (ACTIVE, TRIAL, EXPIRED)"
)
def cambiar_estado_suscripcion_clinica(
    id: int,
    payload: CambiarEstadoSuscripcionRequest,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_superadmin)
):
    """Permite al SuperAdmin cambiar el estado de suscripción de una clínica."""
    clinica = db.query(Clinica).filter(
        Clinica.id == id,
        Clinica.is_deleted == False
    ).first()

    if not clinica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clínica no encontrada."
        )

    nuevo_estado = payload.estado_suscripcion.strip().upper()
    if nuevo_estado not in ("TRIAL", "ACTIVE", "ACTIVO", "EXPIRED", "EXPIRADO"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Estado inválido. Valores permitidos: TRIAL, ACTIVE, EXPIRED."
        )

    ahora = get_lima_now()
    if nuevo_estado in ("ACTIVE", "ACTIVO"):
        clinica.estado_suscripcion = "ACTIVE"
        clinica.plan_activo = "emprendedor"
    elif nuevo_estado in ("EXPIRED", "EXPIRADO"):
        clinica.estado_suscripcion = "EXPIRED"
        clinica.trial_ends_at = ahora - timedelta(days=1)
    else:
        clinica.estado_suscripcion = "TRIAL"
        if not clinica.trial_ends_at or clinica.trial_ends_at <= ahora:
            clinica.trial_ends_at = ahora + timedelta(days=14)

    db.commit()
    db.refresh(clinica)

    datos_actualizados = _serializar_clinica_admin(clinica, db)
    return {
        "mensaje": f"Estado de '{clinica.nombre_mostrado}' actualizado a {datos_actualizados['estado_suscripcion']}.",
        "clinica": datos_actualizados
    }


@router.post(
    "/usuarios/{id}/promover",
    summary="Promover un usuario al rol SUPER_ADMIN"
)
def promover_usuario_superadmin(
    id: int,
    db: Session = Depends(get_db),
    current_user: Veterinario = Depends(require_superadmin)
):
    """
    Permite al SuperAdmin actual otorgar el rol SUPER_ADMIN (e is_superadmin=True)
    a otro usuario registrado en la plataforma.
    """
    usuario = db.query(Veterinario).filter(
        Veterinario.id == id,
        Veterinario.is_deleted == False
    ).first()

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado."
        )

    usuario.rol = "SUPER_ADMIN"
    usuario.is_superadmin = True
    db.commit()
    db.refresh(usuario)

    return {
        "mensaje": f"El usuario '{usuario.nombre or usuario.email}' ahora tiene privilegios de SUPER_ADMIN.",
        "usuario": {
            "id": usuario.id,
            "nombre": usuario.nombre,
            "email": usuario.email,
            "username": usuario.username,
            "rol": usuario.rol,
            "is_superadmin": usuario.is_superadmin,
            "clinica_id": usuario.clinica_id
        }
    }
