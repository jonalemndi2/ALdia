"""Cuentas concretas de caja/banco y sus movimientos inmutables."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import func, case, update, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from dinero import a_pesos
from models import CuentaTesoreria, MovimientoTesoreria, Chequera

router = APIRouter()


class CuentaEntrada(BaseModel):
    nombre: str
    clase: str
    banco: str = ""
    alias_cbu: str = ""
    moneda: str = "ARS"

    @field_validator("clase")
    @classmethod
    def clase_valida(cls, valor):
        if valor not in {"caja_chica", "banco"}:
            raise ValueError("clase debe ser caja_chica o banco")
        return valor

    @field_validator("moneda")
    @classmethod
    def moneda_valida(cls, valor):
        valor = valor.strip().upper()
        if valor not in {"ARS", "USD"}:
            raise ValueError("moneda debe ser ARS o USD")
        return valor


class OperacionCheque(BaseModel):
    cuenta_tesoreria_id: int
    fecha: str
    referencia: str = ""

    @field_validator("fecha")
    @classmethod
    def fecha_valida(cls, valor):
        from datetime import datetime
        datetime.strptime(valor, "%Y-%m-%d")
        return valor


@router.get("/cuentas")
def cuentas(solo_activas: bool = True, db: Session = Depends(get_db)):
    q = db.query(CuentaTesoreria)
    if solo_activas:
        q = q.filter(CuentaTesoreria.activa.is_(True))
    return q.order_by(CuentaTesoreria.clase, CuentaTesoreria.nombre).all()


@router.post("/cuentas")
def crear_cuenta(datos: CuentaEntrada, db: Session = Depends(get_db)):
    if datos.clase == "banco" and not datos.banco.strip():
        raise HTTPException(422, "Una cuenta bancaria debe indicar el banco")
    cuenta = CuentaTesoreria(**datos.model_dump())
    db.add(cuenta)
    try:
        db.commit(); db.refresh(cuenta)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe una cuenta con ese nombre")
    return cuenta


@router.get("/saldos")
def saldos(db: Session = Depends(get_db)):
    filas = db.query(
        CuentaTesoreria,
        func.coalesce(func.sum(case(
            (MovimientoTesoreria.sentido == "ingreso", MovimientoTesoreria.monto),
            else_=-MovimientoTesoreria.monto,
        )), 0),
    ).outerjoin(MovimientoTesoreria, MovimientoTesoreria.cuenta_id == CuentaTesoreria.id).group_by(CuentaTesoreria.id).all()
    return [{"id": c.id, "nombre": c.nombre, "clase": c.clase, "banco": c.banco,
             "moneda": c.moneda, "saldo": a_pesos(int(s))} for c, s in filas]


@router.get("/movimientos")
def movimientos(cuenta_id: int = None, db: Session = Depends(get_db)):
    q = db.query(MovimientoTesoreria)
    if cuenta_id:
        q = q.filter(MovimientoTesoreria.cuenta_id == cuenta_id)
    return q.order_by(MovimientoTesoreria.fecha.desc(), MovimientoTesoreria.id.desc()).all()


@router.get("/cheques")
def cheques(disponibles: bool = False, db: Session = Depends(get_db)):
    q = db.query(Chequera).filter(Chequera.tipo == 1)
    if disponibles:
        q = q.filter((Chequera.pagado == "") | (Chequera.pagado.is_(None)))
    return q.order_by(Chequera.vencimiento, Chequera.id).all()


def _banco_activo(db, cuenta_id):
    cuenta = db.query(CuentaTesoreria).filter(CuentaTesoreria.id == cuenta_id).first()
    if not cuenta or not cuenta.activa or cuenta.clase != "banco":
        raise HTTPException(422, "Debe seleccionar una cuenta bancaria activa")
    return cuenta


@router.post("/cheques/{cheque_id}/depositar")
def depositar(cheque_id: int, datos: OperacionCheque, db: Session = Depends(get_db)):
    cuenta = _banco_activo(db, datos.cuenta_tesoreria_id)
    cheque = db.query(Chequera).filter(Chequera.id == cheque_id, Chequera.tipo == 1).first()
    if not cheque:
        raise HTTPException(404, "Cheque recibido no encontrado")
    r = db.execute(update(Chequera).where(
        Chequera.id == cheque_id, or_(Chequera.pagado == "", Chequera.pagado.is_(None)),
    ).values(pagado=f"Depositado {datos.fecha}", cuenta_tesoreria_id=cuenta.id))
    if r.rowcount != 1:
        raise HTTPException(409, "El cheque ya no está disponible para depositar")
    db.add(MovimientoTesoreria(
        cuenta_id=cuenta.id, fecha=datos.fecha, sentido="ingreso", monto=cheque.monto,
        origen_tipo="deposito_cheque", origen_id=cheque.id,
        referencia=datos.referencia or cheque.numcheque, descripcion="Depósito de cheque recibido",
    ))
    db.commit()
    return {"ok": True, "cheque_id": cheque_id, "cuenta_id": cuenta.id}


@router.post("/cheques/{cheque_id}/marcar-debitado")
def marcar_debitado(cheque_id: int, datos: OperacionCheque, db: Session = Depends(get_db)):
    cuenta = _banco_activo(db, datos.cuenta_tesoreria_id)
    cheque = db.query(Chequera).filter(Chequera.id == cheque_id, Chequera.tipo == 0).first()
    if not cheque:
        raise HTTPException(404, "Cheque propio no encontrado")
    if cheque.cuenta_tesoreria_id != cuenta.id:
        raise HTTPException(422, "El cheque no pertenece a la cuenta bancaria seleccionada")
    r = db.execute(update(Chequera).where(
        Chequera.id == cheque_id, or_(Chequera.pagado == "", Chequera.pagado.is_(None)),
    ).values(pagado=f"Debitado {datos.fecha}"))
    if r.rowcount != 1:
        raise HTTPException(409, "El cheque ya fue conciliado")
    db.add(MovimientoTesoreria(
        cuenta_id=cuenta.id, fecha=datos.fecha, sentido="egreso", monto=cheque.monto,
        origen_tipo="debito_cheque", origen_id=cheque.id,
        referencia=datos.referencia or cheque.numcheque, descripcion="Débito de cheque propio",
    ))
    db.commit()
    return {"ok": True, "cheque_id": cheque_id, "cuenta_id": cuenta.id}
