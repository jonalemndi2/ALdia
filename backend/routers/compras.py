"""
compras.py - Routers para Compras a proveedores y Devoluciones.

El frontend (Web/js/modules/proveedores.js) postea a /api/compras/ y
/api/devoluciones/. Antes no existia ningun router montado en esas rutas, por lo
que el mount estatico de "/" respondia 405. Aca se exponen ambos endpoints.
"""
from datetime import datetime
import hashlib
import json
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

import saldos
from database import get_db
from dinero import a_pesos, aplicar_alicuota, multiplicar
from models import (
    Proveedor, StockMercaderia, FacturaProveedor, Compra, NCP, Deposito,
    ExistenciaDeposito, MovimientoStock, DevolucionCompraItem
)
from schemas import CompraCreate, DevolucionCreate, NotaCreditoProveedorCreate
from secuencias import siguiente_numero

router = APIRouter()
router_devoluciones = APIRouter()


def _compra_salida(cabecera: FacturaProveedor) -> dict:
    return {
        "id": cabecera.id, "proveedor": cabecera.proveedor,
        "num_factura": cabecera.num_factura, "fecha": cabecera.fecha,
        "subtotal": a_pesos(cabecera.subtotal), "iva": a_pesos(cabecera.iva),
        "total": a_pesos(cabecera.total), "estado": cabecera.estado,
    }


@router.get("/")
def listar_compras(proveedor: str = None, limite: int = 20, db: Session = Depends(get_db)):
    if limite < 1 or limite > 500:
        raise HTTPException(422, "limite debe estar entre 1 y 500")
    q = db.query(FacturaProveedor)
    if proveedor:
        q = q.filter(FacturaProveedor.proveedor == proveedor)
    return [_compra_salida(c) for c in q.order_by(FacturaProveedor.id.desc()).limit(limite).all()]


@router.get("/{factura_id}")
def detalle_compra(factura_id: int, db: Session = Depends(get_db)):
    cabecera = db.query(FacturaProveedor).filter(FacturaProveedor.id == factura_id).first()
    if not cabecera:
        raise HTTPException(404, "Factura de compra no encontrada")
    salida = _compra_salida(cabecera)
    salida["renglones"] = renglones_compra(factura_id, db)
    return salida


