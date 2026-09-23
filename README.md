# SherekePet - SaaS Veterinario (Sprints 1, 2 & 3 - Modo Solo)

Backend y Frontend Web desarrollado en **FastAPI**, **SQLAlchemy**, **Jinja2** y **Tailwind CSS** para el SaaS Veterinario SherekePet.

---

## 🏛️ Reglas de Arquitectura

1. **Multi-tenant**:
   - Toda tabla operativa (`sp_veterinarios`, `sp_clientes`, `sp_mascotas`, `sp_atenciones`, `sp_vacunas`, `sp_seguimientos`, `sp_medication_plans`, `sp_dose_trackings`, `sp_web_push_subscriptions`) incluye de forma obligatoria la clave foránea e índice `clinica_id`.
2. **Zona Horaria Estricta**:
   - Obligatoriamente `'America/Lima'` (`UTC-5`) para todos los registros de auditoría y timestamps (`created_at`, `updated_at`, `deleted_at`) mediante `get_lima_now()` (`datetime.now(ZoneInfo('America/Lima'))`).
   - Soporte universal garantizado con `tzdata`.
3. **Soft Delete**:
   - Todas las tablas implementan `is_deleted = Column(Boolean, default=False)` y `deleted_at = Column(DateTime, nullable=True)`.
   - Las consultas operativas omiten los registros marcados como eliminados (`is_deleted == False`).
4. **Inicialización Segura**:
   - `app/database.py` inicializa las tablas con sentencias idempotentes `CREATE TABLE IF NOT EXISTS` garantizando cero bloqueos o errores de colisión en despliegues con SQLite local o PostgreSQL en Render.
5. **Mobile-First & PWA Cero Fricción**:
   - UI adaptada para celulares con Tailwind CSS, botones con área táctil mínima de 44px (`min-h-[44px]`), soporte offline y manifest PWA (`manifest.json` y `service-worker.js`).

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
│   ├── follow_up/
│   │   ├── models.py           # sp_medication_plans, sp_dose_trackings, sp_web_push_subscriptions
│   │   ├── schemas.py          # Schemas para planes y confirmación de tomas
│   │   ├── services.py         # Motor de medicación dinámica y Ventana de Sueño (23:00 - 06:00 -> 07:00 AM)
│   │   └── routes.py           # Endpoints API, PWA statics y Portal del Cliente
│   ├── auth/
│   │   ├── schemas.py          # Schemas Pydantic para Auth
│   │   ├── service.py          # Lógica de negocio de Auth
│   │   └── routes.py           # POST /api/auth/vet/login y client/login
│   ├── templates/
│   │   ├── base.html           # Layout base Tailwind CSS responsivo
│   │   ├── clinic/
│   │   │   ├── dashboard.html      # Panel Veterinario con KPIs, buscador y WhatsApp 1-clic
│   │   │   ├── paciente_form.html  # Registro Cero Fricción con autocompletado RENIEC en vivo
│   │   │   └── ficha_mascota.html  # Ficha clínica, carnet de vacunas y registro de atenciones
│   │   └── client/
│   │       ├── login.html          # Acceso de dueños con DNI y PIN de 4 dígitos
│   │       ├── dashboard.html      # Portal móvil del cliente PWA (1 columna, tarjetas)
│   │       └── carnet.html         # Carnet digital de vacunas y botón grande "[✔ Ya se la di]"
│   ├── database.py             # Engine, sessionmaker, get_db e init_db seguro
│   └── main.py                 # FastAPI app, CORS, lifespan & healthcheck
├── tests/
│   ├── conftest.py             # Fixtures de SQLite en memoria y TestClient
│   ├── test_models.py          # Tests de multi-tenant, soft delete y timezone
│   ├── test_auth.py            # Tests de autenticación para vet y cliente
│   ├── test_clinic_sprint2.py  # Tests de RENIEC, WhatsApp, paciente rápido y atenciones
│   └── test_follow_up_sprint3.py # Tests de medicación dinámica, ventana de sueño, PWA y portal
├── .env.example
├── requirements.txt
└── README.md
```

---

## 🚀 Instalación y Ejecución

```bash
# 1. Crear y activar entorno virtual
python -m venv .venv
.venv\Scripts\activate   # En Linux/Mac: source .venv/bin/activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Iniciar el servidor
uvicorn app.main:app --reload --port 8000
```

### Enlaces de Interés:
- **Panel del Veterinario**: `http://localhost:8000/dashboard`
- **Registro Rápido Paciente**: `http://localhost:8000/pacientes/nuevo`
- **Portal del Cliente PWA**: `http://localhost:8000/portal/dashboard`
- **Login Dueños PWA**: `http://localhost:8000/portal/login`
- **PWA Manifest**: `http://localhost:8000/manifest.json`
- **Swagger UI**: `http://localhost:8000/docs`

---

## 💊 Motor de Medicación Dinámica (Sprint 3)

1. **Creación del Plan**:
   - `POST /api/medication/plan`: Registra medicamento, frecuencia en horas y total de dosis. Programa la primera dosis automáticamente.
2. **Confirmación de Tomas y Reprogramación**:
   - `POST /api/medication/dose/{id}/confirm`: El cliente confirma la toma desde el botón móvil **"[✔ Ya se la di]"**.
   - Calcula la próxima hora programada (`hora_consumo_real + frecuencia_horas`).
