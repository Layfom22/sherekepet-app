# SherekePet - SaaS Veterinario (Sprint 1 & Sprint 2 - Modo Solo)

Backend y Frontend Web desarrollado en **FastAPI**, **SQLAlchemy**, **Jinja2** y **Tailwind CSS** para el SaaS Veterinario SherekePet.

---

## 🏛️ Reglas de Arquitectura

1. **Multi-tenant**:
   - Toda tabla operativa (`sp_veterinarios`, `sp_clientes`, `sp_mascotas`, `sp_atenciones`, `sp_vacunas`, `sp_seguimientos`) incluye de forma obligatoria la clave foránea e índice `clinica_id`.
2. **Zona Horaria Estricta**:
   - Obligatoriamente `'America/Lima'` (`UTC-5`) para todos los registros de auditoría y timestamps (`created_at`, `updated_at`, `deleted_at`) mediante `get_lima_now()` (`datetime.now(ZoneInfo('America/Lima'))`).
   - Soporte universal garantizado con `tzdata`.
3. **Soft Delete**:
   - Todas las tablas implementan `is_deleted = Column(Boolean, default=False)` y `deleted_at = Column(DateTime, nullable=True)`.
   - Las consultas operativas omiten los registros marcados como eliminados (`is_deleted == False`).
4. **Inicialización Segura**:
   - `app/database.py` inicializa las tablas con sentencias idempotentes `CREATE TABLE IF NOT EXISTS` garantizando cero bloqueos o errores de colisión en despliegues con SQLite local o PostgreSQL en Render.
5. **Mobile-First & Cero Fricción**:
   - UI adaptada para celulares y laptops con Tailwind CSS, botones con área táctil mínima de 44px (`min-h-[44px]`), consulta asíncrona a RENIEC y canal de contacto 1-Clic por WhatsApp.

---

## 📁 Estructura del Proyecto

```
SHEREKEPET/
├── app/
│   ├── core/
│   │   ├── config.py           # Configuración con Pydantic Settings (.env)
│   │   ├── timezone.py         # Helper de hora para America/Lima
│   │   ├── security.py         # Hash de PIN (bcrypt) y tokens JWT (PyJWT)
│   │   └── models.py           # Base, SoftDeleteMixin, TimestampMixin, Clinica (sp_clinicas)
│   ├── clinic/
│   │   ├── models.py           # sp_veterinarios, sp_clientes, sp_mascotas, sp_atenciones, sp_vacunas, sp_seguimientos
│   │   ├── schemas.py          # Schemas Pydantic (Paciente rápido, Atenciones, RENIEC)
│   │   ├── routes.py           # Endpoints API REST y vistas web Jinja2
│   │   └── services/
│   │       ├── reniec_service.py   # Consulta asíncrona a apis.net.pe
│   │       └── whatsapp_service.py # Normalizador de teléfonos peruanos (+51) y enlaces wa.me
│   ├── auth/
│   │   ├── schemas.py          # Schemas Pydantic para Auth
│   │   ├── service.py          # Lógica de negocio de Auth
│   │   └── routes.py           # POST /api/auth/vet/login y client/login
│   ├── templates/
│   │   ├── base.html           # Layout base Tailwind CSS responsivo
│   │   └── clinic/
│   │       ├── dashboard.html      # Panel Veterinario con KPIs, buscador y WhatsApp 1-clic
│   │       ├── paciente_form.html  # Registro Cero Fricción con autocompletado RENIEC en vivo
│   │       └── ficha_mascota.html  # Ficha clínica, carnet de vacunas y registro de atenciones
│   ├── database.py             # Engine, sessionmaker, get_db e init_db seguro
│   └── main.py                 # FastAPI app, CORS, lifespan & healthcheck
├── tests/
│   ├── conftest.py             # Fixtures de SQLite en memoria y TestClient
│   ├── test_models.py          # Tests de multi-tenant, soft delete y timezone
│   ├── test_auth.py            # Tests de autenticación para vet y cliente
│   └── test_clinic_sprint2.py  # Tests de RENIEC, WhatsApp, paciente rápido y atenciones con vacunas
├── .env.example
├── requirements.txt
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

Navega a:
- **Panel Veterinario (Dashboard)**: `http://localhost:8000/dashboard`
- **Registro Rápido de Pacientes**: `http://localhost:8000/pacientes/nuevo`
- **Swagger UI**: `http://localhost:8000/docs`

---

## 🩺 Módulos del Sprint 2

### 1. Integración RENIEC (`apis.net.pe`)
- Endpoint: `GET /api/reniec/dni/{dni}`
- Servicio: `app/clinic/services/reniec_service.py`
- Lee token Bearer desde `APIS_NET_PE_TOKEN`.

### 2. Registro Cero Fricción
- Endpoint: `POST /api/clinic/paciente-rapido`
- Registra al Cliente y a su Mascota en una sola transacción atómica.

### 3. Atenciones y Cálculo Automático de Vacunas y Notificaciones
- Endpoint: `POST /api/clinic/atenciones`
- Al registrar una atención con `tipo_atencion = 'VACUNACION'`, el sistema genera automáticamente:
  - Fila en `sp_vacunas` con la fecha del próximo refuerzo.
  - Fila en `sp_seguimientos` con fecha programada, plantilla de recordatorio y enlace directo a WhatsApp.

### 4. Canal WhatsApp 1-Clic
- Utilidad: `app/clinic/services/whatsapp_service.py`
- Normaliza números celulares de Perú a formato internacional `519XXXXXXXX` y genera el enlace directo `https://wa.me/51...` con mensaje codificado.
- Endpoint: `PATCH /api/clinic/seguimientos/{id}/marcar-enviado`.

---

## 🧪 Ejecución de Pruebas

Para ejecutar la suite completa de pruebas unitarias y de integración:

```bash
pytest -v
```
