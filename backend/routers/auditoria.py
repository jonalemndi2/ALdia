"""
auditoria.py (router) - Consulta y exportacion del registro de auditoria.

SOLO LECTURA, A PROPOSITO
─────────────────────────
Este router expone UNICAMENTE metodos GET. No hay -- ni debe agregarse nunca --
un endpoint que borre, edite, "depure" ni "archive" filas de auditoria, tampoco
para el administrador: un log que el administrador puede borrar no sirve como
auditoria, porque el primer sospechoso de tapar un movimiento es justamente
quien tiene todos los permisos.

Si en el futuro el volumen molesta, la solucion correcta es exportar y archivar
el archivo de base fuera de la aplicacion (tarea del sistema operativo), no
darle a la aplicacion la capacidad de borrar su propio historial.

La inmutabilidad se refuerza en tres capas mas, descriptas en backend/auditoria.py:
guardas ORM before_update/before_delete, MetaData propio (a salvo de reset-db) y
esta ausencia deliberada de rutas de escritura.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
import csv
import io

from database import get_db
from models import Usuario
from routers.auth import current_user_dep
from auditoria import RegistroAuditoria, ROLES_LECTURA_AUDITORIA

router = APIRouter()

TOPE_EXPORTACION = 20000  # filas por CSV; evita tumbar el servidor de un pedido


def require_lectura_auditoria(user: Usuario = Depends(current_user_dep)) -> Usuario:
    """Solo `administrador` y `auditor` pueden leer el registro.

    La lista esta fija en el codigo (ROLES_LECTURA_AUDITORIA) y NO sale de la
    tabla `modulos`: que el administrador pueda repartir el acceso de lectura
    desde una pantalla debilitaria la auditoria sin dejar rastro visible.
    """
    rol = (user.rol or "").lower()
    if rol not in ROLES_LECTURA_AUDITORIA:
        raise HTTPException(
            status_code=403,
            detail=(
                f"El registro de auditoria solo puede consultarlo un usuario con rol "
                f"administrador o auditor (su rol es '{rol or 'sin rol'}')."
            ),
        )
    return user


def _filtrar(
    db: Session,
    desde: str | None,
    hasta: str | None,
    usuario: str | None,
    modulo: str | None,
    accion: str | None,
    resultado: str | None,
    texto: str | None,
    canal: str | None = None,
    solicitante: str | None = None,
):
    q = db.query(RegistroAuditoria)
    # fecha_hora es 'YYYY-MM-DD HH:MM:SS': comparar contra 'YYYY-MM-DD' funciona
    # para el limite inferior; para el superior hay que incluir todo el dia.
    if desde:
        q = q.filter(RegistroAuditoria.fecha_hora >= f"{desde} 00:00:00")
    if hasta:
        q = q.filter(RegistroAuditoria.fecha_hora <= f"{hasta} 23:59:59")
    if usuario:
        q = q.filter(RegistroAuditoria.usuario == usuario)
    if modulo:
        q = q.filter(RegistroAuditoria.modulo == modulo)
    if accion:
        q = q.filter(RegistroAuditoria.accion == accion)
    # Por donde entro la operacion (web, openclaw, whatsapp, telegram) y quien
    # la pidio del otro lado del canal.
    if canal:
        q = q.filter(RegistroAuditoria.canal == canal)
    if solicitante:
        q = q.filter(RegistroAuditoria.solicitante == solicitante)
    if resultado:
        q = q.filter(RegistroAuditoria.resultado == resultado)
    if texto:
        patron = f"%{texto}%"
        q = q.filter(
            RegistroAuditoria.descripcion.ilike(patron)
            | RegistroAuditoria.numero_registro.ilike(patron)
            | RegistroAuditoria.ruta.ilike(patron)
        )
    return q


def _fila(r: RegistroAuditoria) -> dict:
    return {
        "id": r.id,
        "fecha_hora": r.fecha_hora,
        "usuario": r.usuario,
        "usuario_id": r.usuario_id,
        "rol": r.rol,
        "modulo": r.modulo,
        "accion": r.accion,
        "metodo": r.metodo,
        "ruta": r.ruta,
        "tipo_registro": r.tipo_registro,
        "numero_registro": r.numero_registro,
        "descripcion": r.descripcion,
        "valor_anterior": r.valor_anterior,
        "valor_nuevo": r.valor_nuevo,
        "ip": r.ip,
        "resultado": r.resultado,
        "codigo_http": r.codigo_http,
        # Origen: `usuario` es la cuenta autenticada; si esa cuenta la usa un
        # agente, `solicitante` dice qué persona del otro lado pidió la operación.
        "actor_tipo": getattr(r, "actor_tipo", "persona") or "persona",
        "canal": getattr(r, "canal", "web") or "web",
        "agente": getattr(r, "agente", "") or "",
        "solicitante": getattr(r, "solicitante", "") or "",
    }


@router.get("/")
def consultar_auditoria(
    desde: str = Query(None, description="Fecha inicial YYYY-MM-DD (inclusive)"),
    hasta: str = Query(None, description="Fecha final YYYY-MM-DD (inclusive)"),
    usuario: str = Query(None),
    modulo: str = Query(None),
    accion: str = Query(None),
    resultado: str = Query(None, description="exito | rechazado"),
    texto: str = Query(None, description="Busqueda libre en descripcion/numero/ruta"),
    canal: str = Query(None, description="web | openclaw | whatsapp | telegram"),
    solicitante: str = Query(None, description="Quien pidio la operacion (numero, user_id)"),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_lectura_auditoria),
):
    """Consultar el registro, ordenado por fecha descendente y paginado.

    El registro crece indefinidamente (una fila por escritura), por eso la
    consulta es siempre paginada: nunca devuelve la tabla entera.
    """
    q = _filtrar(db, desde, hasta, usuario, modulo, accion, resultado, texto,
                 canal, solicitante)
    total = q.count()
    filas = (
        q.order_by(RegistroAuditoria.fecha_hora.desc(), RegistroAuditoria.id.desc())
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
        .all()
    )
    return {
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "paginas": max(1, (total + por_pagina - 1) // por_pagina),
        "filas": [_fila(r) for r in filas],
    }


@router.get("/filtros")
def valores_de_filtro(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_lectura_auditoria),
):
    """Valores presentes en el registro, para poblar los desplegables de la pantalla."""
    def distintos(columna):
        return sorted({v for (v,) in db.query(columna).distinct().all() if v})

    return {
        "usuarios": distintos(RegistroAuditoria.usuario),
        "modulos": distintos(RegistroAuditoria.modulo),
        "acciones": distintos(RegistroAuditoria.accion),
        "resultados": distintos(RegistroAuditoria.resultado),
    }


@router.get("/exportar.csv")
def exportar_csv(
    desde: str = Query(None),
    hasta: str = Query(None),
    usuario: str = Query(None),
    modulo: str = Query(None),
    accion: str = Query(None),
    resultado: str = Query(None),
    texto: str = Query(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_lectura_auditoria),
):
    """Exportar a CSV el resultado del filtro (hasta TOPE_EXPORTACION filas).

    Exportar es una LECTURA: no modifica ni vacia el registro.
    """
    q = _filtrar(db, desde, hasta, usuario, modulo, accion, resultado, texto)
    filas = (
        q.order_by(RegistroAuditoria.fecha_hora.desc(), RegistroAuditoria.id.desc())
        .limit(TOPE_EXPORTACION)
        .all()
    )

    columnas = [
        "id", "fecha_hora", "usuario", "usuario_id", "rol", "modulo", "accion",
        "metodo", "ruta", "tipo_registro", "numero_registro", "descripcion",
        "valor_anterior", "valor_nuevo", "ip", "resultado", "codigo_http",
    ]
    buffer = io.StringIO()
    # delimitador ';' y BOM: es lo que Excel en espanol abre bien de un doble clic.
    escritor = csv.DictWriter(buffer, fieldnames=columnas, delimiter=";",
                              quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    escritor.writeheader()
    for r in filas:
        escritor.writerow(_fila(r))

    contenido = "﻿" + buffer.getvalue()
    return Response(
        content=contenido.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="auditoria.csv"'},
    )
