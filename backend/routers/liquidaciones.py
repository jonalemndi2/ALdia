"""
liquidaciones.py - Router para Liquidaciones de Cereales (LPG), Hacienda (LSP) y Rubros Especiales.

Toda la aritmética vive en el servidor en CENTAVOS enteros (`dinero.py`):
  Bruto operación   = Σ (cantidad_neta × precio_unitario) + IVA operación
  Total deducciones = Σ base_imponible + IVA deducciones (flete, secado, comisión, SENASA...)
  Total retenciones = Σ retenciones (SISA/IVA, Ganancias, IIBB, Checkoff...)
  Neto liquidado    = Bruto operación - Total deducciones - Total retenciones

Al confirmarse una liquidación:
  - Si es `compra` (a productor/proveedor): ingresa `cantidad_neta` al stock físico
    (`MovimientoStock` + `ExistenciaDeposito`) y suma `neto_liquidado` al saldo del proveedor
    mediante `saldos.aplicar_a_proveedor`.
  - Si es `venta` (a acopio/frigorífico/cliente): descuenta `cantidad_neta` del stock físico
    y suma `neto_liquidado` al saldo del cliente mediante `saldos.aplicar_a_cliente`.
"""
import hashlib
import json
import re
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

import saldos
from database import get_db
from dinero import a_pesos, aplicar_alicuota, multiplicar
from errores import ErrorDeNegocio
from models import (
    Cliente,
    Deposito,
    ExistenciaDeposito,
    Liquidacion,
    LiquidacionDeduccion,
    LiquidacionItem,
    LiquidacionRetencion,
    MovimientoStock,
    Proveedor,
    StockMercaderia,
    Usuario,
)
from paises import pais_configurado
from routers.auth import current_user_dep
from schemas import AutorizacionCOE, LiquidacionCreate
from secuencias import siguiente_numero
from security import exigir_modulo
from tiempo import ahora_utc

router = APIRouter()

MODULO_POR_RUBRO = {
    "granos": "liquidaciones_granos",
    "hacienda": "liquidaciones_hacienda",
    "general": "ventas",
}


def _verificar_modulo_rubro(request: Request, db: Session, user: Usuario, rubro: str) -> None:
    clave = MODULO_POR_RUBRO.get((rubro or "granos").lower(), "liquidaciones_granos")
    exigir_modulo(request, db, user, clave)


def _deposito_principal(db: Session) -> Deposito:
    deposito = db.query(Deposito).filter(Deposito.nombre == "Principal").first()
    if not deposito:
        deposito = Deposito(nombre="Principal", activo=True)
        db.add(deposito)
        db.flush()
    return deposito


def _existencia(db: Session, deposito_id: int, producto: StockMercaderia) -> ExistenciaDeposito:
    existencia = (
        db.query(ExistenciaDeposito)
        .filter(
            ExistenciaDeposito.deposito_id == deposito_id,
            ExistenciaDeposito.codigo == producto.codigo,
        )
        .first()
    )
    if not existencia:
        existencia = ExistenciaDeposito(
            deposito_id=deposito_id,
            codigo=producto.codigo,
            cantidad=producto.cantidad or 0.0,
            costo_promedio=producto.precom or 0,
        )
        db.add(existencia)
        db.flush()
    return existencia


def _serializar_cabecera(liq: Liquidacion) -> dict:
    try:
        datos_dom = json.loads(liq.datos_dominio or "{}")
    except (ValueError, TypeError):
        datos_dom = {}
    bruto_con_iva = (liq.subtotal_bruto or 0) + (liq.iva_operacion or 0)
    deducciones_con_iva = (liq.subtotal_deducciones or 0) + (liq.iva_deducciones or 0)
    return {
        "id": liq.id,
        "rubro": liq.rubro,
        "operacion": liq.operacion,
        "cliente": liq.cliente,
        "proveedor": liq.proveedor,
        "tercero": liq.cliente if liq.operacion == "venta" else liq.proveedor,
        "fecha": liq.fecha,
        "num_comprobante": liq.num_comprobante or "",
        "codigo_autorizacion": liq.codigo_autorizacion,
        "subtotal_bruto": a_pesos(liq.subtotal_bruto),
        "iva_operacion": a_pesos(liq.iva_operacion),
        "total_bruto_operacion": a_pesos(bruto_con_iva),
        "subtotal_deducciones": a_pesos(liq.subtotal_deducciones),
        "iva_deducciones": a_pesos(liq.iva_deducciones),
        "total_deducciones": a_pesos(deducciones_con_iva),
        "total_retenciones": a_pesos(liq.total_retenciones),
        "neto_liquidado": a_pesos(liq.neto_liquidado),
        "datos_dominio": datos_dom,
        "observaciones": liq.observaciones or "",
        "estado": liq.estado,
        "moneda": pais_configurado().moneda,
    }


