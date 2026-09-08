"""
pagos.py - Router para Pagos a Proveedores
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import update, or_
from typing import List

import saldos
import medios_de_pago
from libro_tesoreria import revertir as revertir_movimiento
from database import get_db
from models import Pago, Proveedor, Caja, Chequera, CuentaTesoreria, MovimientoTesoreria
from schemas import PagoCreate, PagoResponse
from secuencias import siguiente_numero

router = APIRouter()


# La regla de que hacer con cada medio de pago vive en backend/medios_de_pago.py.
# Antes era esta misma funcion de dos lineas, duplicada aca y en el otro router:
# cualquier medio nuevo habia que acordarse de contemplarlo en los dos lados, y
# todo lo que no dijera "cheque" caia en la rama del efectivo por descarte.
_es_cheque = medios_de_pago.es_cheque


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
    medio = medios_de_pago.resolver(pago_data.tipo)
    cuenta = None
    if pago_data.cheque_id is not None:
        if not medio.es_valor:
            raise HTTPException(422, "cheque_id sólo se admite para pago con cheque de tercero")
    elif medio.clave == "transferencia" or medio.en_el_banco:
        if not pago_data.cuenta_tesoreria_id:
            raise HTTPException(422, "La transferencia debe indicar el banco origen")
        if not pago_data.referencia.strip():
            raise HTTPException(422, "La transferencia debe indicar una referencia")
        cuenta = db.query(CuentaTesoreria).filter(CuentaTesoreria.id == pago_data.cuenta_tesoreria_id).first()
        if not cuenta or not cuenta.activa or cuenta.clase != "banco":
            raise HTTPException(422, "La cuenta origen debe ser un banco activo")
    elif medio.clave == "efectivo":
        if not pago_data.cuenta_tesoreria_id:
            raise HTTPException(422, "El efectivo debe indicar la caja chica origen")
        cuenta = db.query(CuentaTesoreria).filter(CuentaTesoreria.id == pago_data.cuenta_tesoreria_id).first()
        if not cuenta or not cuenta.activa or cuenta.clase != "caja_chica":
            raise HTTPException(422, "La cuenta origen debe ser una caja chica activa")
    elif medio.es_valor:
        if not pago_data.cuenta_tesoreria_id:
            raise HTTPException(422, "El cheque propio debe seleccionar su cuenta bancaria")
        cuenta = db.query(CuentaTesoreria).filter(CuentaTesoreria.id == pago_data.cuenta_tesoreria_id).first()
        if not cuenta or not cuenta.activa or cuenta.clase != "banco":
            raise HTTPException(422, "La chequera propia debe pertenecer a una cuenta bancaria activa")
        if not all([pago_data.referencia.strip(), pago_data.vencimiento.strip()]):
            raise HTTPException(422, "El cheque propio requiere numero y vencimiento")
        pago_data.banco = cuenta.banco

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
        if int(cheque.monto or 0) != int(pago_data.monto):
            raise HTTPException(
                status_code=422,
                detail="En esta versión el cheque de tercero debe aplicarse por su monto exacto",
            )
        # Compare-and-set: aun fuera del middleware BEGIN IMMEDIATE, sólo una
        # transacción puede cambiar disponible -> endosado.
        usados = db.execute(update(Chequera).where(
            Chequera.id == pago_data.cheque_id,
            or_(Chequera.pagado == "", Chequera.pagado.is_(None)),
            Chequera.tipo == 1,
        ).values(pagado=f"Pago N° {new_ord} - {pago_data.fecha}"))
        if usados.rowcount != 1:
            raise HTTPException(409, "El cheque ya no está disponible")
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
            cuenta_tesoreria_id=cuenta.id,
        ))
    else:
        db.add(Caja(
            referencia=f"PAGO {new_ord}",
            fecha=pago_data.fecha,
            cuenta=medios_de_pago.cuenta_de(pago_data.tipo),
            debe=0,
            haber=pago_data.monto,
            descripcion=f"Pago a {proveedor.nombre or proveedor.cuit}",
        ))
        db.add(MovimientoTesoreria(
            cuenta_id=cuenta.id, fecha=pago_data.fecha, sentido="egreso",
            monto=pago_data.monto, origen_tipo="pago", origen_id=new_ord,
            referencia=pago_data.referencia,
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

    # El cheque propio emitido tambien es parte de la orden de pago. Antes la
    # orden se anulaba pero el cheque seguia pendiente (o incluso debitado),
    # dejando una obligacion bancaria sin proveedor que la explicara.
    cheque_propio = db.query(Chequera).filter(
        Chequera.tipo == 0,
        Chequera.descripcion == f"Pago N° {ordpago}",
    ).first()
    if cheque_propio:
        estado_cheque = (cheque_propio.pagado or "").strip()
        if estado_cheque.startswith("Debitado"):
            debito = db.query(MovimientoTesoreria).filter(
                MovimientoTesoreria.origen_tipo == "debito_cheque",
                MovimientoTesoreria.origen_id == cheque_propio.id,
                MovimientoTesoreria.estado == "confirmado",
            ).first()
            if not debito:
                raise HTTPException(
                    status_code=409,
                    detail="El cheque figura debitado pero no se encontro su movimiento de tesoreria",
                )
            revertir_movimiento(
                db, debito, fecha=pago.fecha,
                origen_tipo="reversa_debito_cheque", origen_id=cheque_propio.id,
                referencia=f"ANULA DEBITO CHEQUE {cheque_propio.id}",
                descripcion=f"Reversa por anulacion del pago N° {ordpago}",
            )
        elif estado_cheque:
            raise HTTPException(
                status_code=409,
                detail=f"No se puede anular el pago: el cheque tiene estado '{estado_cheque}'",
            )
        cheque_propio.pagado = f"Anulado {pago.fecha}"

    saldos.aplicar_a_proveedor(db, pago.proveedor, +(pago.monto or 0))

    mov = db.query(Caja).filter(Caja.referencia == f"PAGO {ordpago}").first()
    if mov:
        db.delete(mov)
    tesoreria = db.query(MovimientoTesoreria).filter(
        MovimientoTesoreria.origen_tipo == "pago",
        MovimientoTesoreria.origen_id == ordpago,
        MovimientoTesoreria.estado == "confirmado",
    ).first()
    if tesoreria:
        revertir_movimiento(
            db, tesoreria, fecha=pago.fecha,
            origen_tipo="reversa_pago", origen_id=ordpago,
            referencia=f"ANULA PAGO {ordpago}",
            descripcion="Reversa auditable de pago",
        )

    # Si se habia endosado un cheque de tercero, vuelve a quedar disponible.
    endosado = db.query(Chequera).filter(
        Chequera.pagado.like(f"Pago N° {ordpago} -%")
    ).first()
    if endosado:
        endosado.pagado = ""

    db.delete(pago)
    db.commit()
    return {"message": "Pago eliminado correctamente"}
