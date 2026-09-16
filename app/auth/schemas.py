import re
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class TokenData(BaseModel):
    sub: str
    clinica_id: int
    role: str
    exp: Optional[int] = None


class VetLoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Correo electrónico del veterinario")
    password: Optional[str] = Field(None, min_length=4, description="Contraseña de acceso")
    google_id: Optional[str] = Field(None, description="Identificador único proporcionado por Google")
    google_token: Optional[str] = Field(None, description="Token de autenticación / id_token de Google")
    clinica_id: Optional[int] = Field(None, description="ID de la clínica asignada (opcional si ya existe)")


class VetRegisterRequest(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=150, description="Nombre del profesional")
    email: EmailStr = Field(..., description="Correo electrónico del veterinario")
    password: str = Field(..., min_length=4, description="Contraseña de acceso")
    nombre_clinica: str = Field(..., min_length=2, max_length=200, description="Nombre de la clínica veterinaria")


class VetInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: Optional[str] = None
    email: str
    rol: str
    clinica_id: int
    is_active: bool


class VetLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    veterinario: VetInfo


class ClientLoginRequest(BaseModel):
    clinica_id: int = Field(..., description="Identificador de la clínica veterinaria (multi-tenant)")
    dni: str = Field(..., min_length=4, max_length=20, description="DNI del cliente / dueño de mascota")
    pin: Optional[str] = Field(None, description="PIN actual de 4 dígitos numéricos")
    nuevo_pin: Optional[str] = Field(None, description="Nuevo PIN de 4 dígitos numéricos (para primer ingreso)")

    @field_validator("pin", "nuevo_pin")
    @classmethod
    def validate_pin_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not re.fullmatch(r"^\d{4}$", v):
                raise ValueError("El PIN debe constar exactamente de 4 dígitos numéricos.")
        return v


class ClientInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dni: str
    telefono: Optional[str]
    clinica_id: int


class ClientLoginResponse(BaseModel):
    access_token: Optional[str] = None
    token_type: str = "bearer"
    requires_pin_setup: bool = False
    message: str
    cliente: Optional[ClientInfo] = None