def _serializar_detalle(db: Session, liq: Liquidacion) -> dict:
    salida = _serializar_cabecera(liq)
    items = (
        db.query(LiquidacionItem)
        .filter(LiquidacionItem.liquidacion_id == liq.id)
        .order_by(LiquidacionItem.id)
        .all()
    )
    deducciones = (
        db.query(LiquidacionDeduccion)
        .filter(LiquidacionDeduccion.liquidacion_id == liq.id)
        .order_by(LiquidacionDeduccion.id)
        .all()
    )
    retenciones = (
        db.query(LiquidacionRetencion)
        .filter(LiquidacionRetencion.liquidacion_id == liq.id)
        .order_by(LiquidacionRetencion.id)
        .all()
    )
    salida["items"] = [
        {
            "id": i.id,
            "codigo": i.codigo,
            "descripcion": i.descripcion,
            "cabezas": i.cabezas,
            "cantidad_bruta": i.cantidad_bruta,
            "merma_pct": i.merma_pct,
            "merma_cantidad": i.merma_cantidad,
            "cantidad_neta": i.cantidad_neta,
            "unidad": i.unidad,
            "precio_unitario": a_pesos(i.precio_unitario),
            "iva_alicuota": i.iva_alicuota,
            "subtotal": a_pesos(i.subtotal),
            "iva_importe": a_pesos(i.iva_importe),
            "total": a_pesos((i.subtotal or 0) + (i.iva_importe or 0)),
        }
        for i in items
    ]
    salida["deducciones"] = [
        {
            "id": d.id,
            "concepto": d.concepto,
            "descripcion": d.descripcion,
            "base_imponible": a_pesos(d.base_imponible),
            "iva_alicuota": d.iva_alicuota,
            "iva_importe": a_pesos(d.iva_importe),
            "total": a_pesos(d.total),
        }
        for d in deducciones
    ]
    salida["retenciones"] = [
        {
            "id": r.id,
            "tipo": r.tipo,
            "descripcion": r.descripcion,
            "base_calculo": a_pesos(r.base_calculo),
            "alicuota": r.alicuota,
            "importe": a_pesos(r.importe),
            "certificado": r.certificado,
        }
        for r in retenciones
    ]
    return salida


