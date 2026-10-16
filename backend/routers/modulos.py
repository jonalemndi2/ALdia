"""
modulos.py - Router para gestión de módulos del sistema.

ALdia es modular: cada instalación prende solo los módulos que usa (un comercio
no ve las liquidaciones de granos; un productor no necesita el libro IVA de un
supermercado) y define qué roles tienen acceso a cada uno.

La lista de módulos activos tiene UNA sola fuente: la tabla `modulos`. La editan
el panel (Administración → Módulos) o, si está definida, la variable de entorno
ALDIA_MODULOS, que la fija en cada arranque. El servidor MCP no guarda una lista
propia: le pregunta al backend (GET /api/modulos/permisos) y le muestra al
asistente solo las herramientas de los módulos activos.
"""
import os
import sys

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List

from auditoria import ROLES_LECTURA_AUDITORIA
from database import get_db
from errores import ErrorDeNegocio
from models import Modulo, Usuario
from schemas import ModuloResponse, ModuloUpdate, ModuloBase
from routers.auth import current_user_dep, require_admin
from security import ROL_AGENTE, ROL_SOLO_LECTURA, puede_en_modulo

router = APIRouter()

# Los perfiles y ALDIA_MODULOS lo prenden siempre: es la pantalla desde la que
# se administra todo lo demás.
MODULO_ADMINISTRACION = "administracion"

# Lo que el asistente NO debería poder hacer por chat salvo que alguien lo
# decida a conciencia: crear y borrar usuarios, prender y apagar módulos, borrar
# movimientos de caja. No protege ninguna ruta del backend (el panel lo sigue
# haciendo); lo lee el servidor MCP para ocultar esas herramientas.
MODULO_ADMIN_POR_CHAT = "administracion_por_chat"

VARIABLE_MODULOS = "ALDIA_MODULOS"


