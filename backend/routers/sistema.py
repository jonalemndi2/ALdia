"""
sistema.py - Version instalada, novedades y actualizacion de ALdia.

GET  /api/sistema/version     cualquier usuario logueado (incluido un agente).
POST /api/sistema/actualizar  solo administrador. Ver backend/version.py.
"""
from fastapi import APIRouter, Depends, Query

import version as v
from database import DB_PATH
from errores import ErrorDeNegocio
from models import Usuario
from routers.auth import current_user_dep, require_admin

router = APIRouter()


@router.get("/version")
def obtener_version(
    refrescar: bool = Query(False, description="Volver a consultar el repositorio, sin cache"),
    usuario: Usuario = Depends(current_user_dep),
):
    """Version instalada y, si se puede consultar, si hay una nueva y sus novedades."""
    datos = v.estado()
    if refrescar and (usuario.rol or "").lower() == "administrador":
        datos["actualizacion"] = v.buscar_actualizacion(refrescar=True)
    return datos


@router.post("/actualizar")
def actualizar_sistema(_: Usuario = Depends(require_admin)):
    """Instala la ultima version publicada (copia de seguridad previa incluida)."""
    try:
        return v.actualizar(DB_PATH)
    except v.ErrorDeActualizacion as exc:
        raise ErrorDeNegocio("ACTUALIZACION_NO_POSIBLE", f"No se actualizo: {exc}", detalle=str(exc)) from None
