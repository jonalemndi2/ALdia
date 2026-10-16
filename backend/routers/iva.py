"""
iva.py - Router para consulta de IVA
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from dinero import a_pesos
from models import Factura, FacturaProveedor, GastoFactura, Liquidacion

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
    iva_percibido_fac = int(query_fac.scalar() or 0)

    # Liquidaciones de venta confirmadas:
    # - iva_operacion suma al debito fiscal
    # - iva_deducciones (flete, secado, comision descontados por el comprador/acopio) suma al credito fiscal
    query_liq_venta = db.query(
        func.coalesce(func.sum(Liquidacion.iva_operacion), 0),
        func.coalesce(func.sum(Liquidacion.iva_deducciones), 0),
        func.coalesce(func.sum(Liquidacion.total_retenciones), 0),
    ).filter(Liquidacion.operacion == "venta", Liquidacion.estado == "confirmada")
    if fecha_desde:
        query_liq_venta = query_liq_venta.filter(Liquidacion.fecha >= fecha_desde)
    if fecha_hasta:
        query_liq_venta = query_liq_venta.filter(Liquidacion.fecha <= fecha_hasta)
    liq_venta_iva_op, liq_venta_iva_ded, retenciones_sufridas = [
        int(x or 0) for x in query_liq_venta.one()
    ]

    # Liquidaciones de compra confirmadas (acopio/consignatario comprando al productor):
    # - iva_operacion suma al credito fiscal (compra de grano/hacienda)
    # - iva_deducciones suma al debito fiscal (servicios facturados/descontados al productor)
    query_liq_compra = db.query(
        func.coalesce(func.sum(Liquidacion.iva_operacion), 0),
        func.coalesce(func.sum(Liquidacion.iva_deducciones), 0),
        func.coalesce(func.sum(Liquidacion.total_retenciones), 0),
    ).filter(Liquidacion.operacion == "compra", Liquidacion.estado == "confirmada")
    if fecha_desde:
        query_liq_compra = query_liq_compra.filter(Liquidacion.fecha >= fecha_desde)
    if fecha_hasta:
        query_liq_compra = query_liq_compra.filter(Liquidacion.fecha <= fecha_hasta)
    liq_compra_iva_op, liq_compra_iva_ded, retenciones_practicadas = [
        int(x or 0) for x in query_liq_compra.one()
    ]

    # IVA pagado (facturas de proveedores + gastos)
    query_prov = db.query(FacturaProveedor).with_entities(
        func.coalesce(func.sum(FacturaProveedor.iva), 0)
    )
    if fecha_desde:
        query_prov = query_prov.filter(FacturaProveedor.fecha >= fecha_desde)
    if fecha_hasta:
        query_prov = query_prov.filter(FacturaProveedor.fecha <= fecha_hasta)
    iva_pagado_prov = int(query_prov.scalar() or 0)

    query_gastos = db.query(GastoFactura).with_entities(
        func.coalesce(func.sum(GastoFactura.iva), 0)
    )
    if fecha_desde:
        query_gastos = query_gastos.filter(GastoFactura.fecha >= fecha_desde)
    if fecha_hasta:
        query_gastos = query_gastos.filter(GastoFactura.fecha <= fecha_hasta)
    iva_pagado_gastos = int(query_gastos.scalar() or 0)

    # Toda la aritmetica, en centavos enteros.
    iva_liquidaciones_debito = liq_venta_iva_op + liq_compra_iva_ded
    iva_liquidaciones_credito = liq_compra_iva_op + liq_venta_iva_ded

    iva_percibido = iva_percibido_fac + iva_liquidaciones_debito
    iva_total_pagado = iva_pagado_prov + iva_pagado_gastos + iva_liquidaciones_credito
    iva_a_pagar = iva_percibido - iva_total_pagado

    # Recien aca se pasa a pesos, para el contrato de la API.
    return {
        "iva_percibido": a_pesos(iva_percibido),
        "iva_pagado_proveedores": a_pesos(iva_pagado_prov),
        "iva_pagado_gastos": a_pesos(iva_pagado_gastos),
        "iva_liquidaciones_debito": a_pesos(iva_liquidaciones_debito),
        "iva_liquidaciones_credito": a_pesos(iva_liquidaciones_credito),
        "retenciones_sufridas": a_pesos(retenciones_sufridas),
        "retenciones_practicadas": a_pesos(retenciones_practicadas),
        "iva_total_pagado": a_pesos(iva_total_pagado),
        "iva_a_pagar": a_pesos(iva_a_pagar),
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
    }
