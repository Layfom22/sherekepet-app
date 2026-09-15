from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.database import init_db
from app.auth.routes import router as auth_router
from app.clinic.routes import router as clinic_router
from fastapi.responses import RedirectResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicialización segura de la base de datos (CREATE TABLE IF NOT EXISTS)
    init_db()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="SaaS Veterinario SherekePet - Backend Core, Auth & Panel Clínico (Sprint 1 & 2)",
    version="0.2.0",
    lifespan=lifespan
)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrar rutas
app.include_router(auth_router)
app.include_router(clinic_router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/api/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "project": settings.PROJECT_NAME,
        "timezone": settings.DEFAULT_TIMEZONE
    }
