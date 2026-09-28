from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["Legal y Cumplimiento"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/terminos-y-condiciones", response_class=HTMLResponse, summary="Términos y Condiciones")
def vista_terminos_y_condiciones(request: Request):
    """Renderiza los Términos y Condiciones con cláusula expresa de Puerto Seguro / DMCA."""
    return templates.TemplateResponse(
        request=request,
        name="legal/terminos_condiciones.html",
        context={}
    )


@router.get("/politica-privacidad", response_class=HTMLResponse, summary="Política de Privacidad")
def vista_politica_privacidad(request: Request):
    """Renderiza la Política de Privacidad y Protección de Datos Personales."""
    return templates.TemplateResponse(
        request=request,
        name="legal/politica_privacidad.html",
        context={}
    )


@router.get("/politica-reembolsos", response_class=HTMLResponse, summary="Política de Reembolsos")
def vista_politica_reembolsos(request: Request):
    """Renderiza la Política de Reembolsos, Cancelaciones y Facturación."""
    return templates.TemplateResponse(
        request=request,
        name="legal/politica_reembolsos.html",
        context={}
    )
