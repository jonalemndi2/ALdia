"""
cobros.py - Router para Cobros
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import Cobro, Cliente, Caja, Chequera
from schemas import CobroCreate, CobroResponse

router = APIRouter()


def _es_cheque(tipo: str) -> bool:
    return "cheque" in (tipo or "").strip().lower()


@router.get("/", response_model=List[CobroResponse])
def get_cobros(fecha: str = None, cliente: str = None, db: Session = Depends(get_db)):
    query = db.query(Cobro)
    if fecha:
        query = query.filter(Cobro.fecha == fecha)
    if cliente:
        query = query.filter(Cobro.cliente == cliente)
    return query.order_by(Cobro.ordcobro.desc()).all()


@router.post("/", response_model=CobroResponse)
def create_cobro(cobro_data: CobroCreate, db: Session = Depends(get_db)):
    """Registrar un cobro y aplicar TODOS sus efectos contables.

    Antes este endpoint solo insertaba la fila del cobro: el descuento del saldo
    del cliente y el ingreso a caja los hacia el navegador contra una base local
    que ya no existe, con lo cual se perdian en silencio. Ahora se hace todo aca,
    en una sola transaccion, para que no pueda quedar un cobro registrado con el
    saldo del cliente sin actualizar.
    """
    cliente = db.query(Cliente).filter(Cliente.cuit == cobro_data.cliente).first()
    if not cliente:
        raise HTTPException(
            status_code=404,
            detail=f"El cliente {cobro_data.cliente} no existe: no se puede registrar el cobro",
        )

    last = db.query(Cobro).order_by(Cobro.ordcobro.desc()).first()
    new_ord = (last.ordcobro + 1) if last else 1

    # Los campos del cheque no son columnas de `cobros`: se usan mas abajo.
    datos = cobro_data.model_dump(exclude={"banco", "vencimiento", "cheque_id"})
    new_cobro = Cobro(ordcobro=new_ord, **datos)
    db.add(new_cobro)

    # 1) El cobro cancela deuda: baja el saldo del cliente.
    cliente.saldo = (cliente.saldo or 0) - cobro_data.monto  # centavos: exacto

    # 2) Ingreso de dinero. Un cheque no entra a caja hasta que se cobra: se
    #    registra en la chequera como valor a depositar.
    if _es_cheque(cobro_data.tipo):
        db.add(Chequera(
            numcheque=cobro_data.referencia or "",
            tipo=1,  # 1 = recibido/a cobrar
            monto=cobro_data.monto,
            banco=cobro_data.banco or "",
            # Vencimiento real del cheque; si no lo informan, la fecha del cobro.
            vencimiento=cobro_data.vencimiento or cobro_data.fecha,
            cuit=cliente.cuit,
            nombre=cliente.nombre or "",
            descripcion=f"Cobro N° {new_ord}",
        ))
    else:
        db.add(Caja(
            referencia=f"COBRO {new_ord}",
            fecha=cobro_data.fecha,
            debe=cobro_data.monto,
            haber=0,
            descripcion=f"Cobro a {cliente.nombre or cliente.cuit}",
        ))

    db.commit()
    db.refresh(new_cobro)
    return new_cobro


@router.delete("/{ordcobro}")
def delete_cobro(ordcobro: int, db: Session = Depends(get_db)):
    """Anular un cobro revirtiendo sus efectos (saldo del cliente y caja)."""
    cobro = db.query(Cobro).filter(Cobro.ordcobro == ordcobro).first()
    if not cobro:
        raise HTTPException(status_code=404, detail="Cobro no encontrado")

    # Revertir el saldo: si el cobro lo bajo, anularlo lo devuelve.
    cliente = db.query(Cliente).filter(Cliente.cuit == cobro.cliente).first()
    if cliente:
        cliente.saldo = (cliente.saldo or 0) + (cobro.monto or 0)

    # Revertir el movimiento de caja generado al crearlo.
    mov = db.query(Caja).filter(Caja.referencia == f"COBRO {ordcobro}").first()
    if mov:
        db.delete(mov)

    db.delete(cobro)
    db.commit()
    return {"message": "Cobro eliminado correctamente"}
