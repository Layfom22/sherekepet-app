import io
import json
import pytest
from app.core.models import Clinica
from app.core.security import create_access_token
from app.clinic.models import Especie, Raza, Mascota, Cliente, RegistroVacuna, Veterinario


def test_catalogo_especies_y_razas(client, db_session):
    """Verifica el endpoint reactivo del catálogo de especies y razas."""
    # Aseguramos existencia de especies y razas en la BD de test
    perro = Especie(nombre="Canino (Perro)")
    db_session.add(perro)
    db_session.flush()

    raza1 = Raza(especie_id=perro.id, nombre="Labrador Retriever")
    raza2 = Raza(especie_id=perro.id, nombre="Bulldog Francés")
    db_session.add_all([raza1, raza2])
    db_session.commit()

    resp = client.get("/api/clinic/catalogo")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    canino = next((item for item in data if item["nombre"] == "Canino (Perro)"), None)
    assert canino is not None
    razas_nombres = [r["nombre"] for r in canino["razas"]]
    assert "Labrador Retriever" in razas_nombres
    assert "Bulldog Francés" in razas_nombres


def test_subir_logo_clinica(client, test_clinica, db_session):
    """Verifica la subida de logo a Cloudflare R2 y actualización de logo_url."""
    fake_webp = b"RIFF\x1a\x00\x00\x00WEBPVP8 \x0e\x00\x00\x00"
    files = {"file": ("logo.webp", io.BytesIO(fake_webp), "image/webp")}
    data = {"clinica_id": str(test_clinica.id)}

    resp = client.post("/api/clinic/logo", files=files, data=data)
    assert resp.status_code == 200
    res_json = resp.json()
    assert "logos/" in res_json["logo_url"]

    # Verificar en BD
    db_session.refresh(test_clinica)
    assert test_clinica.logo_url == res_json["logo_url"]

    # Rechazo de formato no admitido
    files_invalid = {"file": ("test.txt", io.BytesIO(b"texto plano"), "text/plain")}
    resp_invalid = client.post("/api/clinic/logo", files=files_invalid, data=data)
    assert resp_invalid.status_code == 400


def test_subir_foto_mascota(client, test_clinica, db_session):
    """Verifica la subida de foto de mascota a Cloudflare R2 y actualización de foto_url."""
    cliente = Cliente(clinica_id=test_clinica.id, dni="99887766", nombre_completo="Ana Lopez")
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(
        clinica_id=test_clinica.id,
        cliente_id=cliente.id,
        nombre="Boby",
        especie="Canino"
    )
    db_session.add(mascota)
    db_session.commit()

    fake_webp = b"RIFF\x1a\x00\x00\x00WEBPVP8 \x0e\x00\x00\x00"
    files = {"file": ("mascota.webp", io.BytesIO(fake_webp), "image/webp")}

    resp = client.post(f"/api/mascotas/{mascota.id}/foto", files=files)
    assert resp.status_code == 200
    res_json = resp.json()
    assert "mascotas/" in res_json["foto_url"]

    # Verificar en BD
    db_session.refresh(mascota)
    assert mascota.foto_url == res_json["foto_url"]


