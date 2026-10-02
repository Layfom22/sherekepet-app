"""
Servicio de correo transaccional (Resend SDK + Fallback SMTP) para SherekePet.
Optimizado con buenas prácticas de entregabilidad (Anti-Spam) para Outlook/Hotmail y Gmail:
- Alineación estricta de dominio (sherekepet.com en remitente, enlaces e imágenes).
- CSS 100% inline sin bloques <style> penalizados por filtros SmartScreen.
- Paridad Multipart (text/plain + text/html).
- Cabeceras X-Entity-Ref-ID y Reply-To explícitas.
"""
import uuid
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_otp_email(destinatario: str, otp_code: str, nombre: Optional[str] = None) -> bool:
    """
    Envía un correo electrónico con el código OTP de verificación.
    Prioriza el SDK oficial de Resend y aplica reglas anti-spam para bandeja principal.
    """
    destinatario = destinatario.strip().lower()
    saludo_nombre = f" {nombre.strip()}" if nombre and nombre.strip() else ""
    remitente = settings.SMTP_FROM or "SherekePet <soporte@sherekepet.com>"
    asunto = f"Verifica tu cuenta en SherekePet (Código: {otp_code})"

    # Versión Texto Plano (Obligatoria para evitar penalización MPART_ALT_DIFF en filtros antispam)
    texto_plano = (
        f"Hola{saludo_nombre},\n\n"
        f"Bienvenido a SherekePet. Para completar la activación de tu clínica veterinaria, "
        f"ingresa el siguiente código de verificación de 6 dígitos:\n\n"
        f"{otp_code}\n\n"
        f"Este código es válido por 15 minutos.\n"
        f"Si no solicitaste crear esta cuenta, puedes ignorar este correo de forma segura.\n\n"
        f"Atentamente,\n"
        f"Equipo de Soporte SherekePet\n"
        f"https://sherekepet.com"
    )

    # Versión HTML con estilos 100% inline y tablas compatibles con Outlook / Gmail
    html_contenido = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Verifica tu cuenta en SherekePet</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f8fafc; padding: 32px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width: 480px; background-color: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; padding: 32px; box-shadow: 0 2px 8px rgba(0,0,0,0.04);">
          <tr>
            <td align="center" style="padding-bottom: 16px;">
              <img src="https://sherekepet.com/static/img/logo_sherekepet.png" alt="SherekePet" width="150" style="max-height: 52px; width: auto; border: 0; display: block;" />
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-bottom: 16px;">
              <span style="display: inline-block; padding: 4px 12px; background-color: #f0fdf9; border: 1px solid #ccfbf1; color: #0f766e; border-radius: 9999px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">
                SaaS Veterinario
              </span>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-bottom: 8px;">
              <h1 style="margin: 0; color: #0f172a; font-size: 20px; font-weight: 800;">Verifica tu Cuenta</h1>
            </td>
          </tr>
          <tr>
            <td style="padding-bottom: 20px; font-size: 14px; color: #475569; line-height: 1.6; text-align: center;">
              Hola<strong>{saludo_nombre}</strong>, ingresa este código de 6 dígitos en la pantalla de verificación para activar tu clínica y comenzar tus 14 días de prueba gratis:
            </td>
          </tr>
          <tr>
            <td style="padding-bottom: 24px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f0fdfa; border: 2px dashed #0d9488; border-radius: 12px;">
                <tr>
                  <td align="center" style="padding: 20px;">
                    <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #0d9488; margin-bottom: 6px; letter-spacing: 0.05em;">
                      Código de Verificación
                    </div>
                    <div style="font-size: 34px; font-weight: 900; letter-spacing: 6px; color: #0f766e; font-family: 'Courier New', Courier, monospace;">
                      {otp_code}
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="font-size: 12px; color: #64748b; line-height: 1.5; text-align: center;">
              Este código es válido por <strong>15 minutos</strong>.<br>
              Si no solicitaste este registro, puedes ignorar este mensaje de forma segura.
            </td>
          </tr>
          <tr>
            <td style="padding-top: 24px; margin-top: 24px; border-top: 1px solid #f1f5f9; font-size: 11px; color: #94a3b8; text-align: center;">
              Enviado por <a href="https://sherekepet.com" style="color: #0d9488; text-decoration: none; font-weight: 600;">SherekePet SaaS</a> &bull; Plataforma de Gestión Veterinaria
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    # 1. Prioridad: Enviar vía SDK oficial de Resend si RESEND_API_KEY está configurado
    if settings.RESEND_API_KEY:
        try:
            import resend
            resend.api_key = settings.RESEND_API_KEY
            headers_antispam = {
                "X-Entity-Ref-ID": str(uuid.uuid4()),
            }
            try:
                res = resend.Emails.send({
                    "from": remitente,
                    "to": [destinatario],
                    "reply_to": "soporte@sherekepet.com",
                    "subject": asunto,
                    "html": html_contenido,
                    "text": texto_plano,
                    "headers": headers_antispam
                })
            except Exception as ex_dom:
                err_str = str(ex_dom).lower()
                if "not verified" in err_str or "validation_error" in err_str or "domain" in err_str:
                    logger.info("Dominio personalizado no verificado en Resend; reintentando con sandbox onboarding@resend.dev")
                    res = resend.Emails.send({
                        "from": "SherekePet <onboarding@resend.dev>",
                        "to": [destinatario],
                        "subject": asunto,
                        "html": html_contenido,
                        "text": texto_plano,
                        "headers": headers_antispam
                    })
                else:
                    raise ex_dom

            print(f"[OK] Correo OTP enviado con éxito vía Resend a {destinatario}: {res}")
            return True
        except Exception as e:
            logger.warning(f"Error enviando correo OTP con Resend: {e}")
            print(f"[WARN] Error enviando correo OTP vía Resend a {destinatario}: {e}")

    # 2. Si no hay Resend y faltan credenciales SMTP, registrar en consola para no bloquear pruebas
    if not (settings.SMTP_USER and settings.SMTP_PASS):
        print(f"[OTP SIMULADO] Código para {destinatario}: {otp_code} (Configure RESEND_API_KEY o credenciales SMTP para envío a bandeja real)")
        return False

    # 3. Fallback: Enviar vía SMTP clásico
    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = remitente if "<" in remitente else f"SherekePet <{remitente}>"
    msg["To"] = destinatario
    msg["Reply-To"] = "soporte@sherekepet.com"
    msg.attach(MIMEText(texto_plano, "plain", "utf-8"))
    msg.attach(MIMEText(html_contenido, "html", "utf-8"))

    try:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
        if settings.SMTP_TLS:
            server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASS)
        server.sendmail(remitente, [destinatario], msg.as_string())
        server.quit()
        print(f"[OK] Correo OTP enviado con éxito a {destinatario}")
        return True
    except Exception as e:
        logger.warning(f"Error al enviar correo OTP por SMTP: {e}")
        print(f"[WARN] Error enviando correo OTP a {destinatario}: {e}")
        print(f"[FALLBACK OTP] Código generado para {destinatario}: {otp_code}")
        return False


