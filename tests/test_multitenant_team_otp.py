from app.core.models import Clinica
from app.clinic.models import Veterinario, Mascota, Cliente
from app.core.security import create_access_token


def test_multitenant_isolation_on_registration(client, db_session):
    """
    1. Aislamiento Multi-tenant Estricto:
    Cada registro nuevo crea una Clínica independiente y asigna el rol ADMIN.
    """
    reg_payload_a = {
        "nombre": "Dra. Ana López",
        "nombre_clinica": "Clínica San Borja",
        "email": "ana@sanborja.com",
        "password": "Password123"
    }
    resp_a = client.post("/registro", data=reg_payload_a, follow_redirects=False)
    assert resp_a.status_code == 303
    assert "/verificar" in resp_a.headers["location"]

    vet_a = db_session.query(Veterinario).filter(Veterinario.email == "ana@sanborja.com").first()
    assert vet_a is not None
    assert vet_a.rol == "ADMIN"
    assert vet_a.is_verified is False

    reg_payload_b = {
        "nombre": "Dr. Beto Benítez",
        "nombre_clinica": "Veterinaria Miraflores",
        "email": "beto@miraflores.com",
        "password": "Password123"
    }
    resp_b = client.post("/registro", data=reg_payload_b, follow_redirects=False)
    assert resp_b.status_code == 303

    vet_b = db_session.query(Veterinario).filter(Veterinario.email == "beto@miraflores.com").first()
    assert vet_b is not None
    assert vet_b.rol == "ADMIN"
    assert vet_b.clinica_id != vet_a.clinica_id


def test_otp_verification_flow(client, db_session):
    """
    3. Verificación de Correo OTP:
    - No permite login clásico si no está verificado.
    - Valida código OTP de 6 dígitos para activar la cuenta.
    - Reenvía OTP si es solicitado.
    """
    reg_payload = {
        "nombre": "Dr. Carlos Castro",
        "nombre_clinica": "Clínica PetCare",
        "email": "carlos@petcare.com",
        "password": "Password123"
    }
    client.post("/registro", data=reg_payload)

    # Intento de login antes de verificar
    login_resp = client.post("/login", data={"email": "carlos@petcare.com", "password": "Password123"})
    assert login_resp.status_code == 200
    assert "verificar" in login_resp.text.lower() or "código" in login_resp.text.lower()

    vet = db_session.query(Veterinario).filter(Veterinario.email == "carlos@petcare.com").first()
    assert vet.is_verified is False
    assert len(vet.otp_code) == 6

    # Reenviar OTP
    reenvio_resp = client.post("/api/auth/reenviar-otp", json={"email": "carlos@petcare.com"})
    assert reenvio_resp.status_code == 200
    db_session.refresh(vet)
    nuevo_otp = vet.otp_code

    # Verificación errónea
    bad_verif = client.post("/verificar", data={"email": "carlos@petcare.com", "otp_code": "000000"})
    assert bad_verif.status_code == 200
    assert "incorrecto" in bad_verif.text.lower()

    # Verificación exitosa
    good_verif = client.post("/verificar", data={"email": "carlos@petcare.com", "otp_code": nuevo_otp}, follow_redirects=False)
    assert good_verif.status_code == 303
    assert good_verif.headers["location"] == "/dashboard"

    db_session.refresh(vet)
    assert vet.is_verified is True

    # Login después de verificar
    client.cookies.clear()
    login_success = client.post("/login", data={"email": "carlos@petcare.com", "password": "Password123"}, follow_redirects=False)
    assert login_success.status_code == 303
    assert login_success.headers["location"] == "/dashboard"