# Catálogo de módulos por defecto que se siembra en la primera ejecución.
# Los verticales (agro) y la administración por chat nacen apagados: se prenden
# con un perfil, desde el panel o con ALDIA_MODULOS.
MODULOS_DEFAULT = [
    {"clave": "stock", "nombre": "Stock", "descripcion": "Inventario y mercadería", "icono": "bi-box-seam", "categoria": "operaciones", "habilitado": True, "roles": "administrador,encargado_ventas,encargado_compras,encargado_deposito,auditor", "orden": 10},
    {"clave": "clientes", "nombre": "Clientes", "descripcion": "Gestión de clientes y deudores", "icono": "bi-people", "categoria": "ventas", "habilitado": True, "roles": "administrador,encargado_ventas,caja,auditor", "orden": 20},
    {"clave": "ventas", "nombre": "Ventas", "descripcion": "Remitos y facturación", "icono": "bi-receipt", "categoria": "ventas", "habilitado": True, "roles": "administrador,encargado_ventas,auditor", "orden": 30},
    {"clave": "liquidaciones_granos", "nombre": "Liquidaciones de Granos", "descripcion": "Cereales, acopio, mermas, cartas de porte y LPG", "icono": "bi-moisture", "categoria": "agro", "habilitado": False, "roles": "administrador,encargado_ventas,encargado_compras,finanzas,auditor", "orden": 35},
    {"clave": "liquidaciones_hacienda", "nombre": "Liquidaciones de Hacienda", "descripcion": "Tropas, DTE, RENSPA, desbaste y liquidación pecuaria", "icono": "bi-tags", "categoria": "agro", "habilitado": False, "roles": "administrador,encargado_ventas,encargado_compras,finanzas,auditor", "orden": 36},
    {"clave": "proveedores", "nombre": "Proveedores", "descripcion": "Proveedores, compras y pagos", "icono": "bi-truck", "categoria": "compras", "habilitado": True, "roles": "administrador,encargado_compras,auditor", "orden": 40},
    {"clave": "gastos", "nombre": "Gastos", "descripcion": "Facturas de gastos y notas", "icono": "bi-cash-stack", "categoria": "compras", "habilitado": True, "roles": "administrador,encargado_compras,finanzas,auditor", "orden": 50},
    {"clave": "cuentas_corrientes", "nombre": "Cuentas Corrientes", "descripcion": "Cobros y cuentas corrientes", "icono": "bi-journal-text", "categoria": "finanzas", "habilitado": True, "roles": "administrador,caja,finanzas,auditor", "orden": 60},
    {"clave": "caja", "nombre": "Caja", "descripcion": "Caja chica, bancos y chequera", "icono": "bi-safe", "categoria": "finanzas", "habilitado": True, "roles": "administrador,caja,finanzas,auditor", "orden": 70},
    {"clave": "iva", "nombre": "IVA", "descripcion": "Libro IVA ventas y compras", "icono": "bi-percent", "categoria": "finanzas", "habilitado": True, "roles": "administrador,finanzas,auditor", "orden": 80},
    {"clave": "administracion", "nombre": "Administración", "descripcion": "Usuarios, módulos y mantenimiento", "icono": "bi-gear", "categoria": "admin", "habilitado": True, "roles": "administrador", "orden": 90},
    {"clave": "administracion_por_chat", "nombre": "Administración por chat", "descripcion": "Deja que el asistente de IA cree y borre usuarios, prenda o apague módulos y borre movimientos de caja. Apagado, eso se hace solo desde el panel.", "icono": "bi-shield-exclamation", "categoria": "admin", "habilitado": False, "roles": "administrador", "orden": 95},
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


def _leer_variable_modulos() -> tuple[set[str] | None, list[str]]:
    """(módulos que pide ALDIA_MODULOS, claves que no reconoce).

    Los módulos son None si la variable no está definida. Acepta claves de
    módulo y nombres de perfil separados por coma, y se pueden mezclar:
    `ALDIA_MODULOS=comercio,liquidaciones_granos`. Administración va siempre.
    """
    crudo = os.getenv(VARIABLE_MODULOS, "").strip()
    if not crudo:
        return None, []
    validos = {m["clave"] for m in MODULOS_DEFAULT}
    activos = {MODULO_ADMINISTRACION}
    desconocidos = []
    for item in (x.strip().lower() for x in crudo.split(",")):
        if not item:
            continue
        if item in PERFILES_NEGOCIO:
            activos.update(PERFILES_NEGOCIO[item]["modulos_activos"])
        elif item in validos:
            activos.add(item)
        else:
            desconocidos.append(item)
    return activos, desconocidos


def modulos_fijados_por_entorno() -> bool:
    return bool(os.getenv(VARIABLE_MODULOS, "").strip())


def aplicar_modulos_del_entorno(db: Session) -> None:
    """Si ALDIA_MODULOS está definida, deja prendidos exactamente esos módulos.

    Corre en cada arranque, después de sembrar. Así una instalación armada con
    variables de entorno (docker compose, imagen preconfigurada) arranca siempre
    igual, y el panel no puede dejarla distinta de lo que dice su configuración
    (ver _exigir_modulos_editables).
    """
    activos, desconocidos = _leer_variable_modulos()
    if activos is None:
        return
    if desconocidos:
        validos = ", ".join(m["clave"] for m in MODULOS_DEFAULT)
        print(
            f"[ALdia] {VARIABLE_MODULOS}: se ignoran claves desconocidas "
            f"({', '.join(desconocidos)}). Módulos: {validos}. "
            f"Perfiles: {', '.join(PERFILES_NEGOCIO)}.",
            file=sys.stderr, flush=True,
        )
    for m in db.query(Modulo).all():
        m.habilitado = m.clave in activos
    db.commit()


def _exigir_modulos_editables() -> None:
    if modulos_fijados_por_entorno():
        raise ErrorDeNegocio(
            "MODULOS_FIJADOS_POR_ENTORNO",
            f"Los módulos activos los fija la variable {VARIABLE_MODULOS}: se cambian "
            "ahí y se reinicia ALdia. Desde acá solo se pueden editar los roles.",
        )


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
    """Activa los módulos del perfil elegido y desactiva los que no aplican (solo administrador).

    No toca la administración por chat: no es un rubro sino una decisión
    aparte, y cambiar de rubro no debería prenderla ni apagarla sin avisar.
    """
    perfil = PERFILES_NEGOCIO.get((clave_perfil or "").strip().lower())
    if not perfil:
        validos = ", ".join(sorted(PERFILES_NEGOCIO))
        raise HTTPException(
            status_code=404,
            detail=f"Perfil de negocio '{clave_perfil}' no encontrado. Perfiles válidos: {validos}",
        )
    _exigir_modulos_editables()
    seed_modulos(db)
    activos_set = set(perfil["modulos_activos"]) | {MODULO_ADMINISTRACION}
    modulos = db.query(Modulo).order_by(Modulo.orden).all()
    habilitados, deshabilitados = [], []
    for m in modulos:
        if m.clave == MODULO_ADMIN_POR_CHAT:
            continue
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


@router.get("/permisos")
def permisos_del_usuario(
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user_dep),
):
    """Qué puede leer y qué puede escribir el usuario conectado en cada módulo.

    Lo consulta el servidor MCP para mostrarle al asistente solo las
    herramientas que va a poder usar. Cada respuesta sale del mismo control que
    aplica la ruta real (security.puede_en_modulo), así que no pueden
    contradecirse; si el pedido declara un actor (X-Actor-User-ID), cuentan los
    permisos de los dos.
    """
    modulos = []
    for m in db.query(Modulo).order_by(Modulo.orden).all():
        habilitado = bool(m.habilitado)
        modulos.append({
            "clave": m.clave,
            "nombre": m.nombre,
            "habilitado": habilitado,
            "lectura": habilitado and puede_en_modulo(request, db, user, m.clave, "GET"),
            "escritura": habilitado and puede_en_modulo(request, db, user, m.clave, "POST"),
        })
    return {
        "usuario": user.username,
        "rol": user.rol,
        "modulos": modulos,
        # El registro de auditoría no es un módulo: sus lectores están fijos en
        # el código (ver routers/auditoria.py).
        "auditoria": (user.rol or "").lower() in ROLES_LECTURA_AUDITORIA,
        "fijados_por_entorno": modulos_fijados_por_entorno(),
    }


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
    if update_data.get("habilitado") is None:
        update_data.pop("habilitado", None)
    # El panel manda `habilitado` en cada guardado aunque solo cambien los
    # roles: se rechaza solo si de verdad cambia.
    elif bool(update_data["habilitado"]) != bool(modulo.habilitado):
        _exigir_modulos_editables()
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
