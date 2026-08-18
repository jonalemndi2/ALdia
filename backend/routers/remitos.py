"""
remitos.py - Router para Remitos y Ventas
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import Remito, Venta, StockMercaderia
from schemas import (
    RemitoCreate, RemitoResponse, VentaCreate, VentaResponse,
    RemitoNoFacturadoResponse,
)

router = APIRouter()


@router.get("/", response_model=List[RemitoResponse])
def get_remitos(fecha: str = None, db: Session = Depends(get_db)):
    query = db.query(Remito)
    if fecha:
        query = query.filter(Remito.fecha == fecha)
    return query.order_by(Remito.id.desc()).all()


@router.get("/nofacturados", response_model=List[RemitoNoFacturadoResponse])
def get_remitos_no_facturados(db: Session = Depends(get_db)):
    """Lineas de remitos sin factura asociada.

    Devuelve las lineas (tabla ventas) y no las cabeceras, porque la grilla del
    frontend (Remitos.remitosNoFacturados) muestra nmov/codigo/producto/
    cantidad/precio, que son campos de la linea y no del remito.
    """
    return (
        db.query(Venta)
        .filter((Venta.idfactura == 0) | (Venta.idfactura.is_(None)))
        .order_by(Venta.nmov.desc())
        .all()
    )


# NOTA: las rutas con path fijo deben declararse ANTES de "/{remito_id}",
# porque FastAPI resuelve por orden de declaracion y el parametro las captura.
@router.get("/{remito_id}", response_model=RemitoResponse)
def get_remito(remito_id: int, db: Session = Depends(get_db)):
    remito = db.query(Remito).filter(Remito.id == remito_id).first()
    if not remito:
        raise HTTPException(status_code=404, detail="Remito no encontrado")
    return remito


@router.post("/", response_model=RemitoResponse)
def create_remito(remito_data: RemitoCreate, db: Session = Depends(get_db)):
    # Get next ID
    last = db.query(Remito).order_by(Remito.id.desc()).first()
    new_id = (last.id + 1) if last else 1
    
    new_remito = Remito(
        id=new_id,
        cliente=remito_data.cliente,
        fecha=remito_data.fecha,
        total=remito_data.total,
        iva=remito_data.iva,
    )
    db.add(new_remito)

    # El frontend manda las lineas dentro del mismo POST: se persisten como
    # ventas y se descuenta el stock entregado.
    for item in remito_data.items:
        db.add(Venta(
            codigo=item.codigo,
            producto=item.producto,
            cantidad=item.cantidad,
            precio=item.precio,
            unidad=item.unidad,
            nmov=new_id,
            idfactura=0,
            cliente=remito_data.cliente,
            fecha=remito_data.fecha,
        ))
        producto = db.query(StockMercaderia).filter(StockMercaderia.codigo == item.codigo).first()
        if producto:
            producto.cantidad = (producto.cantidad or 0) - item.cantidad

    db.commit()
    db.refresh(new_remito)
    return new_remito


@router.get("/{remito_id}/ventas", response_model=List[VentaResponse])
def get_remito_ventas(remito_id: int, db: Session = Depends(get_db)):
    ventas = db.query(Venta).filter(Venta.nmov == remito_id).all()
    return ventas


@router.post("/ventas", response_model=VentaResponse)
def create_venta(venta_data: VentaCreate, db: Session = Depends(get_db)):
    new_venta = Venta(**venta_data.model_dump())
    db.add(new_venta)
    db.commit()
    db.refresh(new_venta)
    return new_venta
