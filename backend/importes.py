"""
importes.py - Neto, IVA y total de un comprobante de venta, calculados en UN lugar.

La factura al guardarse, el remito, la cotizacion que pide el asistente y el
armado del pedido de CAE usan esta misma funcion. Antes la factura guardaba los
totales que mandaba el cliente (el navegador o el servidor MCP, sumando con
float) y el pedido de CAE los recalculaba aca: si diferian en mas de 5 centavos,
AFIP no autorizaba el comprobante, y la cuenta corriente del cliente quedaba con
un importe distinto del declarado.

La alicuota de cada renglon es la del articulo en el stock (21 % si no tiene),
igual que siempre la uso el pedido de CAE: no se le cree al cliente.
"""
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from dinero import ImportesComprobante, a_pesos, importes_de_renglones
from models import StockMercaderia

ALICUOTA_POR_DEFECTO = 21.0


def alicuotas_del_stock(db: Session, codigos: Iterable[Optional[int]]) -> dict[int, float]:
    codigos = {c for c in codigos if c is not None}
    if not codigos:
        return {}
    filas = db.query(StockMercaderia).filter(StockMercaderia.codigo.in_(codigos)).all()
    return {
        s.codigo: float(s.iva if s.iva is not None else ALICUOTA_POR_DEFECTO)
        for s in filas
    }


def importes_de_venta(db: Session, renglones) -> ImportesComprobante:
    """Importes a partir de renglones (precio en centavos, cantidad, codigo de articulo).

    Se toma el valor absoluto de precio y cantidad: el signo de un comprobante
    lo da su tipo (una nota de credito), no sus renglones.
    """
    lista = [(precio, cantidad, codigo) for precio, cantidad, codigo in renglones]
    alicuotas = alicuotas_del_stock(db, (codigo for _, _, codigo in lista))
    return importes_de_renglones(
        (abs(precio or 0), abs(cantidad or 0), alicuotas.get(codigo, ALICUOTA_POR_DEFECTO))
        for precio, cantidad, codigo in lista
    )


def importes_en_pesos(importes: ImportesComprobante) -> dict:
    """Los importes como los devuelve la API: pesos con 2 decimales."""
    return {
        "neto": a_pesos(importes.neto),
        "iva": a_pesos(importes.iva),
        "total": a_pesos(importes.total),
        "por_alicuota": [
            {"alicuota": alicuota, "base": a_pesos(base), "iva": a_pesos(iva)}
            for alicuota, (base, iva) in importes.por_alicuota.items()
        ],
        "renglones": [a_pesos(neto) for neto in importes.netos],
    }
