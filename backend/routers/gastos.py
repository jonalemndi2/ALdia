"""
gastos.py - Router para Gastos
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

import saldos
from database import get_db
from dinero import a_pesos, importes_de_renglones
from models import GastoFactura, CompraGasto, Proveedor
from schemas import GastoCreate, GastoResponse
from secuencias import siguiente_numero

router = APIRouter()


@router.get("/", response_model=List[GastoResponse])
def get_gastos(fecha: str = None, db: Session = Depends(get_db)):
    query = db.query(GastoFactura)
    if fecha:
        query = query.filter(GastoFactura.fecha == fecha)
    return query.order_by(GastoFactura.id.desc()).all()


@router.post("/", response_model=GastoResponse)
def create_gasto(gasto_data: GastoCreate, db: Session = Depends(get_db)):
    """Registrar una factura de gasto con todos sus efectos, en una transaccion.

    Antes este endpoint solo insertaba la cabecera: los renglones se perdian, el
    saldo del proveedor no se movia y el egreso de caja lo tenia que disparar el
    navegador en una segunda peticion (si fallaba, el gasto quedaba sin asiento).
    """
    proveedor = db.query(Proveedor).filter(Proveedor.cuit == gasto_data.proveedor).first()
    if not proveedor:
        raise HTTPException(
            status_code=404,
            detail=f"El proveedor {gasto_data.proveedor} no existe: no se puede cargar el gasto",
        )

    # Numero de gasto desde el contador de la serie "gasto", no un max+1.
    # Ver backend/secuencias.py.
    new_id = siguiente_numero(db, "gasto")

    # Sin importes declarados, neto, IVA y total salen de los conceptos con el
    # mismo criterio que una factura (el IVA una vez por alicuota). Si vienen
    # declarados se respetan: son los del comprobante del proveedor, que es el
    # que vale para el credito fiscal.
    if gasto_data.items and not ({"subtotal", "iva", "total"} & gasto_data.model_fields_set):
        importes = importes_de_renglones((c.monto, 1, c.iva) for c in gasto_data.items)
        gasto_data.subtotal, gasto_data.iva, gasto_data.total = (
            importes.neto, importes.iva, importes.total)

    datos = gasto_data.model_dump(exclude={"items"})
    new_gasto = GastoFactura(id=new_id, **datos)
    db.add(new_gasto)
    # Los renglones apuntan a la cabecera por clave foranea, y sin relationship()
    # SQLAlchemy no sabe que tiene que insertarla primero: sin este flush, todo
    # gasto CON conceptos fallaba con "FOREIGN KEY constraint failed".
    db.flush()

    # 1) Renglones del gasto, ahora persistidos de verdad.
    for item in gasto_data.items:
        db.add(CompraGasto(
            gastos_id=new_id,
            descripcion=item.descripcion,
            monto=item.monto,
            iva=item.iva,
        ))

    # 2) El gasto genera deuda con el proveedor. La escritura del saldo pasa
    #    SIEMPRE por backend/saldos.py (centavos enteros).
    saldos.aplicar_a_proveedor(db, proveedor.cuit, +(gasto_data.total or 0))

    # El comprobante DEVENGA deuda. El dinero sale recien al registrar el pago
    # al proveedor, indicando caja/banco/cheque. Mezclar ambos hechos duplicaba
    # egresos cuando luego se cargaba la orden de pago.

    db.commit()
    db.refresh(new_gasto)
    return new_gasto


@router.get("/{gasto_id}/conceptos")
def get_gasto_conceptos(gasto_id: int, db: Session = Depends(get_db)):
    """Renglones de una factura de gasto.

    `monto` se guarda en centavos y sale en pesos; `iva` es la ALICUOTA del
    renglon (21.0 = 21%), no un importe, asi que se devuelve tal cual.
    """
    conceptos = db.query(CompraGasto).filter(CompraGasto.gastos_id == gasto_id).all()
    return [
        {
            "id": c.id,
            "gastos_id": c.gastos_id,
            "descripcion": c.descripcion,
            "monto": a_pesos(c.monto),
            "iva": c.iva,
        }
        for c in conceptos
    ]


@router.delete("/{gasto_id}")
def delete_gasto(gasto_id: int, db: Session = Depends(get_db)):
    """Anular un gasto revirtiendo el saldo del proveedor y el asiento de caja."""
    gasto = db.query(GastoFactura).filter(GastoFactura.id == gasto_id).first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")

    saldos.aplicar_a_proveedor(db, gasto.proveedor, -(gasto.total or 0))

    # Delete associated conceptos first
    db.query(CompraGasto).filter(CompraGasto.gastos_id == gasto_id).delete()
    db.delete(gasto)
    db.commit()
    return {"message": "Gasto eliminado correctamente"}