def test_asistente_creation_and_limits(client, db_session):
    """
    5. Cuenta de Asistente de Equipo:
    - Crear asistente con username y contraseña (sin OTP, is_verified=True).
    - Límite estricto de máximo 1 asistente por clínica.
    - Login con username (sin email).
    """
    # 1. Crear clínica y Admin verificado
    clinica = Clinica(nombre="Vet Salcedo", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    admin = Veterinario(
        clinica_id=clinica.id,
        nombre="Dra. Salcedo",
        email="salcedo@vetsalcedo.com",
        rol="ADMIN",
        is_verified=True,
        is_active=True
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    admin_token = create_access_token({
        "sub": str(admin.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "ADMIN",
        "email": admin.email
    })

    client.cookies.set("vet_token", admin_token)

    # 2. Crear Asistente
    payload_asistente = {
        "nombre": "Lucía Asistente",
        "username": "lucia_salcedo",
        "password": "Password123"
    }
    resp_asistente = client.post("/api/clinic/asistentes", json=payload_asistente)
    assert resp_asistente.status_code == 200
    data = resp_asistente.json()
    assert data["asistente"]["username"] == "lucia_salcedo"
    assert data["asistente"]["rol"] == "ASISTENTE"

    # Verificar en BD que el asistente no requiere OTP
    asistente = db_session.query(Veterinario).filter(Veterinario.username == "lucia_salcedo").first()
    assert asistente is not None
    assert asistente.is_verified is True
    assert asistente.rol == "ASISTENTE"

    # 3. Intentar crear segundo asistente (debe fallar por límite de 1)
    payload_segundo = {
        "nombre": "Pedro Segundo",
        "username": "pedro_salcedo",
        "password": "Password123"
    }
    resp_segundo = client.post("/api/clinic/asistentes", json=payload_segundo)
    assert resp_segundo.status_code == 400
    assert "límite" in resp_segundo.json()["detail"].lower()

    # 4. Login del asistente usando username (no email)
    client.cookies.clear()
    login_asistente = client.post("/login", data={"email": "lucia_salcedo", "password": "Password123"}, follow_redirects=False)
    assert login_asistente.status_code == 303
    assert login_asistente.headers["location"] == "/dashboard"
    assert "vet_token" in login_asistente.cookies

    # 5. Restricción de Asistente: no puede subir logo
    client.cookies.set("vet_token", login_asistente.cookies["vet_token"])
    logo_attempt = client.post(
        "/api/clinic/logo",
        files={"file": ("logo.png", b"fakecontent", "image/png")},
        data={"clinica_id": str(clinica.id)}
    )
    assert logo_attempt.status_code == 403


def test_multitenant_data_access_isolation(client, db_session):
    """
    Multi-tenant: Un veterinario de Clínica A no puede ver las fichas de pacientes de Clínica B.
    """
    clinica_a = Clinica(nombre="Clínica Alfa", zona_horaria="America/Lima", plan_activo="solo")
    clinica_b = Clinica(nombre="Clínica Beta", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add_all([clinica_a, clinica_b])
    db_session.flush()

    vet_a = Veterinario(clinica_id=clinica_a.id, nombre="Dr. Alfa", email="alfa@clinica.com", rol="ADMIN", is_verified=True)
    vet_b = Veterinario(clinica_id=clinica_b.id, nombre="Dr. Beta", email="beta@clinica.com", rol="ADMIN", is_verified=True)
    db_session.add_all([vet_a, vet_b])
    db_session.flush()

    cliente_b = Cliente(clinica_id=clinica_b.id, dni="11223344", nombre_completo="Dueño Beta")
    db_session.add(cliente_b)
    db_session.flush()

    mascota_b = Mascota(clinica_id=clinica_b.id, cliente_id=cliente_b.id, nombre="Firulais Beta", especie="Canino", raza="Mestizo")
    db_session.add(mascota_b)
    db_session.commit()
    db_session.refresh(mascota_b)

    token_a = create_access_token({
        "sub": str(vet_a.id),
        "clinica_id": clinica_a.id,
        "role": "vet",
        "rol": "ADMIN",
        "email": vet_a.email
    })
    client.cookies.set("vet_token", token_a)

    # Vet A intenta acceder a la ficha de Mascota B
    resp = client.get(f"/pacientes/{mascota_b.id}")
    assert resp.status_code == 404


def test_trial_badge_and_user_identity_in_views(client, db_session):
    """
    4. SaaS Free Trial & 2. Identidad Visual:
    - Navbar muestra nombre y rol.
    - Dashboard muestra badge con días restantes de prueba para ADMIN.
    """
    clinica = Clinica(nombre="Veterinaria Prueba 14D", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add(clinica)
    db_session.flush()

    admin = Veterinario(
        clinica_id=clinica.id,
        nombre="Dra. Lorena Admin",
        email="lorena@prueba14d.com",
        rol="ADMIN",
        is_verified=True
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    admin_token = create_access_token({
        "sub": str(admin.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "ADMIN",
        "email": admin.email
    })
    client.cookies.set("vet_token", admin_token)

    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Dra. Lorena Admin" in resp.text
    assert "ADMIN" in resp.text
    assert "Prueba:" in resp.text or "días restantes" in resp.text
