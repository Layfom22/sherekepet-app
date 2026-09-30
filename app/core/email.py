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
