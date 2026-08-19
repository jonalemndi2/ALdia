"""
cobros.py - Router para Cobros
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

import saldos
import medios_de_pago
from database import get_db
from models import Cobro, Cliente, Caja, Chequera
from schemas import CobroCreate, CobroResponse
from secuencias import siguiente_numero

router = APIRouter()


# La regla de que hacer con cada medio de pago vive en backend/medios_de_pago.py.
# Antes era esta misma funcion de dos lineas, duplicada aca y en el otro router:
# cualquier medio nuevo habia que acordarse de contemplarlo en los dos lados, y
# todo lo que no dijera "cheque" caia en la rama del efectivo por descarte.
_es_cheque = medios_de_pago.es_cheque


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

    # Numero de recibo desde el contador de la serie "cobro", no un max+1.
    # Ver backend/secuencias.py.
    new_ord = siguiente_numero(db, "cobro")

    # Los campos del cheque no son columnas de `cobros`: se usan mas abajo.
    datos = cobro_data.model_dump(exclude={"banco", "vencimiento", "cheque_id"})
    new_cobro = Cobro(ordcobro=new_ord, **datos)
    db.add(new_cobro)

    # 1) El cobro cancela deuda: baja el saldo del cliente. La escritura del
    #    saldo pasa SIEMPRE por backend/saldos.py (centavos enteros, exacto).
    saldos.aplicar_a_cliente(db, cliente.cuit, -cobro_data.monto)

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
            # Una transferencia o una tarjeta caen en la cuenta de banco: la
            # plata entro, pero no esta en el cajon y no aparece al cerrar caja.
            cuenta=medios_de_pago.cuenta_de(cobro_data.tipo),
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
    saldos.aplicar_a_cliente(db, cobro.cliente, +(cobro.monto or 0))

    # Revertir el movimiento de caja generado al crearlo.
    mov = db.query(Caja).filter(Caja.referencia == f"COBRO {ordcobro}").first()
    if mov:
        db.delete(mov)

    db.delete(cobro)
    db.commit()
    return {"message": "Cobro eliminado correctamente"}