def test_paciente_rapido_con_nuevos_campos(client, test_clinica, db_session):
    """Verifica registro con especie_id, raza_id, alergias dinámicas y condiciones previas."""
    especie = Especie(nombre="Felino (Gato)")
    db_session.add(especie)
    db_session.flush()
    raza = Raza(especie_id=especie.id, nombre="Siamés")
    db_session.add(raza)
    db_session.commit()

    payload = {
        "clinica_id": test_clinica.id,
        "dni": "88776655",
        "nombres": "Lucia",
        "apellido_paterno": "Fernandez",
        "telefono": "999888777",
        "mascota_nombre": "Misu",
        "especie_id": especie.id,
        "raza_id": raza.id,
        "mascota_peso": 4.1,
        "tiene_alergias": True,
        "detalle_alergias": "Intolerancia a la proteína de res",
        "condiciones_previas": "Asma felina leve diagnosticada en 2024"
    }

    resp = client.post("/api/clinic/paciente-rapido", json=payload)
    assert resp.status_code == 201
    res_data = resp.json()
    assert res_data["mascota"]["nombre"] == "Misu"
    assert res_data["mascota"]["especie"] == "Felino (Gato)"
    assert res_data["mascota"]["raza"] == "Siamés"

    # Verificar en base de datos
    mascota_db = db_session.query(Mascota).filter(Mascota.id == res_data["mascota"]["id"]).first()
    assert mascota_db is not None
    assert mascota_db.especie_id == especie.id
    assert mascota_db.raza_id == raza.id
    assert mascota_db.tiene_alergias is True
    assert mascota_db.detalle_alergias == "Intolerancia a la proteína de res"
    assert mascota_db.condiciones_previas == "Asma felina leve diagnosticada en 2024"