def _fingerprint_payload(data: LiquidacionCreate) -> str:
    canonico = {
        "rubro": data.rubro,
        "operacion": data.operacion,
        "cliente": data.cliente or "",
        "proveedor": data.proveedor or "",
        "fecha": data.fecha,
        "num_comprobante": (data.num_comprobante or "").strip(),
        "items": [
            (
                i.codigo,
                i.descripcion.strip(),
                i.cabezas,
                format(i.cantidad_bruta, ".8g"),
                format(i.cantidad_neta, ".8g"),
                int(i.precio_unitario),
                format(i.iva_alicuota, ".4g"),
            )
            for i in data.items
        ],
        "deducciones": [
            (d.concepto, int(d.base_imponible), format(d.iva_alicuota, ".4g"))
            for d in data.deducciones
        ],
        "retenciones": [
            (r.tipo, int(r.base_calculo), format(r.alicuota, ".4g"), int(r.importe))
            for r in data.retenciones
        ],
    }
    return hashlib.sha256(
        json.dumps(canonico, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _aplicar_confirmacion(db: Session, cabecera: Liquidacion) -> None:
    """Ejecuta los efectos físicos (stock) y financieros (cuenta corriente) de una liquidación."""
    if cabecera.estado == "confirmada":
        return
    if cabecera.estado != "borrador":
        raise HTTPException(
            status_code=409,
            detail=f"Sólo se puede confirmar una liquidación en borrador (estado actual: {cabecera.estado})",
        )

    deposito = _deposito_principal(db)
    renglones = (
        db.query(LiquidacionItem)
        .filter(LiquidacionItem.liquidacion_id == cabecera.id)
        .order_by(LiquidacionItem.id)
        .all()
    )

    for renglon in renglones:
        if renglon.codigo is None:
            continue
        producto = (
            db.query(StockMercaderia)
            .filter(StockMercaderia.codigo == renglon.codigo)
            .first()
        )
        if not producto:
            raise ErrorDeNegocio(
                "PRODUCTO_NO_EXISTE",
                f"El producto {renglon.codigo} no existe en el stock",
                codigo=renglon.codigo,
            )
        existencia = _existencia(db, deposito.id, producto)
        anterior_costo = existencia.costo_promedio or 0
        cant_actual = float(existencia.cantidad or 0.0)
        cant_mov = float(renglon.cantidad_neta or 0.0)

        if cabecera.operacion == "compra":
            nueva_cantidad = cant_actual + cant_mov
            costo_unit = int(renglon.precio_unitario or 0)
            promedio = (
                round((cant_actual * anterior_costo + cant_mov * costo_unit) / nueva_cantidad)
                if nueva_cantidad > 0
                else costo_unit
            )
            db.add(
                MovimientoStock(
                    deposito_id=deposito.id,
                    codigo=renglon.codigo,
                    fecha=cabecera.fecha,
                    sentido="entrada",
                    cantidad=cant_mov,
                    costo_unitario=costo_unit,
                    costo_anterior=anterior_costo,
                    costo_resultante=promedio,
                    origen_tipo="liquidacion_compra",
                    origen_id=cabecera.id,
                    origen_renglon_id=renglon.id,
                )
            )
            existencia.cantidad = nueva_cantidad
            existencia.costo_promedio = promedio
            producto.cantidad = nueva_cantidad
            producto.precom = promedio
        else:
            # Liquidación de venta: valida y descuenta stock neto entregado/liquidado
            if cant_actual + 1e-9 < cant_mov:
                raise ErrorDeNegocio(
                    "STOCK_INSUFICIENTE",
                    f"Stock insuficiente de '{producto.producto}': se intentan liquidar "
                    f"{cant_mov:g} y hay {cant_actual:g}",
                    producto=producto.producto,
                    pedido=cant_mov,
                    disponible=cant_actual,
                )
            nueva_cantidad = max(0.0, cant_actual - cant_mov)
            db.add(
                MovimientoStock(
                    deposito_id=deposito.id,
                    codigo=renglon.codigo,
                    fecha=cabecera.fecha,
                    sentido="salida",
                    cantidad=cant_mov,
                    costo_unitario=anterior_costo,
                    costo_anterior=anterior_costo,
                    costo_resultante=anterior_costo,
                    origen_tipo="liquidacion_venta",
                    origen_id=cabecera.id,
                    origen_renglon_id=renglon.id,
                )
            )
            existencia.cantidad = nueva_cantidad
            producto.cantidad = nueva_cantidad

    if cabecera.operacion == "venta":
        saldos.aplicar_a_cliente(db, cabecera.cliente, +(cabecera.neto_liquidado or 0))
    else:
        saldos.aplicar_a_proveedor(db, cabecera.proveedor, +(cabecera.neto_liquidado or 0))

    cabecera.estado = "confirmada"


@router.get("/")
def listar_liquidaciones(
    request: Request,
    rubro: str = None,
    operacion: str = None,
    tercero: str = None,
    estado: str = None,
    fecha_desde: str = None,
    fecha_hasta: str = None,
    limite: int = 50,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user_dep),
):
    if limite < 1 or limite > 500:
        raise HTTPException(status_code=422, detail="limite debe estar entre 1 y 500")

    if rubro:
        _verificar_modulo_rubro(request, db, user, rubro)
        rubros_permitidos = [rubro.strip().lower()]
    else:
        # Si no filtra por rubro, verificamos a cuáles rubros de liquidación tiene acceso
        rubros_permitidos = []
        for r, mod_clave in MODULO_POR_RUBRO.items():
            try:
                exigir_modulo(request, db, user, mod_clave)
                rubros_permitidos.append(r)
            except ErrorDeNegocio:
                continue
        if not rubros_permitidos:
            exigir_modulo(request, db, user, "liquidaciones_granos")

    q = db.query(Liquidacion).filter(Liquidacion.rubro.in_(rubros_permitidos))
    if operacion:
        q = q.filter(Liquidacion.operacion == operacion.strip().lower())
    if tercero:
        t = tercero.strip()
        q = q.filter((Liquidacion.cliente == t) | (Liquidacion.proveedor == t))
    if estado:
        q = q.filter(Liquidacion.estado == estado.strip().lower())
    if fecha_desde:
        q = q.filter(Liquidacion.fecha >= fecha_desde)
    if fecha_hasta:
        q = q.filter(Liquidacion.fecha <= fecha_hasta)

    filas = q.order_by(Liquidacion.id.desc()).limit(limite).all()
    return [_serializar_cabecera(f) for f in filas]


@router.get("/{liquidacion_id}")
def detalle_liquidacion(
    liquidacion_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user_dep),
):
    liq = db.query(Liquidacion).filter(Liquidacion.id == liquidacion_id).first()
    if not liq:
        raise ErrorDeNegocio("COMPROBANTE_NO_ENCONTRADO", "Liquidación no encontrada")
    _verificar_modulo_rubro(request, db, user, liq.rubro)
    return _serializar_detalle(db, liq)


