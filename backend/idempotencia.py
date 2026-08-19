"""
idempotencia.py - Que un reintento no ejecute la operacion dos veces.

EL PROBLEMA QUE RESUELVE
========================
Un agente reintenta cuando no recibe respuesta. Si la operacion ya se ejecuto y
lo que se perdio fue la respuesta, el reintento la ejecuta de nuevo: dos cobros,
dos facturas. Con facturacion electronica es peor, porque un timeout no
significa que AFIP no haya procesado el pedido.

Este riesgo NO existia cuando el unico cliente era un navegador con una persona
mirando la pantalla: nace con el agente, que reintenta a ciegas.

COMO FUNCIONA
=============
Quien llama manda un identificador propio de la operacion en la cabecera
`X-Operation-Id`. La primera vez se ejecuta y se guarda la respuesta; si llega
otra vez el mismo identificador, se devuelve la respuesta original SIN volver a
ejecutar nada.

La tabla vive en el mismo MetaData que la auditoria, y por el mismo motivo: no
debe desaparecer con un borrado de datos del comercio, porque entonces un
reintento posterior volveria a ejecutar.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from auditoria import BaseAuditoria
from database import SessionLocal

CABECERA_OPERACION = "x-operation-id"

# Cuanto se recuerda una operacion. Un reintento razonable ocurre en segundos o
# minutos; guardar mas tiempo solo hace crecer la tabla sin aportar seguridad.
RETENCION = timedelta(days=7)


class OperacionProcesada(BaseAuditoria):
    __tablename__ = "operaciones_procesadas"

    operacion_id = Column(String(120), primary_key=True)
    metodo = Column(String(10), default="")
    ruta = Column(String(300), default="")
    # Huella de los parametros: detecta que el mismo identificador se reuse con
    # datos distintos, que es un error de quien llama y no un reintento.
    huella = Column(String(64), default="")
    estado_http = Column(Integer, default=200)
    respuesta = Column(Text, default="")
    usuario = Column(String(80), default="")
    creada = Column(DateTime, default=datetime.utcnow)


Index("ix_operaciones_creada", OperacionProcesada.creada)


class OperacionConflictiva(Exception):
    """Mismo identificador de operacion, pero con otros datos."""


def huella_de(metodo: str, ruta: str, cuerpo: bytes) -> str:
    base = f"{metodo}|{ruta}|".encode() + (cuerpo or b"")
    return hashlib.sha256(base).hexdigest()


def buscar(operacion_id: str, huella: str) -> OperacionProcesada | None:
    """La respuesta ya dada para esa operacion, si existe.

    Lanza OperacionConflictiva si el identificador ya se uso para otra cosa:
    devolver la respuesta vieja seria mentir, y ejecutar seria arriesgar un
    duplicado. Lo correcto es avisar.
    """
    if not operacion_id:
        return None
    sesion = SessionLocal()
    try:
        previa = (
            sesion.query(OperacionProcesada)
            .filter(OperacionProcesada.operacion_id == operacion_id)
            .first()
        )
        if previa is None:
            return None
        if previa.huella and huella and previa.huella != huella:
            raise OperacionConflictiva(
                f"El identificador de operacion '{operacion_id}' ya se uso para otra "
                f"operacion distinta ({previa.metodo} {previa.ruta}). Use uno nuevo."
            )
        sesion.expunge(previa)
        return previa
    finally:
        sesion.close()


def registrar(
    operacion_id: str,
    metodo: str,
    ruta: str,
    huella: str,
    estado_http: int,
    respuesta: bytes,
    usuario: str,
) -> None:
    """Guarda la respuesta para poder repetirla ante un reintento."""
    if not operacion_id:
        return
    sesion = SessionLocal()
    try:
        sesion.add(OperacionProcesada(
            operacion_id=operacion_id[:120],
            metodo=metodo[:10],
            ruta=ruta[:300],
            huella=huella,
            estado_http=estado_http,
            respuesta=(respuesta or b"").decode("utf-8", "replace")[:20000],
            usuario=(usuario or "")[:80],
        ))
        sesion.commit()
    except Exception:
        # Una carrera entre dos reintentos simultaneos puede chocar contra la
        # clave primaria. No es un problema: significa que la otra ya la guardo.
        sesion.rollback()
    finally:
        sesion.close()


def purgar() -> int:
    """Borra las operaciones mas viejas que la ventana de retencion."""
    sesion = SessionLocal()
    try:
        corte = datetime.utcnow() - RETENCION
        borradas = (
            sesion.query(OperacionProcesada)
            .filter(OperacionProcesada.creada < corte)
            .delete(synchronize_session=False)
        )
        sesion.commit()
        return borradas
    finally:
        sesion.close()


def cuerpo_de_conflicto(exc: OperacionConflictiva) -> bytes:
    return json.dumps({"detail": str(exc), "codigo": "OPERACION_CONFLICTIVA"},
                      ensure_ascii=False).encode()