def test_atencion_vacunacion_con_enfermedades_cubiertas(client, test_clinica, db_session):
    """Verifica el guardado y consulta de vacunas con lista de enfermedades cubiertas."""
    cliente = Cliente(clinica_id=test_clinica.id, dni="12121212", nombre_completo="Roberto Gomez")
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(
        clinica_id=test_clinica.id,
        cliente_id=cliente.id,
        nombre="Thor",
        especie="Canino"
    )
    db_session.add(mascota)
    db_session.commit()

    payload = {
        "clinica_id": test_clinica.id,
        "mascota_id": mascota.id,
        "tipo_atencion": "VACUNACION",
        "motivo": "Vacunación anual séxtuple",
        "tipo_vacuna": "Séxtuple Canina",
        "marca_lote": "Zoetis Lote 994B",
        "fecha_proximo_refuerzo": "2026-09-15",
        "enfermedades_cubiertas": [
            "Parvovirus",
            "Distemper",
            "Hepatitis Infecciosa",
            "Parainfluenza",
            "Leptospira"
        ]
    }

    resp = client.post("/api/clinic/atenciones", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["vacuna_id"] is not None
    assert "Parvovirus" in data["enfermedades_cubiertas"]

    # Comprobar modelo en BD y property lista_enfermedades
    vacuna_db = db_session.query(RegistroVacuna).filter(RegistroVacuna.mascota_id == mascota.id).first()
    assert vacuna_db is not None
    assert vacuna_db.lista_enfermedades == [
        "Parvovirus",
        "Distemper",
        "Hepatitis Infecciosa",
        "Parainfluenza",
        "Leptospira"
    ]


def test_muro_de_contencion_bloqueo_rol_cliente(client, test_clinica, db_session):
    """Verifica que un usuario con rol 'client' reciba HTTP 403 en todas las rutas de veterinario."""
    # Generar token JWT con rol 'client'
    client_token = create_access_token({"sub": "78965412", "role": "client", "clinic_id": test_clinica.id})
    client.cookies.set("client_token", client_token)

    # 1. Intentar acceder a /dashboard
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 403
    assert "Acceso denegado" in resp_dash.text

    # 2. Intentar acceder a /pacientes/nuevo
    resp_nuevo = client.get("/pacientes/nuevo")
    assert resp_nuevo.status_code == 403

    # 3. Intentar acceder a API clínica con Header Bearer de rol 'client'
    headers = {"Authorization": f"Bearer {client_token}"}
    resp_api = client.get("/api/clinic/catalogo", headers=headers)
    assert resp_api.status_code == 403

    # 4. Limpiar cookies y verificar que sin token de cliente se accede normalmente
    client.cookies.clear()
    resp_dash_ok = client.get("/dashboard")
    assert resp_dash_ok.status_code == 200


@pytest.mark.anyio
async def test_r2_storage_upload_direct():
    """Verifica directamente upload_image_to_r2 con mock de S3 boto3."""
    from unittest.mock import patch, MagicMock
    from app.core.storage import upload_image_to_r2

    mock_s3 = MagicMock()
    with patch("app.core.storage.get_r2_client", return_value=mock_s3), \
         patch("app.core.storage.settings.R2_BUCKET_NAME", "test-bucket"), \
         patch("app.core.storage.settings.R2_PUBLIC_URL", "https://cdn.sherekepet.com"):

        url = await upload_image_to_r2(
            file_bytes=b"fake-image-data",
            filename="foto_paciente.webp",
            folder="mascotas",
            content_type="image/webp"
        )
        assert url.startswith("https://cdn.sherekepet.com/mascotas/")
        assert url.endswith("foto_paciente.webp")
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["ContentType"] == "image/webp"


def test_directorio_pacientes_list(client, test_clinica, db_session):
    """Verifica el endpoint GET /pacientes y su buscador."""
    # Crear cliente y mascotas
    c1 = Cliente(clinica_id=test_clinica.id, dni="44556677", nombre_completo="Carlos Alcantara", telefono="+51987654321")
    db_session.add(c1)
    db_session.commit()

    m1 = Mascota(clinica_id=test_clinica.id, cliente_id=c1.id, nombre="Rocky", especie="Canino", raza="Boxer")
    m2 = Mascota(clinica_id=test_clinica.id, cliente_id=c1.id, nombre="Michi", especie="Felino", raza="Siames")
    db_session.add_all([m1, m2])
    db_session.commit()

    # 1. Listado completo
    resp = client.get("/pacientes")
    assert resp.status_code == 200
    assert "Directorio de Pacientes" in resp.text
    assert "Rocky" in resp.text
    assert "Michi" in resp.text
    assert "Carlos Alcantara" in resp.text

    # 2. Búsqueda con filtro
    resp_busqueda = client.get("/pacientes?q=Rocky")
    assert resp_busqueda.status_code == 200
    assert "Rocky" in resp_busqueda.text
    assert "Michi" not in resp_busqueda.text


def test_actualizar_perfil_mascota_dni(client, test_clinica, db_session):
    """Verifica la actualización de datos no clínicos del DNI de la mascota."""
    c = Cliente(clinica_id=test_clinica.id, dni="12345678", nombre_completo="Maria Gomez")
    db_session.add(c)
    db_session.commit()

    m = Mascota(clinica_id=test_clinica.id, cliente_id=c.id, nombre="Luna", especie="Canino")
    db_session.add(m)
    db_session.commit()

    payload = {
        "sexo": "Hembra",
        "fecha_nacimiento": "2022-05-15",
        "microchip": "900215000987654",
        "rasgos_distintivos": "Mancha marrón en la pata trasera"
    }

    resp = client.post(f"/api/portal/mascotas/{m.id}", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["sexo"] == "Hembra"
    assert data["fecha_nacimiento"] == "2022-05-15"
    assert data["microchip"] == "900215000987654"
    assert data["rasgos_distintivos"] == "Mancha marrón en la pata trasera"

    # Verificar persistencia en base de datos
    db_session.refresh(m)
    assert m.sexo == "Hembra"
    assert str(m.fecha_nacimiento) == "2022-05-15"
    assert m.microchip == "900215000987654"
    assert m.rasgos_distintivos == "Mancha marrón en la pata trasera"


def test_auth_veterinario_registro_login_logout(client, db_session):
    """Verifica registro, login con contraseña y logout del veterinario."""
    # 1. Registro (redirige a /verificar)
    reg_payload = {
        "nombre": "Dr. Martin San Martin",
        "nombre_clinica": "Clínica Veterinaria Los Sauces",
        "email": "martin@saucesvet.com",
        "password": "miPasswordSeguro123"
    }
    resp_reg = client.post("/registro", data=reg_payload, follow_redirects=False)
    assert resp_reg.status_code == 303
    assert "/verificar" in resp_reg.headers["location"]

    # 1.1 Verificación de OTP
    vet_reg = db_session.query(Veterinario).filter(Veterinario.email == "martin@saucesvet.com").first()
    assert vet_reg is not None
    assert vet_reg.is_verified is False
    assert vet_reg.otp_code is not None

    resp_verif = client.post("/verificar", data={"email": "martin@saucesvet.com", "otp_code": vet_reg.otp_code}, follow_redirects=False)
    assert resp_verif.status_code == 303
    assert resp_verif.headers["location"] == "/dashboard"
    assert "vet_token" in resp_verif.cookies

    # 2. Login con contraseña correcta (cuenta ya verificada)
    client.cookies.clear()
    login_payload = {
        "email": "martin@saucesvet.com",
        "password": "miPasswordSeguro123"
    }
    resp_login = client.post("/login", data=login_payload, follow_redirects=False)
    assert resp_login.status_code == 303
    assert resp_login.headers["location"] == "/dashboard"
    assert "vet_token" in resp_login.cookies

    # 3. Login con contraseña errónea
    client.cookies.clear()
    bad_login = {
        "email": "martin@saucesvet.com",
        "password": "passwordIncorrecto"
    }
    resp_bad = client.post("/login", data=bad_login)
    assert resp_bad.status_code == 200
    assert "Contraseña incorrecta" in resp_bad.text

    # 4. Logout
    resp_logout = client.get("/logout", follow_redirects=False)
    assert resp_logout.status_code == 303
    assert resp_logout.headers["location"] == "/login"


def test_resetear_pin_cliente(client, test_clinica, db_session):
    """Verifica el endpoint PATCH /api/clinic/clientes/{id}/reset-pin."""
    from app.core.security import hash_pin
    c = Cliente(
        clinica_id=test_clinica.id,
        dni="88776655",
        nombre_completo="Juan Perez",
        pin_hash=hash_pin("1234")
    )
    db_session.add(c)
    db_session.commit()

    assert c.pin_hash is not None

    resp = client.patch(f"/api/clinic/clientes/{c.id}/reset-pin")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["pin_hash"] is None

    db_session.refresh(c)
    assert c.pin_hash is None


def test_multi_clinica_selector(client, db_session):
    """Verifica que un dueño con DNI en múltiples clínicas ingrese directamente a su dashboard unificado sin pasar por selección de clínica."""
    from app.core.models import Clinica
    clinica1 = Clinica(nombre="Veterinaria Norte", zona_horaria="America/Lima", plan_activo="solo")
    clinica2 = Clinica(nombre="Veterinaria Sur", zona_horaria="America/Lima", plan_activo="solo")
    db_session.add_all([clinica1, clinica2])
    db_session.commit()

    c1 = Cliente(clinica_id=clinica1.id, dni="99887766", nombre_completo="Pedro Castillo")
    c2 = Cliente(clinica_id=clinica2.id, dni="99887766", nombre_completo="Pedro Castillo")
    db_session.add_all([c1, c2])
    db_session.commit()

    # Intento de login: accede directamente al dashboard de mascotas unificadas
    resp = client.post("/portal/login", data={"dni": "99887766", "pin": "1234"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/portal/dashboard"


def test_catalogo_extendido_con_especies_y_razas(client, db_session):
    """Verifica que el catálogo tenga las 6 especies principales y gran variedad de razas."""
    from seed_catalogos import seed_catalogos
    seed_catalogos(db_session)

    resp = client.get("/api/clinic/catalogo")
    assert resp.status_code == 200
    catalog = resp.json()
    nombres_especies = [item["nombre"] for item in catalog]
    assert "Canino (Perro)" in nombres_especies
    assert "Felino (Gato)" in nombres_especies
    assert "Ave" in nombres_especies
    assert "Roedor" in nombres_especies
    assert "Reptil" in nombres_especies
    assert "Exótico" in nombres_especies

    canino = next(e for e in catalog if e["nombre"] == "Canino (Perro)")
    felino = next(e for e in catalog if e["nombre"] == "Felino (Gato)")
    assert len(canino["razas"]) >= 50
    assert len(felino["razas"]) >= 20


@pytest.mark.anyio
async def test_subida_imagen_local_fallback_y_serving(client, test_clinica):
    """Verifica que sin R2 configurado, la imagen se guarde en uploads/ y se sirva estáticamente."""
    from unittest.mock import patch
    import io

    with patch("app.core.storage.get_r2_client", return_value=None):
        fake_png = b"RIFF\x1a\x00\x00\x00WEBPVP8 \x0e\x00\x00\x00"
        resp = client.post(
            "/api/clinic/logo",
            files={"file": ("logo_test.webp", io.BytesIO(fake_png), "image/webp")},
            data={"clinica_id": str(test_clinica.id)}
        )
        assert resp.status_code == 200
        data = resp.json()
        logo_url = data["logo_url"]
        assert logo_url.startswith("/uploads/logos/")

        # Verificar que el servidor estático sirva el archivo correctamente
        resp_img = client.get(logo_url)
        assert resp_img.status_code == 200
        assert resp_img.content == fake_png


def test_registro_veterinario_validacion_sin_500(client):
    """Verifica que un registro con datos inválidos muestre error amigable y nunca 500."""
    # 1. Contraseña demasiado corta (< 4 caracteres)
    resp = client.post("/registro", data={
        "nombre": "Dr. House",
        "nombre_clinica": "Princeton Plainsboro",
        "email": "house@princeton.com",
        "password": "12"
    })
    assert resp.status_code == 200
    assert "Internal Server Error" not in resp.text
    assert "password" in resp.text.lower() or "error" in resp.text.lower() or "caracteres" in resp.text.lower()

    # 2. Email con formato inválido
    resp2 = client.post("/registro", data={
        "nombre": "Dr. Wilson",
        "nombre_clinica": "Oncology Dept",
        "email": "not-an-email",
        "password": "secretpassword"
    })
    assert resp2.status_code == 200
    assert "Internal Server Error" not in resp2.text


def test_google_oauth_redirect_and_callback(client, db_session):
    """Verifica la redirección hacia Google y el callback exitoso que registra al veterinario."""
    from unittest.mock import patch, MagicMock

    with patch("app.auth.routes.settings.GOOGLE_CLIENT_ID", "mock-google-client-id"), \
         patch("app.auth.routes.settings.GOOGLE_CLIENT_SECRET", "mock-secret"):
        # 1. Endpoint de inicio de Google OAuth
        resp_login = client.get("/auth/google/login", follow_redirects=False)
        assert resp_login.status_code in (302, 307)
        assert "accounts.google.com" in resp_login.headers["location"]
        assert "client_id=mock-google-client-id" in resp_login.headers["location"]

        # 2. Callback exitoso con mock de httpx
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {"access_token": "mock_google_access_token"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "email": "vet.google@example.com",
        "sub": "google-user-id-9988",
        "name": "Dra. Google"
    }

    class MockAsyncClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, **kwargs):
            return mock_token_resp
        async def get(self, url, **kwargs):
            return mock_userinfo_resp

    with patch("httpx.AsyncClient", return_value=MockAsyncClient()):
        resp_cb = client.get("/auth/google/callback?code=mock_oauth_code", follow_redirects=False)
        assert resp_cb.status_code == 303
        assert resp_cb.headers["location"] == "/dashboard"
        assert "vet_token" in resp_cb.cookies

        # Comprobar que se creó en base de datos
        from app.clinic.models import Veterinario
        vet = db_session.query(Veterinario).filter(Veterinario.email == "vet.google@example.com").first()
        assert vet is not None
        assert vet.nombre == "Dra. Google"
        assert vet.google_id == "google-user-id-9988"



