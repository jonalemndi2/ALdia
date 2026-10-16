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
from security import ROL_AGENTE, ROL_SOLO_LECTURA

router = APIRouter()


# Catálogo de módulos por defecto que se siembra en la primera ejecución.
MODULOS_DEFAULT = [
    {"clave": "stock", "nombre": "Stock", "descripcion": "Inventario y mercadería", "icono": "bi-box-seam", "categoria": "operaciones", "habilitado": True, "roles": "administrador,encargado_ventas,encargado_compras,encargado_deposito,auditor", "orden": 10},
    {"clave": "clientes", "nombre": "Clientes", "descripcion": "Gestión de clientes y deudores", "icono": "bi-people", "categoria": "ventas", "habilitado": True, "roles": "administrador,encargado_ventas,caja,auditor", "orden": 20},
    {"clave": "ventas", "nombre": "Ventas", "descripcion": "Remitos y facturación", "icono": "bi-receipt", "categoria": "ventas", "habilitado": True, "roles": "administrador,encargado_ventas,auditor", "orden": 30},
    {"clave": "liquidaciones_granos", "nombre": "Liquidaciones de Granos", "descripcion": "Cereales, acopio, mermas, cartas de porte y LPG", "icono": "bi-moisture", "categoria": "agro", "habilitado": True, "roles": "administrador,encargado_ventas,encargado_compras,finanzas,auditor", "orden": 35},
    {"clave": "liquidaciones_hacienda", "nombre": "Liquidaciones de Hacienda", "descripcion": "Tropas, DTE, RENSPA, desbaste y liquidación pecuaria", "icono": "bi-tags", "categoria": "agro", "habilitado": True, "roles": "administrador,encargado_ventas,encargado_compras,finanzas,auditor", "orden": 36},
    {"clave": "proveedores", "nombre": "Proveedores", "descripcion": "Proveedores, compras y pagos", "icono": "bi-truck", "categoria": "compras", "habilitado": True, "roles": "administrador,encargado_compras,auditor", "orden": 40},
    {"clave": "gastos", "nombre": "Gastos", "descripcion": "Facturas de gastos y notas", "icono": "bi-cash-stack", "categoria": "compras", "habilitado": True, "roles": "administrador,encargado_compras,finanzas,auditor", "orden": 50},
    {"clave": "cuentas_corrientes", "nombre": "Cuentas Corrientes", "descripcion": "Cobros y cuentas corrientes", "icono": "bi-journal-text", "categoria": "finanzas", "habilitado": True, "roles": "administrador,caja,finanzas,auditor", "orden": 60},
    {"clave": "caja", "nombre": "Caja", "descripcion": "Caja chica, bancos y chequera", "icono": "bi-safe", "categoria": "finanzas", "habilitado": True, "roles": "administrador,caja,finanzas,auditor", "orden": 70},
    {"clave": "iva", "nombre": "IVA", "descripcion": "Libro IVA ventas y compras", "icono": "bi-percent", "categoria": "finanzas", "habilitado": True, "roles": "administrador,finanzas,auditor", "orden": 80},
    {"clave": "administracion", "nombre": "Administración", "descripcion": "Usuarios, módulos y mantenimiento", "icono": "bi-gear", "categoria": "admin", "habilitado": True, "roles": "administrador", "orden": 90},
]

