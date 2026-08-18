"""
config.py - Router para la configuración del negocio (clave-valor).

Permite personalizar la instalación para cada comercio/supermercado:
nombre, CUIT, dirección, condición IVA, punto de venta, etc.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict

from database import get_db
from models import Configuracion, Usuario
from schemas import ConfigItem
from routers.auth import require_admin

router = APIRouter()


# Configuración por defecto del negocio.
CONFIG_DEFAULT = {
    "negocio_nombre": "Mi Supermercado",
    "negocio_cuit": "",
    "negocio_direccion": "",
    "negocio_localidad": "",
    "negocio_telefono": "",
    "negocio_iva": "Responsable Inscripto",
    "negocio_punto_venta": "0001",
    "negocio_moneda": "ARS",
}


def seed_config(db: Session) -> int:
    """Inserta las claves de configuración por defecto que falten."""
    creados = 0
    for clave, valor in CONFIG_DEFAULT.items():
        existing = db.query(Configuracion).filter(Configuracion.clave == clave).first()
        if not existing:
            db.add(Configuracion(clave=clave, valor=valor))
            creados += 1
    db.commit()
    return creados


@router.get("/")
def obtener_config(db: Session = Depends(get_db)) -> Dict[str, str]:
    """Obtener toda la configuración del negocio como diccionario (público para la UI)."""
    items = db.query(Configuracion).all()
    return {item.clave: item.valor for item in items}


@router.put("/")
def actualizar_config(
    cambios: Dict[str, str],
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Actualizar uno o varios valores de configuración (solo administrador)."""
    for clave, valor in cambios.items():
        item = db.query(Configuracion).filter(Configuracion.clave == clave).first()
        if item:
            item.valor = valor
        else:
            db.add(Configuracion(clave=clave, valor=valor))
    db.commit()
    return {"message": "Configuración actualizada", "actualizados": len(cambios)}