@router.post("/")
def crear_liquidacion(
    data: LiquidacionCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user_dep),
    x_operation_id: str = Header(None),
):
    """Crea una liquidación (borrador o confirmada) calculando subtotales, mermas, IVAs y neto en centavos."""
    _verificar_modulo_rubro(request, db, user, data.rubro)

    if data.codigo_autorizacion:
        pais = pais_configurado()
        if not pais.requiere_autorizacion_fiscal:
            raise ErrorDeNegocio(
                "OPERACION_NO_APLICA_EN_ESTE_PAIS",
                f"En {pais.nombre} las liquidaciones no utilizan código de autorización fiscal (COE).",
            )

    # Validar existencia del tercero (cliente en venta, proveedor en compra)
    if data.operacion == "venta":
        ficha = db.query(Cliente).filter(Cliente.cuit == data.cliente).first()
        if not ficha:
            raise ErrorDeNegocio(
                "CLIENTE_NO_EXISTE",
                f"El cliente '{data.cliente}' no está dado de alta",
                cuit=data.cliente,
            )
    else:
        ficha = db.query(Proveedor).filter(Proveedor.cuit == data.proveedor).first()
        if not ficha:
            raise ErrorDeNegocio(
                "PROVEEDOR_NO_EXISTE",
                f"El proveedor '{data.proveedor}' no está dado de alta",
                cuit=data.proveedor,
            )

    fingerprint = _fingerprint_payload(data)
    if x_operation_id:
        existente = (
            db.query(Liquidacion)
            .filter(Liquidacion.operation_id == x_operation_id)
            .first()
        )
        if existente:
            if existente.payload_fingerprint and existente.payload_fingerprint != fingerprint:
                raise ErrorDeNegocio(
                    "OPERACION_CONFLICTIVA",
                    "X-Operation-Id ya fue utilizado para una liquidación con datos distintos",
                )
            return _serializar_detalle(db, existente)

    # Validar artículos referenciados y calcular renglones en centavos enteros
    subtotal_bruto = 0
    iva_operacion = 0
    renglones_preparados = []

    for item in data.items:
        if item.codigo is not None:
            prod = db.query(StockMercaderia).filter(StockMercaderia.codigo == item.codigo).first()
            if not prod:
                raise ErrorDeNegocio(
                    "PRODUCTO_NO_EXISTE",
                    f"El artículo {item.codigo} no existe en el stock",
                    codigo=item.codigo,
                )
        sub_item = multiplicar(item.precio_unitario, item.cantidad_neta)
        iva_item = aplicar_alicuota(sub_item, item.iva_alicuota)
        subtotal_bruto += sub_item
        iva_operacion += iva_item
        renglones_preparados.append((item, sub_item, iva_item))

    # Calcular deducciones (flete, secado, zarandeo, comisión, SENASA, guías...)
    subtotal_deducciones = 0
    iva_deducciones = 0
    deducciones_preparadas = []
    for ded in data.deducciones:
        iva_ded = aplicar_alicuota(ded.base_imponible, ded.iva_alicuota)
        tot_ded = ded.base_imponible + iva_ded
        subtotal_deducciones += ded.base_imponible
        iva_deducciones += iva_ded
        deducciones_preparadas.append((ded, iva_ded, tot_ded))

    # Calcular retenciones (SISA, IVA, Ganancias, IIBB, Checkoff...)
    total_retenciones = 0
    retenciones_preparadas = []
    for ret in data.retenciones:
        base_ret = ret.base_calculo if ret.base_calculo > 0 else subtotal_bruto
        imp_ret = ret.importe
        if imp_ret == 0 and ret.alicuota > 0:
            imp_ret = aplicar_alicuota(base_ret, ret.alicuota)
        total_retenciones += imp_ret
        retenciones_preparadas.append((ret, base_ret, imp_ret))

    neto_liquidado = (
        (subtotal_bruto + iva_operacion)
        - (subtotal_deducciones + iva_deducciones)
        - total_retenciones
    )
    if neto_liquidado < 0:
        raise ErrorDeNegocio(
            "IMPORTES_NO_CIERRAN",
            "Las deducciones y retenciones superan el total bruto de la operación "
            f"(bruto con IVA: {a_pesos(subtotal_bruto + iva_operacion):.2f}, "
            f"deducciones + retenciones: {a_pesos(subtotal_deducciones + iva_deducciones + total_retenciones):.2f})",
        )

    liq_id = siguiente_numero(db, "liquidacion")
    cabecera = Liquidacion(
        id=liq_id,
        rubro=data.rubro,
        operacion=data.operacion,
        cliente=data.cliente,
        proveedor=data.proveedor,
        fecha=data.fecha,
        num_comprobante=(data.num_comprobante or "").strip(),
        codigo_autorizacion=(data.codigo_autorizacion or "").strip() or None,
        subtotal_bruto=subtotal_bruto,
        iva_operacion=iva_operacion,
        subtotal_deducciones=subtotal_deducciones,
        iva_deducciones=iva_deducciones,
        total_retenciones=total_retenciones,
        neto_liquidado=neto_liquidado,
        datos_dominio=json.dumps(data.datos_dominio or {}, ensure_ascii=False),
        observaciones=(data.observaciones or "").strip(),
        estado="borrador",
        operation_id=x_operation_id,
        payload_fingerprint=fingerprint,
    )
    db.add(cabecera)
    db.flush()

    for item, sub_item, iva_item in renglones_preparados:
        db.add(
            LiquidacionItem(
                liquidacion_id=liq_id,
                codigo=item.codigo,
                descripcion=item.descripcion,
                cabezas=item.cabezas,
                cantidad_bruta=item.cantidad_bruta,
                merma_pct=item.merma_pct,
                merma_cantidad=item.merma_cantidad,
                cantidad_neta=item.cantidad_neta,
                unidad=item.unidad,
                precio_unitario=item.precio_unitario,
                iva_alicuota=item.iva_alicuota,
                subtotal=sub_item,
                iva_importe=iva_item,
            )
        )

    for ded, iva_ded, tot_ded in deducciones_preparadas:
        db.add(
            LiquidacionDeduccion(
                liquidacion_id=liq_id,
                concepto=ded.concepto,
                descripcion=ded.descripcion,
                base_imponible=ded.base_imponible,
                iva_alicuota=ded.iva_alicuota,
                iva_importe=iva_ded,
                total=tot_ded,
            )
        )

    for ret, base_ret, imp_ret in retenciones_preparadas:
        db.add(
            LiquidacionRetencion(
                liquidacion_id=liq_id,
                tipo=ret.tipo,
                descripcion=ret.descripcion,
                base_calculo=base_ret,
                alicuota=ret.alicuota,
                importe=imp_ret,
                certificado=ret.certificado,
            )
        )

    db.flush()
    if data.estado == "confirmada":
        _aplicar_confirmacion(db, cabecera)

    db.commit()
    db.refresh(cabecera)
    return _serializar_detalle(db, cabecera)


