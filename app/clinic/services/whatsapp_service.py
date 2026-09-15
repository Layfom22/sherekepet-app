import re
import urllib.parse


def normalizar_telefono_peru(telefono: str) -> str:
    """
    Normaliza un número telefónico de Perú agregando el prefijo 51 si corresponde.
    Elimina caracteres especiales como espacios, guiones y paréntesis.
    Ejemplos:
    - '987654321' -> '51987654321'
    - '+51 987 654 321' -> '51987654321'
    - '51987654321' -> '51987654321'
    """
    # Conservar solo dígitos
    limpio = re.sub(r"\D", "", telefono)

    if not limpio:
        return ""

    # Si ya tiene prefijo 51 y tiene 11 dígitos
    if limpio.startswith("51") and len(limpio) == 11:
        return limpio

    # Si tiene 9 dígitos (formato estándar de celular en Perú)
    if len(limpio) == 9 and limpio.startswith("9"):
        return f"51{limpio}"

    # Si ya tiene más de 9 dígitos sin '51'
    return limpio


def generar_enlace_whatsapp(telefono: str, mensaje: str) -> str:
    """
    Genera un enlace directo a WhatsApp (wa.me) con el número normalizado
    y el texto codificado para URL.
    """
    if not telefono:
        return "#"

    numero = normalizar_telefono_peru(telefono)
    if not numero:
        return "#"

    texto_codificado = urllib.parse.quote(mensaje.strip())
    return f"https://wa.me/{numero}?text={texto_codificado}"
