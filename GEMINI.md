# SherekePet — Guía de Arquitectura y Reglas de Seguridad (GEMINI.md)

Este archivo se carga automáticamente en cada sesión de desarrollo con agentes de IA. **Todo agente debe cumplir estrictamente estas reglas antes de escribir o modificar código.**

## 🔒 Checklist de Seguridad Obligatorio (Zero-Regression Policy)

1. **Autenticación y Aislamiento Multi-Tenant (`clinica_id`)**:
   - Todo endpoint de clínica (`/api/clinic/*`, `/api/citas/*`, `/api/mascotas/*`, `/api/medication/plan`, `/api/reniec/*`) **DEBE** requerir `current_user: Veterinario = Depends(require_current_vet)`.
   - **PROHIBIDO** usar `target_clinica_id = current_user.clinica_id if current_user else 1`. El `clinica_id` siempre proviene de `current_user.clinica_id` (salvo `current_user.is_superadmin == True`).
   - Toda consulta SQLAlchemy sobre recursos de clínica debe incluir `.filter(Modelo.clinica_id == current_user.clinica_id)`.

2. **Portal de Dueños de Mascotas (`/portal/*` y `/api/portal/*`)**:
   - **PROHIBIDO** aceptar `?cliente_id=` en query params o body como método de autenticación. Usa exclusivamente `obtener_cliente_autenticado(request, db)` basado en el JWT `client_token`.
   - Toda ruta que acceda a una mascota o dosis por ID (`/portal/carnet/{mascota_id}`, `/api/portal/mascotas/{mascota_id}`, `/api/medication/dose/{id}/*`) debe validar pertenencia con `_verificar_acceso_mascota_o_dosis(request, db, mascota)`.

3. **Protección contra Fuerza Bruta y Enumeración**:
   - Usa `rate_limiter.check_rate_limit(...)` (`app/core/rate_limit.py`) en todos los endpoints de login, registro, OTP y consulta de DNI.
   - Mantén el bloqueo de 5 intentos fallidos de PIN (`rate_limiter.check_pin_lockout` / `record_pin_failure`).

4. **Facturación SaaS y Pasarela de Pagos**:
   - Nunca actives suscripciones en `/configuracion/facturacion/retorno-mp` ni en `/api/billing/webhook/mercadopago` sin verificar la firma HMAC (`MP_WEBHOOK_SECRET`) o consultar el estado real del `payment_id` en la API de Mercado Pago (`MP_ACCESS_TOKEN`).
   - Respeta el bloqueo de `SubscriptionMiddleware` (`HTTP 402`) cuando `clinica.tiene_suscripcion_activa == False`.

5. **Subida de Archivos y Prevención XSS**:
   - Prohibido permitir `image/svg+xml` (`.svg`) en endpoints de subida de fotos o logos. Usa siempre `upload_image_to_r2` que ejecuta `validate_safe_image()`.
   - Escapa siempre con `_esc()` cualquier variable de usuario en correos HTML (`app/core/email.py`) y evita `innerHTML` con datos no sanitizados en plantillas.

6. **Pruebas de Regresión Obligatorias**:
   - Antes de finalizar cualquier cambio, ejecuta `.\.venv\Scripts\pytest` y verifica que `tests/test_security_audit.py` pase al 100%.
