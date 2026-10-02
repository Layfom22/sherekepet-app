"""
Script y función de inicialización para asignar el rol SUPER_ADMIN
al usuario principal de la plataforma (roggerjjj@gmail.com).
"""
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.clinic.models import Veterinario

SUPERADMIN_DEFAULT_EMAIL = "roggerjjj@gmail.com"


def seed_superadmin(db: Session, email: str = SUPERADMIN_DEFAULT_EMAIL) -> Optional[Veterinario]:
    """
    Busca al usuario con email `roggerjjj@gmail.com` y le asigna el rol `SUPER_ADMIN`
    e `is_superadmin = True` de forma idempotente.
    """
    clean_email = (email or SUPERADMIN_DEFAULT_EMAIL).strip().lower()
    usuario = db.query(Veterinario).filter(
        func.lower(Veterinario.email) == clean_email,
        Veterinario.is_deleted == False
    ).first()

    if usuario:
        hubo_cambio = False
        if usuario.rol != "SUPER_ADMIN":
            usuario.rol = "SUPER_ADMIN"
            hubo_cambio = True
        if not getattr(usuario, "is_superadmin", False):
            usuario.is_superadmin = True
            hubo_cambio = True
        if hubo_cambio:
            db.commit()
            db.refresh(usuario)
            print(f"[OK] Usuario '{clean_email}' inicializado con rol SUPER_ADMIN (is_superadmin=True).")
    return usuario


if __name__ == "__main__":
    from app.database import SessionLocal, init_db
    init_db()
    session = SessionLocal()
    try:
        user = seed_superadmin(session)
        if user:
            print(f"SuperAdmin activo: ID={user.id} | Email={user.email} | Rol={user.rol} | is_superadmin={user.is_superadmin}")
        else:
            print(f"Aviso: El usuario {SUPERADMIN_DEFAULT_EMAIL} aún no se encuentra registrado en la base de datos local. Se asignará SUPER_ADMIN automáticamente al iniciar sesión o registrarse.")
    finally:
        session.close()
