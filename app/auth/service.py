from typing import Tuple
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.models import Clinica
from app.clinic.models import Veterinario, Cliente
from app.core.security import hash_pin, verify_pin, hash_password, verify_password, create_access_token
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
        """
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

        # Crear nueva Clínica
        clinica = Clinica(
            nombre=request.nombre_clinica.strip(),
            zona_horaria="America/Lima",
            plan_activo="solo"
        )
        db.add(clinica)
        db.flush()

        # Crear Veterinario
        vet = Veterinario(
            clinica_id=clinica.id,
            email=email_clean,
            nombre=request.nombre.strip(),
            password_hash=hash_password(request.password),
            rol="veterinario",
            is_active=True
        )
        db.add(vet)
        db.commit()
        db.refresh(vet)

        token_payload = {
            "sub": str(vet.id),
            "clinica_id": vet.clinica_id,
            "role": "vet",
            "email": vet.email,
            "nombre": vet.nombre
        }
        token = create_access_token(data=token_payload)

        return VetLoginResponse(
            access_token=token,
            token_type="bearer",
            veterinario=VetInfo.model_validate(vet)
        )

    @staticmethod
    def login_veterinario(db: Session, request: VetLoginRequest) -> VetLoginResponse:
        """
        Autentica a un veterinario mediante Correo/Contraseña o Google Auth.
        Si ya existe, verifica credenciales y genera JWT.
        Si no existe pero se envía clinica_id válida (flujo legacy/auto), lo registra.
        """
        email_clean = request.email.strip().lower()

        # Filtrar siempre registros no borrados (Soft Delete)
        query = db.query(Veterinario).filter(
            Veterinario.email == email_clean,
            Veterinario.is_deleted == False
        )
        if request.clinica_id:
            query = query.filter(Veterinario.clinica_id == request.clinica_id)
        
        vet = query.first()

        if not vet:
            # Si el veterinario no existe, verificar si se especificó clínica para autoregistro inicial (Google flow)
            if not request.clinica_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No existe una cuenta registrada con este correo electrónico."
                )
            
            # Verificar existencia de la clínica
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
                email=email_clean,
                google_id=request.google_id,
                password_hash=hash_password(request.password) if request.password else None,
                rol="veterinario",
                is_active=True
            )
            db.add(vet)
            db.commit()
            db.refresh(vet)
        else:
            if not vet.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="La cuenta de veterinario se encuentra desactivada."
                )

            # Si envió contraseña, validarla
            if request.password:
                if not vet.password_hash or not verify_password(request.password, vet.password_hash):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Contraseña incorrecta."
                    )

            # Actualizar google_id si no estaba seteado y viene de Google Auth
            if request.google_id and not vet.google_id:
                vet.google_id = request.google_id
                db.commit()
                db.refresh(vet)

        # Generación de token JWT
        token_payload = {
            "sub": str(vet.id),
            "clinica_id": vet.clinica_id,
            "role": "vet",
            "email": vet.email,
            "nombre": vet.nombre
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

        # CASO 1: Primer ingreso (pin_hash es NULL)
        if cliente.pin_hash is None:
            if not request.nuevo_pin:
                return ClientLoginResponse(
                    access_token=None,
                    requires_pin_setup=True,
                    message="Primer ingreso detectado: Es obligatorio crear un PIN numérico de 4 dígitos.",
                    cliente=ClientInfo.model_validate(cliente)
                )

            # Establecer nuevo PIN
            cliente.pin_hash = hash_pin(request.nuevo_pin)
            db.commit()
            db.refresh(cliente)

            # Emitir JWT una vez configurado el PIN
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
