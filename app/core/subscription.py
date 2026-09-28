from typing import Optional
from fastapi import Request, HTTPException, status, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.core.models import Clinica
from app.database import SessionLocal, get_db


def verificar_suscripcion(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[Clinica]:
    """
    Dependencia de FastAPI para verificar si la clínica del usuario autenticado
    cuenta con una suscripción válida (Plan ACTIVO o TRIAL vigente dentro de los 14 días).
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

    clinica_id = payload.get("clinica_id")
    if not clinica_id:
        return None

    clinica = db.query(Clinica).filter(
        Clinica.id == int(clinica_id),
        Clinica.is_deleted == False
    ).first()

    if not clinica:
        return None

    if not clinica.tiene_suscripcion_activa:
        accept = request.headers.get("accept", "")
        if "text/html" in accept and "application/json" not in accept:
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,
                headers={"Location": "/configuracion/facturacion?alerta=suscripcion_expirada"}
            )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Suscripción expirada. Tu periodo de prueba de 14 días ha finalizado. Actualiza al Plan Emprendedor para continuar operando."
        )

    return clinica


class SubscriptionMiddleware(BaseHTTPMiddleware):
    """
    Middleware global para proteger rutas operativas (POST, PUT, PATCH, DELETE).
    Si la clínica del veterinario superó los 14 días de prueba y no tiene plan activo,
    bloquea las operaciones y redirige a /configuracion/facturacion o responde HTTP 402.
    """

    RUTAS_EXCLUIDAS_PREFIX = (
        "/api/auth",
        "/auth",
        "/login",
        "/logout",
        "/registro",
        "/verificar",
        "/portal",
        "/api/portal",
        "/configuracion/facturacion",
        "/api/billing",
        "/static",
        "/uploads",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/health",
        "/terminos-y-condiciones",
        "/politica-privacidad",
        "/politica-reembolsos",
    )

    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        # Solo auditar métodos de mutación operativa
        if method not in ("POST", "PUT", "PATCH", "DELETE"):
            return await call_next(request)

        path = request.url.path

        # Omitir rutas de autenticación, portal cliente y facturación
        for prefix in self.RUTAS_EXCLUIDAS_PREFIX:
            if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
                return await call_next(request)

        # Detectar veterinario autenticado
        token = request.cookies.get("vet_token")
        if not token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1]

        if not token:
            return await call_next(request)

        payload = decode_access_token(token)
        if not payload or payload.get("role") == "client":
            return await call_next(request)

        clinica_id = payload.get("clinica_id")
        if not clinica_id:
            return await call_next(request)

        # Obtener sesión respetando overrides (para tests con SQLite en memoria y producción)
        get_db_func = request.app.dependency_overrides.get(get_db, None)
        if get_db_func:
            db_gen = get_db_func()
            db = next(db_gen)
            close_gen = True
        else:
            db = SessionLocal()
            close_gen = False

        try:
            clinica = db.query(Clinica).filter(
                Clinica.id == int(clinica_id),
                Clinica.is_deleted == False
            ).first()

            if clinica and not clinica.tiene_suscripcion_activa:
                accept = request.headers.get("accept", "")
                if "text/html" in accept and "application/json" not in accept:
                    return RedirectResponse(
                        url="/configuracion/facturacion?alerta=suscripcion_expirada",
                        status_code=status.HTTP_303_SEE_OTHER
                    )
                return JSONResponse(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    content={
                        "detail": "Suscripción expirada. Tu periodo de prueba de 14 días ha finalizado. Actualiza a Plan Emprendedor para continuar.",
                        "redirect_url": "/configuracion/facturacion",
                        "estado_suscripcion": clinica.estado_suscripcion,
                        "dias_restantes": 0
                    }
                )
        except Exception:
            # En caso de error de base de datos transitorio, permitir que continúe
            pass
        finally:
            if close_gen:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
            else:
                db.close()

        return await call_next(request)
