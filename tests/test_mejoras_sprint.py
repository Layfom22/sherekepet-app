import io
import json
import pytest
from app.core.models import Clinica
from app.core.security import create_access_token
from app.clinic.models import Especie, Raza, Mascota, Cliente, RegistroVacuna


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
    """Verifica la subida y conversión de logo a Base64 data URI."""
    # Archivo PNG simulado válido
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    files = {"file": ("logo.png", io.BytesIO(fake_png), "image/png")}
    data = {"clinica_id": str(test_clinica.id)}

    resp = client.post("/api/clinic/logo", files=files, data=data)
    assert resp.status_code == 200
    res_json = resp.json()
    assert "data:image/png;base64," in res_json["logo_b64"]

    # Verificar en BD
    db_session.refresh(test_clinica)
    assert test_clinica.logo_b64 == res_json["logo_b64"]

    # Rechazo de formato no admitido
    files_invalid = {"file": ("test.txt", io.BytesIO(b"texto plano"), "text/plain")}
    resp_invalid = client.post("/api/clinic/logo", files=files_invalid, data=data)
    assert resp_invalid.status_code == 400


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
