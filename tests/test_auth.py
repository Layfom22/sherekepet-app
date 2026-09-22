from app.clinic.models import Cliente, Veterinario
from app.core.security import decode_access_token, hash_pin


def test_vet_login_auto_register_and_jwt(client, test_clinica):
    """Test login/registro de veterinario retornando JWT con claims correctos."""
    payload = {
        "email": "doctor@veterinaria.com",
        "google_id": "google_oauth_123456",
        "clinica_id": test_clinica.id
    }
    response = client.post("/api/auth/vet/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["veterinario"]["email"] == "doctor@veterinaria.com"
    assert data["veterinario"]["clinica_id"] == test_clinica.id

    # Validar decodificación de JWT
    token_claims = decode_access_token(data["access_token"])
    assert token_claims is not None
    assert token_claims["role"] == "vet"
    assert token_claims["clinica_id"] == test_clinica.id
    assert token_claims["email"] == "doctor@veterinaria.com"


def test_vet_login_unregistered_without_clinic(client):
    """Veterinario no registrado sin especificar clínica retorna 404."""
    payload = {
        "email": "desconocido@veterinaria.com"
    }
    response = client.post("/api/auth/vet/login", json=payload)
    assert response.status_code == 404


def test_client_first_login_flow(client, db_session, test_clinica):
    """
    Flujo de cliente en primer ingreso:
    1. pin_hash es NULL: Se detecta primer ingreso y se exige crear PIN.
    2. Validación estricta: PIN debe ser de 4 dígitos numéricos.
    3. Se proporciona nuevo_pin de 4 dígitos: Se guarda el hash y se retorna JWT.
    """
    # 1. Crear cliente sin PIN configurado
    cliente = Cliente(
        clinica_id=test_clinica.id,
        dni="45678901",
        pin_hash=None,
        telefono="999888777"
    )
    db_session.add(cliente)
    db_session.commit()

    # Intento de login sin enviar PIN
    resp_init = client.post("/api/auth/client/login", json={
        "clinica_id": test_clinica.id,
        "dni": "45678901"
    })
    assert resp_init.status_code == 200
    data_init = resp_init.json()
    assert data_init["requires_pin_setup"] is True
    assert data_init["access_token"] is None
    assert "Es obligatorio crear un PIN" in data_init["message"]

    # Intento de establecer un PIN inválido (menos de 4 dígitos o no numérico)
    resp_invalid_len = client.post("/api/auth/client/login", json={
        "clinica_id": test_clinica.id,
        "dni": "45678901",
        "nuevo_pin": "12"
    })
    assert resp_invalid_len.status_code == 422

    resp_invalid_chars = client.post("/api/auth/client/login", json={
        "clinica_id": test_clinica.id,
        "dni": "45678901",
        "nuevo_pin": "12ab"
    })
    assert resp_invalid_chars.status_code == 422

    # Configuración exitosa del PIN de 4 dígitos
    resp_setup = client.post("/api/auth/client/login", json={
        "clinica_id": test_clinica.id,
        "dni": "45678901",
        "nuevo_pin": "5432"
    })
    assert resp_setup.status_code == 200
    data_setup = resp_setup.json()
    assert data_setup["requires_pin_setup"] is False
    assert data_setup["access_token"] is not None
    assert "PIN creado con éxito" in data_setup["message"]

    # Verificar que el hash se almacenó en la base de datos
    db_session.refresh(cliente)
    assert cliente.pin_hash is not None


def test_client_subsequent_login_flow(client, db_session, test_clinica):
    """
    Flujo de cliente con PIN ya configurado:
    1. Si no envía PIN, retorna 400.
    2. Si envía PIN incorrecto, retorna 401.
    3. Si envía DNI + PIN correcto, retorna JWT.
    """
    # Crear cliente con PIN "9876" ya hasheado
    cliente = Cliente(
        clinica_id=test_clinica.id,
        dni="87654321",
        pin_hash=hash_pin("9876"),
        telefono="911222333"
    )
    db_session.add(cliente)
    db_session.commit()

    # 1. Intento sin PIN
    resp_no_pin = client.post("/api/auth/client/login", json={
        "clinica_id": test_clinica.id,
        "dni": "87654321"
    })
    assert resp_no_pin.status_code == 400
    assert "Debe ingresar su PIN" in resp_no_pin.json()["detail"]

    # 2. Intento con PIN incorrecto
    resp_wrong_pin = client.post("/api/auth/client/login", json={
        "clinica_id": test_clinica.id,
        "dni": "87654321",
        "pin": "1111"
    })
    assert resp_wrong_pin.status_code == 401
    assert "PIN incorrecto" in resp_wrong_pin.json()["detail"]

    # 3. Intento con PIN correcto
    resp_ok = client.post("/api/auth/client/login", json={
        "clinica_id": test_clinica.id,
        "dni": "87654321",
        "pin": "9876"
    })
    assert resp_ok.status_code == 200
    data_ok = resp_ok.json()
    assert data_ok["access_token"] is not None

    # Validar claims del JWT emitido para el cliente
    claims = decode_access_token(data_ok["access_token"])
    assert claims["role"] == "client"
    assert claims["clinica_id"] == test_clinica.id
    assert claims["dni"] == "87654321"


def test_client_not_found(client, test_clinica):
    """Intento de login con DNI inexistente retorna 404."""
    resp = client.post("/api/auth/client/login", json={
        "clinica_id": test_clinica.id,
        "dni": "00000000",
        "pin": "1234"
    })
    assert resp.status_code == 404


def test_usuario_nuevo_o_sin_sesion_redirige_a_login(client):
    """
    Verifica que si un usuario ingresa por primera vez o sin sesión activa:
    - La ruta raíz (/) redirige a /login (303).
    - El dashboard (/dashboard) redirige a /login (303).
    - Las vistas de clínica (/pacientes, /configuracion, /agenda) redirigen a /login (303).
    """
    client.cookies.clear()

    resp_root = client.get("/", follow_redirects=False)
    assert resp_root.status_code == 303
    assert resp_root.headers["location"] == "/login"

    resp_dash = client.get("/dashboard", follow_redirects=False)
    assert resp_dash.status_code == 303
    assert resp_dash.headers["location"] == "/login"

    resp_cfg = client.get("/configuracion", follow_redirects=False)
    assert resp_cfg.status_code == 303
    assert resp_cfg.headers["location"] == "/login"

    resp_agenda = client.get("/agenda", follow_redirects=False)
    assert resp_agenda.status_code == 303
    assert resp_agenda.headers["location"] == "/login"

    resp_pacientes = client.get("/pacientes", follow_redirects=False)
    assert resp_pacientes.status_code == 303
    assert resp_pacientes.headers["location"] == "/login"
