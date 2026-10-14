from datetime import timedelta
from app.core.models import Clinica
from app.clinic.models import Veterinario
from app.core.security import create_access_token
from app.core.timezone import get_lima_now
from seed_superadmin import seed_superadmin


def test_seed_superadmin_rogger(db_session, test_clinica):
    """Verifica que seed_superadmin asigne rol SUPER_ADMIN e is_superadmin=True a roggerjjj@gmail.com."""
    vet = Veterinario(
        clinica_id=test_clinica.id,
        email="roggerjjj@gmail.com",
        nombre="Roger C.",
        password_hash="hash_test",
        rol="ADMIN",
        is_active=True,
        is_verified=True
    )
    db_session.add(vet)
    db_session.commit()
    db_session.refresh(vet)

    assert vet.rol == "ADMIN"
    assert vet.is_superadmin is False

    actualizado = seed_superadmin(db_session)
    assert actualizado is not None
    assert actualizado.id == vet.id
    assert actualizado.rol == "SUPER_ADMIN"
    assert actualizado.is_superadmin is True


def test_require_superadmin_bloquea_no_autorizados(client, db_session, test_clinica):
    """Verifica que usuarios sin sesión o con rol ADMIN/ASISTENTE reciban 403 en endpoints /admin."""
    # 1. Sin autenticación
    resp_anon = client.get("/admin/clinicas")
    assert resp_anon.status_code == 403
    assert resp_anon.json()["detail"] == "Acceso denegado. Privilegios insuficientes."

    # 2. Usuario con rol ADMIN normal
    vet_normal = Veterinario(
        clinica_id=test_clinica.id,
        email="normal@vet.pe",
        nombre="Dr. Normal",
        password_hash="hash_test",
        rol="ADMIN",
        is_superadmin=False,
        is_active=True,
        is_verified=True
    )
    db_session.add(vet_normal)
    db_session.commit()
    db_session.refresh(vet_normal)

    token_normal = create_access_token({
        "sub": str(vet_normal.id),
        "clinica_id": test_clinica.id,
        "role": "vet",
        "rol": "ADMIN",
        "is_verified": True
    })
    client.cookies.set("vet_token", token_normal)

    for url, method in [
        ("/admin", "GET"),
        ("/admin/clinicas", "GET"),
        (f"/admin/clinicas/{test_clinica.id}/ajustar-dias", "POST"),
        (f"/admin/usuarios/{vet_normal.id}/promover", "POST"),
    ]:
        if method == "GET":
            resp = client.get(url)
        else:
            resp = client.post(url, json={"dias_a_sumar": 5})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Acceso denegado. Privilegios insuficientes."


