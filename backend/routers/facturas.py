"""
facturas.py - Router para Facturas
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import Factura, Venta, Cliente, StockMercaderia
from schemas import FacturaCreate, FacturaResponse, VentaResponse

router = APIRouter()

# Los renglones facturados sin remito previo (factura sin entrega) no pertenecen
# a ningun movimiento de remito: se marcan con nmov 0 para que no colisionen con
# los IDs de remito al reimprimir.
NMOV_SIN_REMITO = 0


@router.get("/", response_model=List[FacturaResponse])
def get_facturas(fecha: str = None, cliente: str = None, db: Session = Depends(get_db)):
    query = db.query(Factura)
    if fecha:
        query = query.filter(Factura.fecha == fecha)
    if cliente:
        query = query.filter(Factura.cliente == cliente)
    return query.order_by(Factura.facturanumero.desc()).all()


@router.get("/{factura_num}/ventas", response_model=List[VentaResponse])
def get_factura_ventas(factura_num: int, db: Session = Depends(get_db)):
    """Renglones de una factura.

    Sin esta ruta, imprimir una factura obligaba al navegador a recorrer todos
    los remitos y filtrar (N+1 peticiones, con tope de resultados), lo que se
    degradaba a medida que crecia la base.
    """
    return db.query(Venta).filter(Venta.idfactura == factura_num).all()


@router.get("/{factura_num}", response_model=FacturaResponse)
def get_factura(factura_num: int, db: Session = Depends(get_db)):
    factura = db.query(Factura).filter(Factura.facturanumero == factura_num).first()
    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    return factura


@router.post("/", response_model=FacturaResponse)
def create_factura(factura_data: FacturaCreate, db: Session = Depends(get_db)):
    # Get next invoice number
    last = db.query(Factura).order_by(Factura.facturanumero.desc()).first()
    new_num = (last.facturanumero + 1) if last else 1
    
    new_factura = Factura(
        facturanumero=new_num,
        cliente=factura_data.cliente,
        fecha=factura_data.fecha,
        subtotal=factura_data.subtotal,
        iva=factura_data.iva,
        total=factura_data.total,
    )
    db.add(new_factura)

    # Las lineas que llegan CON id son renglones de remito ya existentes: quedan
    # asociados a la factura para que el remito deje de figurar como no facturado.
    venta_ids = [i.id for i in factura_data.items if i.id is not None]
    if venta_ids:
        db.query(Venta).filter(Venta.id.in_(venta_ids)).update(
            {Venta.idfactura: new_num}, synchronize_session=False
        )

    # Las lineas SIN id son renglones nuevos (factura sin entrega): se crean y se
    # descuenta el stock aca, en la misma transaccion.
    for item in factura_data.items:
        if item.id is not None:
            continue
        if item.codigo is None:
            continue
        producto = db.query(StockMercaderia).filter(
            StockMercaderia.codigo == item.codigo
        ).first()
        if not producto:
            raise HTTPException(
                status_code=404,
                detail=f"El producto {item.codigo} no existe: no se puede facturar",
            )
        cantidad = item.cantidad or 0.0
        disponible = producto.cantidad or 0.0
        if cantidad > disponible:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Stock insuficiente de '{producto.producto}': "
                    f"se intentan facturar {cantidad} y hay {disponible}"
                ),
            )
        db.add(Venta(
            codigo=item.codigo,
            producto=item.producto or producto.producto,
            cantidad=cantidad,
            precio=item.precio if item.precio is not None else (producto.preven or 0),
            unidad=item.unidad or producto.unidad or "",
            nmov=NMOV_SIN_REMITO,
            idfactura=new_num,
            cliente=new_factura.cliente,
            fecha=factura_data.fecha,
        ))
        producto.cantidad = disponible - cantidad

    # La factura genera deuda en la cuenta corriente del cliente. Antes esto lo
    # hacia el navegador contra una base local que ya no existe, con lo cual la
    # cuenta corriente nunca se actualizaba realmente.
    cliente = db.query(Cliente).filter(Cliente.cuit == new_factura.cliente).first()
    if cliente:
        # Saldos EN CENTAVOS: suma de enteros, exacta. Antes eran floats y
        # cada factura metia un error de fraccion de centavo en la cuenta
        # corriente, que se acumulaba comprobante tras comprobante.
        cliente.saldo = (cliente.saldo or 0) + (factura_data.total or 0)

    db.commit()
    db.refresh(new_factura)
    return new_factura


@router.delete("/{factura_num}")
def delete_factura(factura_num: int, db: Session = Depends(get_db)):
    """Anular una factura: libera sus remitos y revierte la deuda del cliente."""
    factura = db.query(Factura).filter(Factura.facturanumero == factura_num).first()
    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    # Los renglones facturados sin remito no existen fuera de esta factura: se
    # eliminan y se devuelve el stock. Los que vienen de un remito solo se
    # desasocian, para que el remito vuelva a figurar como no facturado.
    sin_remito = db.query(Venta).filter(
        Venta.idfactura == factura_num, Venta.nmov == NMOV_SIN_REMITO
    ).all()
    for v in sin_remito:
        producto = db.query(StockMercaderia).filter(
            StockMercaderia.codigo == v.codigo
        ).first()
        if producto:
            producto.cantidad = (producto.cantidad or 0.0) + (v.cantidad or 0.0)
        db.delete(v)

    db.query(Venta).filter(
        Venta.idfactura == factura_num, Venta.nmov != NMOV_SIN_REMITO
    ).update({Venta.idfactura: 0}, synchronize_session=False)

    cliente = db.query(Cliente).filter(Cliente.cuit == factura.cliente).first()
    if cliente:
        cliente.saldo = (cliente.saldo or 0) - (factura.total or 0)

    db.delete(factura)
    db.commit()
    return {"message": "Factura eliminada correctamente"}
