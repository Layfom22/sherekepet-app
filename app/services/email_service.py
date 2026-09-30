import logging
from typing import Optional
import resend
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.database import SessionLocal
from app.clinic.models import Cita, Mascota
from app.core.models import Clinica

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="app/templates")


async def enviar_alerta_paciente(cita_id: int, destinatario_email: str) -> Optional[dict]:
    """
    Función asíncrona para consultar la Cita, Mascota y Clínica correspondiente,
    y enviar un correo transaccional de recordatorio con soporte de Marca Blanca (White-labeling)
    usando el SDK oficial de resend.
    """
    if not destinatario_email:
        logger.warning(f"[EMAIL] No se proporcionó destinatario_email para cita_id={cita_id}")
        return None

    db = SessionLocal()
    try:
        # 1. Consultar Cita, Mascota y Clínica correspondiente
        cita = db.query(Cita).filter(Cita.id == cita_id).first()
        if not cita:
            logger.warning(f"[EMAIL] Cita con ID {cita_id} no encontrada en base de datos.")
            return None

        mascota = cita.mascota or db.query(Mascota).filter(Mascota.id == cita.mascota_id).first()
        clinica = cita.clinica or db.query(Clinica).filter(Clinica.id == cita.clinica_id).first()

        if not clinica or not mascota:
            logger.warning(f"[EMAIL] Datos incompletos (clínica o mascota) para la cita ID {cita_id}.")
            return None

        # 2. Configurar remitente dinámico (Marca Blanca / White-labeling)
        nombre_emisor = clinica.nombre_comercial if clinica.nombre_comercial else clinica.nombre
        from_email = f"{nombre_emisor} <soporte@sherekepet.com>"

        # 3. Asunto personalizado
        subject = f"Recordatorio de Cita Médica para {mascota.nombre} - {nombre_emisor}"

        # 4. Renderizar plantilla HTML con Jinja2
        template = templates.get_template("emails/recordatorio.html")
        html_content = template.render(
            cita=cita,
            mascota=mascota,
            clinica=clinica
        )

        # 5. Asegurar inicialización de API Key en el SDK oficial de Resend
        if settings.RESEND_API_KEY:
            resend.api_key = settings.RESEND_API_KEY

        import uuid
        hora_txt = cita.hora.strftime('%H:%M') if cita.hora and hasattr(cita.hora, 'strftime') else str(cita.hora)
        texto_plano = (
            f"Recordatorio de Cita Médica Confirmada - {nombre_emisor}\n\n"
            f"Paciente: {mascota.nombre}\n"
            f"Fecha: {cita.fecha}\n"
            f"Hora: {hora_txt}\n"
            f"Motivo: {cita.motivo}\n\n"
            f"Recomendación: Llegar con 10 minutos de anticipación.\n\n"
            f"Este recordatorio médico fue enviado a través de SherekePet, "
            f"la plataforma tecnológica de {nombre_emisor}. Por favor, no respondas a este correo."
        )

        # 6. Construir y enviar el payload con resend.Emails.send()
        payload = {
            "from": from_email,
            "to": [destinatario_email],
            "reply_to": "soporte@sherekepet.com",
            "subject": subject,
            "html": html_content,
            "text": texto_plano,
            "headers": {"X-Entity-Ref-ID": str(uuid.uuid4())}
        }

        try:
            response = resend.Emails.send(payload)
        except Exception as ex_dom:
            err_str = str(ex_dom).lower()
            if "not verified" in err_str or "validation_error" in err_str or "domain" in err_str:
                logger.info("Dominio no verificado en Resend; reintentando con sandbox onboarding@resend.dev")
                payload["from"] = f"{nombre_emisor} <onboarding@resend.dev>"
                response = resend.Emails.send(payload)
            else:
                raise ex_dom

        logger.info(f"[EMAIL] Correo de alerta enviado exitosamente a {destinatario_email} para cita {cita_id}: {response}")
        return response

    except Exception as e:
        logger.error(f"[EMAIL] Error al enviar correo de alerta con Resend para cita {cita_id}: {e}")
        return None
    finally:
        db.close()
