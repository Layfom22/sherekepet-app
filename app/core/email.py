"""
Servicio de correo SMTP para SherekePet.
Maneja el envío de códigos de verificación OTP para registro y seguridad de cuentas.
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_otp_email(destinatario: str, otp_code: str, nombre: Optional[str] = None) -> bool:
    """
    Envía un correo electrónico con el código OTP de verificación usando SMTP.
    Compatible con Office 365 / Hotmail / Gmail y cualquier servidor SMTP TLS.
    
    Retorna True si el envío fue exitoso, o False si falló o SMTP no está configurado.
    """
    destinatario = destinatario.strip().lower()
    saludo_nombre = f" {nombre.strip()}" if nombre and nombre.strip() else ""

    # Si no hay credenciales SMTP configuradas, registrar advertencia en logs
    if not (settings.SMTP_USER and settings.SMTP_PASS):
        print(f"[OTP SIMULADO] Código para {destinatario}: {otp_code} (Configure SMTP_USER y SMTP_PASS para envío real)")
        return False

    remitente = settings.SMTP_FROM or settings.SMTP_USER

    # Estructura del correo
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{otp_code} es tu código de verificación SherekePet"
    msg["From"] = f"SherekePet <{remitente}>"
    msg["To"] = destinatario

    # Versión Texto Plano
    texto_plano = f"""
Hola{saludo_nombre},

Gracias por registrarte en SherekePet.
Tu código de verificación de 6 dígitos es:

{otp_code}

Este código es válido por 15 minutos. Si no solicitaste este registro, puedes ignorar este mensaje.

El equipo de SherekePet
https://sherekepet-app.onrender.com
"""

    # Versión HTML con diseño moderno Tailwind / SaaS
    html_contenido = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b; }}
    .card {{ max-width: 480px; margin: 0 auto; background: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; padding: 32px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
    .badge {{ display: inline-block; padding: 4px 12px; background-color: #f0fdf9; border: 1px solid #ccfbf1; color: #0f766e; border-radius: 9999px; font-size: 12px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 16px; }}
    .otp-box {{ background: #f0fdfa; border: 2px dashed #0d9488; border-radius: 12px; text-align: center; padding: 20px; margin: 24px 0; }}
    .otp-code {{ font-size: 36px; font-weight: 900; letter-spacing: 6px; color: #0f766e; font-family: monospace; }}
    .footer {{ text-align: center; font-size: 11px; color: #94a3b8; margin-top: 24px; }}
  </style>
</head>
<body>
  <div class="card">
    <div style="text-align: center; margin-bottom: 16px;">
      <img src="https://sherekepet-app.onrender.com/static/img/logo_sherekepet.png" alt="SherekePet" style="max-height: 52px; width: auto; border: 0;" />
    </div>
    <div style="text-align: center;">
      <div class="badge">SaaS Veterinario</div>
    </div>
    <h2 style="margin: 0 0 8px 0; color: #0f172a; font-size: 20px; text-align: center;">Verifica tu Cuenta</h2>
    <p style="font-size: 14px; color: #64748b; line-height: 1.5; margin: 0 0 16px 0;">
      Hola<strong>{saludo_nombre}</strong>, ingresa este código de 6 dígitos en la pantalla de verificación para activar tu clínica y comenzar tus 14 días de prueba gratis.
    </p>

    <div class="otp-box">
      <div style="font-size: 12px; font-weight: bold; text-transform: uppercase; color: #0d9488; margin-bottom: 6px;">Código de Verificación</div>
      <div class="otp-code">{otp_code}</div>
    </div>

    <p style="font-size: 12px; color: #64748b; line-height: 1.4; margin: 0;">
      ⏳ Este código expira en <strong>15 minutos</strong>.<br>
      Si tú no creaste esta cuenta, puedes desestimar este mensaje de forma segura.
    </p>
  </div>
  <div class="footer">
    SherekePet SaaS &bull; Plataforma Integral para Clínicas Veterinarias
  </div>
</body>
</html>
"""

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
        # En caso de fallo de red SMTP, mostramos en log el código para no bloquear al usuario
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

    if not (settings.SMTP_USER and settings.SMTP_PASS):
        print(f"[NOTIFICACIÓN CITA SIMULADA] Para: {destinatario} | Mascota: {mascota_nombre} | Fecha: {fecha_str} {hora_str}")
        return False

    remitente = settings.SMTP_FROM or settings.SMTP_USER
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🐾 Nueva Cita Solicitada: {mascota_nombre} ({fecha_str} {hora_str})"
    msg["From"] = f"SherekePet <{remitente}>"
    msg["To"] = destinatario

    texto_plano = f"""
Hola,

{cliente_nombre} ha solicitado una cita para su mascota {mascota_nombre} en {clinica_nombre}.

Detalles de la cita:
- Mascota: {mascota_nombre}
- Fecha: {fecha_str}
- Hora: {hora_str}
- Motivo: {motivo}
- Contacto Dueño: {cliente_telefono or 'No registrado'}

Ingresa a tu panel de SherekePet para confirmarla:
https://sherekepet-app.onrender.com/dashboard#seccionCitasPendientes
"""

    html_contenido = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8fafc; padding: 24px; color: #1e293b; margin: 0; }}
    .card {{ max-width: 500px; margin: 0 auto; background: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; padding: 28px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
    .badge {{ display: inline-block; padding: 4px 12px; background-color: #fef3c7; border: 1px solid #fde68a; color: #92400e; border-radius: 9999px; font-size: 11px; font-weight: bold; text-transform: uppercase; margin-bottom: 14px; }}
    .info-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; margin: 18px 0; }}
    .btn {{ display: inline-block; padding: 12px 24px; background-color: #0f766e; color: #ffffff; text-decoration: none; border-radius: 10px; font-weight: bold; font-size: 13px; text-align: center; }}
  </style>
</head>
<body>
  <div class="card">
    <div style="text-align: center; margin-bottom: 16px;">
      <img src="https://sherekepet-app.onrender.com/static/img/logo_sherekepet.png" alt="SherekePet" style="max-height: 48px; width: auto; border: 0;" />
    </div>
    <div style="text-align: center;">
      <div class="badge">🔔 Nueva Solicitud de Cita</div>
    </div>
    <h2 style="margin: 0 0 8px 0; color: #0f172a; font-size: 18px; text-align: center;">Cita Agendada por Propietario</h2>
    <p style="font-size: 13px; color: #64748b; line-height: 1.5; margin: 0 0 16px 0;">
      El propietario <strong>{cliente_nombre}</strong> ha programado una cita desde el portal para su mascota <strong>{mascota_nombre}</strong>.
    </p>

    <div class="info-box">
      <p style="margin: 4px 0; font-size: 13px;"><strong>📅 Fecha:</strong> {fecha_str}</p>
      <p style="margin: 4px 0; font-size: 13px;"><strong>⏰ Hora:</strong> {hora_str}</p>
      <p style="margin: 4px 0; font-size: 13px;"><strong>📝 Motivo:</strong> {motivo}</p>
      <p style="margin: 4px 0; font-size: 13px;"><strong>📞 Teléfono:</strong> {cliente_telefono or 'No registrado'}</p>
    </div>

    <div style="text-align: center; margin-top: 24px;">
      <a href="https://sherekepet-app.onrender.com/dashboard#seccionCitasPendientes" class="btn" style="color:#ffffff;">
        Ver y Confirmar en el Dashboard
      </a>
    </div>
  </div>
</body>
</html>
"""

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