3. **Regla de Ventana de Sueño**:
   - Si `es_estricto == False` y la siguiente hora calculada cae entre **23:00 y 06:59**, se reajusta automáticamente a las **07:00 AM** para proteger el descanso del dueño.
   - Si `es_estricto == True`, no se aplica la ventana de sueño (para fármacos críticos como antiepilépticos).
4. **Finalización del Tratamiento**:
   - Al confirmar la última dosis (`total_dosis`), el plan se marca como `'COMPLETADO'`.

---

## 🧪 Ejecución de Pruebas

```bash
pytest -v
```
*(70 pruebas unitarias y de integración pasando al 100%)*

---

## 🎨 Sistema de Iconografía y Consistencia Visual (Lucide Icons)

SherekePet utiliza **exclusivamente [Lucide Icons](https://lucide.dev/)** para garantizar una estética veterinaria profesional, moderna, limpia y semánticamente coherente en todas sus vistas (Clínica y Portal del Cliente). Está **estrictamente prohibido el uso de emojis, iconos de Windows o flechas Unicode** en componentes de interfaz.

### 1. Carga y Rendimiento
- **Distribución local / offline-first**: El bundle se sirve desde `app/static/js/lucide.min.js`, sin depender de CDNs externas durante la renderización en producción ni fallar en conexiones lentas.
- **Inicialización centralizada**:
  ```javascript
  window.initLucideIcons = function() {
      if (window.lucide) {
          lucide.createIcons({
              attrs: {
                  'stroke-width': 1.8,
                  'stroke-linecap': 'round',
                  'stroke-linejoin': 'round'
              }
          });
      }
  };
  ```
- **Contenido dinámico**: Toda función JavaScript que inyecte HTML con `data-lucide` debe invocar `window.initLucideIcons?.()` inmediatamente después de la inserción en el DOM.

### 2. Estándares Visuales y Dimensiones
| Tipo de Elemento | Clases de Tamaño Tailwind | Dimensiones | Grosor de Trazo |
| :--- | :--- | :--- | :--- |
| **Navegación / Header** | `w-[18px] h-[18px]` | 18×18 px | `1.8` |
| **Botones Principales (Touch)** | `w-[18px] h-[18px]` o `w-5 h-5` | 18–20 px | `1.8` |
| **Badges / Botones de Tabla** | `w-3.5 h-3.5` o `w-4 h-4` | 14–16 px | `1.8` |
| **Encabezados de Tarjeta** | `w-5 h-5` | 20×20 px | `1.8` |
| **Empty States / Hero** | `w-10 h-10` a `w-12 h-12` | 40–48 px | `1.8` |

### 3. Mapeo Semántico Obligatorio
| Entidad / Función | Icono Lucide (`data-lucide`) | Justificación Semántica |
| :--- | :--- | :--- |
| **Dashboard / Panel Principal** | `layout-dashboard` | Representa la vista integral de métricas y tarjetas. |
| **Mascota / Paciente / Especie** | `paw-print` | Huella veterinaria universal y distintiva. |
| **Dueño / Cliente / Perfil** | `user-round` o `user` | Representación humana limpia para clientes y veterinarios. |
| **Clínica / Veterinaria** | `hospital` o `building-2` | Establecimiento de salud médica veterinaria. |
| **Agenda / Calendario / Cita** | `calendar-days` o `calendar` | Organización temporal y citas programadas. |
| **Atención / Historial Clínico** | `stethoscope` o `file-text` | Práctica médica clínica y expediente veterinario. |
| **Vacunas / Inmunizaciones** | `syringe` | Procedimiento de vacunación biológica. |
| **Tratamiento / Medicación** | `pill` | Administración de fármacos y dosificación. |
| **WhatsApp / Mensajería** | `message-circle` | Comunicación directa por chat o WhatsApp wa.me. |
| **Horarios / Tiempo / Duración** | `clock-3` o `clock` | Intervalos horarios y tiempos de espera. |
| **Configuración / Ajustes** | `settings` | Panel de opciones administrativas y parámetros. |
| **Búsqueda** | `search` | Exploración de registros en listas y tablas. |
| **Filtros** | `filter` | Segmentación y filtrado de datos. |
| **Acción Crear / Agregar** | `plus` | Incorporación de nuevos registros. |
| **Acción Guardar** | `save` | Persistencia de datos en formularios. |
| **Acción Editar** | `pencil` | Modificación de registros existentes. |
| **Acción Eliminar / Descartar** | `trash-2` | Borrado lógico o confirmación destructiva. |
| **Acción Cancelar / Cerrar** | `x` | Cierre de modales y descarte de diálogos. |
| **Confirmación / Éxito** | `check` o `circle-check` | Estados completados o verificados con éxito. |
| **Alertas / Advertencias** | `triangle-alert` | Notificaciones preventivas o de atención médica. |
| **Navegación / Flujo** | `arrow-left`, `arrow-right`, `chevron-right` | Dirección y avance de pantallas. |
| **Carga Asíncrona** | `loader-2` (con `animate-spin`) | Indicador de espera o petición en curso. |
| **Cerrar Sesión** | `log-out` | Salida de la sesión activa. |

### 4. Accesibilidad (A11y)
- Todo icono decorativo incluye `aria-hidden="true"`.
- Los botones sin texto descriptivo incluyen `aria-label="..."` y `title="..."` explícito.

