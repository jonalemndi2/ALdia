"""
pagos.py - Router para Pagos a Proveedores
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

import saldos
from database import get_db
from models import Pago, Proveedor, Caja, Chequera
from schemas import PagoCreate, PagoResponse
from secuencias import siguiente_numero

router = APIRouter()


def _es_cheque(tipo: str) -> bool:
    return "cheque" in (tipo or "").strip().lower()


@router.get("/", response_model=List[PagoResponse])
def get_pagos(fecha: str = None, proveedor: str = None, db: Session = Depends(get_db)):
    query = db.query(Pago)
    if fecha:
        query = query.filter(Pago.fecha == fecha)
    if proveedor:
        query = query.filter(Pago.proveedor == proveedor)
    return query.order_by(Pago.ordpago.desc()).all()


@router.post("/", response_model=PagoResponse)
def create_pago(pago_data: PagoCreate, db: Session = Depends(get_db)):
    """Registrar un pago a proveedor con todos sus efectos contables.

    Igual que en cobros: antes solo se insertaba la fila y el descuento del saldo
    del proveedor y el egreso de caja se hacian en el navegador contra una base
    local que ya no existe, perdiendose en silencio.
    """
    proveedor = db.query(Proveedor).filter(Proveedor.cuit == pago_data.proveedor).first()
    if not proveedor:
        raise HTTPException(
            status_code=404,
            detail=f"El proveedor {pago_data.proveedor} no existe: no se puede registrar el pago",
        )

    # Numero de orden de pago desde el contador de la serie "pago".
    # Ver backend/secuencias.py.
    new_ord = siguiente_numero(db, "pago")

    # Los campos del cheque no son columnas de `pagos`: se usan mas abajo.
    datos = pago_data.model_dump(exclude={"banco", "vencimiento", "cheque_id"})
    new_pago = Pago(ordpago=new_ord, **datos)
    db.add(new_pago)

    # 1) El pago cancela deuda propia: baja el saldo del proveedor. La escritura
    #    del saldo pasa SIEMPRE por backend/saldos.py (centavos enteros, exacto).
    saldos.aplicar_a_proveedor(db, proveedor.cuit, -pago_data.monto)

    # 2) Salida de dinero.
    if pago_data.cheque_id is not None:
        # Se paga endosando un cheque de tercero que ya teniamos. No sale plata
        # de caja: se marca ese cheque como usado para que no se pueda endosar
        # dos veces (antes no se marcaba y el mismo cheque seguia disponible).
        cheque = db.query(Chequera).filter(Chequera.id == pago_data.cheque_id).first()
        if not cheque:
            raise HTTPException(status_code=404, detail="El cheque indicado no existe")
        if (cheque.pagado or "").strip():
            raise HTTPException(
                status_code=400,
                detail=f"El cheque {cheque.numcheque} ya fue utilizado ({cheque.pagado})",
            )
        cheque.pagado = f"Pago N° {new_ord} - {pago_data.fecha}"
    elif _es_cheque(pago_data.tipo):
        # Cheque propio: se registra como emitido y no sale de caja hasta que se debita.
        db.add(Chequera(
            numcheque=pago_data.referencia or "",
            tipo=0,  # 0 = emitido
            monto=pago_data.monto,
            banco=pago_data.banco or "",
            vencimiento=pago_data.vencimiento or pago_data.fecha,
            cuit=proveedor.cuit,
            nombre=proveedor.nombre or "",
            descripcion=f"Pago N° {new_ord}",
        ))
    else:
        db.add(Caja(
            referencia=f"PAGO {new_ord}",
            fecha=pago_data.fecha,
            debe=0,
            haber=pago_data.monto,
            descripcion=f"Pago a {proveedor.nombre or proveedor.cuit}",
        ))

    db.commit()
    db.refresh(new_pago)
    return new_pago


@router.delete("/{ordpago}")
def delete_pago(ordpago: int, db: Session = Depends(get_db)):
    """Anular un pago revirtiendo sus efectos (saldo del proveedor y caja)."""
    pago = db.query(Pago).filter(Pago.ordpago == ordpago).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    saldos.aplicar_a_proveedor(db, pago.proveedor, +(pago.monto or 0))

    mov = db.query(Caja).filter(Caja.referencia == f"PAGO {ordpago}").first()
    if mov:
        db.delete(mov)

    # Si se habia endosado un cheque de tercero, vuelve a quedar disponible.
    endosado = db.query(Chequera).filter(
        Chequera.pagado.like(f"Pago N° {ordpago} -%")
    ).first()
    if endosado:
        endosado.pagado = ""

    db.delete(pago)
    db.commit()
    return {"message": "Pago eliminado correctamente"}