@router.post("/{liquidacion_id}/confirmar")
def confirmar_liquidacion(
    liquidacion_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user_dep),
):
    """Confirma un borrador de liquidación: impacta stock neto y cuenta corriente."""
    liq = db.query(Liquidacion).filter(Liquidacion.id == liquidacion_id).first()
    if not liq:
        raise ErrorDeNegocio("COMPROBANTE_NO_ENCONTRADO", "Liquidación no encontrada")
    _verificar_modulo_rubro(request, db, user, liq.rubro)
    _aplicar_confirmacion(db, liq)
    db.commit()
    db.refresh(liq)
    return _serializar_detalle(db, liq)


@router.post("/{liquidacion_id}/coe")
def registrar_coe(
    liquidacion_id: int,
    datos: AutorizacionCOE,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user_dep),
):
    """Registra el Código de Operación Electrónica (COE) en países con autorización fiscal de liquidaciones."""
    pais = pais_configurado()
    if not pais.requiere_autorizacion_fiscal:
        raise ErrorDeNegocio(
            "OPERACION_NO_APLICA_EN_ESTE_PAIS",
            f"En {pais.nombre} las liquidaciones no requieren COE ({pais.organismo_fiscal or 'sin organismo fiscal'}).",
        )
    liq = db.query(Liquidacion).filter(Liquidacion.id == liquidacion_id).first()
    if not liq:
        raise ErrorDeNegocio("COMPROBANTE_NO_ENCONTRADO", "Liquidación no encontrada")
    _verificar_modulo_rubro(request, db, user, liq.rubro)

    if liq.codigo_autorizacion:
        raise ErrorDeNegocio(
            "CAE_YA_EMITIDO",
            f"La liquidación #{liquidacion_id} ya tiene código de autorización ({liq.codigo_autorizacion}).",
        )
    limpio = re.sub(r"[^0-9]", "", str(datos.coe or ""))
    if len(limpio) != 12:
        raise ErrorDeNegocio(
            "DATOS_INVALIDOS",
            f"El COE debe tener 12 dígitos numéricos (recibido: {datos.coe!r}).",
        )
    liq.codigo_autorizacion = limpio
    if datos.observaciones:
        liq.observaciones = (
            f"{liq.observaciones} | {datos.observaciones}".strip(" |")
            if liq.observaciones
            else datos.observaciones.strip()
        )
    db.commit()
    db.refresh(liq)
    return _serializar_detalle(db, liq)


