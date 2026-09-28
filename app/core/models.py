from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base, Mapped, mapped_column, relationship

from app.core.timezone import get_lima_now

Base = declarative_base()


class SoftDeleteMixin:
    """Mixin para implementar eliminación lógica (soft delete)."""
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def soft_delete(self) -> None:
        """Marca la entidad como eliminada y asigna deleted_at en America/Lima."""
        self.is_deleted = True
        self.deleted_at = get_lima_now()

    def restore(self) -> None:
        """Restaura una entidad previamente eliminada de forma lógica."""
        self.is_deleted = False
        self.deleted_at = None


class TimestampMixin:
    """Mixin para registrar marcas de tiempo estrictas en America/Lima."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_lima_now,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_lima_now,
        onupdate=get_lima_now,
        nullable=False
    )


class Clinica(Base, SoftDeleteMixin, TimestampMixin):
    """Modelo Tenant Principal: Clínica Veterinaria."""
    __tablename__ = "sp_clinicas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    nombre_comercial: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    zona_horaria: Mapped[str] = mapped_column(String(50), default="America/Lima", nullable=False)
    plan_activo: Mapped[str] = mapped_column(String(50), default="solo", nullable=False)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    telefono: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Motor de Suscripciones (SaaS Billing)
    estado_suscripcion: Mapped[str] = mapped_column(String(50), default="TRIAL", nullable=False)
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        default=lambda: get_lima_now() + timedelta(days=14),
        nullable=True
    )

    def __init__(self, **kwargs):
        if "estado_suscripcion" not in kwargs:
            kwargs["estado_suscripcion"] = "TRIAL"
        if "trial_ends_at" not in kwargs:
            kwargs["trial_ends_at"] = get_lima_now() + timedelta(days=14)
        super().__init__(**kwargs)

    @property
    def nombre_mostrado(self) -> str:
        """Retorna el nombre comercial si está definido, de lo contrario la razón social / nombre."""
        return self.nombre_comercial.strip() if (self.nombre_comercial and self.nombre_comercial.strip()) else self.nombre

    @property
    def dias_restantes_trial(self) -> int:
        """Calcula los días restantes del periodo de prueba gratuito de 14 días."""
        if not self.trial_ends_at:
            return 0
        ahora = get_lima_now()
        t_end = self.trial_ends_at
        if t_end.tzinfo is None:
            t_end = t_end.replace(tzinfo=ahora.tzinfo)
        diff = t_end - ahora
        if diff.total_seconds() <= 0:
            return 0
        return max(0, diff.days + (1 if diff.seconds > 0 else 0))

    @property
    def tiene_suscripcion_activa(self) -> bool:
        """Determina si la clínica tiene acceso operativo activo (Plan ACTIVO o TRIAL vigente)."""
        estado = (self.estado_suscripcion or "").upper()
        if estado in ["ACTIVO", "PAGADO"]:
            return True
        if estado == "TRIAL":
            if not self.trial_ends_at:
                return True
            ahora = get_lima_now()
            t_end = self.trial_ends_at
            if t_end.tzinfo is None:
                t_end = t_end.replace(tzinfo=ahora.tzinfo)
            return t_end >= ahora
        return False

    # Relaciones operativas
    veterinarios = relationship("Veterinario", back_populates="clinica", cascade="all, delete-orphan")
    clientes = relationship("Cliente", back_populates="clinica", cascade="all, delete-orphan")
    mascotas = relationship("Mascota", back_populates="clinica", cascade="all, delete-orphan")
    citas = relationship("Cita", back_populates="clinica", cascade="all, delete-orphan")
    horarios = relationship("HorarioAtencion", back_populates="clinica", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Clinica(id={self.id}, nombre='{self.nombre}', estado_suscripcion='{self.estado_suscripcion}', trial_ends_at='{self.trial_ends_at}')>"
