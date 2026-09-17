from typing import Tuple
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.models import Clinica
from app.clinic.models import Veterinario, Cliente
from app.core.security import hash_pin, verify_pin, hash_password, verify_password, create_access_token
from app.core.timezone import get_lima_now
from app.auth.schemas import (
    VetLoginRequest,
    VetLoginResponse,
    VetRegisterRequest,
    VetInfo,
    ClientLoginRequest,
    ClientLoginResponse,
    ClientInfo,
)


class AuthService:
    @staticmethod
    def register_veterinario(db: Session, request: VetRegisterRequest) -> VetLoginResponse:
        """
        Registra una nueva clínica y su veterinario titular con correo y contraseña.
        Asigna el rol 'ADMIN' y genera un código OTP de verificación de 6 dígitos.
        """
        import random
        from datetime import timedelta
        from app.core.email import send_otp_email

        email_clean = request.email.strip().lower()

        # Verificar si el correo ya existe
        existente = db.query(Veterinario).filter(
            Veterinario.email == email_clean,
            Veterinario.is_deleted == False
        ).first()
        if existente:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ya existe una cuenta registrada con este correo electrónico."
            )

        # 1. Aislamiento Multi-tenant Estricto: Siempre crear nueva Clínica
        clinica = Clinica(
            nombre=request.nombre_clinica.strip(),
            zona_horaria="America/Lima",
            plan_activo="solo"
        )
        db.add(clinica)
        db.flush()

        # Generar código OTP de 6 dígitos válido por 15 minutos
        otp_code = f"{random.randint(100000, 999999)}"
        otp_expires_at = get_lima_now() + timedelta(minutes=15)

        # 2. Crear Veterinario con rol ADMIN y pendiente de verificación
        vet = Veterinario(
            clinica_id=clinica.id,
            email=email_clean,
            nombre=request.nombre.strip(),
            password_hash=hash_password(request.password),
            rol="ADMIN",
            is_active=True,
            is_verified=False,
            otp_code=otp_code,
            otp_expires_at=otp_expires_at
        )
        db.add(vet)
        db.commit()
        db.refresh(vet)

        # Enviar correo con código OTP
        send_otp_email(destinatario=vet.email, otp_code=otp_code, nombre=vet.nombre)

        token_payload = {
            "sub": str(vet.id),
            "clinica_id": vet.clinica_id,
            "role": "vet",
            "rol": vet.rol,
            "email": vet.email,
            "username": vet.username,
            "nombre": vet.nombre,
            "is_verified": False
        }
        token = create_access_token(data=token_payload)

        return VetLoginResponse(
            access_token=token,
            token_type="bearer",
            veterinario=VetInfo.model_validate(vet)
        )

    @staticmethod
    def verificar_otp(db: Session, email: str, otp_code: str) -> VetLoginResponse:
        """
        Verifica el código OTP de 6 dígitos y activa la cuenta del veterinario (is_verified=True).
        """
        email_clean = email.strip().lower()
        vet = db.query(Veterinario).filter(
            Veterinario.email == email_clean,
            Veterinario.is_deleted == False
        ).first()

        if not vet:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró ninguna cuenta asociada a este correo electrónico."
            )

        if vet.is_verified:
            # Si ya está verificada, generar token y retornar
            token_payload = {
                "sub": str(vet.id),
                "clinica_id": vet.clinica_id,
                "role": "vet",
                "rol": vet.rol,
                "email": vet.email,
                "username": vet.username,
                "nombre": vet.nombre,
                "is_verified": True
            }
            token = create_access_token(data=token_payload)
            return VetLoginResponse(access_token=token, token_type="bearer", veterinario=VetInfo.model_validate(vet))

        if not vet.otp_code or vet.otp_code.strip() != otp_code.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El código de verificación ingresado es incorrecto."
            )

        if vet.otp_expires_at:
            now = get_lima_now()
            now_naive = now.replace(tzinfo=None)
            ha_expirado = (vet.otp_expires_at < now) if vet.otp_expires_at.tzinfo else (vet.otp_expires_at < now_naive)
            if ha_expirado:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El código de verificación ha expirado. Por favor solicita uno nuevo."
                )

        # Activar cuenta
        vet.is_verified = True
        vet.otp_code = None
        vet.otp_expires_at = None
        db.commit()
        db.refresh(vet)

        token_payload = {
            "sub": str(vet.id),
            "clinica_id": vet.clinica_id,
            "role": "vet",
            "rol": vet.rol,
            "email": vet.email,
            "username": vet.username,
            "nombre": vet.nombre,
            "is_verified": True
        }
        token = create_access_token(data=token_payload)

        return VetLoginResponse(
            access_token=token,
            token_type="bearer",
            veterinario=VetInfo.model_validate(vet)
        )

    @staticmethod
    def reenviar_otp(db: Session, email: str) -> dict:
        """
        Genera y reenvía un nuevo código OTP al correo electrónico registrado.
        """
        import random
        from datetime import timedelta
        from app.core.email import send_otp_email

        email_clean = email.strip().lower()
        vet = db.query(Veterinario).filter(
            Veterinario.email == email_clean,
            Veterinario.is_deleted == False
        ).first()

        if not vet:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró una cuenta con ese correo."
            )

        if vet.is_verified:
            return {"mensaje": "La cuenta ya se encuentra verificada."}

        nuevo_otp = f"{random.randint(100000, 999999)}"
        vet.otp_code = nuevo_otp
        vet.otp_expires_at = get_lima_now() + timedelta(minutes=15)
        db.commit()

        send_otp_email(destinatario=vet.email, otp_code=nuevo_otp, nombre=vet.nombre)
        return {"mensaje": "Se ha enviado un nuevo código de verificación a tu correo."}

    @staticmethod
    def login_veterinario(db: Session, request: VetLoginRequest) -> VetLoginResponse:
        """
        Autentica a un veterinario mediante Correo/Contraseña, Username (Asistente) o Google Auth.
        """
        ident_clean = request.email.strip().lower()

        # Filtrar por email O por username
        query = db.query(Veterinario).filter(
            ((Veterinario.email == ident_clean) | (Veterinario.username == ident_clean)),
            Veterinario.is_deleted == False
        )
        if request.clinica_id:
            query = query.filter(Veterinario.clinica_id == request.clinica_id)

        vet = query.first()

        if not vet:
            # Si el veterinario no existe pero se envía clinica_id (flujo legacy)
            if not request.clinica_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No existe una cuenta registrada con este correo o usuario."
                )

            clinica = db.query(Clinica).filter(
                Clinica.id == request.clinica_id,
                Clinica.is_deleted == False
            ).first()
            if not clinica:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="La clínica especificada no existe o fue dada de baja."
                )

            vet = Veterinario(
                clinica_id=request.clinica_id,
                email=ident_clean,
                google_id=request.google_id,
                password_hash=hash_password(request.password) if request.password else None,
                rol="ADMIN",
                is_active=True,
                is_verified=True if request.google_id else False
            )
            db.add(vet)
            db.commit()
            db.refresh(vet)
        else:
            if not vet.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="La cuenta se encuentra desactivada."
                )

            # Si envió contraseña, validarla
            if request.password:
                if not vet.password_hash or not verify_password(request.password, vet.password_hash):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Contraseña incorrecta."
                    )

            # Verificar si la cuenta requiere verificación por OTP (los asistentes no requieren OTP)
            if vet.rol != "ASISTENTE" and not vet.is_verified:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Tu cuenta no ha sido verificada. Ingresa el código OTP enviado a tu correo para activarla."
                )

            # Actualizar google_id si no estaba seteado y viene de Google Auth
            if request.google_id and not vet.google_id:
                vet.google_id = request.google_id
                vet.is_verified = True
                db.commit()
                db.refresh(vet)

        # Generación de token JWT
        token_payload = {
            "sub": str(vet.id),
            "clinica_id": vet.clinica_id,
            "role": "vet",
            "rol": vet.rol,
            "email": vet.email,
            "username": vet.username,
            "nombre": vet.nombre,
            "is_verified": vet.is_verified
        }
        token = create_access_token(data=token_payload)

        return VetLoginResponse(
            access_token=token,
            token_type="bearer",
            veterinario=VetInfo.model_validate(vet)
        )

    @staticmethod
    def login_cliente(db: Session, request: ClientLoginRequest) -> ClientLoginResponse:
        """
        Autenticación de clientes/dueños de mascotas por DNI y PIN de 4 dígitos.
        - Si es primer ingreso (pin_hash es NULL), exige crear un PIN de 4 dígitos.
        - Si ya posee PIN, valida DNI + PIN para retornar el JWT.
        """
        # Multi-tenant: buscar cliente en su clínica omitiendo eliminados
        cliente = db.query(Cliente).filter(
            Cliente.clinica_id == request.clinica_id,
            Cliente.dni == request.dni,
            Cliente.is_deleted == False
        ).first()

        if not cliente:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cliente no registrado con ese DNI en esta clínica."
            )

        # CASO 1: Primer ingreso (pin_hash es NULL o vacío)
        if not cliente.pin_hash or not str(cliente.pin_hash).strip():
            pin_a_establecer = request.nuevo_pin or request.pin
            if not pin_a_establecer:
                return ClientLoginResponse(
                    access_token=None,
                    requires_pin_setup=True,
                    message="Primer ingreso detectado: Es obligatorio crear un PIN numérico de 4 dígitos.",
                    cliente=ClientInfo.model_validate(cliente)
                )

            # Validar formato de 4 dígitos numéricos
            pin_clean = str(pin_a_establecer).strip()
            if not (len(pin_clean) == 4 and pin_clean.isdigit()):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="El PIN debe constar exactamente de 4 dígitos numéricos."
                )

            # Establecer y encriptar nuevo PIN (bcrypt)
            cliente.pin_hash = hash_pin(pin_clean)
            db.commit()
            db.refresh(cliente)

            # Emitir JWT directamente para evitar doble inicio de sesión
            token_payload = {
                "sub": str(cliente.id),
                "clinica_id": cliente.clinica_id,
                "role": "client",
                "dni": cliente.dni
            }
            token = create_access_token(data=token_payload)

            return ClientLoginResponse(
                access_token=token,
                token_type="bearer",
                requires_pin_setup=False,
                message="PIN creado con éxito. Sesión iniciada.",
                cliente=ClientInfo.model_validate(cliente)
            )

        # CASO 2: Cliente con PIN ya configurado
        if not request.pin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debe ingresar su PIN de 4 dígitos para acceder."
            )

        if not verify_pin(request.pin, cliente.pin_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="PIN incorrecto."
            )

        # Emitir JWT al validar DNI + PIN
        token_payload = {
            "sub": str(cliente.id),
            "clinica_id": cliente.clinica_id,
            "role": "client",
            "dni": cliente.dni
        }
        token = create_access_token(data=token_payload)

        return ClientLoginResponse(
            access_token=token,
            token_type="bearer",
            requires_pin_setup=False,
            message="Autenticación exitosa.",
            cliente=ClientInfo.model_validate(cliente)
        )
