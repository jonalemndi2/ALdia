"""
iva.py - Router para consulta de IVA
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from dinero import a_pesos
from models import Factura, FacturaProveedor, GastoFactura

router = APIRouter()


@router.get("/consulta")
def consultar_iva(fecha_desde: str = None, fecha_hasta: str = None, db: Session = Depends(get_db)):
    """Consultar IVA del período (posición mensual).

    Los importes de IVA estan en CENTAVOS: las sumas del periodo y la resta
    final (debito - credito) se hacen con enteros y cierran exactas. Con Float,
    un periodo con cientos de comprobantes terminaba con un desvio de centavos
    en la posicion que despues no coincidia con la DDJJ.
    """
    # IVA percibido / debito fiscal (facturas emitidas)
    query_fac = db.query(Factura).with_entities(
        func.coalesce(func.sum(Factura.iva), 0)
    )
    if fecha_desde:
        query_fac = query_fac.filter(Factura.fecha >= fecha_desde)
    if fecha_hasta:
        query_fac = query_fac.filter(Factura.fecha <= fecha_hasta)
    iva_percibido = query_fac.scalar() or 0
    
    # IVA pagado (facturas de proveedores + gastos)
    query_prov = db.query(FacturaProveedor).with_entities(
        func.coalesce(func.sum(FacturaProveedor.iva), 0)
    )
    if fecha_desde:
        query_prov = query_prov.filter(FacturaProveedor.fecha >= fecha_desde)
    if fecha_hasta:
        query_prov = query_prov.filter(FacturaProveedor.fecha <= fecha_hasta)
    iva_pagado_prov = query_prov.scalar() or 0
    
    query_gastos = db.query(GastoFactura).with_entities(
        func.coalesce(func.sum(GastoFactura.iva), 0)
    )
    if fecha_desde:
        query_gastos = query_gastos.filter(GastoFactura.fecha >= fecha_desde)
    if fecha_hasta:
        query_gastos = query_gastos.filter(GastoFactura.fecha <= fecha_hasta)
    iva_pagado_gastos = query_gastos.scalar() or 0
    
    # Toda la aritmetica, en centavos enteros.
    iva_percibido = int(iva_percibido)
    iva_pagado_prov = int(iva_pagado_prov)
    iva_pagado_gastos = int(iva_pagado_gastos)
    iva_total_pagado = iva_pagado_prov + iva_pagado_gastos
    iva_a_pagar = iva_percibido - iva_total_pagado

    # Recien aca se pasa a pesos, para el contrato de la API.
    return {
        "iva_percibido": a_pesos(iva_percibido),
        "iva_pagado_proveedores": a_pesos(iva_pagado_prov),
        "iva_pagado_gastos": a_pesos(iva_pagado_gastos),
        "iva_total_pagado": a_pesos(iva_total_pagado),
        "iva_a_pagar": a_pesos(iva_a_pagar),
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta
    }
