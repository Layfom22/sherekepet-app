from datetime import datetime
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
    zona_horaria: Mapped[str] = mapped_column(String(50), default="America/Lima", nullable=False)
    plan_activo: Mapped[str] = mapped_column(String(50), default="solo", nullable=False)
    logo_b64: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relaciones operativas
    veterinarios = relationship("Veterinario", back_populates="clinica", cascade="all, delete-orphan")
    clientes = relationship("Cliente", back_populates="clinica", cascade="all, delete-orphan")
    mascotas = relationship("Mascota", back_populates="clinica", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Clinica(id={self.id}, nombre='{self.nombre}', plan='{self.plan_activo}')>"
