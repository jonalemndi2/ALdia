"""
modulos.py - Router para gestión de módulos del sistema.

Permite habilitar/deshabilitar módulos por instalación (licencia) y definir
qué roles tienen acceso a cada uno. Pensado para vender el sistema a distintos
comercios/supermercados con configuraciones diferentes.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import Modulo, Usuario
from schemas import ModuloResponse, ModuloUpdate, ModuloBase
from routers.auth import current_user_dep, require_admin

router = APIRouter()


# Catálogo de módulos por defecto que se siembra en la primera ejecución.
MODULOS_DEFAULT = [
    {"clave": "stock", "nombre": "Stock", "descripcion": "Inventario y mercadería", "icono": "bi-box-seam", "categoria": "operaciones", "habilitado": True, "roles": "administrador,encargado_ventas,encargado_compras,encargado_deposito,auditor", "orden": 10},
    {"clave": "clientes", "nombre": "Clientes", "descripcion": "Gestión de clientes y deudores", "icono": "bi-people", "categoria": "ventas", "habilitado": True, "roles": "administrador,encargado_ventas,caja,auditor", "orden": 20},
    {"clave": "ventas", "nombre": "Ventas", "descripcion": "Remitos y facturación", "icono": "bi-receipt", "categoria": "ventas", "habilitado": True, "roles": "administrador,encargado_ventas,auditor", "orden": 30},
    {"clave": "proveedores", "nombre": "Proveedores", "descripcion": "Proveedores, compras y pagos", "icono": "bi-truck", "categoria": "compras", "habilitado": True, "roles": "administrador,encargado_compras,auditor", "orden": 40},
    {"clave": "gastos", "nombre": "Gastos", "descripcion": "Facturas de gastos y notas", "icono": "bi-cash-stack", "categoria": "compras", "habilitado": True, "roles": "administrador,encargado_compras,finanzas,auditor", "orden": 50},
    {"clave": "cuentas_corrientes", "nombre": "Cuentas Corrientes", "descripcion": "Cobros y cuentas corrientes", "icono": "bi-journal-text", "categoria": "finanzas", "habilitado": True, "roles": "administrador,caja,finanzas,auditor", "orden": 60},
    {"clave": "caja", "nombre": "Caja", "descripcion": "Caja chica, bancos y chequera", "icono": "bi-safe", "categoria": "finanzas", "habilitado": True, "roles": "administrador,caja,finanzas,auditor", "orden": 70},
    {"clave": "iva", "nombre": "IVA", "descripcion": "Libro IVA ventas y compras", "icono": "bi-percent", "categoria": "finanzas", "habilitado": True, "roles": "administrador,finanzas,auditor", "orden": 80},
    {"clave": "administracion", "nombre": "Administración", "descripcion": "Usuarios, módulos y mantenimiento", "icono": "bi-gear", "categoria": "admin", "habilitado": True, "roles": "administrador", "orden": 90},
]


def seed_modulos(db: Session) -> int:
    """Inserta los módulos por defecto que aún no existan. Devuelve cuántos creó."""
    creados = 0
    for m in MODULOS_DEFAULT:
        existing = db.query(Modulo).filter(Modulo.clave == m["clave"]).first()
        if not existing:
            db.add(Modulo(**m))
            creados += 1
    db.commit()
    return creados


@router.get("/", response_model=List[ModuloResponse])
def listar_modulos(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Listar todos los módulos (solo administrador)."""
    return db.query(Modulo).order_by(Modulo.orden).all()


@router.get("/activos", response_model=List[ModuloResponse])
def modulos_activos(db: Session = Depends(get_db), user: Usuario = Depends(current_user_dep)):
    """Listar los módulos habilitados a los que el usuario actual tiene acceso por su rol."""
    rol = (user.rol or "").lower()
    modulos = db.query(Modulo).filter(Modulo.habilitado == True).order_by(Modulo.orden).all()  # noqa: E712
    if rol == "administrador":
        return modulos
    return [m for m in modulos if rol in [r.strip().lower() for r in (m.roles or "").split(",")]]


@router.put("/{clave}", response_model=ModuloResponse)
def actualizar_modulo(
    clave: str,
    data: ModuloUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Habilitar/deshabilitar un módulo o cambiar sus roles (solo administrador)."""
    modulo = db.query(Modulo).filter(Modulo.clave == clave).first()
    if not modulo:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(modulo, key, value)
    db.commit()
    db.refresh(modulo)
    return modulo


@router.post("/seed")
def poblar_modulos(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Re-sembrar los módulos por defecto que falten (solo administrador)."""
    creados = seed_modulos(db)
    return {"message": f"{creados} módulos creados", "creados": creados}
