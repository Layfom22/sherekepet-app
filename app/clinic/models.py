from datetime import date, datetime
from typing import Optional, List
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import Base, SoftDeleteMixin, TimestampMixin


class Especie(Base, TimestampMixin):
    """Catálogo de Especies animales (Canino, Felino, etc.)."""
    __tablename__ = "sp_especies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    nombre: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    # Relaciones
    razas: Mapped[List["Raza"]] = relationship("Raza", back_populates="especie", cascade="all, delete-orphan")
    mascotas: Mapped[List["Mascota"]] = relationship("Mascota", back_populates="especie_rel")

    def __repr__(self) -> str:
        return f"<Especie(id={self.id}, nombre='{self.nombre}')>"


class Raza(Base, TimestampMixin):
    """Catálogo de Razas dependientes de una Especie."""
    __tablename__ = "sp_razas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    especie_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_especies.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    nombre: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Relaciones
    especie = relationship("Especie", back_populates="razas")
    mascotas: Mapped[List["Mascota"]] = relationship("Mascota", back_populates="raza_rel")

    def __repr__(self) -> str:
        return f"<Raza(id={self.id}, nombre='{self.nombre}', especie_id={self.especie_id})>"


class Veterinario(Base, SoftDeleteMixin, TimestampMixin):
    """Modelo de Autenticación y Perfil de Veterinario."""
    __tablename__ = "sp_veterinarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    clinica_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_clinicas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    nombre: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    google_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    rol: Mapped[str] = mapped_column(String(50), default="ADMIN", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    otp_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    otp_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relaciones
    clinica = relationship("Clinica", back_populates="veterinarios")
    atenciones = relationship("AtencionClinica", back_populates="veterinario")

    def __repr__(self) -> str:
        return f"<Veterinario(id={self.id}, email='{self.email}', clinica_id={self.clinica_id})>"