def test_endpoints_admin_clinicas_ajustar_dias_y_promover(client, db_session):
    """
    Verifica el flujo completo del SuperAdmin:
    - GET /admin/clinicas
    - POST /admin/clinicas/{id}/ajustar-dias (positivo y negativo)
    - POST /admin/usuarios/{id}/promover
    - GET /admin (vista admin_dashboard.html)
    - Preservación de permisos veterinarios para roggerjjj@gmail.com
    """
    ahora = get_lima_now()

    # Clínica 1 (Titular SuperAdmin: Roger C.)
    clinica_roger = Clinica(
        nombre="Clínica Central Roger",
        telefono="999888777",
        estado_suscripcion="ACTIVE",
        plan_activo="emprendedor"
    )
    # Clínica 2 (En Trial)
    clinica_trial = Clinica(
        nombre="Veterinaria Los Olivos",
        telefono="988111222",
        estado_suscripcion="TRIAL",
        trial_ends_at=ahora + timedelta(days=10)
    )
    db_session.add_all([clinica_roger, clinica_trial])
    db_session.flush()

    vet_roger = Veterinario(
        clinica_id=clinica_roger.id,
        email="roggerjjj@gmail.com",
        nombre="Roger C.",
        password_hash="hash_roger",
        rol="ADMIN",
        is_active=True,
        is_verified=True
    )
    vet_olivos = Veterinario(
        clinica_id=clinica_trial.id,
        email="olivos@vet.pe",
        nombre="Dra. María",
        password_hash="hash_maria",
        rol="ADMIN",
        is_active=True,
        is_verified=True
    )
    db_session.add_all([vet_roger, vet_olivos])
    db_session.commit()

    # Ejecutar semilla para roggerjjj@gmail.com
    seed_superadmin(db_session)
    db_session.refresh(vet_roger)
    assert vet_roger.rol == "SUPER_ADMIN"
    assert vet_roger.is_superadmin is True

    token_roger = create_access_token({
        "sub": str(vet_roger.id),
        "clinica_id": clinica_roger.id,
        "role": "vet",
        "rol": vet_roger.rol,
        "is_superadmin": True,
        "is_verified": True
    })
    client.cookies.set("vet_token", token_roger)

    # 1. GET /admin/clinicas
    resp_list = client.get("/admin/clinicas")
    assert resp_list.status_code == 200
    data_list = resp_list.json()
    assert len(data_list) == 2

    item_trial = next(c for c in data_list if c["id"] == clinica_trial.id)
    assert item_trial["estado_suscripcion"] == "TRIAL"
    assert item_trial["contacto_email"] == "olivos@vet.pe"
    assert 9 <= item_trial["dias_restantes"] <= 11

    # 2. POST /admin/clinicas/{id}/ajustar-dias (sumar +15 días)
    resp_sumar = client.post(
        f"/admin/clinicas/{clinica_trial.id}/ajustar-dias",
        json={"dias_a_sumar": 15}
    )
    assert resp_sumar.status_code == 200
    assert resp_sumar.json()["dias_restantes"] >= 24
    assert resp_sumar.json()["estado_suscripcion"] == "TRIAL"

    # 3. POST /admin/clinicas/{id}/ajustar-dias (restar -40 días -> EXPIRED)
    resp_restar = client.post(
        f"/admin/clinicas/{clinica_trial.id}/ajustar-dias",
        json={"dias_a_sumar": -40}
    )
    assert resp_restar.status_code == 200
    assert resp_restar.json()["dias_restantes"] == 0
    assert resp_restar.json()["estado_suscripcion"] == "EXPIRED"

    # 4. POST /admin/usuarios/{id}/promover
    resp_prom = client.post(f"/admin/usuarios/{vet_olivos.id}/promover")
    assert resp_prom.status_code == 200
    assert resp_prom.json()["usuario"]["rol"] == "SUPER_ADMIN"
    assert resp_prom.json()["usuario"]["is_superadmin"] is True

    db_session.refresh(vet_olivos)
    assert vet_olivos.rol == "SUPER_ADMIN"
    assert vet_olivos.is_superadmin is True

    # 5. Vista HTML /admin (admin_dashboard.html)
    resp_html = client.get("/admin")
    assert resp_html.status_code == 200
    assert "Panel SuperAdmin" in resp_html.text
    assert "Ajustar Días" in resp_html.text
    assert "Veterinaria Los Olivos" in resp_html.text

    # 6. Verificar que Roger C. conserva todas sus vistas y funciones como Veterinario
    for ruta_vet in ["/dashboard", "/pacientes", "/agenda", "/configuracion"]:
        resp_v = client.get(ruta_vet)
        assert resp_v.status_code == 200


