"""
Módulo de almacenamiento para Cloudflare R2 (Compatible con AWS S3 API).
Maneja la subida de imágenes y assets para Clínicas y Mascotas en SherekePet.
"""
import os
import uuid
import re
import anyio
from typing import Optional
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import settings


ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def sanitize_filename(filename: str) -> str:
    """Limpia el nombre de archivo para evitar caracteres inseguros y extensiones ejecutables."""
    base_name = os.path.basename(filename)
    clean_name = re.sub(r'[^a-zA-Z0-9_\.-]', '_', base_name)
    # Bloquear extensiones peligrosas (svg, html, htm, js, xml)
    lower_name = clean_name.lower()
    if lower_name.endswith((".svg", ".html", ".htm", ".js", ".xml", ".xhtml", ".php")):
        clean_name = clean_name.rsplit(".", 1)[0] + ".webp"
    return clean_name or "image.webp"


def validate_safe_image(file_bytes: bytes, content_type: str) -> None:
    """
    Valida que el archivo subido sea una imagen rasterizada segura (PNG, JPEG, WEBP, GIF)
    y rechaza explícitamente SVG, HTML o scripts embebidos (prevención de Stored XSS).
    """
    ct = (content_type or "").strip().lower()
    if ct not in ALLOWED_IMAGE_MIMES:
        raise ValueError("Formato de imagen inválido. Solo se admiten PNG, JPEG, WEBP y GIF (SVG no permitido por seguridad).")

    # Inspección de primeros bytes para bloquear payloads XML/SVG/HTML/Script disfrazados
    head_sample = file_bytes[:512].lower()
    dangerous_markers = (b"<svg", b"<script", b"<!doctype html", b"<html", b"javascript:", b"onload=", b"onerror=")
    if any(marker in head_sample for marker in dangerous_markers):
        raise ValueError("El archivo contiene código activo o etiquetas no permitidas.")


def get_r2_client():
    """Inicializa y retorna un cliente boto3 S3 configurado para Cloudflare R2."""
    if not (settings.R2_ACCOUNT_ID and settings.R2_ACCESS_KEY and settings.R2_SECRET_KEY):
        return None

    endpoint_url = f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.R2_ACCESS_KEY,
        aws_secret_access_key=settings.R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto"
    )


def generar_url_firmada_r2(object_key: str, expiration_seconds: int = 900) -> Optional[str]:
    """
    Genera una URL temporal pre-firmada (S3v4 Presigned URL) para lectura segura de objetos privados en R2.
    """
    s3_client = get_r2_client()
    if not s3_client or not settings.R2_BUCKET_NAME:
        return None
    return s3_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.R2_BUCKET_NAME,
            "Key": object_key.lstrip("/"),
        },
        ExpiresIn=expiration_seconds,
    )


def _sync_put_object(s3_client, bucket: str, key: str, data: bytes, content_type: str):
    """Llamada síncrona a put_object para ser ejecutada en thread pool."""
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType=content_type
    )


async def upload_image_to_r2(
    file_bytes: bytes,
    filename: str,
    folder: str = "clinicas",
    content_type: str = "image/webp"
) -> str:
    """
    Valida y sube un archivo binario de imagen a Cloudflare R2 y retorna su URL.
    """
    validate_safe_image(file_bytes, content_type)
    clean_name = sanitize_filename(filename)
    unique_key = f"{folder.strip('/')}/{uuid.uuid4().hex[:10]}_{clean_name}"

    s3_client = get_r2_client()

    # Si R2 está configurado, subir directamente a Cloudflare R2
    if s3_client and settings.R2_BUCKET_NAME:
        await anyio.to_thread.run_sync(
            _sync_put_object,
            s3_client,
            settings.R2_BUCKET_NAME,
            unique_key,
            file_bytes,
            content_type
        )
        # Si se trata de comprobantes de pago privados y no hay R2_PUBLIC_URL forzada, o si se solicita URL firmada:
        if settings.R2_PUBLIC_URL:
            base_public_url = settings.R2_PUBLIC_URL.rstrip('/')
            return f"{base_public_url}/{unique_key}"
        presigned = generar_url_firmada_r2(unique_key, expiration_seconds=3600)
        if presigned:
            return presigned
        return f"https://{settings.R2_BUCKET_NAME}.r2.dev/{unique_key}"

    # Fallback local: Guarda el archivo en la carpeta 'uploads/'
    clean_folder = folder.strip('/')
    upload_dir = os.path.join("uploads", clean_folder)
    os.makedirs(upload_dir, exist_ok=True)

    file_name_with_uuid = f"{uuid.uuid4().hex[:10]}_{clean_name}"
    local_file_path = os.path.join(upload_dir, file_name_with_uuid)

    def _write_local():
        with open(local_file_path, "wb") as f:
            f.write(file_bytes)

    await anyio.to_thread.run_sync(_write_local)
    return f"/uploads/{clean_folder}/{file_name_with_uuid}"

