"""
caja.py - Router para Caja y Chequera
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
import re

import medios_de_pago
from libro_tesoreria import revertir as revertir_movimiento
from database import get_db
from dinero import a_pesos
from models import Caja, Chequera, Cobro, CuentaTesoreria, MovimientoTesoreria, Pago
from schemas import CajaCreate, CajaResponse

router = APIRouter()


@router.get("/", response_model=List[CajaResponse])
def get_caja(fecha: str = None, db: Session = Depends(get_db)):
    query = db.query(Caja)
    if fecha:
        query = query.filter(Caja.fecha == fecha)
    return query.order_by(Caja.id.desc()).all()


@router.post("/", response_model=CajaResponse)
def create_caja(caja_data: CajaCreate, db: Session = Depends(get_db)):
    cuenta = None
    if caja_data.cuenta_tesoreria_id is not None:
        cuenta = db.query(CuentaTesoreria).filter(
            CuentaTesoreria.id == caja_data.cuenta_tesoreria_id,
            CuentaTesoreria.activa.is_(True),
            CuentaTesoreria.clase == "caja_chica",
        ).first()
        if not cuenta:
            raise HTTPException(422, "El movimiento manual debe indicar una caja chica activa")

    new_caja = Caja(**caja_data.model_dump(exclude={"cuenta_tesoreria_id"}))
    db.add(new_caja)
    db.flush()
    if cuenta:
        db.add(MovimientoTesoreria(
            cuenta_id=cuenta.id,
            fecha=new_caja.fecha,
            sentido="ingreso" if new_caja.debe else "egreso",
            monto=new_caja.debe or new_caja.haber,
            origen_tipo="caja_manual",
            origen_id=new_caja.id,
            referencia=new_caja.referencia,
            descripcion=new_caja.descripcion,
        ))
    db.commit()
    db.refresh(new_caja)
    return new_caja


@router.get("/saldo")
def get_saldo(db: Session = Depends(get_db)):
    """Saldo actual de caja: suma de ingresos menos suma de egresos.

    Debe y haber estan en CENTAVOS, asi que la suma y la resta las hace SQLite
    con enteros y son exactas por muchos movimientos que haya. Solo al final se
    convierte a pesos, porque la API habla en pesos hacia afuera.
    """
    def _saldo(cuenta=None):
        # Session no expone .func: hay que usar sqlalchemy.func (antes daba 500).
        q = db.query(func.coalesce(func.sum(Caja.debe), 0),
                     func.coalesce(func.sum(Caja.haber), 0))
        if cuenta is not None:
            q = q.filter(Caja.cuenta == cuenta)
        debe, haber = q.first()
        return int(debe or 0) - int(haber or 0)

    # `saldo` sigue siendo el total de siempre, para no romper lo que ya lo lee.
    # Lo que se agrega es la apertura: cuanto de eso se puede contar cerrando la
    # caja a la noche, y cuanto esta en una cuenta.
    return {
        "saldo": a_pesos(_saldo()),
        "efectivo": a_pesos(_saldo(medios_de_pago.CUENTA_EFECTIVO)),
        "banco": a_pesos(_saldo(medios_de_pago.CUENTA_BANCO)),
    }


@router.get("/chequera")
def get_chequera(db: Session = Depends(get_db)):
    """Cheques en cartera y emitidos. `monto` sale en pesos (en la base son centavos)."""
    cheques = db.query(Chequera).order_by(Chequera.id.desc()).all()
    return [
        {
            "id": c.id,
            "numcheque": c.numcheque,
            "tipo": c.tipo,
            "monto": a_pesos(c.monto),
            "vencimiento": c.vencimiento,
            "banco": c.banco,
            "cuit": c.cuit,
            "nombre": c.nombre,
            "descripcion": c.descripcion,
            "pagado": c.pagado,
        }
        for c in cheques
    ]


@router.delete("/{caja_id}")
def delete_caja(caja_id: int, db: Session = Depends(get_db)):
    caja = db.query(Caja).filter(Caja.id == caja_id).first()
    if not caja:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")

    # Cobros y pagos se anulan desde su propio circuito, que tambien restaura
    # la cuenta corriente y revierte tesoreria. Borrar solo esta fila dejaba
    # los tres libros diciendo cosas distintas.
    origen = re.fullmatch(r"(COBRO|PAGO)\s+(\d+)", (caja.referencia or "").strip())
    if origen:
        numero = int(origen.group(2))
        existe = (
            db.query(Cobro).filter(Cobro.ordcobro == numero).first()
            if origen.group(1) == "COBRO"
            else db.query(Pago).filter(Pago.ordpago == numero).first()
        )
        if existe:
            endpoint = "cobros" if origen.group(1) == "COBRO" else "pagos"
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Este movimiento pertenece a {origen.group(1).lower()} {numero}; "
                    f"anule /api/{endpoint}/{numero} para revertir todos sus efectos"
                ),
            )

    tesoreria = db.query(MovimientoTesoreria).filter(
        MovimientoTesoreria.origen_tipo == "caja_manual",
        MovimientoTesoreria.origen_id == caja_id,
        MovimientoTesoreria.estado == "confirmado",
    ).first()
    if tesoreria:
        revertir_movimiento(
            db, tesoreria, fecha=caja.fecha,
            origen_tipo="reversa_caja_manual", origen_id=caja_id,
            referencia=f"ANULA CAJA MANUAL {caja_id}",
            descripcion="Reversa auditable de movimiento manual de caja",
        )

    db.delete(caja)
    db.commit()
    return {"message": "Movimiento eliminado correctamente"}
