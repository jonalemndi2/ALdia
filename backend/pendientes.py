"""
pendientes.py - Operaciones que esperan una aclaracion antes de ejecutarse.

EL PROBLEMA QUE RESUELVE
========================
`confirmar=true` alcanza para "¿estas seguro?", pero no para una ambiguedad:

    Usuario:  "Jose me pago la factura con este cheque."
    Sistema:  "Hay dos clientes llamados Jose Perez. ¿Cual?"

Sin estado, el agente tiene que volver a armar la operacion entera con el dato
corregido. Puede cambiar otra cosa sin querer, y el usuario ya dio su
conformidad sobre algo que no es exactamente lo que se va a ejecutar.

COMO FUNCIONA
=============
La operacion se guarda tal como iba a ejecutarse (metodo, ruta y cuerpo) junto
con el motivo por el que quedo trabada y los candidatos entre los que hay que
elegir. Confirmarla es decir "ejecuta lo que ya describiste, con esta
aclaracion": el servidor mezcla la correccion en el cuerpo original y reejecuta
la MISMA peticion.

POR QUE SE GUARDA LA PETICION Y NO UNA LLAMADA A UNA FUNCION
============================================================
Reejecutar la peticion la hace pasar de nuevo por todo lo que ya existe:
permisos, validaciones, auditoria e idempotencia. Y funciona para cualquier
operacion sin que las 44 herramientas del MCP tengan que saber que esto existe.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from database import Base

# Cuanto vive una operacion sin confirmar. Una aclaracion conversacional ocurre
# en minutos; pasado ese rato, los datos del negocio pueden haber cambiado y
# reejecutar a ciegas seria peligroso.
VIGENCIA = timedelta(hours=1)

ESTADO_PENDIENTE = "pendiente"
ESTADO_CONFIRMADA = "confirmada"
ESTADO_CANCELADA = "cancelada"
ESTADO_EXPIRADA = "expirada"

# Motivos por los que una operacion queda trabada. Son codigos estables para
# que el agente pueda decidir sin interpretar texto.
MOTIVO_AMBIGUO = "AMBIGUEDAD"
MOTIVO_CONFIRMACION = "CONFIRMACION_REQUERIDA"


class OperacionPendiente(Base):
    __tablename__ = "operaciones_pendientes"

    id = Column(String(50), primary_key=True)
    # La peticion original, para poder reejecutarla igual.
    metodo = Column(String(10), nullable=False)
    ruta = Column(String(300), nullable=False)
    cuerpo = Column(Text, default="{}")

    # Por que quedo trabada y entre que opciones hay que elegir.
    motivo = Column(String(40), default=MOTIVO_AMBIGUO)
    descripcion = Column(String(500), default="")
    candidatos = Column(Text, default="[]")
    campo = Column(String(60), default="")   # que campo del cuerpo hay que corregir

    estado = Column(String(20), default=ESTADO_PENDIENTE)
    usuario = Column(String(80), default="")   # quien la creo: solo el puede confirmarla
    creada = Column(DateTime, default=datetime.utcnow)
    vence = Column(DateTime, default=lambda: datetime.utcnow() + VIGENCIA)


Index("ix_pendientes_usuario", OperacionPendiente.usuario)
Index("ix_pendientes_estado", OperacionPendiente.estado)


def nuevo_id() -> str:
    return f"pend_{uuid.uuid4().hex[:16]}"


def esta_vigente(op: OperacionPendiente) -> bool:
    return op.estado == ESTADO_PENDIENTE and datetime.utcnow() < op.vence


def a_dict(op: OperacionPendiente) -> dict:
    """Forma que ve quien la consulta. El cuerpo original NO se expone entero:
    puede tener datos que no hacen falta para elegir y solo agregan ruido."""
    return {
        "id": op.id,
        "estado": op.estado if esta_vigente(op) or op.estado != ESTADO_PENDIENTE
                  else ESTADO_EXPIRADA,
        "motivo": op.motivo,
        "descripcion": op.descripcion,
        "campo_a_corregir": op.campo,
        "candidatos": json.loads(op.candidatos or "[]"),
        "operacion": f"{op.metodo} {op.ruta}",
        "creada": op.creada.isoformat(timespec="seconds") if op.creada else None,
        "vence": op.vence.isoformat(timespec="seconds") if op.vence else None,
    }


def aplicar_correcciones(cuerpo: dict, correcciones: dict) -> dict:
    """Mezcla las correcciones sobre el cuerpo original.

    Mezcla PROFUNDA en los diccionarios anidados, para que corregir un campo no
    borre el resto del bloque que lo contiene.
    """
    resultado = dict(cuerpo or {})
    for clave, valor in (correcciones or {}).items():
        if isinstance(valor, dict) and isinstance(resultado.get(clave), dict):
            resultado[clave] = aplicar_correcciones(resultado[clave], valor)
        else:
            resultado[clave] = valor
    return resultado