def send_appointment_notification_email(
    destinatario: str,
    cliente_nombre: str,
    cliente_telefono: str,
    mascota_nombre: str,
    fecha_str: str,
    hora_str: str,
    motivo: str,
    clinica_nombre: str
) -> bool:
    """Envía un correo de notificación al veterinario cuando un cliente agenda una cita."""
    destinatario = (destinatario or "").strip().lower()
    if not destinatario or "@" not in destinatario:
        return False

    remitente = settings.SMTP_FROM or "SherekePet <soporte@sherekepet.com>"
    asunto = f"Nueva cita solicitada para {mascota_nombre} ({fecha_str} {hora_str})"

    texto_plano = (
        f"Hola,\n\n"
        f"{cliente_nombre} ha solicitado una cita para su mascota {mascota_nombre} en {clinica_nombre}.\n\n"
        f"Detalles de la cita:\n"
        f"- Mascota: {mascota_nombre}\n"
        f"- Fecha: {fecha_str}\n"
        f"- Hora: {hora_str}\n"
        f"- Motivo: {motivo}\n"
        f"- Contacto Dueño: {cliente_telefono or 'No registrado'}\n\n"
        f"Ingresa a tu panel de SherekePet para confirmarla:\n"
        f"https://sherekepet.com/dashboard#seccionCitasPendientes\n"
    )

    html_contenido = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Nueva Cita Solicitada</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f8fafc; padding: 28px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width: 500px; background-color: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; padding: 28px;">
          <tr>
            <td align="center" style="padding-bottom: 16px;">
              <img src="https://sherekepet.com/static/img/logo_sherekepet.png" alt="SherekePet" width="140" style="max-height: 48px; width: auto; border: 0; display: block;" />
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-bottom: 12px;">
              <span style="display: inline-block; padding: 4px 12px; background-color: #fef3c7; border: 1px solid #fde68a; color: #92400e; border-radius: 9999px; font-size: 11px; font-weight: bold; text-transform: uppercase;">
                Nueva Solicitud de Cita
              </span>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-bottom: 8px;">
              <h2 style="margin: 0; color: #0f172a; font-size: 18px;">Cita Agendada por Propietario</h2>
            </td>
          </tr>
          <tr>
            <td style="font-size: 13px; color: #64748b; line-height: 1.5; padding-bottom: 16px; text-align: center;">
              El propietario <strong>{cliente_nombre}</strong> ha programado una cita desde el portal para su mascota <strong>{mascota_nombre}</strong>.
            </td>
          </tr>
          <tr>
            <td style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px;">
              <p style="margin: 4px 0; font-size: 13px;"><strong>Fecha:</strong> {fecha_str}</p>
              <p style="margin: 4px 0; font-size: 13px;"><strong>Hora:</strong> {hora_str}</p>
              <p style="margin: 4px 0; font-size: 13px;"><strong>Motivo:</strong> {motivo}</p>
              <p style="margin: 4px 0; font-size: 13px;"><strong>Teléfono:</strong> {cliente_telefono or 'No registrado'}</p>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-top: 24px;">
              <a href="https://sherekepet.com/dashboard#seccionCitasPendientes" style="display: inline-block; padding: 12px 24px; background-color: #0f766e; color: #ffffff; text-decoration: none; border-radius: 10px; font-weight: bold; font-size: 13px;">
                Ver y Confirmar en el Dashboard
              </a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    if settings.RESEND_API_KEY:
        try:
            import resend
            resend.api_key = settings.RESEND_API_KEY
            res = resend.Emails.send({
                "from": remitente,
                "to": [destinatario],
                "reply_to": "soporte@sherekepet.com",
                "subject": asunto,
                "html": html_contenido,
                "text": texto_plano,
                "headers": {"X-Entity-Ref-ID": str(uuid.uuid4())}
            })
            logger.info(f"[OK] Correo de cita enviado vía Resend a {destinatario}: {res}")
            return True
        except Exception as e:
            logger.warning(f"Error enviando correo de cita con Resend: {e}")

    if not (settings.SMTP_USER and settings.SMTP_PASS):
        print(f"[NOTIFICACIÓN CITA SIMULADA] Para: {destinatario} | Mascota: {mascota_nombre} | Fecha: {fecha_str} {hora_str}")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = remitente if "<" in remitente else f"SherekePet <{remitente}>"
    msg["To"] = destinatario
    msg.attach(MIMEText(texto_plano, "plain", "utf-8"))
    msg.attach(MIMEText(html_contenido, "html", "utf-8"))

    try:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
        if settings.SMTP_TLS:
            server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASS)
        server.sendmail(remitente, [destinatario], msg.as_string())
        server.quit()
        logger.info(f"[OK] Correo de cita enviado a {destinatario}")
        return True
    except Exception as e:
        logger.warning(f"Error enviando correo de cita por SMTP: {e}")
        return False


