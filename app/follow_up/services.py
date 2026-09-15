from datetime import datetime, timedelta
from typing import Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.timezone import get_lima_now, LIMA_TZ
from app.follow_up.models import MedicationPlan, DoseTracking


def ajustar_ventana_sueno(hora_programada: datetime) -> datetime:
    """
    Ajusta una hora programada si cae dentro de la ventana de sueño (23:00 - 06:59).
    - Si cae a las 23:xx -> se reprograma a las 07:00 AM del día siguiente.
    - Si cae entre las 00:00 y 06:59 -> se reprograma a las 07:00 AM del mismo día.
    """
    # Asegurar zona horaria de Lima
    if hora_programada.tzinfo is None:
        hora_programada = hora_programada.replace(tzinfo=LIMA_TZ)

    hora = hora_programada.hour

    # Caso 1: Cae entre 23:00 y 23:59 -> 07:00 AM del día siguiente
    if hora >= 23:
        dia_siguiente = (hora_programada + timedelta(days=1)).date()
        return datetime(
            year=dia_siguiente.year,
            month=dia_siguiente.month,
            day=dia_siguiente.day,
            hour=7,
            minute=0,
            second=0,
            microsecond=0,
            tzinfo=LIMA_TZ
        )

    # Caso 2: Cae entre 00:00 y 06:59 -> 07:00 AM del mismo día
    if hora < 7:
        return datetime(
            year=hora_programada.year,
            month=hora_programada.month,
            day=hora_programada.day,
            hour=7,
            minute=0,
            second=0,
            microsecond=0,
            tzinfo=LIMA_TZ
        )

    return hora_programada


def crear_plan_medicacion(
    db: Session,
    pet_id: int,
    clinic_id: int,
    medicamento: str,
    frecuencia_horas: int,
    total_dosis: int,
    es_estricto: bool = False,
    hora_inicio: Optional[datetime] = None
) -> Tuple[MedicationPlan, DoseTracking]:
    """
    Crea un plan de medicación e inserta automáticamente la primera dosis pendiente.
    """
    if frecuencia_horas <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La frecuencia en horas debe ser un número entero mayor a 0."
        )

    if total_dosis <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El total de dosis debe ser mayor a 0."
        )

    plan = MedicationPlan(
        pet_id=pet_id,
        clinic_id=clinic_id,
        medicamento=medicamento.strip(),
        frecuencia_horas=frecuencia_horas,
        total_dosis=total_dosis,
        es_estricto=es_estricto,
        estado="ACTIVO"
    )
    db.add(plan)
    db.flush()

    # Programar primera toma
    primera_hora = hora_inicio or get_lima_now()
    if primera_hora.tzinfo is None:
        primera_hora = primera_hora.replace(tzinfo=LIMA_TZ)

    # Si no es estricto, aplicar validación de ventana de sueño a la primera dosis si fuera programada en la noche
    if not es_estricto:
        primera_hora = ajustar_ventana_sueno(primera_hora)

    primera_dosis = DoseTracking(
        plan_id=plan.id,
        numero_dosis=1,
        hora_programada=primera_hora,
        estado="PENDIENTE"
    )
    db.add(primera_dosis)
    db.commit()
    db.refresh(plan)
    db.refresh(primera_dosis)

    return plan, primera_dosis


def confirmar_toma(
    db: Session,
    dose_id: int,
    hora_real: Optional[datetime] = None
) -> Tuple[DoseTracking, Optional[DoseTracking]]:
    """
    Registra el consumo real de una dosis y calcula dinámicamente la siguiente toma.
    Si el plan no es estricto y la siguiente hora cae en la ventana de sueño (23:00 - 06:00),
    se ajusta automáticamente a las 07:00 AM.
    """
    dosis = db.query(DoseTracking).filter(DoseTracking.id == dose_id).first()
    if not dosis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registro de dosis no encontrado."
        )

    if dosis.estado == "CONSUMIDO":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta dosis ya fue confirmada previamente."
        )

    ahora = hora_real or get_lima_now()
    if ahora.tzinfo is None:
        ahora = ahora.replace(tzinfo=LIMA_TZ)

    dosis.estado = "CONSUMIDO"
    dosis.hora_consumo_real = ahora

    plan = dosis.plan
    siguiente_dosis: Optional[DoseTracking] = None

    # Verificar si faltan dosis por tomar
    if dosis.numero_dosis < plan.total_dosis:
        # Calcular siguiente hora a partir del consumo real
        proxima_hora = ahora + timedelta(hours=plan.frecuencia_horas)

        # Regla de Ventana de Sueño si el plan NO es estricto
        if not plan.es_estricto:
            proxima_hora = ajustar_ventana_sueno(proxima_hora)

        siguiente_dosis = DoseTracking(
            plan_id=plan.id,
            numero_dosis=dosis.numero_dosis + 1,
            hora_programada=proxima_hora,
            estado="PENDIENTE"
        )
        db.add(siguiente_dosis)
    else:
        # Última dosis completada
        plan.estado = "COMPLETADO"

    db.commit()
    db.refresh(dosis)
    if siguiente_dosis:
        db.refresh(siguiente_dosis)

    return dosis, siguiente_dosis
