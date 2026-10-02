from datetime import timedelta
from app.core.timezone import get_lima_now
from app.core.models import Clinica
from app.clinic.models import Veterinario
from app.core.security import create_access_token


def test_rutas_legales_publicas(client):
    """Verifica que las rutas legales /terminos-y-condiciones, /politica-privacidad y /politica-reembolsos respondan 200."""
    # 1. Términos y Condiciones con cláusula DMCA / Puerto Seguro
    resp_tc = client.get("/terminos-y-condiciones")
    assert resp_tc.status_code == 200
    assert "Términos y Condiciones" in resp_tc.text
    assert "Puerto Seguro" in resp_tc.text
    assert "DMCA" in resp_tc.text
    assert "soporte@sherekepet.com" in resp_tc.text

    # 2. Política de Privacidad
    resp_pp = client.get("/politica-privacidad")
    assert resp_pp.status_code == 200
    assert "Política de Privacidad" in resp_pp.text
    assert "Cookies" in resp_pp.text
    assert "ARCO" in resp_pp.text

    # 3. Política de Reembolsos
    resp_pr = client.get("/politica-reembolsos")
    assert resp_pr.status_code == 200
    assert "Política de Reembolsos" in resp_pr.text
    assert "Plan Emprendedor" in resp_pr.text
    assert "49.00" in resp_pr.text


def test_landing_page_footer_y_cookie_banner(client):
    """Verifica que la landing pública tenga en el footer la información de la empresa, enlaces legales y el banner de cookies."""
    resp = client.get("/")
    assert resp.status_code == 200
    
    # Enlaces legales
    assert "/terminos-y-condiciones" in resp.text
    assert "/politica-privacidad" in resp.text
    assert "/politica-reembolsos" in resp.text

    # Texto visible obligatorio de footer
    assert "Razón Social: [TU EMPRESA] | RUC: [TU RUC] | Contacto:" in resp.text
    assert "soporte@sherekepet.com" in resp.text

    # Cookie Consent Banner
    assert 'id="cookieConsentBanner"' in resp.text
    assert "Aceptar" in resp.text
    assert "Rechazar" in resp.text
    assert "cookie_consent" in resp.text


def test_consentimiento_registro_clinica_y_duenos(client):
    """Verifica que los formularios de registro incluyan el checkbox obligatorio y enlaces target=_blank."""
    # 1. Registro de Clínica
    resp_reg = client.get("/registro")
    assert resp_reg.status_code == 200
    assert 'id="acepta_terminos"' in resp_reg.text
    assert 'required' in resp_reg.text
    assert 'href="/terminos-y-condiciones"' in resp_reg.text
    assert 'href="/politica-privacidad"' in resp_reg.text
    assert 'target="_blank"' in resp_reg.text

    # 2. Login / Registro de PIN Dueños en Portal
    resp_portal = client.get("/portal/login")
    assert resp_portal.status_code == 200
    assert 'id="aceptaTerminosCliente"' in resp_portal.text
    assert 'target="_blank"' in resp_portal.text


