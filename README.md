# SherekePet - SaaS Veterinario (Sprint 1 - Modo Solo)

Backend API desarrollado en **FastAPI** y **SQLAlchemy** para el SaaS Veterinario SherekePet.

---

## 🏛️ Reglas de Arquitectura

1. **Multi-tenant**:
   - Toda tabla operativa (`veterinarios`, `clientes`, `mascotas`) incluye de forma obligatoria la clave foránea e índice `clinica_id`.
2. **Zona Horaria Estricta**:
   - Obligatoriamente `'America/Lima'` (`UTC-5`) para todos los registros de auditoría y timestamps (`created_at`, `updated_at`, `deleted_at`) mediante `datetime.now(ZoneInfo('America/Lima'))`.
   - Incluye soporte universal con paquete `tzdata` compatible en Linux, macOS y Windows.
3. **Soft Delete**:
   - Todas las tablas implementan `is_deleted = Column(Boolean, default=False)` y `deleted_at = Column(DateTime, nullable=True)`.
   - Las consultas operativas omiten los registros marcados como eliminados (`is_deleted == False`).
4. **Inicialización Segura**:
   - `app/database.py` inicializa las tablas con sentencias idempotentes `CREATE TABLE IF NOT EXISTS` garantizando cero bloqueos o errores de colisión.

---

## 📁 Estructura del Proyecto

```
SHEREKEPET/
├── app/
│   ├── core/
│   │   ├── config.py           # Configuración con Pydantic Settings
│   │   ├── timezone.py         # Helper de hora para America/Lima
│   │   ├── security.py         # Hash de PIN (bcrypt) y tokens JWT (PyJWT)
│   │   └── models.py           # Base, SoftDeleteMixin, TimestampMixin, Clinica
│   ├── clinic/
│   │   └── models.py           # Modelos Veterinario, Cliente, Mascota
│   ├── auth/
│   │   ├── schemas.py          # Schemas Pydantic con tipado estricto
│   │   ├── service.py          # Lógica de negocio (Google Auth & PIN 4 dígitos)
│   │   └── routes.py           # Endpoints POST /api/auth/vet/login y client/login
│   ├── database.py             # Engine, sessionmaker, get_db e init_db seguro
│   └── main.py                 # FastAPI app, CORS, lifespan & healthcheck
├── tests/
│   ├── conftest.py             # Fixtures de SQLite en memoria y TestClient
│   ├── test_models.py          # Tests de multi-tenant, soft delete y timezone
│   └── test_auth.py            # Tests de autenticación para vet y cliente
├── .env.example                # Variables de entorno de referencia
├── requirements.txt            # Dependencias del proyecto
└── README.md
```

---

## 🚀 Instalación y Ejecución

### 1. Clonar o ingresar al repositorio y crear entorno virtual

```bash
python -m venv .venv
# En Windows:
.venv\Scripts\activate
# En Linux/Mac:
source .venv/bin/activate
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar variables de entorno

```bash
copy .env.example .env
```

### 4. Iniciar el servidor de desarrollo

```bash
uvicorn app.main:app --reload --port 8000
```

La documentación interactiva estará disponible en:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Healthcheck: `http://localhost:8000/api/health`

---

## 🔐 Endpoints de Autenticación

### 1. `POST /api/auth/vet/login`
Autenticación de personal veterinario mediante credenciales / Google OAuth.
- **Request**:
  ```json
  {
    "email": "doctor@veterinaria.pe",
    "google_id": "google_12345678",
    "clinica_id": 1
  }
  ```
- **Response**:
  ```json
  {
    "access_token": "eyJhbGciOi...",
    "token_type": "bearer",
    "veterinario": {
      "id": 1,
      "email": "doctor@veterinaria.pe",
      "rol": "veterinario",
      "clinica_id": 1,
      "is_active": true
    }
  }
  ```

### 2. `POST /api/auth/client/login`
Autenticación para dueños de mascotas mediante DNI y PIN.

- **Caso 1: Primer ingreso (`pin_hash` es NULL)**
  - Request inicial:
    ```json
    {
      "clinica_id": 1,
      "dni": "72345678"
    }
    ```
  - Response:
    ```json
    {
      "access_token": null,
      "token_type": "bearer",
      "requires_pin_setup": true,
      "message": "Primer ingreso detectado: Es obligatorio crear un PIN numérico de 4 dígitos."
    }
    ```
  - Establecimiento de PIN (envío con `nuevo_pin`):
    ```json
    {
      "clinica_id": 1,
      "dni": "72345678",
      "nuevo_pin": "4521"
    }
    ```
  - Response: Retorna `access_token` JWT inmediatamente.

- **Caso 2: Cliente con PIN configurado**
  - Request:
    ```json
    {
      "clinica_id": 1,
      "dni": "72345678",
      "pin": "4521"
    }
    ```
  - Response: Retorna `access_token` JWT con claims del cliente y `clinica_id`.

---

## 🧪 Ejecución de Pruebas

Para ejecutar la suite completa de pruebas unitarias y de integración:

```bash
pytest -v
```
