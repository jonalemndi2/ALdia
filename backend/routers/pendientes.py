"""
routers/pendientes.py - API de operaciones pendientes de aclaracion.

Ver backend/pendientes.py para el porque del diseno.
"""
import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

import pendientes as P
from database import get_db
from tiempo import ahora_utc
from models import Usuario
from routers.auth import current_user_dep

router = APIRouter()


class CrearPendiente(BaseModel):
    metodo: str
    ruta: str
    cuerpo: dict = {}
    motivo: str = P.MOTIVO_AMBIGUO
    descripcion: str = ""
    candidatos: list = []
    campo: str = ""


class Confirmacion(BaseModel):
    correcciones: dict = {}


def _buscar(db: Session, pendiente_id: str, user: Usuario) -> P.OperacionPendiente:
    op = db.query(P.OperacionPendiente).filter(
        P.OperacionPendiente.id == pendiente_id
    ).first()
    if not op:
        raise HTTPException(status_code=404, detail="La operación pendiente no existe")
    # Solo quien la creo puede confirmarla: una operacion pendiente lleva la
    # conformidad de una persona concreta sobre algo concreto.
    if op.usuario != user.username and (user.rol or "").lower() != "administrador":
        raise HTTPException(
            status_code=403,
            detail="Esa operación pendiente la creó otro usuario",
        )
    return op


@router.post("/")
def crear(
    datos: CrearPendiente,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user_dep),
):
    """Guardar una operación que espera una aclaración para poder ejecutarse."""
    ruta = (datos.ruta or "").strip()
    if not ruta.startswith("/api/"):
        raise HTTPException(status_code=400, detail="La ruta debe empezar con /api/")
    # Sin esto, una operacion pendiente podria apuntar a este mismo router y
    # confirmarla dispararia una cadena de confirmaciones.
    if ruta.startswith("/api/pendientes"):
        raise HTTPException(
            status_code=400,
            detail="Una operación pendiente no puede apuntar al módulo de pendientes",
        )
    if datos.metodo.upper() not in ("POST", "PUT", "PATCH", "DELETE"):
        raise HTTPException(status_code=400, detail="Método no admitido")

    op = P.OperacionPendiente(
        id=P.nuevo_id(),
        metodo=datos.metodo.upper(),
        ruta=ruta[:300],
        cuerpo=json.dumps(datos.cuerpo or {}, ensure_ascii=False),
        motivo=(datos.motivo or P.MOTIVO_AMBIGUO)[:40],
        descripcion=(datos.descripcion or "")[:500],
        candidatos=json.dumps(datos.candidatos or [], ensure_ascii=False)[:8000],
        campo=(datos.campo or "")[:60],
        usuario=user.username,
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    return P.a_dict(op)


@router.get("/")
def listar(
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user_dep),
):
    """Las operaciones que esperan una aclaración de este usuario."""
    q = db.query(P.OperacionPendiente).filter(
        P.OperacionPendiente.estado == P.ESTADO_PENDIENTE
    )
    if (user.rol or "").lower() != "administrador":
        q = q.filter(P.OperacionPendiente.usuario == user.username)
    filas = q.order_by(P.OperacionPendiente.creada.desc()).limit(50).all()
    vigentes = [f for f in filas if P.esta_vigente(f)]
    return {"total": len(vigentes), "operaciones": [P.a_dict(f) for f in vigentes]}


@router.get("/{pendiente_id}")
def ver(
    pendiente_id: str,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user_dep),
):
    return P.a_dict(_buscar(db, pendiente_id, user))


@router.post("/{pendiente_id}/cancelar")
def cancelar(
    pendiente_id: str,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user_dep),
):
    """Descartar una operación pendiente sin ejecutarla."""
    op = _buscar(db, pendiente_id, user)
    if op.estado != P.ESTADO_PENDIENTE:
        raise HTTPException(status_code=409, detail=f"La operación ya está {op.estado}")
    op.estado = P.ESTADO_CANCELADA
    db.commit()
    return {"id": op.id, "estado": op.estado}


@router.post("/{pendiente_id}/confirmar")
async def confirmar(
    pendiente_id: str,
    confirmacion: Confirmacion,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user_dep),
):
    """Aplicar la aclaración y ejecutar la operación original.

    Reejecuta la MISMA petición que quedó guardada, con las correcciones
    mezcladas. Al pasar de nuevo por la aplicación entera, se aplican los
    permisos, las validaciones, la auditoría y la idempotencia exactamente igual
    que si la operación hubiera entrado directo: no hay un camino paralelo con
    reglas propias que se pueda desincronizar.
    """
    op = _buscar(db, pendiente_id, user)

    if op.estado != P.ESTADO_PENDIENTE:
        raise HTTPException(
            status_code=409,
            detail=f"La operación ya está {op.estado}: no se puede volver a confirmar",
        )
    if ahora_utc() >= op.vence:
        op.estado = P.ESTADO_EXPIRADA
        db.commit()
        raise HTTPException(
            status_code=409,
            detail=(
                "La operación pendiente venció. Los datos del negocio pueden haber "
                "cambiado: vuelva a pedirla desde cero."
            ),
        )

    cuerpo = P.aplicar_correcciones(json.loads(op.cuerpo or "{}"),
                                    confirmacion.correcciones)

    # Se marca ANTES de ejecutar: si la ejecución falla a mitad, la operación no
    # queda disponible para dispararse otra vez sin que nadie lo revise.
    op.estado = P.ESTADO_CONFIRMADA
    db.commit()

    # Datos que se necesitan después de soltar la sesión.
    metodo, ruta, op_id = op.metodo, op.ruta, op.id

    # IMPRESCINDIBLE soltar la conexión antes de reejecutar. Esta petición es un
    # POST, así que ya abrió su transacción de escritura (BEGIN IMMEDIATE, ver
    # database.py); la reejecución interna abre la suya y quedarían trabadas una
    # contra otra — la petición esperándose a sí misma.
    db.close()

    # Reejecutar por dentro de la aplicación, sin salir a la red.
    cabeceras = {"Content-Type": "application/json"}
    for nombre in ("authorization", "x-actor-user-id", "x-aldia-canal",
                   "x-aldia-agente", "x-aldia-solicitante"):
        valor = request.headers.get(nombre)
        if valor:
            cabeceras[nombre] = valor
    # El identificador de idempotencia se deriva del pendiente: si el agente
    # reintenta la confirmación, la operación no se ejecuta dos veces.
    cabeceras["x-operation-id"] = f"pendiente_{op_id}"

    transporte = httpx.ASGITransport(app=request.app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://interno") as cliente:
        respuesta = await cliente.request(metodo, ruta, json=cuerpo, headers=cabeceras)

    try:
        datos = respuesta.json()
    except ValueError:
        datos = {"detail": respuesta.text[:500]}

    if respuesta.status_code >= 400:
        # La operación se ejecutó y el servidor la rechazó. El pendiente queda
        # confirmado igual: se resolvió, y el resultado fue un rechazo.
        raise HTTPException(status_code=respuesta.status_code, detail=datos.get("detail", datos))

    return {
        "id": op_id,
        "estado": P.ESTADO_CONFIRMADA,
        "ejecutada": f"{metodo} {ruta}",
        "resultado": datos,
    }