def test_modelo_clinica_trial_14_dias_y_billing(client, db_session):
    """
    Verifica que:
    1. Una nueva clínica tenga estado_suscripcion 'TRIAL' y trial_ends_at a ~14 días.
    2. La vista /configuracion/facturacion muestre el Plan Emprendedor de S/ 49.00 / mes y días de prueba.
    3. Si el trial expira, se bloquean operaciones POST y se alerta en facturación.
    4. La activación del Plan Emprendedor restaura el acceso operativo.
    """
    ahora = get_lima_now()

    # 1. Crear clínica de prueba
    clinica = Clinica(
        nombre="Veterinaria San Francisco Test",
        zona_horaria="America/Lima",
        plan_activo="solo"
    )
    db_session.add(clinica)
    db_session.flush()

    assert clinica.estado_suscripcion == "TRIAL"
    assert clinica.trial_ends_at is not None
    assert clinica.tiene_suscripcion_activa is True
    assert clinica.dias_restantes_trial >= 13

    # Crear veterinario titular ADMIN
    vet = Veterinario(
        clinica_id=clinica.id,
        email="vet_trial@sanfrancisco.pe",
        nombre="Dr. Francisco Test",
        password_hash="fakehash",
        rol="ADMIN",
        is_active=True,
        is_verified=True
    )
    db_session.add(vet)
    db_session.commit()
    db_session.refresh(vet)

    # Token de sesión
    token = create_access_token({
        "sub": str(vet.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "ADMIN",
        "is_verified": True
    })
    client.cookies.set("vet_token", token)

    # 2. Ver Facturación en Trial
    resp_bill = client.get("/configuracion/facturacion")
    assert resp_bill.status_code == 200
    assert "Plan Emprendedor" in resp_bill.text
    assert "S/ 49.00" in resp_bill.text
    assert "Periodo de Prueba Activo" in resp_bill.text

    # 3. Forzar expiración del trial
    clinica.trial_ends_at = ahora - timedelta(days=1)
    db_session.commit()
    db_session.refresh(clinica)

    assert clinica.tiene_suscripcion_activa is False

    # Intentar operación PUT de API (bloqueada por middleware con HTTP 402)
    resp_op = client.put(
        "/api/clinic/configuracion",
        json={"nombre": "Veterinaria San Francisco Test", "nombre_comercial": "Nuevo Nombre"}
    )
    assert resp_op.status_code == 402
    assert "Suscripción expirada" in resp_op.json().get("detail", "")
    assert resp_op.json().get("redirect_url") == "/configuracion/facturacion"

    # Ver Facturación con Trial Expirado
    resp_bill_exp = client.get("/configuracion/facturacion")
    assert resp_bill_exp.status_code == 200
    assert "Suscripción Expirada" in resp_bill_exp.text

    # 4. Activar Plan Emprendedor
    resp_act = client.post("/configuracion/facturacion/activar", follow_redirects=False)
    assert resp_act.status_code == 303
    assert "/configuracion/facturacion" in resp_act.headers.get("location", "")

    db_session.refresh(clinica)
    assert clinica.estado_suscripcion == "ACTIVO"
    assert clinica.tiene_suscripcion_activa is True

    # Operación PUT permitida tras activación
    resp_op_ok = client.put(
        "/api/clinic/configuracion",
        json={"nombre": "Veterinaria San Francisco Test", "nombre_comercial": "Veterinaria Activa"}
    )
    assert resp_op_ok.status_code == 200


def test_portal_duenos_legal_y_cookies(client):
    """Verifica que el portal de dueños tenga blindaje legal, consentimiento explícito y cookie banner."""
    # 1. Login de pacientes
    resp = client.get("/portal/login")
    assert resp.status_code == 200

    # Banner de cookies global presente en el portal
    assert 'id="cookieConsentBanner"' in resp.text
    assert "cookie_consent" in resp.text

    # Footer legal con target="_blank"
    assert 'href="/terminos-y-condiciones"' in resp.text
    assert 'href="/politica-privacidad"' in resp.text
    assert 'target="_blank"' in resp.text

    # Consentimiento explícito previo al botón Continuar
    assert "Al continuar, confirmas que has leído y aceptas nuestros" in resp.text

    # 2. Cláusulas de Privacidad de Pacientes y Dueños
    resp_priv = client.get("/politica-privacidad")
    assert resp_priv.status_code == 200
    assert "Tratamiento de Datos de Pacientes y Dueños" in resp_priv.text
    assert "identificador único" in resp_priv.text
    assert "Cloudflare R2" in resp_priv.text
    assert "veterinarias" in resp_priv.text


def test_ciclo_pagos_yape_gracia_y_modo_solo_lectura(client, db_session):
    """
    Verifica el flujo completo de:
    1. Modo Solo Lectura cuando expira la licencia (GET permitido con bannerModoSoloLectura, carnet del dueño intacto, citas online pausadas).
    2. Reporte de pago Yape/Plin sin WhatsApp (/api/billing/reportar-pago).
    3. Aprobación en 1 clic desde el Panel SuperAdmin (/admin/pagos/{id}/aprobar) otorgando +30 días.
    4. Periodo de Gracia de 3 días (bannerPeriodoGracia y acceso operativo activo).
    """
    from app.clinic.models import Cliente, Mascota

    ahora = get_lima_now()
    clinica = Clinica(
        nombre="Veterinaria Los Olivos Test",
        zona_horaria="America/Lima",
        plan_activo="solo",
        estado_suscripcion="TRIAL",
        trial_ends_at=ahora - timedelta(days=2)  # Expirado
    )
    db_session.add(clinica)
    db_session.flush()

    vet = Veterinario(
        clinica_id=clinica.id,
        email="roggerjjj@gmail.com",  # SuperAdmin + Titular
        nombre="Dr. Rogger SuperAdmin",
        password_hash="fakehash",
        rol="SUPER_ADMIN",
        is_superadmin=True,
        is_active=True,
        is_verified=True
    )
    db_session.add(vet)

    cliente_dueno = Cliente(
        clinica_id=clinica.id,
        dni="76543210",
        nombre_completo="María Dueña",
        telefono="999111222"
    )
    db_session.add(cliente_dueno)
    db_session.flush()

    mascota = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente_dueno.id,
        nombre="Firulais",
        especie="Canino"
    )
    db_session.add(mascota)
    db_session.commit()

    # 1. Verificar Modo Solo Lectura (GET /dashboard funciona y muestra bannerModoSoloLectura)
    assert clinica.modo_solo_lectura is True
    token = create_access_token({
        "sub": str(vet.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "SUPER_ADMIN",
        "is_superadmin": True,
        "is_verified": True
    })
    client.cookies.set("vet_token", token)

    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    assert 'id="bannerModoSoloLectura"' in resp_dash.text

    # 2. Verificar que el Carnet del Dueño NUNCA se bloquea aunque la clínica esté vencida
    resp_carnet = client.get(f"/portal/carnet/{mascota.id}")
    assert resp_carnet.status_code == 200
    assert "Firulais" in resp_carnet.text

    # Pero la agenda online del portal sí se pausa para la clínica vencida
    hoy_str = ahora.date().isoformat()
    resp_disp = client.get(f"/api/portal/clinica/{clinica.id}/disponibilidad?fecha={hoy_str}")
    assert resp_disp.status_code == 200
    assert resp_disp.json()["hay_disponibilidad"] is False
    assert resp_disp.json()["licencia_expirada"] is True

    # 3. Reportar pago por Yape directamente en la plataforma (sin WhatsApp)
    resp_reporte = client.post(
        "/api/billing/reportar-pago",
        data={
            "metodo_pago": "YAPE",
            "referencia_operacion": "98765432",
            "notas": "Pago mensual Veterinaria Los Olivos"
        },
        headers={"Accept": "application/json"}
    )
    assert resp_reporte.status_code == 200
    datos_rep = resp_reporte.json()
    assert datos_rep["estado"] == "PENDIENTE_REVISION"
    pago_id = datos_rep["pago_id"]

    # 4. SuperAdmin aprueba el pago en 1 clic (/admin/pagos/{pago_id}/aprobar)
    resp_aprob = client.post(
        f"/admin/pagos/{pago_id}/aprobar",
        headers={"Accept": "application/json"}
    )
    assert resp_aprob.status_code == 200
    assert resp_aprob.json()["estado_pago"] == "APROBADO"

    db_session.refresh(clinica)
    assert clinica.tiene_suscripcion_activa is True
    assert clinica.dias_restantes_suscripcion >= 29

    # 5. Simular vencimiento hace 1 día (entra en Periodo de Gracia de 3 días)
    clinica.subscription_ends_at = ahora - timedelta(days=1)
    db_session.commit()
    db_session.refresh(clinica)

    assert clinica.en_periodo_gracia is True
    assert clinica.tiene_suscripcion_activa is True
    assert clinica.dias_gracia_restantes >= 2

    resp_dash_gracia = client.get("/dashboard")
    assert resp_dash_gracia.status_code == 200
    assert 'id="bannerPeriodoGracia"' in resp_dash_gracia.text

    # 6. Simular vencimiento hace 5 días (superó los 3 días de gracia -> pasa a Modo Solo Lectura)
    clinica.subscription_ends_at = ahora - timedelta(days=5)
    db_session.commit()
    db_session.refresh(clinica)

    assert clinica.en_periodo_gracia is False
    assert clinica.tiene_suscripcion_activa is False
    assert clinica.modo_solo_lectura is True


