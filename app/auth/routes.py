import urllib.parse
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.config import settings
from app.core.security import create_access_token
from app.clinic.models import Veterinario, Cliente
from app.core.models import Clinica
from app.auth.schemas import (
    VetLoginRequest,
    VetLoginResponse,
    ClientLoginRequest,
    ClientLoginResponse,
    VerificarOtpRequest,
    ReenviarOtpRequest,
    CheckDniRequest,
    CheckDniResponse,
)
from app.auth.service import AuthService

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])
google_router = APIRouter(tags=["Google OAuth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def get_google_redirect_uri(request: Request) -> str:
    """Calcula dinámicamente el redirect_uri adecuado para Google OAuth."""
    if settings.GOOGLE_REDIRECT_URI:
        return settings.GOOGLE_REDIRECT_URI

    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:8000"
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    if "onrender.com" in host or "https" in str(request.base_url):
        proto = "https"

    return f"{proto}://{host}/auth/google/callback"


async def handle_google_login_redirect(request: Request):
    redirect_uri = get_google_redirect_uri(request)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account"
    }
    url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=url)


async def handle_google_callback_process(
    request: Request,
    code: Optional[str],
    error: Optional[str],
    db: Session
):
    if error or not code:
        return RedirectResponse(url=f"/login?error=Acceso cancelado con Google: {error or 'Código no recibido'}")

    redirect_uri = get_google_redirect_uri(request)

    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri
            }
        )

        if token_resp.status_code != 200:
            err_text = token_resp.text
            try:
                err_text = token_resp.json().get("error_description", err_text)
            except Exception:
                pass
            return RedirectResponse(url=f"/login?error=Error al validar con Google: {err_text}")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")

        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if userinfo_resp.status_code != 200:
            return RedirectResponse(url="/login?error=No se pudo obtener información del perfil de Google.")

        userinfo = userinfo_resp.json()

    email = userinfo.get("email", "").strip().lower()
    google_id = userinfo.get("sub")
    nombre = userinfo.get("name", "Veterinario")

    if not email:
        return RedirectResponse(url="/login?error=El correo de Google no es válido o no fue proporcionado.")

    # Buscar veterinario existente
    vet = db.query(Veterinario).filter(
        (Veterinario.email == email) | (Veterinario.google_id == google_id),
        Veterinario.is_deleted == False
    ).first()

    if not vet:
        # Registrar nueva Clínica y Veterinario titular
        clinica = Clinica(
            nombre=f"Clínica de {nombre}",
            zona_horaria="America/Lima",
            plan_activo="solo"
        )
        db.add(clinica)
        db.flush()

        vet = Veterinario(
            clinica_id=clinica.id,
            email=email,
            nombre=nombre,
            google_id=google_id,
            rol="ADMIN",
            is_active=True,
            is_verified=True
        )
        db.add(vet)
        db.commit()
        db.refresh(vet)
    else:
        if not vet.is_active:
            return RedirectResponse(url="/login?error=Esta cuenta de veterinario se encuentra desactivada.")
        if not vet.google_id:
            vet.google_id = google_id
        if not vet.nombre and nombre:
            vet.nombre = nombre
        vet.is_verified = True
        db.commit()
        db.refresh(vet)

    # Generar JWT para cookie de sesión
    token_payload = {
        "sub": str(vet.id),
        "clinica_id": vet.clinica_id,
        "role": vet.rol,
        "email": vet.email,
        "username": vet.username,
        "nombre": vet.nombre,
        "is_verified": True
    }
    jwt_token = create_access_token(data=token_payload)

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="vet_token",
        value=jwt_token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7
    )
    return response


@google_router.get("/auth/google/login", summary="Iniciar Google OAuth")
@router.get("/google/login", summary="Iniciar Google OAuth (API)")
async def google_login(request: Request):
    return await handle_google_login_redirect(request)


@google_router.get("/auth/google/callback", summary="Callback Google OAuth")
@router.get("/google/callback", summary="Callback Google OAuth (API)")
async def google_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db)
):
    return await handle_google_callback_process(request, code, error, db)


@google_router.post(
    "/api/portal/check-dni",
    response_model=CheckDniResponse,
    status_code=status.HTTP_200_OK,
    summary="Verificar DNI de Dueño para Login PWA",
    description="Busca al cliente por DNI y determina si existe y si requiere crear su PIN por primera vez."
)
@router.post(
    "/portal/check-dni",
    response_model=CheckDniResponse,
    status_code=status.HTTP_200_OK,
    summary="Verificar DNI de Dueño para Login PWA (Alias Auth)",
    include_in_schema=False
)
def check_dni_portal(
    payload: CheckDniRequest,
    db: Session = Depends(get_db)
) -> CheckDniResponse:
    dni_clean = payload.dni.strip()
    clientes = db.query(Cliente).filter(
        Cliente.dni == dni_clean,
        Cliente.is_deleted == False
    ).all()

    if not clientes:
        return CheckDniResponse(
            exists=False,
            needs_pin=False,
            nombre=None,
            clinica_id=None,
            clinica_nombre=None,
            clinica_logo=None
        )

    cliente = clientes[0]
    needs_pin = bool(cliente.pin_hash is None or str(cliente.pin_hash).strip() == "")
    clinica = cliente.clinica
    clinica_nombre = clinica.nombre_mostrado if clinica else None
    clinica_logo = clinica.logo_url if clinica else None
    nombre = cliente.nombre_completo or cliente.nombres or "Dueño de Mascota"

    return CheckDniResponse(
        exists=True,
        needs_pin=needs_pin,
        nombre=nombre,
        clinica_id=cliente.clinica_id,
        clinica_nombre=clinica_nombre,
        clinica_logo=clinica_logo
    )


@router.post(
    "/vet/login",
    response_model=VetLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Login / Google Auth para Veterinarios",
    description="Autentica al veterinario con credenciales / Google y retorna JWT con clinica_id y rol."
)
def login_vet(
    payload: VetLoginRequest,
    db: Session = Depends(get_db)
) -> VetLoginResponse:
    return AuthService.login_veterinario(db, payload)


@router.post(
    "/verificar",
    response_model=VetLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Verificar código OTP y activar cuenta",
    description="Valida el código de 6 dígitos enviado por correo para activar la cuenta de la clínica."
)
def verificar_otp_api(
    payload: VerificarOtpRequest,
    db: Session = Depends(get_db)
) -> VetLoginResponse:
    return AuthService.verificar_otp(db, payload.email, payload.otp_code)


@router.post(
    "/reenviar-otp",
    status_code=status.HTTP_200_OK,
    summary="Reenviar código OTP de verificación",
    description="Genera un nuevo código OTP y lo envía al correo registrado."
)
def reenviar_otp_api(
    payload: ReenviarOtpRequest,
    db: Session = Depends(get_db)
):
    return AuthService.reenviar_otp(db, payload.email)


@router.post(
    "/client/login",
    response_model=ClientLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Login para Dueños de Mascotas (DNI + PIN)",
    description=(
        "Autenticación para clientes mediante DNI. "
        "Si es primer ingreso (pin_hash es NULL), se exige la creación de un PIN de 4 dígitos (enviando nuevo_pin). "
        "Si ya cuenta con PIN, se valida DNI + PIN para retornar el token JWT."
    )
)
def login_client(
    payload: ClientLoginRequest,
    db: Session = Depends(get_db)
) -> ClientLoginResponse:
    return AuthService.login_cliente(db, payload)

