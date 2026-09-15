from typing import Optional, List
from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import Base, SoftDeleteMixin, TimestampMixin


class Veterinario(Base, SoftDeleteMixin, TimestampMixin):
    """Modelo de Autenticación y Perfil de Veterinario."""
    __tablename__ = "veterinarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    clinica_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clinicas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    google_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    rol: Mapped[str] = mapped_column(String(50), default="veterinario", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relaciones
    clinica = relationship("Clinica", back_populates="veterinarios")

    def __repr__(self) -> str:
        return f"<Veterinario(id={self.id}, email='{self.email}', clinica_id={self.clinica_id})>"


class Cliente(Base, SoftDeleteMixin, TimestampMixin):
    """Modelo de Autenticación y Perfil para Dueños de Mascotas."""
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    clinica_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clinicas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    dni: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    pin_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    telefono: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # Relaciones
    clinica = relationship("Clinica", back_populates="clientes")
    mascotas: Mapped[List["Mascota"]] = relationship(
        "Mascota",
        back_populates="cliente",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Cliente(id={self.id}, dni='{self.dni}', clinica_id={self.clinica_id})>"


class Mascota(Base, SoftDeleteMixin, TimestampMixin):
    """Modelo Operativo de Mascota / Paciente."""
    __tablename__ = "mascotas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    clinica_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clinicas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    cliente_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clientes.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    especie: Mapped[str] = mapped_column(String(50), nullable=False)
    raza: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    peso: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Relaciones
    clinica = relationship("Clinica", back_populates="mascotas")
    cliente = relationship("Cliente", back_populates="mascotas")

    def __repr__(self) -> str:
        return f"<Mascota(id={self.id}, nombre='{self.nombre}', especie='{self.especie}', clinica_id={self.clinica_id})>"