def send_client_appointment_confirmation_email(
    destinatario: str,
    cliente_nombre: str,
    mascota_nombre: str,
    fecha_str: str,
    hora_str: str,
    motivo: str,
    clinica_nombre: str
) -> bool:
    """Envía un correo de confirmación de cita al dueño de la mascota."""
    destinatario = (destinatario or "").strip().lower()
    if not destinatario or "@" not in destinatario:
        return False

    remitente = settings.SMTP_FROM or f"{clinica_nombre} <soporte@sherekepet.com>"
    asunto = f"Cita confirmada para {mascota_nombre} ({fecha_str} a las {hora_str})"

    texto_plano = (
        f"Hola {cliente_nombre},\n\n"
        f"Tu cita para {mascota_nombre} en {clinica_nombre} ha quedado agendada.\n\n"
        f"Detalles de la cita:\n"
        f"- Mascota: {mascota_nombre}\n"
        f"- Fecha: {fecha_str}\n"
        f"- Hora: {hora_str}\n"
        f"- Motivo: {motivo}\n\n"
        f"Puedes revisar tu carnet y recordatorios en:\n"
        f"https://sherekepet.com/portal/dashboard\n"
    )

    html_contenido = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Confirmación de Cita</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f8fafc; padding: 28px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width: 500px; background-color: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; padding: 28px;">
          <tr>
            <td align="center" style="padding-bottom: 12px;">
              <span style="display: inline-block; padding: 4px 12px; background-color: #ecfdf5; border: 1px solid #a7f3d0; color: #065f46; border-radius: 9999px; font-size: 11px; font-weight: bold; text-transform: uppercase;">
                Cita Agendada
              </span>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-bottom: 8px;">
              <h2 style="margin: 0; color: #0f172a; font-size: 18px;">¡Hola {cliente_nombre}!</h2>
            </td>
          </tr>
          <tr>
            <td style="font-size: 13px; color: #64748b; line-height: 1.5; padding-bottom: 16px; text-align: center;">
              Tu cita para <strong>{mascota_nombre}</strong> en <strong>{clinica_nombre}</strong> está registrada.
            </td>
          </tr>
          <tr>
            <td style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px;">
              <p style="margin: 4px 0; font-size: 13px;"><strong>Mascota:</strong> {mascota_nombre}</p>
              <p style="margin: 4px 0; font-size: 13px;"><strong>Fecha:</strong> {fecha_str}</p>
              <p style="margin: 4px 0; font-size: 13px;"><strong>Hora:</strong> {hora_str}</p>
              <p style="margin: 4px 0; font-size: 13px;"><strong>Motivo:</strong> {motivo}</p>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-top: 20px;">
              <a href="https://sherekepet.com/portal/dashboard" style="display: inline-block; padding: 12px 24px; background-color: #4f46e5; color: #ffffff; text-decoration: none; border-radius: 10px; font-weight: bold; font-size: 13px;">
                Abrir Mi Portal SherekePet
              </a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    if settings.RESEND_API_KEY:
        try:
            import resend
            resend.api_key = settings.RESEND_API_KEY
            resend.Emails.send({
                "from": remitente,
                "to": [destinatario],
                "reply_to": "soporte@sherekepet.com",
                "subject": asunto,
                "html": html_contenido,
                "text": texto_plano,
                "headers": {"X-Entity-Ref-ID": str(uuid.uuid4())}
            })
            return True
        except Exception as e:
            logger.warning(f"Error enviando correo de confirmación a cliente con Resend: {e}")

    return False