def test_admin_buscar_clientes_y_reset_pin(client, db_session, test_clinica):
    """
    Verifica que el SuperAdmin pueda:
    1. Buscar propietarios por DNI o nombre de mascota a nivel global.
    2. Detectar si el PIN está configurado o si está bloqueado por intentos fallidos.
    3. Restablecer el PIN (pin_hash=None) y desbloquear el DNI en el rate_limiter.
    4. Garantizar que usuarios sin rol SUPER_ADMIN reciban 403.
    """
    from app.clinic.models import Cliente, Mascota
    from app.core.rate_limit import rate_limiter
    from app.core.security import hash_pin

    # 1. Crear SuperAdmin y Cliente con Mascota
    vet_super = Veterinario(
        clinica_id=test_clinica.id,
        email="superadmin_pin@vet.pe",
        nombre="Super Admin PIN",
        password_hash="hash_test",
        rol="SUPER_ADMIN",
        is_superadmin=True,
        is_active=True,
        is_verified=True
    )
    db_session.add(vet_super)
    db_session.flush()

    cliente = Cliente(
        clinica_id=test_clinica.id,
        dni="76543210",
        nombre_completo="Carlos Dueño Prueba",
        nombres="Carlos",
        apellido_paterno="Dueño",
        telefono="987654321",
        email="carlos@gmail.com",
        pin_hash=hash_pin("1234")
    )
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(
        clinica_id=test_clinica.id,
        cliente_id=cliente.id,
        nombre="Rocky",
        especie="Canino",
        raza="Golden Retriever"
    )
    db_session.add(mascota)
    db_session.commit()

    token_super = create_access_token({
        "sub": str(vet_super.id),
        "clinica_id": test_clinica.id,
        "role": "vet",
        "rol": "SUPER_ADMIN",
        "is_superadmin": True,
        "is_verified": True
    })
    client.cookies.set("vet_token", token_super)

    # 2. Búsqueda por DNI
    resp_busqueda_dni = client.get("/admin/clientes/buscar?q=76543210")
    assert resp_busqueda_dni.status_code == 200
    resultados = resp_busqueda_dni.json()
    assert len(resultados) == 1
    assert resultados[0]["dni"] == "76543210"
    assert resultados[0]["nombre_completo"] == "Carlos Dueño Prueba"
    assert resultados[0]["tiene_pin"] is True
    assert resultados[0]["esta_bloqueado"] is False
    assert len(resultados[0]["mascotas"]) == 1
    assert resultados[0]["mascotas"][0]["nombre"] == "Rocky"

    # 3. Búsqueda por nombre de Mascota
    resp_busqueda_mascota = client.get("/admin/clientes/buscar?q=Rocky")
    assert resp_busqueda_mascota.status_code == 200
    res_m = resp_busqueda_mascota.json()
    assert len(res_m) >= 1
    assert any(c["dni"] == "76543210" for c in res_m)

    # 4. Simular 5 intentos fallidos para bloquear al cliente
    for _ in range(5):
        try:
            rate_limiter.record_pin_failure("76543210")
        except Exception:
            pass

    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        rate_limiter.check_pin_lockout("76543210")
    assert exc_info.value.status_code == 429

    # Verificar que el buscador reporte `esta_bloqueado = True`
    resp_bloqueado = client.get("/admin/clientes/buscar?q=76543210")
    assert resp_bloqueado.status_code == 200
    assert resp_bloqueado.json()[0]["esta_bloqueado"] is True
    assert resp_bloqueado.json()[0]["segundos_bloqueo_restantes"] > 0

    # 5. Restablecer PIN mediante POST /admin/clientes/{dni}/reset-pin
    resp_reset = client.post("/admin/clientes/76543210/reset-pin")
    assert resp_reset.status_code == 200
    data_reset = resp_reset.json()
    assert data_reset["status"] == "ok"
    assert data_reset["dni"] == "76543210"
    assert data_reset["tiene_pin"] is False
    assert data_reset["esta_bloqueado"] is False

    # Verificar en Base de Datos que pin_hash quedó en None
    db_session.refresh(cliente)
    assert cliente.pin_hash is None

    # Verificar que el bloqueo en Rate Limiter fue eliminado (no lanza excepción)
    rate_limiter.check_pin_lockout("76543210")

    # 6. Intentar reset con usuario sin privilegios SuperAdmin
    token_no_super = create_access_token({
        "sub": "999",
        "clinica_id": test_clinica.id,
        "role": "vet",
        "rol": "VET",
        "is_superadmin": False,
        "is_verified": True
    })
    client.cookies.set("vet_token", token_no_super)

    resp_denegado_get = client.get("/admin/clientes/buscar?q=76543210")
    assert resp_denegado_get.status_code == 403

    resp_denegado_post = client.post("/admin/clientes/76543210/reset-pin")
    assert resp_denegado_post.status_code == 403

