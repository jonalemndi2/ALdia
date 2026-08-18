"""
compras.py - Routers para Compras a proveedores y Devoluciones.

El frontend (Web/js/modules/proveedores.js) postea a /api/compras/ y
/api/devoluciones/. Antes no existia ningun router montado en esas rutas, por lo
que el mount estatico de "/" respondia 405. Aca se exponen ambos endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dinero import a_pesos, aplicar_alicuota, multiplicar
from models import (
    Proveedor, StockMercaderia, FacturaProveedor, Compra, NCP
)
from schemas import CompraCreate, DevolucionCreate

router = APIRouter()
router_devoluciones = APIRouter()


def _siguiente_id(db: Session, modelo, columna) -> int:
    ultimo = db.query(modelo).order_by(columna.desc()).first()
    return (getattr(ultimo, columna.key) + 1) if ultimo else 1


@router.post("/")
def create_compra(data: CompraCreate, db: Session = Depends(get_db)):
    """Registrar una compra: cabecera en factprov + items en compras.

    Suma la mercaderia al stock y el total al saldo del proveedor.
    """
    proveedor = db.query(Proveedor).filter(Proveedor.cuit == data.proveedor).first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    # Todo en CENTAVOS enteros. Cada renglon se redondea UNA sola vez (dentro
    # de multiplicar y de aplicar_alicuota) y despues solo se suman enteros, que
    # es exacto. Con floats, el total de la compra y el saldo del proveedor
    # arrastraban un desvio de fraccion de centavo por cada renglon.
    subtotal = 0
    iva_total = 0
    for item in data.items:
        linea = multiplicar(item.precio, item.cantidad)
        subtotal += linea
        producto = db.query(StockMercaderia).filter(StockMercaderia.codigo == item.codigo).first()
        iva_pct = producto.iva if producto and producto.iva is not None else 21.0
        iva_total += aplicar_alicuota(linea, iva_pct)

    factprov_id = _siguiente_id(db, FacturaProveedor, FacturaProveedor.id)
    cabecera = FacturaProveedor(
        id=factprov_id,
        proveedor=data.proveedor,
        fecha=data.fecha,
        subtotal=subtotal,
        iva=iva_total,
        total=subtotal + iva_total,
    )
    db.add(cabecera)

    for item in data.items:
        db.add(Compra(
            codigo=item.codigo,
            producto=item.producto,
            cantidad=item.cantidad,
            precio=item.precio,
            factprov_id=factprov_id,
            fecha=data.fecha,
        ))
        producto = db.query(StockMercaderia).filter(StockMercaderia.codigo == item.codigo).first()
        if producto:
            producto.cantidad = (producto.cantidad or 0) + item.cantidad
            producto.precom = item.precio

    proveedor.saldo = (proveedor.saldo or 0) + subtotal + iva_total

    db.commit()
    db.refresh(cabecera)
    return {
        "id": factprov_id,
        "proveedor": data.proveedor,
        "num_factura": data.num_factura,
        "fecha": data.fecha,
        # Hacia afuera, pesos: el contrato de la API no cambia.
        "subtotal": a_pesos(subtotal),
        "iva": a_pesos(iva_total),
        "total": a_pesos(subtotal + iva_total),
        "items": len(data.items),
    }


@router_devoluciones.post("/")
def create_devolucion(data: DevolucionCreate, db: Session = Depends(get_db)):
    """Registrar una devolucion a proveedor: descuenta stock y saldo, y deja una NCP."""
    proveedor = db.query(Proveedor).filter(Proveedor.cuit == data.proveedor).first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    # Aritmetica en CENTAVOS enteros (ver backend/dinero.py).
    subtotal = 0
    iva_total = 0
    for item in data.items:
        linea = multiplicar(item.precio, item.cantidad)
        subtotal += linea
        producto = db.query(StockMercaderia).filter(StockMercaderia.codigo == item.codigo).first()
        iva_pct = producto.iva if producto and producto.iva is not None else 21.0
        iva_total += aplicar_alicuota(linea, iva_pct)
        if producto:
            producto.cantidad = (producto.cantidad or 0) - item.cantidad

    total = subtotal + iva_total
    proveedor.saldo = (proveedor.saldo or 0) - total

    ncp_id = _siguiente_id(db, NCP, NCP.id)
    detalle = ", ".join(f"{i.producto} x{i.cantidad}" for i in data.items)
    db.add(NCP(
        id=ncp_id,
        proveedor=data.proveedor,
        fecha=data.fecha,
        descripcion=f"Devolución: {detalle}"[:500],
    ))

    db.commit()
    return {
        "id": ncp_id,
        "proveedor": data.proveedor,
        "fecha": data.fecha,
        "subtotal": a_pesos(subtotal),
        "iva": a_pesos(iva_total),
        "total": a_pesos(total),
        "items": len(data.items),
    }
