from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
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
    subscription_ends_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
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
    def dias_restantes_suscripcion(self) -> int:
        """Calcula los días restantes del ciclo mensual pagado (o del trial si está en prueba)."""
        estado = (self.estado_suscripcion or "").upper()
        if estado in ["ACTIVO", "ACTIVE", "PAGADO"]:
            if not self.subscription_ends_at:
                return 30
            ahora = get_lima_now()
            s_end = self.subscription_ends_at
            if s_end.tzinfo is None:
                s_end = s_end.replace(tzinfo=ahora.tzinfo)
            diff = s_end - ahora
            if diff.total_seconds() <= 0:
                return 0
            return max(0, diff.days + (1 if diff.seconds > 0 else 0))
        return self.dias_restantes_trial

    @property
    def en_periodo_gracia(self) -> bool:
        """
        Determina si una clínica con plan ACTIVO venció su mes hace menos de 3 días (Periodo de Gracia).
        Durante estos 3 días sigue pudiendo operar pero recibe una alerta amarilla para renovar.
        """
        estado = (self.estado_suscripcion or "").upper()
        if estado not in ["ACTIVO", "ACTIVE", "PAGADO"] or not self.subscription_ends_at:
            return False
        ahora = get_lima_now()
        s_end = self.subscription_ends_at
        if s_end.tzinfo is None:
            s_end = s_end.replace(tzinfo=ahora.tzinfo)
        if ahora <= s_end:
            return False
        return (ahora - s_end) <= timedelta(days=3)

    @property
    def dias_gracia_restantes(self) -> int:
        """Retorna cuántos días de gracia le quedan (entre 1 y 3) antes del bloqueo por vencimiento."""
        if not self.en_periodo_gracia or not self.subscription_ends_at:
            return 0
        ahora = get_lima_now()
        s_end = self.subscription_ends_at
        if s_end.tzinfo is None:
            s_end = s_end.replace(tzinfo=ahora.tzinfo)
        fin_gracia = s_end + timedelta(days=3)
        diff = fin_gracia - ahora
        if diff.total_seconds() <= 0:
            return 0
        return max(1, diff.days + (1 if diff.seconds > 0 else 0))

    @property
    def tiene_suscripcion_activa(self) -> bool:
        """
        Determina si la clínica tiene acceso operativo activo:
        - Plan ACTIVO vigente (o dentro de los 3 días de gracia post-vencimiento).
        - Periodo TRIAL vigente dentro de los 14 días.
        """
        estado = (self.estado_suscripcion or "").upper()
        if estado in ["ACTIVO", "ACTIVE", "PAGADO"]:
            if not self.subscription_ends_at:
                return True
            ahora = get_lima_now()
            s_end = self.subscription_ends_at
            if s_end.tzinfo is None:
                s_end = s_end.replace(tzinfo=ahora.tzinfo)
            # Incluye 3 días de periodo de gracia para renovaciones mensuales
            return (s_end + timedelta(days=3)) >= ahora
        if estado == "TRIAL":
            if not self.trial_ends_at:
                return True
            ahora = get_lima_now()
            t_end = self.trial_ends_at
            if t_end.tzinfo is None:
                t_end = t_end.replace(tzinfo=ahora.tzinfo)
            return t_end >= ahora
        return False

    @property
    def modo_solo_lectura(self) -> bool:
        """Indica si la clínica se encuentra en Modo Solo Lectura por licencia expirada."""
        return not self.tiene_suscripcion_activa

    @property
    def estado_suscripcion_normalizado(self) -> str:
        """Retorna el estado normalizado para el Panel SuperAdmin: ACTIVE, TRIAL o EXPIRED."""
        estado = (self.estado_suscripcion or "TRIAL").upper()
        if estado in ["EXPIRED", "EXPIRADO", "VENCIDO", "CANCELADO"]:
            return "EXPIRED"
        if estado in ["ACTIVO", "ACTIVE", "PAGADO"]:
            if not self.tiene_suscripcion_activa:
                return "EXPIRED"
            return "ACTIVE"
        # Si está en TRIAL, verificar si ya venció su trial_ends_at
        if not self.tiene_suscripcion_activa:
            return "EXPIRED"
        return "TRIAL"

    # Relaciones operativas
    veterinarios = relationship("Veterinario", back_populates="clinica", cascade="all, delete-orphan")
    clientes = relationship("Cliente", back_populates="clinica", cascade="all, delete-orphan")
    mascotas = relationship("Mascota", back_populates="clinica", cascade="all, delete-orphan")
    citas = relationship("Cita", back_populates="clinica", cascade="all, delete-orphan")
    horarios = relationship("HorarioAtencion", back_populates="clinica", cascade="all, delete-orphan")
    pagos = relationship("PagoSuscripcion", back_populates="clinica", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Clinica(id={self.id}, nombre='{self.nombre}', estado_suscripcion='{self.estado_suscripcion}', trial_ends_at='{self.trial_ends_at}')>"


class PagoSuscripcion(Base, TimestampMixin):
    """Historial de pagos y reportes de comprobantes de suscripción SaaS (S/ 49.00 / mes)."""
    __tablename__ = "sp_pagos_suscripcion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    clinica_id: Mapped[int] = mapped_column(Integer, ForeignKey("sp_clinicas.id"), nullable=False, index=True)
    monto: Mapped[str] = mapped_column(String(20), default="49.00", nullable=False)
    moneda: Mapped[str] = mapped_column(String(10), default="PEN", nullable=False)
    metodo_pago: Mapped[str] = mapped_column(String(50), default="YAPE_PLIN", nullable=False)  # MERCADOPAGO, YAPE_PLIN, ACTIVACION_DIRECTA
    referencia_operacion: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    comprobante_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    estado: Mapped[str] = mapped_column(String(50), default="PENDIENTE_REVISION", nullable=False, index=True)  # APROBADO, PENDIENTE_REVISION, RECHAZADO
    notas: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    periodo_inicio: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    periodo_fin: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    clinica = relationship("Clinica", back_populates="pagos")

