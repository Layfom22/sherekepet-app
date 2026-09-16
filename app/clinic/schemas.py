from datetime import date
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReniecResponse(BaseModel):
    dni: str
    nombres: str
    apellido_paterno: str
    apellido_materno: str
    nombre_completo: str


class RazaItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str


class EspecieConRazas(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    razas: List[RazaItem] = []


class PacienteRapidoRequest(BaseModel):
    clinica_id: int = Field(..., description="ID de la clínica veterinaria")
    dni: str = Field(..., min_length=8, max_length=8, description="DNI de 8 dígitos del cliente")
    nombres: Optional[str] = Field(None, description="Nombres del cliente")
    apellido_paterno: Optional[str] = Field(None, description="Apellido paterno")
    apellido_materno: Optional[str] = Field(None, description="Apellido materno")
    nombre_completo: Optional[str] = Field(None, description="Nombre completo del cliente")
    telefono: Optional[str] = Field(None, description="Teléfono celular para contacto / WhatsApp")
    
    # Datos de la Mascota
    mascota_nombre: str = Field(..., min_length=1, max_length=100, description="Nombre de la mascota")
    especie_id: Optional[int] = Field(None, description="ID del catálogo de especies")
    raza_id: Optional[int] = Field(None, description="ID del catálogo de razas")
    mascota_especie: Optional[str] = Field("Canino", description="Texto de especie (fallback/legacy)")
    mascota_raza: Optional[str] = Field(None, description="Texto de raza (fallback/legacy)")
    mascota_peso: Optional[float] = Field(None, ge=0, description="Peso actual en kg")
    
    # Salud y alergias
    tiene_alergias: bool = Field(False, description="¿Tiene alergias conocidas?")
    detalle_alergias: Optional[str] = Field(None, description="Detalle de las alergias")
    condiciones_previas: Optional[str] = Field(None, description="Condiciones previas o antecedentes clínicos")
    mascota_alergias: Optional[str] = Field(None, description="Campo legado de alergias")

    @field_validator("dni")
    @classmethod
    def validate_dni(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or len(v) != 8:
            raise ValueError("El DNI debe tener exactamente 8 dígitos numéricos.")
        return v


class ClienteSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dni: str
    nombre_completo: Optional[str]
    telefono: Optional[str]
    clinica_id: int


class MascotaSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    especie: str
    raza: Optional[str]
    peso: Optional[float]
    especie_id: Optional[int] = None
    raza_id: Optional[int] = None
    tiene_alergias: bool = False
    detalle_alergias: Optional[str] = None
    condiciones_previas: Optional[str] = None
    alergias: Optional[str] = None
    cliente_id: int
    clinica_id: int


class PacienteRapidoResponse(BaseModel):
    mensaje: str
    cliente: ClienteSummary
    mascota: MascotaSummary


class AtencionCreateRequest(BaseModel):
    clinica_id: int = Field(..., description="ID de la clínica")
    mascota_id: int = Field(..., description="ID de la mascota atendida")
    veterinario_id: Optional[int] = Field(None, description="ID del veterinario a cargo")
    tipo_atencion: str = Field(..., description="'CONSULTA', 'VACUNACION', 'DESPARASITACION', 'GROOMING', 'CIRUGIA'")
    motivo: str = Field(..., max_length=255, description="Motivo de la atención")
    diagnostico: Optional[str] = Field(None, description="Diagnóstico médico")
    tratamiento: Optional[str] = Field(None, description="Tratamiento o indicaciones")
    peso_actual_kg: Optional[float] = Field(None, ge=0, description="Peso registrado durante la atención")

    # Campos requeridos si tipo_atencion == 'VACUNACION'
    tipo_vacuna: Optional[str] = Field(None, description="Ej: Séxtuple, Rabia, Triple Felina, Antipulgas")
    marca_lote: Optional[str] = Field(None, description="Laboratorio, marca y número de lote")
    fecha_aplicacion: Optional[date] = Field(None, description="Fecha de aplicación de la vacuna")
    fecha_proximo_refuerzo: Optional[date] = Field(None, description="Fecha estimada del próximo refuerzo")
    enfermedades_cubiertas: Optional[List[str]] = Field(None, description="Lista de enfermedades cubiertas por esta dosis")

    @field_validator("tipo_atencion")
    @classmethod
    def validate_tipo_atencion(cls, v: str) -> str:
        validos = {"CONSULTA", "VACUNACION", "DESPARASITACION", "GROOMING", "CIRUGIA"}
        v_upper = v.strip().upper()
        if v_upper not in validos:
            raise ValueError(f"tipo_atencion debe ser uno de: {', '.join(validos)}")
        return v_upper


class AtencionResponse(BaseModel):
    id: int
    tipo_atencion: str
    motivo: str
    mascota_id: int
    vacuna_id: Optional[int] = None
    seguimiento_id: Optional[int] = None
    enfermedades_cubiertas: Optional[List[str]] = None
    mensaje: str


class SeguimientoUpdateResponse(BaseModel):
    id: int
    estado: str
    mensaje: str


class LogoUploadResponse(BaseModel):
    mensaje: str
    logo_b64: str
