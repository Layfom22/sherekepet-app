from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.database import init_db
from app.auth.routes import router as auth_router, google_router
from app.clinic.routes import router as clinic_router
from app.follow_up.routes import router as follow_up_router
from fastapi.responses import RedirectResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicialización segura de la base de datos (CREATE TABLE IF NOT EXISTS)
    init_db()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="SaaS Veterinario SherekePet - Backend Core, Auth, Panel Clínico & Portal PWA (Sprints 1, 2, 3)",
    version="0.3.0",
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

import os
from fastapi.staticfiles import StaticFiles

# Asegurar y montar directorio para archivos subidos localmente
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Registrar rutas
app.include_router(google_router)
app.include_router(auth_router)
app.include_router(clinic_router)
app.include_router(follow_up_router)


@app.get("/", include_in_schema=False)
def root(request: Request):
    if request.cookies.get("vet_token"):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    if request.cookies.get("client_token"):
        return RedirectResponse(url="/portal/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/api/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "project": settings.PROJECT_NAME,
        "timezone": settings.DEFAULT_TIMEZONE
    }
