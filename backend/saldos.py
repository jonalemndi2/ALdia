"""
saldos.py - Unico lugar del sistema donde se escribe un saldo.

EL PROBLEMA
===========
`clientes.saldo` y `proveedores.saldo` son datos DERIVADOS: se pueden calcular
sumando los comprobantes y restando los pagos. Pero ademas se guardan, y hasta
esta version se escribian desde ONCE lugares sueltos repartidos en cinco
routers, cada uno con su propio `(x.saldo or 0) + algo`.

Con once escrituras independientes alcanza con que UNA se olvide, se revierta mal
o quede a medias para que el saldo empiece a mentir. Y como no hay nada que lo
compare contra la realidad, miente en silencio: el listado de deudores muestra un
numero que ya no corresponde a ningun movimiento, y nadie se entera hasta que un
cliente reclama.

Un ejemplo real que estaba en el codigo: al anular una factura desde
`/api/facturas/{n}` se revertia el saldo, pero al anular la MISMA factura desde
`/api/admin/movimientos/factura/{n}` no, con un comentario explicando que no se
tocaba "para no descuadrar". Dos caminos para la misma operacion, con dos
resultados distintos. Eso es exactamente lo que pasa cuando la regla no vive en
un solo lugar.

QUE SE HIZO (y que NO)
======================
NO se elimino el campo. Listar deudores recalculando cliente por cliente no
escala y el campo se usa en varias pantallas. Lo que se hizo es que no pueda
desviarse en silencio:

  1. UNA SOLA PUERTA DE ESCRITURA. Los routers ya no asignan `.saldo`: llaman a
     `aplicar_a_cliente()` / `aplicar_a_proveedor()`. Si manana hace falta
     auditar, loguear o validar cada movimiento de saldo, se toca aca y vale
     para todo el sistema.

  2. UNA DEFINICION EXPLICITA de que es el saldo, escrita como consulta
     (`recalcular_cliente` / `recalcular_proveedor`). Antes esa definicion
     estaba implicita y repartida en los once `+=`.

  3. UNA VERIFICACION que recalcula desde los movimientos y compara contra lo
     guardado (`verificar()`), expuesta como
     `GET /api/admin/verificar-saldos` y visible en la pantalla de Estado de la
     Base de Datos. La diferencia, si la hay, se informa con nombre, CUIT e
     importe.

  4. UNA REPARACION EXPLICITA (`reparar()`), solo administrador, que pisa el
     guardado con el calculado. Es deliberadamente un POST separado y no algo
     que la verificacion haga sola: corregir un saldo es una decision contable,
     no un efecto colateral de mirar una pantalla. Queda registrada en la
     auditoria como cualquier otra escritura (el middleware audita todo POST a
     /api/*, y los eventos ORM ya observan el campo `saldo`).

DEFINICION DEL SALDO
====================
    saldo del CLIENTE     = facturas emitidas  -  cobros recibidos
    saldo del PROVEEDOR   = facturas de compra + gastos - pagos - notas de credito

Positivo = nos deben (cliente) / debemos (proveedor). Todo en CENTAVOS enteros,
asi que la comparacion es exacta: una diferencia de 1 es una diferencia de un
centavo real, no un error de redondeo (ver backend/dinero.py).

LIMITE CONOCIDO
===============
Las tablas `nncv`, `nndv`, `nfan` y `ndprov` (notas de credito y debito) no
participan del calculo porque HOY ningun endpoint del sistema las escribe ni
mueve el saldo por ellas: incluirlas cambiaria el resultado de la verificacion
por movimientos que el sistema no genera. Si algun dia se implementan esas
pantallas, hay que sumarlas a las consultas de abajo Y a los routers que las
creen. Queda dicho aca para que no se descubra por accidente.
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    Cliente, Cobro, Factura, FacturaProveedor, GastoFactura, NCP, Pago, Proveedor,
)


def _suma(db: Session, columna, filtro) -> int:
    """Suma una columna de dinero (centavos) devolviendo SIEMPRE un int."""
    return int(db.query(func.coalesce(func.sum(columna), 0)).filter(filtro).scalar() or 0)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Calculo del saldo desde los movimientos (la definicion, hecha codigo)
# ─────────────────────────────────────────────────────────────────────────────

def recalcular_cliente(db: Session, cuit: str) -> int:
    """Saldo del cliente segun sus movimientos. En centavos."""
    facturado = _suma(db, Factura.total, Factura.cliente == cuit)
    cobrado = _suma(db, Cobro.monto, Cobro.cliente == cuit)
    return facturado - cobrado


def recalcular_proveedor(db: Session, cuit: str) -> int:
    """Saldo del proveedor segun sus movimientos. En centavos."""
    comprado = _suma(db, FacturaProveedor.total, FacturaProveedor.proveedor == cuit)
    gastado = _suma(db, GastoFactura.total, GastoFactura.proveedor == cuit)
    pagado = _suma(db, Pago.monto, Pago.proveedor == cuit)
    devuelto = _suma(db, NCP.monto, NCP.proveedor == cuit)
    return comprado + gastado - pagado - devuelto


# ─────────────────────────────────────────────────────────────────────────────
# 2. Unica puerta de ESCRITURA
#
# Todo router que mueva plata de una cuenta corriente pasa por aca. `delta` va
# en CENTAVOS y con signo: positivo = aumenta la deuda, negativo = la cancela.
# ─────────────────────────────────────────────────────────────────────────────

def aplicar_a_cliente(db: Session, cuit: str, delta: int) -> Cliente | None:
    """Mueve el saldo del cliente en `delta` centavos. Devuelve la ficha.

    No hace commit: forma parte de la transaccion del comprobante que lo llama,
    para que el saldo y el movimiento entren o no entren juntos.
    """
    if not cuit:
        return None
    cliente = db.query(Cliente).filter(Cliente.cuit == cuit).first()
    if cliente is None:
        return None
    cliente.saldo = int(cliente.saldo or 0) + int(delta or 0)
    return cliente


def aplicar_a_proveedor(db: Session, cuit: str, delta: int) -> Proveedor | None:
    """Mueve el saldo del proveedor en `delta` centavos. Devuelve la ficha."""
    if not cuit:
        return None
    proveedor = db.query(Proveedor).filter(Proveedor.cuit == cuit).first()
    if proveedor is None:
        return None
    proveedor.saldo = int(proveedor.saldo or 0) + int(delta or 0)
    return proveedor


# ─────────────────────────────────────────────────────────────────────────────
# 3. Verificacion de consistencia (solo lectura)
# ─────────────────────────────────────────────────────────────────────────────

def _diferencias_clientes(db: Session) -> list[dict]:
    """Un renglon por cliente cuyo saldo guardado no coincide con el calculado.

    Se resuelve con dos agregaciones y un recorrido en memoria, no con una
    consulta por cliente: sobre un padron de miles de fichas la version ingenua
    tardaria minutos.
    """
    facturado = dict(
        db.query(Factura.cliente, func.coalesce(func.sum(Factura.total), 0))
        .group_by(Factura.cliente).all()
    )
    cobrado = dict(
        db.query(Cobro.cliente, func.coalesce(func.sum(Cobro.monto), 0))
        .group_by(Cobro.cliente).all()
    )

    diferencias = []
    for c in db.query(Cliente).all():
        calculado = int(facturado.get(c.cuit, 0) or 0) - int(cobrado.get(c.cuit, 0) or 0)
        guardado = int(c.saldo or 0)
        if calculado != guardado:
            diferencias.append({
                "tipo": "cliente",
                "cuit": c.cuit,
                "nombre": c.nombre or "",
                "saldo_guardado": guardado,     # centavos
                "saldo_calculado": calculado,   # centavos
                "diferencia": guardado - calculado,
            })
    return diferencias


def _diferencias_proveedores(db: Session) -> list[dict]:
    """Un renglon por proveedor cuyo saldo guardado no coincide con el calculado."""
    comprado = dict(
        db.query(FacturaProveedor.proveedor, func.coalesce(func.sum(FacturaProveedor.total), 0))
        .group_by(FacturaProveedor.proveedor).all()
    )
    gastado = dict(
        db.query(GastoFactura.proveedor, func.coalesce(func.sum(GastoFactura.total), 0))
        .group_by(GastoFactura.proveedor).all()
    )
    pagado = dict(
        db.query(Pago.proveedor, func.coalesce(func.sum(Pago.monto), 0))
        .group_by(Pago.proveedor).all()
    )
    devuelto = dict(
        db.query(NCP.proveedor, func.coalesce(func.sum(NCP.monto), 0))
        .group_by(NCP.proveedor).all()
    )

    diferencias = []
    for p in db.query(Proveedor).all():
        calculado = (
            int(comprado.get(p.cuit, 0) or 0)
            + int(gastado.get(p.cuit, 0) or 0)
            - int(pagado.get(p.cuit, 0) or 0)
            - int(devuelto.get(p.cuit, 0) or 0)
        )
        guardado = int(p.saldo or 0)
        if calculado != guardado:
            diferencias.append({
                "tipo": "proveedor",
                "cuit": p.cuit,
                "nombre": p.nombre or "",
                "saldo_guardado": guardado,
                "saldo_calculado": calculado,
                "diferencia": guardado - calculado,
            })
    return diferencias


def verificar(db: Session) -> dict:
    """Recalcula todos los saldos y los compara con lo guardado. NO modifica nada.

    Todos los importes salen en CENTAVOS; la traduccion a pesos la hace el router
    (routers/admin.py), que es donde vive el contrato con el frontend.
    """
    diferencias = _diferencias_clientes(db) + _diferencias_proveedores(db)
    diferencias.sort(key=lambda d: abs(d["diferencia"]), reverse=True)
    return {
        "consistente": not diferencias,
        "clientes_revisados": db.query(Cliente).count(),
        "proveedores_revisados": db.query(Proveedor).count(),
        "cantidad_diferencias": len(diferencias),
        "desvio_total": sum(abs(d["diferencia"]) for d in diferencias),
        "diferencias": diferencias,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Reparacion explicita (solo administrador; ver routers/admin.py)
# ─────────────────────────────────────────────────────────────────────────────

def reparar(db: Session) -> dict:
    """Pisa el saldo guardado con el calculado. NO hace commit: lo hace el router.

    Deliberadamente separada de `verificar()`: el usuario primero ve el desvio y
    despues decide. Al escribir sobre `Cliente.saldo` / `Proveedor.saldo` a
    traves del ORM, los eventos de backend/auditoria.py capturan el valor
    anterior y el nuevo de cada ficha, asi que la correccion queda asentada
    ficha por ficha en el registro de auditoria.
    """
    antes = verificar(db)
    corregidos = []
    for d in antes["diferencias"]:
        if d["tipo"] == "cliente":
            ficha = db.query(Cliente).filter(Cliente.cuit == d["cuit"]).first()
        else:
            ficha = db.query(Proveedor).filter(Proveedor.cuit == d["cuit"]).first()
        if ficha is None:
            continue
        ficha.saldo = d["saldo_calculado"]
        corregidos.append(d)
    return {
        "corregidos": len(corregidos),
        "desvio_corregido": sum(abs(d["diferencia"]) for d in corregidos),
        "detalle": corregidos,
    }