def send_medication_reminder_email(
    destinatario: str,
    cliente_nombre: str,
    mascota_nombre: str,
    medicamento: str,
    numero_dosis: int,
    total_dosis: int,
    hora_programada_str: str,
    frecuencia_horas: int,
    mascota_id: int
) -> bool:
    """Envía recordatorio / programación de la siguiente toma de medicamento al correo del dueño."""
    destinatario = (destinatario or "").strip().lower()
    if not destinatario or "@" not in destinatario:
        return False

    remitente = settings.SMTP_FROM or "SherekePet <soporte@sherekepet.com>"
    esquema = "Mañana y Noche (cada 12h)" if frecuencia_horas == 12 else f"Cada {frecuencia_horas} horas"
    asunto = f"💊 Próxima toma de {mascota_nombre}: {medicamento} a las {hora_programada_str}"

    texto_plano = (
        f"Hola {cliente_nombre},\n\n"
        f"Recordatorio de medicación para {mascota_nombre}:\n"
        f"- Medicamento: {medicamento}\n"
        f"- Dosis pendiente: {numero_dosis} de {total_dosis}\n"
        f"- Frecuencia: {esquema}\n"
        f"- Próxima toma programada: {hora_programada_str}\n\n"
        f"Cuando le des su pastilla, confirma la toma en tu carnet digital:\n"
        f"https://sherekepet.com/portal/carnet/{mascota_id}\n"
    )

    html_contenido = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Recordatorio de Medicación</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f8fafc; padding: 28px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width: 500px; background-color: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; padding: 28px;">
          <tr>
            <td align="center" style="padding-bottom: 12px;">
              <span style="display: inline-block; padding: 4px 12px; background-color: #fef3c7; border: 1px solid #fde68a; color: #92400e; border-radius: 9999px; font-size: 11px; font-weight: bold; text-transform: uppercase;">
                💊 Recordatorio de Medicación
              </span>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-bottom: 8px;">
              <h2 style="margin: 0; color: #0f172a; font-size: 18px;">Próxima toma para {mascota_nombre}</h2>
            </td>
          </tr>
          <tr>
            <td style="background-color: #f0fdfa; border: 1px solid #99f6e4; border-radius: 12px; padding: 16px; margin-top: 12px;">
              <p style="margin: 4px 0; font-size: 14px; color: #0f766e;"><strong>Medicamento:</strong> {medicamento}</p>
              <p style="margin: 4px 0; font-size: 13px;"><strong>Dosis:</strong> {numero_dosis} de {total_dosis} ({esquema})</p>
              <p style="margin: 8px 0 4px 0; font-size: 16px; font-weight: 800; color: #0f172a;">⏰ Hora Programada: {hora_programada_str}</p>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-top: 20px;">
              <a href="https://sherekepet.com/portal/carnet/{mascota_id}" style="display: inline-block; padding: 12px 24px; background-color: #059669; color: #ffffff; text-decoration: none; border-radius: 10px; font-weight: bold; font-size: 13px;">
                Confirmar Toma ("Ya se la di")
              </a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    if settings.RESEND_API_KEY:
        try:
            import resend
            resend.api_key = settings.RESEND_API_KEY
            resend.Emails.send({
                "from": remitente,
                "to": [destinatario],
                "reply_to": "soporte@sherekepet.com",
                "subject": asunto,
                "html": html_contenido,
                "text": texto_plano,
                "headers": {"X-Entity-Ref-ID": str(uuid.uuid4())}
            })
            return True
        except Exception as e:
            logger.warning(f"Error enviando recordatorio de medicación con Resend: {e}")

    return False