class Cliente(Base, SoftDeleteMixin, TimestampMixin):
    """Modelo de Autenticación y Perfil para Dueños de Mascotas."""
    __tablename__ = "sp_clientes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    clinica_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_clinicas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    dni: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    pin_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    telefono: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    nombres: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    apellido_paterno: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    apellido_materno: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    nombre_completo: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relaciones
    clinica = relationship("Clinica", back_populates="clientes")
    mascotas: Mapped[List["Mascota"]] = relationship(
        "Mascota",
        back_populates="cliente",
        cascade="all, delete-orphan"
    )
    seguimientos = relationship(
        "SeguimientoNotificacion",
        back_populates="cliente",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Cliente(id={self.id}, dni='{self.dni}', nombre='{self.nombre_completo}', clinica_id={self.clinica_id})>"


class Mascota(Base, SoftDeleteMixin, TimestampMixin):
    """Modelo Operativo de Mascota / Paciente con catálogos y ficha de salud extendida."""
    __tablename__ = "sp_mascotas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    clinica_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_clinicas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    cliente_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_clientes.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    especie_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("sp_especies.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    raza_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("sp_razas.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    especie: Mapped[str] = mapped_column(String(50), default="Canino", nullable=False)
    raza: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    peso: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Salud y alergias
    alergias: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tiene_alergias: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    detalle_alergias: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    condiciones_previas: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Multimedia / Cloudflare R2
    foto_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Perfil / DNI de Mascota (Datos no clínicos editables por el dueño)
    fecha_nacimiento: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sexo: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 'Macho', 'Hembra'
    rasgos_distintivos: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    microchip: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relaciones
    clinica = relationship("Clinica", back_populates="mascotas")
    cliente = relationship("Cliente", back_populates="mascotas")
    especie_rel = relationship("Especie", back_populates="mascotas")
    raza_rel = relationship("Raza", back_populates="mascotas")
    atenciones: Mapped[List["AtencionClinica"]] = relationship(
        "AtencionClinica",
        back_populates="mascota",
        cascade="all, delete-orphan"
    )
    vacunas: Mapped[List["RegistroVacuna"]] = relationship(
        "RegistroVacuna",
        back_populates="mascota",
        cascade="all, delete-orphan"
    )
    seguimientos: Mapped[List["SeguimientoNotificacion"]] = relationship(
        "SeguimientoNotificacion",
        back_populates="mascota",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Mascota(id={self.id}, nombre='{self.nombre}', especie='{self.especie}', clinica_id={self.clinica_id})>"


class AtencionClinica(Base, SoftDeleteMixin, TimestampMixin):
    """Modelo de Atención Clínica Veterinaria."""
    __tablename__ = "sp_atenciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    clinica_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_clinicas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    mascota_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_mascotas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    veterinario_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("sp_veterinarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    tipo_atencion: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )  # 'CONSULTA', 'VACUNACION', 'DESPARASITACION', 'GROOMING', 'CIRUGIA'
    motivo: Mapped[str] = mapped_column(String(255), nullable=False)
    diagnostico: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tratamiento: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    peso_actual_kg: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)

    # Relaciones
    mascota = relationship("Mascota", back_populates="atenciones")
    veterinario = relationship("Veterinario", back_populates="atenciones")
    vacunas = relationship("RegistroVacuna", back_populates="atencion")

    def __repr__(self) -> str:
        return f"<AtencionClinica(id={self.id}, tipo='{self.tipo_atencion}', mascota_id={self.mascota_id})>"


class RegistroVacuna(Base, SoftDeleteMixin, TimestampMixin):
    """Modelo de Registro de Vacunas con enfermedades cubiertas."""
    __tablename__ = "sp_vacunas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    clinica_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_clinicas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    mascota_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_mascotas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    atencion_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("sp_atenciones.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    tipo_vacuna: Mapped[str] = mapped_column(String(100), nullable=False)
    marca_lote: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    fecha_aplicacion: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_proximo_refuerzo: Mapped[date] = mapped_column(Date, nullable=False)
    estado: Mapped[str] = mapped_column(String(30), default="VIGENTE", nullable=False)  # 'VIGENTE', 'POR_VENCER', 'VENCIDO'
    
    # Digitalización inteligente: lista JSON de enfermedades cubiertas
    enfermedades_cubiertas: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relaciones
    mascota = relationship("Mascota", back_populates="vacunas")
    atencion = relationship("AtencionClinica", back_populates="vacunas")

    @property
    def lista_enfermedades(self) -> list:
        if not self.enfermedades_cubiertas:
            return []
        try:
            import json
            data = json.loads(self.enfermedades_cubiertas)
            if isinstance(data, list):
                return data
            return [str(data)]
        except Exception:
            return [self.enfermedades_cubiertas]

    def __repr__(self) -> str:
        return f"<RegistroVacuna(id={self.id}, tipo='{self.tipo_vacuna}', refuerzo={self.fecha_proximo_refuerzo})>"


class SeguimientoNotificacion(Base, SoftDeleteMixin, TimestampMixin):
    """Modelo para Notificaciones y Recordatorios a Clientes."""
    __tablename__ = "sp_seguimientos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    clinica_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_clinicas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    cliente_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_clientes.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    mascota_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_mascotas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    tipo: Mapped[str] = mapped_column(String(50), nullable=False)  # 'REFUERZO_VACUNA', 'CONTROL_MEDICO', 'BAÑO'
    fecha_programada: Mapped[date] = mapped_column(Date, nullable=False)
    mensaje_plantilla: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(String(30), default="PENDIENTE", nullable=False)  # 'PENDIENTE', 'ENVIADO', 'CONFIRMADO'

    # Relaciones
    cliente = relationship("Cliente", back_populates="seguimientos")
    mascota = relationship("Mascota", back_populates="seguimientos")

    def __repr__(self) -> str:
        return f"<SeguimientoNotificacion(id={self.id}, tipo='{self.tipo}', estado='{self.estado}')>"
