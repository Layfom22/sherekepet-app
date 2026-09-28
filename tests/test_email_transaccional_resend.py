import pytest
from datetime import date, time
from unittest.mock import patch, MagicMock
from app.core.config import settings
from app.core.models import Clinica
from app.core.security import create_access_token
from app.clinic.models import Veterinario, Cliente, Mascota, Cita
from app.services.email_service import enviar_alerta_paciente


def test_config_resend_api_key_inicializado():
    """Verifica que la configuración incluya RESEND_API_KEY y esté configurado en el SDK de resend."""
    import resend
    assert hasattr(settings, "RESEND_API_KEY")
    # Al inicializar con settings.RESEND_API_KEY
    assert resend.api_key is not None or resend.api_key == ""


def test_enviar_alerta_paciente_marca_blanca_y_resend(db_session):
    import asyncio
    """
    Verifica que el servicio de email:
    1. Consulta la Cita, Mascota y Clínica correspondiente.
    2. Configura el remitente dinámico (Marca Blanca): f"{clinica.nombre_comercial} <soporte@sherekepet.com>".
    3. Construye y envía el payload a resend.Emails.send() con subject, from, to y html.
    4. El HTML contiene logo, nombre de mascota, fecha, motivo y footer institucional exigido.
    """
    # 1. Crear clínica con nombre comercial y logo
    clinica = Clinica(
        nombre="Clínica Veterinaria Central",
        nombre_comercial="VetCare Especialistas",
        logo_url="https://sherekepet.com/logos/vetcare.png",
        telefono="987654321",
        zona_horaria="America/Lima",
        plan_activo="solo"
    )
    db_session.add(clinica)
    db_session.flush()

    cliente = Cliente(
        clinica_id=clinica.id,
        nombre_completo="Valeria Mendoza",
        dni="45678912",
        email="valeria.mendoza@example.com"
    )
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        nombre="Princesa",
        sexo="Hembra"
    )
    db_session.add(mascota)
    db_session.flush()

    cita = Cita(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        mascota_id=mascota.id,
        fecha=date(2026, 11, 20),
        hora=time(16, 45),
        motivo="Control posoperatorio y retiro de puntos",
        estado="Confirmada"
    )
    db_session.add(cita)
    db_session.commit()
    db_session.refresh(cita)

    # 2. Mockear resend.Emails.send y SessionLocal para usar db_session en el test
    with patch("app.services.email_service.SessionLocal", return_value=db_session), \
         patch("resend.Emails.send") as mock_resend_send:
        mock_resend_send.return_value = {"id": "re_mock_123456789"}

        # 3. Invocar enviar_alerta_paciente sincrónicamente con asyncio.run
        res = asyncio.run(enviar_alerta_paciente(
            cita_id=cita.id,
            destinatario_email="valeria.mendoza@example.com"
        ))

        assert res == {"id": "re_mock_123456789"}
        mock_resend_send.assert_called_once()

        call_args = mock_resend_send.call_args[0][0]
        assert isinstance(call_args, dict)

        # Validar remitente con Marca Blanca
        assert call_args["from"] == "VetCare Especialistas <soporte@sherekepet.com>"
        assert call_args["to"] == ["valeria.mendoza@example.com"]
        assert "Princesa" in call_args["subject"]
        assert "VetCare Especialistas" in call_args["subject"]

        # Validar HTML y footer obligatorio
        html = call_args["html"]
        assert "https://sherekepet.com/logos/vetcare.png" in html
        assert "Princesa" in html
        assert "Control posoperatorio y retiro de puntos" in html
        assert "2026-11-20" in html
        assert "16:45" in html
        assert "Este recordatorio médico fue enviado a través de SherekePet, la plataforma tecnológica de VetCare Especialistas. Por favor, no respondas a este correo." in html


def test_endpoint_confirmar_cita_dispara_background_task(client, db_session):
    """
    Verifica que al confirmar una cita mediante PUT /api/citas/{id}/confirmar:
    1. La respuesta HTTP es 200 instantánea.
    2. Se agenda y ejecuta enviar_alerta_paciente como BackgroundTask.
    """
    clinica = Clinica(
        nombre="San Borja Pet",
        nombre_comercial="Clínica San Borja Pet",
        logo_url="https://sherekepet.com/logos/sbpet.png",
        zona_horaria="America/Lima",
        plan_activo="solo"
    )
    db_session.add(clinica)
    db_session.flush()

    vet = Veterinario(
        clinica_id=clinica.id,
        nombre="Dr. Perez",
        email="dr.perez@sbpet.com",
        username="dr_perez",
        password_hash="hash",
        rol="VET",
        is_verified=True
    )
    db_session.add(vet)

    cliente = Cliente(
        clinica_id=clinica.id,
        nombre_completo="Lorena Salas",
        dni="70809010",
        email="lorena.salas@example.com"
    )
    db_session.add(cliente)
    db_session.flush()

    mascota = Mascota(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        nombre="Rocky",
        sexo="Macho"
    )
    db_session.add(mascota)
    db_session.flush()

    cita = Cita(
        clinica_id=clinica.id,
        cliente_id=cliente.id,
        mascota_id=mascota.id,
        fecha=date(2026, 12, 1),
        hora=time(11, 0),
        motivo="Vacunación Anual",
        estado="PENDIENTE"
    )
    db_session.add(cita)
    db_session.commit()
    db_session.refresh(cita)

    # Autenticar como veterinario
    vet_token = create_access_token({
        "sub": str(vet.id),
        "clinica_id": clinica.id,
        "role": "vet",
        "rol": "VET",
        "email": vet.email
    })
    client.cookies.set("vet_token", vet_token)

    # Mockear enviar_alerta_paciente para verificar que BackgroundTasks lo ejecuta
    with patch("app.clinic.routes.enviar_alerta_paciente") as mock_alerta:
        # 1. Enviar confirmación con destinatario_email explícito en payload
        resp = client.put(
            f"/api/citas/{cita.id}/confirmar",
            json={
                "estado": "Confirmada",
                "destinatario_email": "lorena.salas@example.com"
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "Confirmada"
        assert data["id"] == cita.id

        # Verificar que la tarea en segundo plano fue llamada
        mock_alerta.assert_called_once_with(cita.id, "lorena.salas@example.com")

    # 2. Probar que si no viene en payload, se resuelve automáticamente desde cliente.email
    with patch("app.clinic.routes.enviar_alerta_paciente") as mock_alerta_auto:
        resp2 = client.put(
            f"/api/clinic/citas/{cita.id}/confirmar",
            json={"estado": "Confirmada"}
        )
        assert resp2.status_code == 200
        mock_alerta_auto.assert_called_once_with(cita.id, "lorena.salas@example.com")
