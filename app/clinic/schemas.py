from datetime import date
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    tipo_documento: Optional[str] = Field("DNI", description="Tipo de documento (DNI, CE, PASAPORTE, OTRO)")
    dni: str = Field(..., min_length=3, max_length=20, description="DNI o Documento de Identidad del cliente (DNI, CE, Pasaporte)")
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
    fecha_nacimiento: Optional[date] = Field(None, description="Fecha de nacimiento estimada o exacta de la mascota")
    
    # Salud y alergias
    tiene_alergias: bool = Field(False, description="¿Tiene alergias conocidas?")
    detalle_alergias: Optional[str] = Field(None, description="Detalle de las alergias")
    condiciones_previas: Optional[str] = Field(None, description="Condiciones previas o antecedentes clínicos")
    mascota_alergias: Optional[str] = Field(None, description="Campo legado de alergias")
    foto_url: Optional[str] = Field(None, description="URL de la foto de la mascota en Cloudflare R2")

    @field_validator("dni")
    @classmethod
    def validate_dni(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3 or len(v) > 20:
            raise ValueError("El número de documento debe tener entre 3 y 20 caracteres.")
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
    fecha_nacimiento: Optional[date] = None
    foto_url: Optional[str] = None
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

    # Prescripción Médica / Receta (Validación Estricta)
    receta_medicamento: Optional[str] = Field(None, description="Nombre del medicamento/pastilla")
    receta_frecuencia: Optional[str] = Field(None, description="Frecuencia (ej: Cada 8 horas)")
    receta_dosis: Optional[str] = Field(None, description="Cantidad/Dosis (ej: 1 tableta / 15 dosis)")
    receta_frecuencia_horas: Optional[int] = Field(None, ge=1, le=72, description="Frecuencia en horas para plan automatizado")
    receta_total_dosis: Optional[int] = Field(None, ge=1, le=100, description="Total de dosis programadas")

    # Mini-ERP: Selección de Tipo de Baño para descuento de stock
    servicio_bano_id: Optional[int] = Field(None, description="ID del servicio de baño para descontar insumo")

    @field_validator("tipo_atencion")
    @classmethod
    def validate_tipo_atencion(cls, v: str) -> str:
        validos = {"CONSULTA", "VACUNACION", "DESPARASITACION", "GROOMING", "CIRUGIA"}
        v_upper = v.strip().upper()
        if v_upper not in validos:
            raise ValueError(f"tipo_atencion debe ser uno de: {', '.join(validos)}")
        return v_upper

    @model_validator(mode="after")
    def validate_receta_estricta(self):
        med = (self.receta_medicamento or "").strip()
        frec = (self.receta_frecuencia or "").strip()
        dosis = (self.receta_dosis or "").strip()
        if med:
            if not frec:
                raise ValueError("El campo 'Frecuencia' (ej. Cada 8 horas) es estrictamente obligatorio al recetar un medicamento.")
            if not dosis:
                raise ValueError("El campo 'Cantidad / Dosis' es estrictamente obligatorio al recetar un medicamento.")
        return self


class AtencionResponse(BaseModel):
    id: int
    tipo_atencion: str
    motivo: str
    mascota_id: int
    vacuna_id: Optional[int] = None
    seguimiento_id: Optional[int] = None
    enfermedades_cubiertas: Optional[List[str]] = None
    plan_medicacion_id: Optional[int] = None
    stock_descontado: Optional[float] = None
    insumo_nombre: Optional[str] = None
    stock_restante: Optional[float] = None
    mensaje: str


class SeguimientoUpdateResponse(BaseModel):
    id: int
    estado: str
    mensaje: str


class LogoUploadResponse(BaseModel):
    mensaje: str
    logo_url: str
    logo_b64: Optional[str] = None


class MascotaFotoResponse(BaseModel):
    mensaje: str
    mascota_id: int
    foto_url: str


# ==========================================
# HORARIOS DE ATENCIÓN DE LA CLÍNICA
# ==========================================

class DiaHorarioItem(BaseModel):
    dia_semana: int = Field(..., ge=0, le=6, description="0=Lunes, 1=Martes, ..., 6=Domingo")
    dia_nombre: Optional[str] = None
    activo: bool = True
    hora_inicio_1: str = Field("09:00", description="Hora de inicio del turno 1 (HH:MM)")
    hora_fin_1: str = Field("13:00", description="Hora de fin del turno 1 (HH:MM)")
    hora_inicio_2: Optional[str] = Field(None, description="Hora de inicio del turno 2 (HH:MM)")
    hora_fin_2: Optional[str] = Field(None, description="Hora de fin del turno 2 (HH:MM)")
    intervalo_minutos: int = Field(30, ge=10, le=120, description="Duración de cada cita en minutos")


class HorariosConfigRequest(BaseModel):
    intervalo_minutos: int = Field(30, ge=10, le=120)
    dias: List[DiaHorarioItem]


class HorariosConfigResponse(BaseModel):
    mensaje: str
    intervalo_minutos: int
    dias: List[DiaHorarioItem]


# ==========================================
# MINI-ERP: CATÁLOGO DE BAÑOS E INVENTARIO
# ==========================================

class ProductoItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    clinica_id: int
    nombre: str
    stock_actual: float
    unidad_medida: str
    stock_minimo: float


class ServicioBanoItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    clinica_id: int
    nombre: str
    precio: float
    producto_id: Optional[int] = None
    cantidad_consumo: float
    activo: bool
    producto_nombre: Optional[str] = None
    stock_actual: Optional[float] = None
    unidad_medida: Optional[str] = None


class ServicioBanoCreateRequest(BaseModel):
    clinica_id: Optional[int] = None
    nombre: str = Field(..., min_length=2, max_length=100)
    precio: float = Field(..., ge=0)
    producto_id: Optional[int] = None
    cantidad_consumo: float = Field(default=50.0, ge=0)
    activo: bool = True


class ProductoStockUpdateRequest(BaseModel):
    stock_actual: float = Field(..., ge=0)
    stock_minimo: Optional[float] = Field(default=None, ge=0)
    unidad_medida: Optional[str] = None