def send_bath_suggestion_email(
    destinatario: str,
    cliente_nombre: str,
    mascota_nombre: str,
    fecha_sugerida_str: str,
    hora_sugerida_str: str,
    clinica_nombre: str
) -> bool:
    """Envía un correo al dueño sugiriendo la próxima fecha de baño para que confirme o agende su cita."""
    destinatario = (destinatario or "").strip().lower()
    if not destinatario or "@" not in destinatario:
        return False

    remitente = settings.SMTP_FROM or f"{clinica_nombre} <soporte@sherekepet.com>"
    asunto = f"🛁 Próximo baño sugerido para {mascota_nombre} ({fecha_sugerida_str}) - {clinica_nombre}"

    texto_plano = (
        f"Hola {cliente_nombre},\n\n"
        f"¡Gracias por traer hoy a {mascota_nombre} a su baño en {clinica_nombre}!\n"
        f"Para mantener su pelaje y piel saludables, tu veterinario sugiere agendar su próximo baño para:\n\n"
        f"- Mascota: {mascota_nombre}\n"
        f"- Fecha sugerida: {fecha_sugerida_str}\n"
        f"- Hora sugerida: {hora_sugerida_str}\n"
        f"- Veterinaria: {clinica_nombre}\n\n"
        f"Ingresa a tu Portal del Dueño desde tu celular para confirmar o elegir tu hora preferida con un clic:\n"
        f"https://sherekepet.com/portal/dashboard\n"
    )

    html_contenido = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Sugerencia de Próximo Baño</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f8fafc; padding: 28px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width: 500px; background-color: #ffffff; border-radius: 16px; border: 1px solid #99f6e4; padding: 28px;">
          <tr>
            <td align="center" style="padding-bottom: 12px;">
              <span style="display: inline-block; padding: 4px 12px; background-color: #f0fdfa; border: 1px solid #99f6e4; color: #0f766e; border-radius: 9999px; font-size: 11px; font-weight: bold; text-transform: uppercase;">
                ✨ Próximo Baño Sugerido
              </span>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-bottom: 8px;">
              <h2 style="margin: 0; color: #0f172a; font-size: 18px;">¡Hola {cliente_nombre}!</h2>
            </td>
          </tr>
          <tr>
            <td style="font-size: 13px; color: #64748b; line-height: 1.5; padding-bottom: 16px; text-align: center;">
              Para mantener a <strong>{mascota_nombre}</strong> limpio y saludable, <strong>{clinica_nombre}</strong> te sugiere la siguiente fecha para su próximo baño:
            </td>
          </tr>
          <tr>
            <td style="background-color: #f0fdfa; border: 1px solid #99f6e4; border-radius: 12px; padding: 16px;">
              <p style="margin: 4px 0; font-size: 13px; color: #0f172a;"><strong>🐾 Mascota:</strong> {mascota_nombre}</p>
              <p style="margin: 6px 0; font-size: 15px; font-weight: 800; color: #0f766e;">📅 Fecha sugerida: {fecha_sugerida_str}</p>
              <p style="margin: 4px 0; font-size: 13px; color: #0f172a;"><strong>⏰ Hora tentativa:</strong> {hora_sugerida_str} (puedes ajustarla en el portal)</p>
              <p style="margin: 4px 0; font-size: 13px; color: #0f172a;"><strong>🏥 Veterinaria:</strong> {clinica_nombre}</p>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-top: 20px;">
              <a href="https://sherekepet.com/portal/dashboard" style="display: inline-block; padding: 12px 24px; background-color: #0d9488; color: #ffffff; text-decoration: none; border-radius: 10px; font-weight: bold; font-size: 13px;">
                Confirmar o Elegir Hora de Cita
              </a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    if settings.RESEND_API_KEY:
        try:
            import resend
            resend.api_key = settings.RESEND_API_KEY
            try:
                resend.Emails.send({
                    "from": remitente,
                    "to": [destinatario],
                    "reply_to": "soporte@sherekepet.com",
                    "subject": asunto,
                    "html": html_contenido,
                    "text": texto_plano,
                    "headers": {"X-Entity-Ref-ID": str(uuid.uuid4())}
                })
                return True
            except Exception:
                resend.Emails.send({
                    "from": f"{clinica_nombre} <onboarding@resend.dev>",
                    "to": [destinatario],
                    "subject": asunto,
                    "html": html_contenido,
                    "text": texto_plano
                })
                return True
        except Exception as e:
            logger.warning(f"Error enviando correo de sugerencia de baño con Resend: {e}")

    if not (settings.SMTP_USER and settings.SMTP_PASS):
        print(f"[SUGERENCIA BAÑO EMAIL SIMULADO] Para: {destinatario} | Mascota: {mascota_nombre} | Fecha: {fecha_sugerida_str}")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = remitente if "<" in remitente else f"SherekePet <{remitente}>"
    msg["To"] = destinatario
    msg.attach(MIMEText(texto_plano, "plain", "utf-8"))
    msg.attach(MIMEText(html_contenido, "html", "utf-8"))

    try:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
        if settings.SMTP_TLS:
            server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASS)
        server.sendmail(remitente, [destinatario], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        logger.warning(f"Error enviando correo de sugerencia de baño por SMTP: {e}")
        return False


def send_payment_report_notification_email(
    clinica_nombre: str,
    clinica_id: int,
    veterinario_email: str,
    metodo_pago: str,
    referencia_operacion: str,
    monto: str = "49.00",
    comprobante_url: str = ""
) -> bool:
    """Envía una alerta al SuperAdmin cuando una clínica reporta un pago por Yape/Plin para revisión."""
    destinatario = (settings.SOPORTE_EMAIL or "roggerjjj@gmail.com").strip().lower()
    remitente = settings.SMTP_FROM or "SherekePet Billing <soporte@sherekepet.com>"
    asunto = f"💳 Nuevo Pago Reportado ({metodo_pago}): {clinica_nombre} - S/ {monto}"

    texto_plano = (
        f"Nuevo comprobante de pago recibido en SherekePet:\n\n"
        f"- Clínica: {clinica_nombre} (ID #{clinica_id})\n"
        f"- Contacto: {veterinario_email}\n"
        f"- Método: {metodo_pago}\n"
        f"- Monto: S/ {monto}\n"
        f"- N° Operación / Referencia: {referencia_operacion}\n"
        f"- Comprobante: {comprobante_url or 'Sin adjunto'}\n\n"
        f"Ingresa al Panel SuperAdmin (/admin) para aprobar y activar los +30 días.\n"
    )

    html_contenido = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>Nuevo Pago Reportado</title></head>
<body style="margin:0;padding:24px;background-color:#f8fafc;font-family:sans-serif;color:#0f172a;">
  <div style="max-width:520px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;padding:24px;">
    <span style="display:inline-block;padding:4px 12px;background:#eef2ff;color:#4338ca;border-radius:999px;font-size:11px;font-weight:bold;">
      REVISIÓN DE PAGO SAAS
    </span>
    <h2 style="margin:12px 0 8px 0;font-size:18px;">Nuevo pago reportado por {clinica_nombre}</h2>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:16px;font-size:13px;line-height:1.6;">
      <p style="margin:4px 0;"><strong>Clínica:</strong> {clinica_nombre} (#{clinica_id})</p>
      <p style="margin:4px 0;"><strong>Email Titular:</strong> {veterinario_email}</p>
      <p style="margin:4px 0;"><strong>Método:</strong> {metodo_pago}</p>
      <p style="margin:4px 0;"><strong>Monto:</strong> S/ {monto} PEN</p>
      <p style="margin:4px 0;"><strong>N° de Operación:</strong> <code style="background:#e2e8f0;padding:2px 6px;border-radius:4px;">{referencia_operacion}</code></p>
    </div>
    <div style="text-align:center;margin-top:20px;">
      <a href="https://sherekepet.com/admin" style="display:inline-block;padding:12px 24px;background:#4f46e5;color:#ffffff;text-decoration:none;border-radius:10px;font-weight:bold;font-size:13px;">
        Revisar y Aprobar en Panel SuperAdmin
      </a>
    </div>
  </div>
</body>
</html>"""

    if settings.RESEND_API_KEY:
        try:
            import resend
            resend.api_key = settings.RESEND_API_KEY
            resend.Emails.send({
                "from": remitente,
                "to": [destinatario],
                "subject": asunto,
                "html": html_contenido,
                "text": texto_plano
            })
            return True
        except Exception as e:
            logger.warning(f"Error enviando alerta de pago al SuperAdmin vía Resend: {e}")

    return False


def send_payment_approved_email(
    destinatario: str,
    clinica_nombre: str,
    fecha_vencimiento_str: str,
    monto: str = "49.00"
) -> bool:
    """Notifica al veterinario titular que su suscripción Plan Emprendedor fue activada/renovada por 30 días."""
    destinatario = (destinatario or "").strip().lower()
    if not destinatario or "@" not in destinatario:
        return False

    remitente = settings.SMTP_FROM or "SherekePet <soporte@sherekepet.com>"
    asunto = f"✅ Suscripción Activa: Plan Emprendedor ({clinica_nombre})"

    texto_plano = (
        f"¡Hola!\n\n"
        f"Confirmamos la activación del Plan Emprendedor (S/ {monto} / mes) para {clinica_nombre}.\n"
        f"Tu licencia operativa está activa hasta el {fecha_vencimiento_str}.\n\n"
        f"Ingresa a tu panel en: https://sherekepet.com/dashboard\n"
    )

    html_contenido = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>Suscripción Activa</title></head>
<body style="margin:0;padding:24px;background-color:#f8fafc;font-family:sans-serif;color:#0f172a;">
  <div style="max-width:500px;margin:0 auto;background:#ffffff;border:1px solid #a7f3d0;border-radius:16px;padding:24px;">
    <span style="display:inline-block;padding:4px 12px;background:#ecfdf5;color:#065f46;border-radius:999px;font-size:11px;font-weight:bold;">
      PLAN EMPRENDEDOR ACTIVO
    </span>
    <h2 style="margin:12px 0 8px 0;font-size:18px;">¡Gracias por confiar en SherekePet!</h2>
    <p style="font-size:13px;color:#475569;line-height:1.5;">
      El pago de <strong>S/ {monto} PEN</strong> para <strong>{clinica_nombre}</strong> ha sido procesado con éxito.
      Tu clínica cuenta con acceso total ilimitado hasta el <strong>{fecha_vencimiento_str}</strong>.
    </p>
  </div>
</body>
</html>"""

    if settings.RESEND_API_KEY:
        try:
            import resend
            resend.api_key = settings.RESEND_API_KEY
            resend.Emails.send({
                "from": remitente,
                "to": [destinatario],
                "subject": asunto,
                "html": html_contenido,
                "text": texto_plano
            })
            return True
        except Exception as e:
            logger.warning(f"Error enviando confirmación de pago con Resend: {e}")

    return False



