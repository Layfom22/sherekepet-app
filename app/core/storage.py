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


def sanitize_filename(filename: str) -> str:
    """Limpia el nombre de archivo para evitar caracteres inseguros."""
    base_name = os.path.basename(filename)
    clean_name = re.sub(r'[^a-zA-Z0-9_\.-]', '_', base_name)
    return clean_name or "image.webp"


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
    Sube un archivo binario a Cloudflare R2 y retorna la URL pública del recurso.
    
    Parámetros:
    - file_bytes: Bytes del archivo de imagen (generalmente WebP comprimido).
    - filename: Nombre original del archivo.
    - folder: Carpeta/Prefijo en el bucket (ej. 'logos', 'mascotas', 'clinicas').
    - content_type: MIME type del archivo (default: 'image/webp').
    
    Retorna:
    - URL pública accesible del recurso.
    """
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
        base_public_url = (settings.R2_PUBLIC_URL or f"https://{settings.R2_BUCKET_NAME}.r2.dev").rstrip('/')
        return f"{base_public_url}/{unique_key}"

    # Fallback para desarrollo / producción sin credenciales de Cloudflare R2 configuradas:
    # Guarda el archivo localmente en la carpeta 'uploads/' y retorna la URL web accesible
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
