from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.schemas import (
    VetLoginRequest,
    VetLoginResponse,
    ClientLoginRequest,
    ClientLoginResponse,
)
from app.auth.service import AuthService

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])


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