# Perfiles verticales de negocio: activan sólo los módulos que cada tipo de
# empresa necesita (y ocultan el resto tanto en el menú web como en las
# sugerencias operativas del agente). "administracion" nunca se desactiva.
PERFILES_NEGOCIO = {
    "comercio": {
        "clave": "comercio",
        "nombre": "Comercio / PyME / Supermercado",
        "descripcion": "Mostrador, remitos, facturación, compras, stock, cuentas corrientes, caja e impuestos. Oculta módulos agropecuarios.",
        "modulos_activos": [
            "stock", "clientes", "ventas", "proveedores", "gastos",
            "cuentas_corrientes", "caja", "iva", "administracion",
        ],
    },
    "agro_granos": {
        "clave": "agro_granos",
        "nombre": "Agro — Cereales y Acopio",
        "descripcion": "Productor agrícola, acopio o corretaje de granos: liquidaciones de cereales (LPG), insumos en stock, cuentas corrientes, tesorería e IVA.",
        "modulos_activos": [
            "stock", "clientes", "ventas", "liquidaciones_granos",
            "proveedores", "gastos", "cuentas_corrientes", "caja", "iva", "administracion",
        ],
    },
    "agro_hacienda": {
        "clave": "agro_hacienda",
        "nombre": "Agro — Ganadería y Consignataria",
        "descripcion": "Productor ganadero, feedlot o consignatario de hacienda: liquidaciones pecuarias (LSP), tropas, gastos, cuentas corrientes y tesorería.",
        "modulos_activos": [
            "stock", "clientes", "ventas", "liquidaciones_hacienda",
            "proveedores", "gastos", "cuentas_corrientes", "caja", "iva", "administracion",
        ],
    },
    "agro_mixto": {
        "clave": "agro_mixto",
        "nombre": "Agropecuario Mixto (Granos + Hacienda)",
        "descripcion": "Establecimiento mixto, cooperativa o administración agropecuaria con cereales, hacienda, insumos, canjes y tesorería completa.",
        "modulos_activos": [
            "stock", "clientes", "ventas", "liquidaciones_granos", "liquidaciones_hacienda",
            "proveedores", "gastos", "cuentas_corrientes", "caja", "iva", "administracion",
        ],
    },
    "servicios": {
        "clave": "servicios",
        "nombre": "Servicios Profesionales / Contratista",
        "descripcion": "Facturación de servicios, clientes, gastos, cobranzas, bancos e impuestos (sin inventario físico ni módulos agropecuarios).",
        "modulos_activos": [
            "clientes", "ventas", "proveedores", "gastos",
            "cuentas_corrientes", "caja", "iva", "administracion",
        ],
    },
}


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


@router.get("/perfiles")
def listar_perfiles(_: Usuario = Depends(current_user_dep)):
    """Devuelve el catálogo de perfiles verticales de negocio instalables."""
    return list(PERFILES_NEGOCIO.values())


@router.post("/perfiles/{clave_perfil}")
def aplicar_perfil_negocio(
    clave_perfil: str,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Activa los módulos del perfil elegido y desactiva los que no aplican (solo administrador)."""
    perfil = PERFILES_NEGOCIO.get((clave_perfil or "").strip().lower())
    if not perfil:
        validos = ", ".join(sorted(PERFILES_NEGOCIO))
        raise HTTPException(
            status_code=404,
            detail=f"Perfil de negocio '{clave_perfil}' no encontrado. Perfiles válidos: {validos}",
        )
    seed_modulos(db)
    activos_set = set(perfil["modulos_activos"]) | {"administracion"}
    modulos = db.query(Modulo).order_by(Modulo.orden).all()
    habilitados, deshabilitados = [], []
    for m in modulos:
        debe_estar = m.clave in activos_set
        m.habilitado = debe_estar
        if debe_estar:
            habilitados.append(m.clave)
        else:
            deshabilitados.append(m.clave)
    db.commit()
    return {
        "perfil": perfil["clave"],
        "nombre": perfil["nombre"],
        "modulos_habilitados": habilitados,
        "modulos_deshabilitados": deshabilitados,
    }


@router.get("/activos", response_model=List[ModuloResponse])
def modulos_activos(db: Session = Depends(get_db), user: Usuario = Depends(current_user_dep)):
    """Listar los módulos habilitados a los que el usuario actual tiene acceso por su rol."""
    rol = (user.rol or "").lower()
    modulos = db.query(Modulo).filter(Modulo.habilitado == True).order_by(Modulo.orden).all()  # noqa: E712
    if rol == "administrador":
        return modulos

    def visible(m) -> bool:
        roles = [r.strip().lower() for r in (m.roles or "").split(",")]
        # El agente consulta lo mismo que el auditor (ver security.ROL_AGENTE).
        return rol in roles or (rol == ROL_AGENTE and ROL_SOLO_LECTURA in roles)

    return [m for m in modulos if visible(m)]


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
