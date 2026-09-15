from datetime import datetime
from typing import Optional, Any, Dict
from pydantic import BaseModel, ConfigDict, Field


class MedicationPlanCreateRequest(BaseModel):
    pet_id: int = Field(..., description="ID de la mascota")
    clinic_id: int = Field(..., description="ID de la clínica veterinaria")
    medicamento: str = Field(..., min_length=2, max_length=150, description="Nombre del medicamento")
    frecuencia_horas: int = Field(..., gt=0, le=72, description="Frecuencia de toma en horas (ej: 8, 12, 24)")
    total_dosis: int = Field(..., gt=0, le=100, description="Cantidad total de dosis programadas")
    es_estricto: bool = Field(False, description="Si es True, no aplica ventana de sueño (se despierta al dueño)")
    hora_inicio: Optional[datetime] = Field(None, description="Hora de la primera dosis (default: ahora)")


class DoseInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    numero_dosis: int
    hora_programada: datetime
    hora_consumo_real: Optional[datetime] = None
    estado: str


class MedicationPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int
    clinic_id: int
    medicamento: str
    frecuencia_horas: int
    total_dosis: int
    es_estricto: bool
    estado: str
    primera_dosis: Optional[DoseInfo] = None
    mensaje: str


class ConfirmDoseRequest(BaseModel):
    hora_real: Optional[datetime] = Field(None, description="Hora real de la toma (opcional, default: ahora)")


class ConfirmDoseResponse(BaseModel):
    dosis_confirmada_id: int
    numero_dosis: int
    hora_consumo_real: datetime
    plan_completado: bool
    siguiente_dosis: Optional[DoseInfo] = None
    mensaje: str


class WebPushSubscriptionRequest(BaseModel):
    cliente_id: int
    endpoint: str
    keys: Dict[str, Any]
