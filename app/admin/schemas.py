from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class AjustarDiasRequest(BaseModel):
    dias_a_sumar: int = Field(..., description="Cantidad de días a sumar o restar (puede ser negativo) a trial_ends_at")


class CambiarEstadoSuscripcionRequest(BaseModel):
    estado_suscripcion: str = Field(..., description="Nuevo estado: TRIAL, ACTIVE o EXPIRED")


class AdminUsuarioSummary(BaseModel):
    id: int
    nombre: Optional[str] = None
    email: Optional[str] = None
    username: Optional[str] = None
    rol: str
    is_superadmin: bool = False
    is_active: bool = True


class AdminClinicaItem(BaseModel):
    id: int
    nombre: str
    nombre_comercial: Optional[str] = None
    nombre_mostrado: str
    telefono: Optional[str] = None
    email: Optional[str] = None
    contacto_email: Optional[str] = None
    contacto_nombre: Optional[str] = None
    veterinario_id: Optional[int] = None
    veterinario_rol: Optional[str] = None
    veterinario_is_superadmin: bool = False
    fecha_registro: Optional[str] = None
    created_at: Optional[datetime] = None
    estado_suscripcion: str
    trial_ends_at: Optional[datetime] = None
    dias_restantes: int
    plan_activo: str
    total_pacientes: int = 0
    usuarios: List[AdminUsuarioSummary] = []