@router.delete("/{liquidacion_id}")
def anular_liquidacion(
    liquidacion_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user_dep),
):
    """Anula una liquidación. Si estaba confirmada, revierte el saldo y los movimientos de stock."""
    liq = db.query(Liquidacion).filter(Liquidacion.id == liquidacion_id).first()
    if not liq:
        raise ErrorDeNegocio("COMPROBANTE_NO_ENCONTRADO", "Liquidación no encontrada")
    _verificar_modulo_rubro(request, db, user, liq.rubro)

    if liq.estado == "anulada":
        return {"id": liq.id, "estado": "anulada"}

    if liq.estado == "confirmada":
        origen_tipo = "liquidacion_compra" if liq.operacion == "compra" else "liquidacion_venta"
        movimientos = (
            db.query(MovimientoStock)
            .filter(
                MovimientoStock.origen_tipo == origen_tipo,
                MovimientoStock.origen_id == liq.id,
            )
            .order_by(MovimientoStock.id)
            .all()
        )
        for original in movimientos:
            ya_revertido = (
                db.query(MovimientoStock)
                .filter(MovimientoStock.reversa_de == original.id)
                .first()
            )
            if ya_revertido:
                continue
            existencia = (
                db.query(ExistenciaDeposito)
                .filter(
                    ExistenciaDeposito.deposito_id == original.deposito_id,
                    ExistenciaDeposito.codigo == original.codigo,
                )
                .first()
            )
            producto = (
                db.query(StockMercaderia)
                .filter(StockMercaderia.codigo == original.codigo)
                .first()
            )
            if liq.operacion == "compra":
                if not existencia or (existencia.cantidad or 0.0) + 1e-9 < original.cantidad:
                    raise HTTPException(
                        status_code=409,
                        detail="No se puede anular la liquidación: parte del stock ingresado ya fue utilizado",
                    )
                sentido_rev = "salida"
                nueva_cant = max(0.0, (existencia.cantidad or 0.0) - original.cantidad)
                nuevo_costo = original.costo_anterior
            else:
                sentido_rev = "entrada"
                nueva_cant = (existencia.cantidad if existencia else 0.0) + original.cantidad
                nuevo_costo = existencia.costo_promedio if existencia else original.costo_anterior

            db.add(
                MovimientoStock(
                    deposito_id=original.deposito_id,
                    codigo=original.codigo,
                    fecha=ahora_utc().strftime("%Y-%m-%d"),
                    sentido=sentido_rev,
                    cantidad=original.cantidad,
                    costo_unitario=original.costo_unitario,
                    costo_anterior=existencia.costo_promedio if existencia else 0,
                    costo_resultante=nuevo_costo,
                    origen_tipo=f"anulacion_{origen_tipo}",
                    origen_id=liq.id,
                    origen_renglon_id=original.origen_renglon_id,
                    reversa_de=original.id,
                )
            )
            if existencia:
                existencia.cantidad = nueva_cant
                existencia.costo_promedio = nuevo_costo
            if producto:
                producto.cantidad = nueva_cant
                producto.precom = nuevo_costo

        if liq.operacion == "venta":
            saldos.aplicar_a_cliente(db, liq.cliente, -(liq.neto_liquidado or 0))
        else:
            saldos.aplicar_a_proveedor(db, liq.proveedor, -(liq.neto_liquidado or 0))

    liq.estado = "anulada"
    liq.anulada_en = ahora_utc()
    db.commit()
    return {"id": liq.id, "estado": liq.estado}