def _fingerprint_payload(data: CompraCreate) -> str:
    items = sorted((i.codigo, format(i.cantidad, ".12g"), int(i.precio)) for i in data.items)
    canonico = {
        "proveedor": data.proveedor.strip(), "fecha": data.fecha,
        "num_factura": data.num_factura.strip(), "estado": data.estado,
        "items": items,
    }
    return hashlib.sha256(json.dumps(canonico, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fingerprint_guardado(db: Session, factura: FacturaProveedor) -> str:
    items = db.query(Compra).filter(Compra.factprov_id == factura.id).all()
    canonico = {
        "proveedor": factura.proveedor.strip(), "fecha": factura.fecha,
        "num_factura": (factura.num_factura or "").strip(), "estado": factura.estado,
        "items": sorted((i.codigo, format(i.cantidad, ".12g"), int(i.precio)) for i in items),
    }
    return hashlib.sha256(json.dumps(canonico, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _deposito_principal(db: Session) -> Deposito:
    deposito = db.query(Deposito).filter(Deposito.nombre == "Principal").first()
    if not deposito:
        deposito = Deposito(nombre="Principal", activo=True)
        db.add(deposito); db.flush()
    return deposito


def _existencia(db: Session, deposito_id: int, producto: StockMercaderia) -> ExistenciaDeposito:
    existencia = db.query(ExistenciaDeposito).filter(
        ExistenciaDeposito.deposito_id == deposito_id,
        ExistenciaDeposito.codigo == producto.codigo,
    ).first()
    if not existencia:
        # Compatibilidad: al inaugurar el subledger, el saldo físico histórico
        # es el que ya vive en stockmercaderia.
        existencia = ExistenciaDeposito(
            deposito_id=deposito_id, codigo=producto.codigo,
            cantidad=producto.cantidad or 0, costo_promedio=producto.precom or 0,
        )
        db.add(existencia); db.flush()
    return existencia


def _confirmar(db: Session, cabecera: FacturaProveedor) -> None:
    if cabecera.estado == "confirmada":
        return
    if cabecera.estado != "borrador":
        raise HTTPException(status_code=409, detail="Sólo se puede confirmar un borrador")
    deposito = _deposito_principal(db)
    for renglon in db.query(Compra).filter(Compra.factprov_id == cabecera.id).order_by(Compra.id).all():
        producto = db.query(StockMercaderia).filter(StockMercaderia.codigo == renglon.codigo).first()
        existencia = _existencia(db, deposito.id, producto)
        anterior = existencia.costo_promedio or 0
        nueva_cantidad = (existencia.cantidad or 0) + renglon.cantidad
        costo = renglon.precio  # neto: el IVA recuperable no se capitaliza
        promedio = round(((existencia.cantidad or 0) * anterior + renglon.cantidad * costo) / nueva_cantidad)
        movimiento = MovimientoStock(
            deposito_id=deposito.id, codigo=renglon.codigo, fecha=cabecera.fecha,
            sentido="entrada", cantidad=renglon.cantidad, costo_unitario=costo,
            costo_anterior=anterior, costo_resultante=promedio,
            origen_tipo="factura_compra", origen_id=cabecera.id, origen_renglon_id=renglon.id,
        )
        db.add(movimiento)
        existencia.cantidad = nueva_cantidad; existencia.costo_promedio = promedio
        producto.cantidad = nueva_cantidad; producto.precom = promedio
    saldos.aplicar_a_proveedor(db, cabecera.proveedor, +(cabecera.total or 0))
    cabecera.estado = "confirmada"


@router.post("/")
def create_compra(data: CompraCreate, db: Session = Depends(get_db), x_operation_id: str = Header(None)):
    """Registrar una compra: cabecera en factprov + items en compras.

    Suma la mercaderia al stock y el total al saldo del proveedor.
    """
    proveedor = db.query(Proveedor).filter(Proveedor.cuit == data.proveedor).first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    fingerprint = _fingerprint_payload(data)
    if x_operation_id:
        existente = db.query(FacturaProveedor).filter(FacturaProveedor.operation_id == x_operation_id).first()
        if existente:
            guardado = existente.payload_fingerprint or _fingerprint_guardado(db, existente)
            if guardado != fingerprint:
                raise HTTPException(status_code=409, detail="X-Operation-Id ya fue usado con otro payload")
            if not existente.payload_fingerprint:
                existente.payload_fingerprint = guardado; db.commit()
            return {"id": existente.id, "proveedor": existente.proveedor,
                    "num_factura": existente.num_factura, "fecha": existente.fecha,
                    "subtotal": a_pesos(existente.subtotal), "iva": a_pesos(existente.iva),
                    "total": a_pesos(existente.total), "estado": existente.estado,
                    "items": db.query(Compra).filter(Compra.factprov_id == existente.id).count()}
    numero_factura = data.num_factura.strip()
    if numero_factura:
        duplicada = db.query(FacturaProveedor).filter(
            FacturaProveedor.proveedor == data.proveedor,
            FacturaProveedor.num_factura == numero_factura,
        ).first()
        if duplicada:
            raise HTTPException(status_code=409, detail="Ese comprobante del proveedor ya fue registrado")

    # Todo en CENTAVOS enteros. Cada renglon se redondea UNA sola vez (dentro
    # de multiplicar y de aplicar_alicuota) y despues solo se suman enteros, que
    # es exacto. Con floats, el total de la compra y el saldo del proveedor
    # arrastraban un desvio de fraccion de centavo por cada renglon.
    subtotal = 0
    bases_por_iva = {}
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
        bases_por_iva[iva_pct] = bases_por_iva.get(iva_pct, 0) + linea

    iva_total = sum(aplicar_alicuota(base, iva_pct) for iva_pct, base in bases_por_iva.items())

    # Numero de la factura de compra desde el contador. Ver backend/secuencias.py.
    factprov_id = siguiente_numero(db, "compra")
    cabecera = FacturaProveedor(
        id=factprov_id,
        proveedor=data.proveedor,
        fecha=data.fecha,
        subtotal=subtotal,
        iva=iva_total,
        total=subtotal + iva_total,
        num_factura=numero_factura,
        estado="borrador",
        operation_id=x_operation_id,
        payload_fingerprint=fingerprint,
    )
    db.add(cabecera)
    # La cabecera debe existir en la transaccion antes de insertar los renglones.
    # Sin este flush, SQLite puede ver primero el INSERT de `compras` y fallar
    # la FK a `factprov.id` aunque la cabecera ya este agregada en memoria.
    db.flush()

    for item in data.items:
        producto = db.query(StockMercaderia).filter(StockMercaderia.codigo == item.codigo).first()
        db.add(Compra(
            codigo=item.codigo,
            producto=item.producto,
            cantidad=item.cantidad,
            precio=item.precio,
            factprov_id=factprov_id,
            fecha=data.fecha, iva_alicuota=producto.iva or 0,
        ))
    db.flush()
    if data.estado == "confirmada":
        _confirmar(db, cabecera)

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
        "estado": cabecera.estado,
    }


@router.post("/{factura_id}/confirmar")
def confirmar_compra(factura_id: int, db: Session = Depends(get_db)):
    cabecera = db.query(FacturaProveedor).filter(FacturaProveedor.id == factura_id).first()
    if not cabecera:
        raise HTTPException(status_code=404, detail="Factura de compra no encontrada")
    _confirmar(db, cabecera); db.commit()
    return {"id": cabecera.id, "estado": cabecera.estado}


@router.get("/{factura_id}/renglones")
def renglones_compra(factura_id: int, db: Session = Depends(get_db)):
    factura = db.query(FacturaProveedor).filter(FacturaProveedor.id == factura_id).first()
    if not factura:
        raise HTTPException(status_code=404, detail="Factura de compra no encontrada")
    return [{"compra_id": r.id, "codigo": r.codigo, "producto": r.producto,
             "cantidad": r.cantidad, "precio": a_pesos(r.precio)}
            for r in db.query(Compra).filter(Compra.factprov_id == factura_id).order_by(Compra.id).all()]


@router.post("/{factura_id}/anular")
def anular_compra(factura_id: int, db: Session = Depends(get_db)):
    cabecera = db.query(FacturaProveedor).filter(FacturaProveedor.id == factura_id).first()
    if not cabecera:
        raise HTTPException(status_code=404, detail="Factura de compra no encontrada")
    if cabecera.estado == "anulada":
        return {"id": cabecera.id, "estado": "anulada"}
    if cabecera.estado == "borrador":
        cabecera.estado = "anulada"; cabecera.anulada_en = datetime.utcnow(); db.commit()
        return {"id": cabecera.id, "estado": "anulada"}
    deposito = _deposito_principal(db)
    movimientos = db.query(MovimientoStock).filter(
        MovimientoStock.origen_tipo == "factura_compra", MovimientoStock.origen_id == factura_id
    ).order_by(MovimientoStock.id.desc()).all()
    requeridas = {}
    for original in movimientos:
        clave = (original.deposito_id, original.codigo)
        requeridas[clave] = requeridas.get(clave, 0) + original.cantidad
    for (deposito_id, codigo), cantidad in requeridas.items():
        existencia = db.query(ExistenciaDeposito).filter(
            ExistenciaDeposito.deposito_id == deposito_id,
            ExistenciaDeposito.codigo == codigo).first()
        if not existencia or existencia.cantidad + 1e-9 < cantidad:
            raise HTTPException(status_code=409, detail="No se puede anular: parte del stock comprado ya no está disponible")
    for original in movimientos:
        existencia = db.query(ExistenciaDeposito).filter(
            ExistenciaDeposito.deposito_id == original.deposito_id,
            ExistenciaDeposito.codigo == original.codigo).first()
        producto = db.query(StockMercaderia).filter(StockMercaderia.codigo == original.codigo).first()
        db.add(MovimientoStock(
            deposito_id=original.deposito_id, codigo=original.codigo, fecha=datetime.utcnow().date().isoformat(),
            sentido="salida", cantidad=original.cantidad, costo_unitario=original.costo_unitario,
            costo_anterior=existencia.costo_promedio, costo_resultante=original.costo_anterior,
            origen_tipo="anulacion_factura_compra", origen_id=factura_id,
            origen_renglon_id=original.origen_renglon_id, reversa_de=original.id,
        ))
        existencia.cantidad -= original.cantidad; existencia.costo_promedio = original.costo_anterior
        producto.cantidad = existencia.cantidad; producto.precom = existencia.costo_promedio
    saldos.aplicar_a_proveedor(db, cabecera.proveedor, -(cabecera.total or 0))
    cabecera.estado = "anulada"; cabecera.anulada_en = datetime.utcnow(); db.commit()
    return {"id": cabecera.id, "estado": "anulada"}


@router.post("/notas-credito-financieras")
def nota_credito_financiera(data: NotaCreditoProveedorCreate, db: Session = Depends(get_db)):
    """Reduce deuda/IVA comercial sin fingir una salida física de mercadería."""
    proveedor = db.query(Proveedor).filter(Proveedor.cuit == data.proveedor).first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    ncp_id = siguiente_numero(db, "nota_credito_proveedor")
    descripcion = " ".join(x for x in (data.referencia.strip(), data.descripcion.strip()) if x)
    db.add(NCP(id=ncp_id, proveedor=data.proveedor, fecha=data.fecha,
               descripcion=descripcion[:500], monto=data.monto))
    saldos.aplicar_a_proveedor(db, data.proveedor, -data.monto)
    db.commit()
    return {"id": ncp_id, "proveedor": data.proveedor, "fecha": data.fecha,
            "monto": a_pesos(data.monto), "mueve_stock": False}


@router_devoluciones.post("/")
def create_devolucion(data: DevolucionCreate, db: Session = Depends(get_db)):
    """Registrar una devolucion a proveedor: descuenta stock y saldo, y deja una NCP."""
    proveedor = db.query(Proveedor).filter(Proveedor.cuit == data.proveedor).first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    if not data.factura_id:
        raise HTTPException(status_code=422, detail="La devolución física debe indicar factura_id")
    factura = db.query(FacturaProveedor).filter(
        FacturaProveedor.id == data.factura_id, FacturaProveedor.proveedor == data.proveedor,
        FacturaProveedor.estado == "confirmada").first()
    if not factura:
        raise HTTPException(status_code=404, detail="Factura confirmada del proveedor no encontrada")

    # Aritmetica en CENTAVOS enteros (ver backend/dinero.py).
    subtotal = 0
    iva_total = 0
    for item in data.items:
        linea = multiplicar(item.precio, item.cantidad)
        subtotal += linea
        compra = db.query(Compra).filter(Compra.id == item.compra_id,
                                         Compra.factprov_id == factura.id).first()
        if not compra:
            raise HTTPException(status_code=422, detail=f"El renglón {item.compra_id} no pertenece a la factura")
        if compra.codigo != item.codigo:
            raise HTTPException(status_code=422, detail="El producto no coincide con el renglón de compra")
        devuelto = db.query(DevolucionCompraItem).filter(DevolucionCompraItem.compra_id == compra.id).all()
        if sum(d.cantidad for d in devuelto) + item.cantidad > compra.cantidad + 1e-9:
            raise HTTPException(status_code=409, detail=f"La devolución supera lo comprado para {item.codigo}")
        producto = db.query(StockMercaderia).filter(StockMercaderia.codigo == item.codigo).first()
        if not producto or (producto.cantidad or 0) + 1e-9 < item.cantidad:
            raise HTTPException(status_code=409, detail=f"Stock insuficiente para devolver {item.codigo}")
        iva_pct = producto.iva if producto and producto.iva is not None else 21.0
        iva_total += aplicar_alicuota(linea, iva_pct)

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
    db.flush()
    deposito = _deposito_principal(db)
    for item in data.items:
        compra = db.query(Compra).filter(Compra.id == item.compra_id,
                                         Compra.factprov_id == factura.id).one()
        producto = db.query(StockMercaderia).filter(StockMercaderia.codigo == item.codigo).first()
        existencia = _existencia(db, deposito.id, producto)
        if existencia.cantidad + 1e-9 < item.cantidad:
            raise HTTPException(status_code=409, detail=f"Stock insuficiente en depósito para devolver {item.codigo}")
        db.add(DevolucionCompraItem(ncp_id=ncp_id, compra_id=compra.id, codigo=item.codigo,
                                    cantidad=item.cantidad, precio=item.precio))
        db.flush()
        dev = db.query(DevolucionCompraItem).filter(DevolucionCompraItem.ncp_id == ncp_id,
                                                    DevolucionCompraItem.compra_id == compra.id).first()
        db.add(MovimientoStock(
            deposito_id=deposito.id, codigo=item.codigo, fecha=data.fecha, sentido="salida",
            cantidad=item.cantidad, costo_unitario=compra.precio,
            costo_anterior=existencia.costo_promedio, costo_resultante=existencia.costo_promedio,
            origen_tipo="devolucion_compra", origen_id=ncp_id, origen_renglon_id=dev.id,
        ))
        existencia.cantidad -= item.cantidad; producto.cantidad = existencia.cantidad

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
