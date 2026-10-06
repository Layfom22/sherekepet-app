---
trigger: always_on
description: Reglas obligatorias de Seguridad OWASP Top 10, Aislamiento Multi-Tenant y Lógica de Negocio para SherekePet
---

# 🛡️ Reglas Obligatorias de Seguridad para Agentes de Desarrollo (SherekePet)

Estas directrices son **obligatorias e inquebrantables** en cada nuevo chat, sprint o refactorización sobre **SherekePet (FastAPI + SQLAlchemy + PostgreSQL + PWA)**.

## 1. Aislamiento Estricto Multi-Tenant (Prevención de BOLA / IDOR)
- **PROHIBIDO usar fallbacks por defecto a `clinica_id = 1`**: Nunca escribas `current_user.clinica_id if current_user else 1` ni confíes en `payload.clinica_id` enviado desde el cliente si el usuario no es `is_superadmin == True`.
- **Dependencia obligatoria en rutas de Clínica**: Todo endpoint bajo `/api/clinic/*`, `/api/citas/*`, `/api/mascotas/*`, `/api/medication/plan` o `/api/reniec/*` **DEBE** inyectar `current_user: Veterinario = Depends(require_current_vet)` (definido en `app/clinic/routes.py`).
- **Filtro obligatorio en consultas SQLAlchemy**: Toda consulta de lectura, edición o borrado sobre `Mascota`, `Cliente`, `Cita`, `AtencionClinica`, `Producto`, `ServicioBano`, `HorarioAtencion` o `SeguimientoNotificacion` en el panel veterinario **DEBE** filtrar explícitamente por `Modelo.clinica_id == current_user.clinica_id` (salvo SuperAdmin verificado).
- **Vinculación Cross-Tenant controlada**: Una clínica solo puede auto-vincular una mascota externa en `/pacientes/{id}` si existe una `Cita` real agendada en `target_clinica_id`. Jamás uses query params manipulables como `?atender_cita=` para autorizar vinculaciones.

## 2. Seguridad en el Portal de Dueños (`/portal/*` y `/api/portal/*`)
- **PROHIBIDO autenticar mediante `?cliente_id=`**: `obtener_cliente_autenticado()` solo puede validar tokens JWT firmados (`client_token` en cookie `HttpOnly` o `Authorization: Bearer`). Nunca aceptes `cliente_id` por query param o body para identificar quién hace la petición.
- **Verificación de propiedad (Ownership)**: Todo acceso a `/portal/carnet/{mascota_id}`, `/api/portal/mascotas/{mascota_id}`, `/api/medication/dose/{id}/confirm` y `/api/medication/dose/{id}/reprogramar` debe verificar `_verificar_acceso_mascota_o_dosis()` validando que `mascota.cliente.dni == cliente_autenticado.dni` (o que sea el veterinario titular de la clínica de la mascota).

## 3. Autenticación, OTP, PIN y Rate Limiting
- **Rate Limiting obligatorio**: Todo endpoint de login, consulta de DNI, verificación OTP o restablecimiento (`POST /api/auth/vet/login`, `POST /api/auth/client/login`, `POST /portal/login`, `GET /api/portal/check-dni`) debe invocar `rate_limiter.check_rate_limit(...)` (`app/core/rate_limit.py`).
- **Protección de PIN de 4 dígitos**: `AuthService.login_cliente` debe mantener activo `rate_limiter.check_pin_lockout` y `rate_limiter.record_pin_failure` (bloqueo temporal HTTP 429 tras 5 intentos fallidos).
- **Verificación de correo (OTP)**: Nunca marques `vet.is_verified = True` automáticamente en `/api/auth/vet/login` solo porque el request incluya `google_id` sin validar un token firmado de Google o el código OTP en `/api/auth/verificar`.
- **Prevención de escalación de privilegios en clínicas**: Nunca auto-crees un usuario `ADMIN` durante el login si la clínica ya cuenta con veterinarios registrados.

## 4. Motor de Suscripciones y Pasarela de Pagos (Anti-Bypass)
- **`SubscriptionMiddleware` (`app/core/subscription.py`)**: Ninguna clínica con `tiene_suscripcion_activa == False` puede ejecutar peticiones de escritura (`POST`, `PUT`, `PATCH`, `DELETE`) ni consumir proxies con costo (`GET /api/reniec/*`), excepto las rutas de facturación (`/configuracion/facturacion`, `/api/billing/*`) y autenticación.
- **Webhooks y Retornos de Mercado Pago**:
  - En `/api/billing/webhook/mercadopago`, valida siempre la firma HMAC-SHA256 (`_verificar_firma_webhook_mp` con `settings.MP_WEBHOOK_SECRET`) o verifica el `payment_id` directamente contra `https://api.mercadopago.com/v1/payments/{payment_id}` usando `settings.MP_ACCESS_TOKEN`.
  - En `/configuracion/facturacion/retorno-mp`, **NUNCA** actives una suscripción confiando únicamente en `?status=approved` de la URL sin verificar el pago en base de datos o en la API de Mercado Pago.

## 5. Prevención de XSS, Inyección HTML y Subida de Archivos (Cloudflare R2)
- **Prohibido `image/svg+xml` y archivos ejecutables**: Todas las subidas de imágenes (`upload_image_to_r2` en `app/core/storage.py`) deben pasar por `validate_safe_image()`, permitiendo únicamente `image/png`, `image/jpeg`, `image/webp` y `image/gif`, rechazando `.svg`, `.html`, `.js` o payloads con `<script` / `<svg`.
- **Correos Transaccionales (`app/core/email.py`)**: Todo dato proveniente de usuarios (nombres de clientes, mascotas, clínicas, motivos de cita, medicamentos, referencias de pago) interpolado en plantillas HTML de correo **DEBE** escaparse con `_esc()` (`html.escape(..., quote=True)`).
- **Frontend / Plantillas Jinja2**:
  - No uses `| safe` en plantillas Jinja2 con contenido ingresado por usuarios.
  - En JavaScript del navegador, evita concatenar URLs o textos de usuario dentro de `innerHTML`; usa `document.createElement` y `textContent`.
- **SQLAlchemy Seguro**: Usa siempre expresiones parametrizadas del ORM de SQLAlchemy. Nunca construyas consultas SQL concatenando strings con f-strings.

## 6. Verificación Automática antes de Finalizar Cualquier Tarea
Antes de dar por terminada cualquier modificación en el proyecto, ejecuta siempre:
```powershell
.\.venv\Scripts\pytest
```
Incluyendo la suite de seguridad `tests/test_security_audit.py` para garantizar que ningún cambio haya roto el aislamiento entre clínicas o reintroducido vulnerabilidades OWASP.
