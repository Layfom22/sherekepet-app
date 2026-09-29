from app.clinic.models import Veterinario


def test_registro_vista_tiene_repetir_contrasena_y_botones_ojo(client):
    """Verifica que la vista GET /registro contenga el campo repetir contraseña y los botones para ver contraseña."""
    resp = client.get("/registro")
    assert resp.status_code == 200
    html = resp.text

    assert 'id="password"' in html
    assert 'id="password_confirm"' in html
    assert 'minlength="8"' in html
    assert 'togglePasswordVisibility' in html
    assert 'data-lucide="eye"' in html
    assert 'Repetir Contraseña' in html
    assert 'passwordMismatchMsg' in html


def test_registro_falla_si_contrasenas_no_coinciden(client):
    """Verifica que si las contraseñas no coinciden se devuelva mensaje de error y no se cree la cuenta."""
    payload = {
        "nombre": "Dr. Fernando",
        "nombre_clinica": "Clínica San Fernando",
        "email": "fernando@sanfernando.com",
        "password": "Password123",
        "password_confirm": "PasswordDiferente456",
        "acepta_terminos": "on"
    }
    resp = client.post("/registro", data=payload)
    assert resp.status_code == 200
    assert "Las contraseñas no coinciden" in resp.text


def test_registro_exitoso_con_contrasenas_coincidentes(client, db_session):
    """Verifica que con contraseñas coincidentes de 8+ caracteres el registro sea exitoso y redirija a /verificar."""
    payload = {
        "nombre": "Dra. Claudia",
        "nombre_clinica": "Clínica PetCare",
        "email": "claudia@petcare.com",
        "password": "MiClaveSegura2026",
        "password_confirm": "MiClaveSegura2026",
        "acepta_terminos": "on"
    }
    resp = client.post("/registro", data=payload, follow_redirects=False)
    assert resp.status_code == 303
    assert "/verificar" in resp.headers["location"]

    vet = db_session.query(Veterinario).filter(Veterinario.email == "claudia@petcare.com").first()
    assert vet is not None
    assert vet.is_verified is False
