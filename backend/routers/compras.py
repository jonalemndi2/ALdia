"""
compras.py - Routers para Compras a proveedores y Devoluciones.

El frontend (Web/js/modules/proveedores.js) postea a /api/compras/ y
/api/devoluciones/. Antes no existia ningun router montado en esas rutas, por lo
que el mount estatico de "/" respondia 405. Aca se exponen ambos endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import saldos
from database import get_db
from dinero import a_pesos, aplicar_alicuota, multiplicar
from models import (
    Proveedor, StockMercaderia, FacturaProveedor, Compra, NCP
)
from schemas import CompraCreate, DevolucionCreate
from secuencias import siguiente_numero

router = APIRouter()
router_devoluciones = APIRouter()


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
        # El articulo tiene que existir: `compras.codigo` es clave foranea contra
        # stockmercaderia. Antes un codigo inexistente se aceptaba, se liquidaba
        # con el 21% por defecto y el renglon quedaba apuntando a la nada.
        producto = db.query(StockMercaderia).filter(StockMercaderia.codigo == item.codigo).first()
        if not producto:
            raise HTTPException(
                status_code=404,
                detail=f"El producto {item.codigo} no existe: no se puede cargar la compra",
            )
        iva_pct = producto.iva if producto.iva is not None else 21.0
        iva_total += aplicar_alicuota(linea, iva_pct)

    # Numero de la factura de compra desde el contador. Ver backend/secuencias.py.
    factprov_id = siguiente_numero(db, "compra")
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

    saldos.aplicar_a_proveedor(db, proveedor.cuit, +(subtotal + iva_total))

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
    saldos.aplicar_a_proveedor(db, proveedor.cuit, -total)

    ncp_id = siguiente_numero(db, "nota_credito_proveedor")
    detalle = ", ".join(f"{i.producto} x{i.cantidad}" for i in data.items)
    db.add(NCP(
        id=ncp_id,
        proveedor=data.proveedor,
        fecha=data.fecha,
        descripcion=f"Devolución: {detalle}"[:500],
        # El IMPORTE de la devolucion ahora queda registrado. Antes solo se
        # restaba del saldo del proveedor y no se guardaba en ningun lado, con
        # lo cual el saldo no se podia recalcular desde los movimientos y toda
        # verificacion de consistencia daba una diferencia inexplicable.
        monto=total,
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
