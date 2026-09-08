"""Operaciones comunes sobre el libro inmutable de tesoreria.

Un movimiento confirmado no se borra ni se sobreescribe para fingir que nunca
existio.  Al anular la operacion que lo origino se marca como reversado y se
agrega el asiento contrario, enlazado por ``reversa_de``.  Centralizarlo aca
evita que cobros, pagos y cheques implementen criterios distintos.
"""
from sqlalchemy.orm import Session

from models import MovimientoTesoreria


def revertir(
    db: Session,
    movimiento: MovimientoTesoreria,
    *,
    fecha: str,
    origen_tipo: str,
    origen_id: int,
    referencia: str,
    descripcion: str,
) -> MovimientoTesoreria:
    """Agrega la contrapartida de ``movimiento`` sin borrar el original."""
    if movimiento.estado != "confirmado":
        raise ValueError("Solo se puede revertir un movimiento confirmado")

    movimiento.estado = "reversado"
    reversa = MovimientoTesoreria(
        cuenta_id=movimiento.cuenta_id,
        fecha=fecha,
        sentido="egreso" if movimiento.sentido == "ingreso" else "ingreso",
        monto=movimiento.monto,
        origen_tipo=origen_tipo,
        origen_id=origen_id,
        referencia=referencia,
        descripcion=descripcion,
        estado="confirmado",
        reversa_de=movimiento.id,
    )
    db.add(reversa)
    return reversa
