import logging
from typing import Any, Dict
from fastapi import HTTPException, status
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RENIEC_API_URL = "https://api.apis.net.pe/v2/reniec/dni"


async def consultar_dni_reniec(dni: str) -> Dict[str, str]:
    """
    Consulta asíncrona de datos de DNI a apis.net.pe con Bearer token.
    Retorna un diccionario normalizado con:
    - nombres
    - apellido_paterno
    - apellido_materno
    - nombre_completo
    """
    dni = dni.strip()
    if not dni.isdigit() or len(dni) != 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El DNI debe tener exactamente 8 dígitos numéricos."
        )

    headers = {
        "Authorization": f"Bearer {settings.APIS_NET_PE_TOKEN}",
        "Accept": "application/json",
        "Referer": "https://apis.net.pe"
    }
    params = {"numero": dni}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(RENIEC_API_URL, params=params, headers=headers)

            if response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="El DNI no fue encontrado en los registros de RENIEC."
                )

            if response.status_code in (401, 403):
                logger.error(f"Error de autorización con apis.net.pe: {response.status_code}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="No se pudo autenticar con el servicio de consulta RENIEC."
                )

            if response.status_code != 200:
                logger.error(f"Error de API RENIEC {response.status_code}: {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Error al comunicarse con el servicio de RENIEC."
                )

            data: Dict[str, Any] = response.json()

            nombres = data.get("nombres") or data.get("nombre") or ""
            apellido_paterno = data.get("apellidoPaterno") or data.get("apellido_paterno") or ""
            apellido_materno = data.get("apellidoMaterno") or data.get("apellido_materno") or ""

            partes = [p.strip() for p in (nombres, apellido_paterno, apellido_materno) if p.strip()]
            nombre_completo = " ".join(partes)

            return {
                "dni": dni,
                "nombres": nombres.strip(),
                "apellido_paterno": apellido_paterno.strip(),
                "apellido_materno": apellido_materno.strip(),
                "nombre_completo": nombre_completo
            }

    except httpx.TimeoutException:
        logger.error(f"Timeout al consultar DNI {dni} en RENIEC.")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Tiempo de espera agotado al consultar el DNI en RENIEC."
        )
    except httpx.RequestError as exc:
        logger.error(f"Error de red al consultar RENIEC: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Error de conexión con el servicio externo de RENIEC."
        )
