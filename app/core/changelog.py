"""
Registro de versiones y novedades de SherekePet (In-App Changelog).
Exclusivo para el Panel de Veterinarios.
"""

SHEREKE_VERSION_ACTUAL = "2.4.0"

NOVEDADES_VETERINARIOS = {
    "version": "2.4.0",
    "fecha": "Octubre 2026",
    "titulo": "Confidencialidad Médica, Simulador en Vivo y Código QR para Mostrador",
    "items": [
        {
            "icono": "lock",
            "etiqueta": "Privacidad",
            "color": "slate",
            "titulo": "Confidencialidad Médica en Atenciones",
            "descripcion": (
                "Tus diagnósticos técnicos, sospechas clínicas y notas internas ahora cuentan con reserva médica "
                "100% privada para tu equipo y nunca se exponen al dueño en su carnet digital. Además, puedes ocultar "
                "atenciones o procedimientos completos con el nuevo interruptor de visibilidad."
            )
        },
        {
            "icono": "smartphone",
            "etiqueta": "Novedad",
            "color": "teal",
            "titulo": "Simulador de Carnet en Tiempo Real (Live Preview)",
            "descripcion": (
                "Al registrar una atención médica o vacuna, observa en tiempo real al costado del formulario "
                "una pantalla interactiva que simula exactamente cómo verá el cliente las indicaciones en su celular."
            )
        },
        {
            "icono": "qr-code",
            "etiqueta": "Mostrador",
            "color": "sky",
            "titulo": "Cartel QR Imprimible para Sala de Espera",
            "descripcion": (
                "Desde el módulo de Pacientes, genera e imprime con 1 clic un cartel institucional con código QR "
                "listo para colocar en recepción, permitiendo a los dueños abrir el carnet digital de su mascota "
                "directamente desde su móvil mientras esperan su turno."
            )
        }
    ]
}
