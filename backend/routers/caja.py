"""
caja.py - Router para Caja y Chequera
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

import medios_de_pago
from database import get_db
from dinero import a_pesos
from models import Caja, Chequera
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
    new_caja = Caja(**caja_data.model_dump())
    db.add(new_caja)
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
    
    db.delete(caja)
    db.commit()
    return {"message": "Movimiento eliminado correctamente"}
