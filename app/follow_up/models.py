from datetime import datetime
from typing import Optional, List
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import Base, TimestampMixin, SoftDeleteMixin


class MedicationPlan(Base, TimestampMixin, SoftDeleteMixin):
    """Plan de medicación recetado a una mascota."""
    __tablename__ = "sp_medication_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    pet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_mascotas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    clinic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_clinicas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    medicamento: Mapped[str] = mapped_column(String(150), nullable=False)
    frecuencia_horas: Mapped[int] = mapped_column(Integer, nullable=False)  # Ej: cada 8 horas
    total_dosis: Mapped[int] = mapped_column(Integer, nullable=False)       # Ej: 15 dosis
    es_estricto: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    estado: Mapped[str] = mapped_column(String(30), default="ACTIVO", nullable=False)  # 'ACTIVO', 'COMPLETADO', 'CANCELADO'

    # Relaciones
    mascota = relationship("Mascota", backref="planes_medicacion")
    clinica = relationship("Clinica", backref="planes_medicacion")
    dosis: Mapped[List["DoseTracking"]] = relationship(
        "DoseTracking",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="DoseTracking.numero_dosis"
    )

    def __repr__(self) -> str:
        return f"<MedicationPlan(id={self.id}, medicamento='{self.medicamento}', pet_id={self.pet_id}, estado='{self.estado}')>"


class DoseTracking(Base, TimestampMixin):
    """Seguimiento individual de cada toma/dosis del tratamiento."""
    __tablename__ = "sp_dose_trackings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    plan_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_medication_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    numero_dosis: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, 3...
    hora_programada: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hora_consumo_real: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    estado: Mapped[str] = mapped_column(String(30), default="PENDIENTE", nullable=False)  # 'PENDIENTE', 'CONSUMIDO'

    # Relaciones
    plan = relationship("MedicationPlan", back_populates="dosis")

    def __repr__(self) -> str:
        return f"<DoseTracking(id={self.id}, plan_id={self.plan_id}, dosis={self.numero_dosis}, estado='{self.estado}')>"


class WebPushSubscription(Base, TimestampMixin):
    """Suscripción Web Push para notificaciones push en PWA."""
    __tablename__ = "sp_web_push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    cliente_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sp_clientes.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    keys_json: Mapped[str] = mapped_column(Text, nullable=False)

    # Relaciones
    cliente = relationship("Cliente", backref="suscripciones_push")

    def __repr__(self) -> str:
        return f"<WebPushSubscription(id={self.id}, cliente_id={self.cliente_id})>"
