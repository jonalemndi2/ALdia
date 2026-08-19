"""
afip.py (router) - Factura electrónica AFIP.

Monta en /api/afip el circuito de autorización de comprobantes contra el
WSFEv1 de AFIP. La lógica de protocolo (WSAA, firma CMS, SOAP) vive en
backend/afip.py; acá está solamente el puente con el negocio: tomar una factura
ya emitida, armar sus importes fiscales y guardar lo que AFIP responda.

Reglas que se respetan en todo el archivo:

  * Si AFIP no está configurado se devuelve 400 con "AFIP no configurado".
    NUNCA un CAE inventado.
  * Un rechazo de AFIP se guarda con resultado 'R' y se devuelve como error
    HTTP (422), no como éxito.
  * La emisión de la factura y el descuento de stock NO se tocan acá: eso ya lo
    hace POST /api/facturas/ de forma transaccional.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

import afip as ws
from errores import ErrorDeNegocio
from database import get_db
from dinero import a_pesos, aplicar_alicuota, multiplicar, porcentaje_desde_importes
from models import Factura, StockMercaderia, Venta
from schemas import CAEResponse, SolicitudCAE

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _config(db: Session) -> ws.AfipConfig:
    return ws.cargar_config(db)


def _config_operativa(db: Session) -> ws.AfipConfig:
    """Configuración lista para operar, o HTTP 400 con el motivo exacto."""
    cfg = _config(db)
    try:
        ws.exigir_operativa(cfg)
    except ws.AfipNoConfigurado as exc:
        raise HTTPException(status_code=400, detail=exc.mensaje)
    return cfg


def _error_afip(exc: ws.AfipError, status: int = 502) -> HTTPException:
    if isinstance(exc, ws.AfipNoConfigurado):
        return HTTPException(status_code=400, detail=exc.mensaje)
    return HTTPException(status_code=status, detail=exc.mensaje)


def _composicion_iva(db: Session, factura: Factura, tipo_comprobante: int) -> dict:
    """Arma los importes fiscales del comprobante a partir de sus renglones.

    Los renglones (tabla `ventas`) no guardan la alícuota; se resuelve contra
    `stockmercaderia`, igual que hace la pantalla de facturación. Si la factura
    no tiene renglones (por ejemplo una nota registrada sin ítems) se deduce una
    única alícuota a partir de subtotal e IVA de la cabecera.

    Se devuelve neto, iva, total y el array AlicIva que espera el WSFEv1.

    DINERO: todo el calculo se hace en CENTAVOS enteros (que es como se
    guardan los importes) y se convierte a decimal de 2 posiciones recien al
    devolver, porque es lo que AFIP espera en el WSFEv1. Asi la base
    imponible por alicuota, el IVA y el total se redondean UNA sola vez, y la
    suma de las alicuotas cierra exactamente con el total declarado.
    """
    signo = -1 if (factura.total or 0) < 0 else 1
    es_nota_credito = tipo_comprobante in ws.TIPOS_NOTA_CREDITO

    # Un total negativo sólo tiene sentido como nota de crédito: AFIP recibe
    # siempre importes positivos y el signo lo da el tipo de comprobante.
    if signo < 0 and not es_nota_credito:
        raise HTTPException(
            status_code=400,
            detail=(
                f"La factura {factura.facturanumero} tiene importe negativo "
                f"({a_pesos(factura.total):.2f}). Para AFIP eso es una Nota de Crédito: "
                "solicite el CAE indicando tipo_comprobante 3 (NC A), 8 (NC B) o 13 (NC C)."
            ),
        )

    renglones = db.query(Venta).filter(Venta.idfactura == factura.facturanumero).all()

    bases: dict = {}
    if renglones:
        alicuotas_stock = {
            s.codigo: (s.iva if s.iva is not None else 21.0)
            for s in db.query(StockMercaderia).all()
        }
        for r in renglones:
            alicuota = float(alicuotas_stock.get(r.codigo, 21.0))
            # multiplicar() redondea el renglon una sola vez, en centavos.
            base = abs(multiplicar(r.precio, r.cantidad))
            bases[alicuota] = bases.get(alicuota, 0) + base
    else:
        neto = abs(factura.subtotal or 0)          # centavos
        iva_importe = abs(factura.iva or 0)        # centavos
        if neto <= 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"La factura {factura.facturanumero} no tiene renglones ni importe neto: "
                    "no se puede armar el comprobante para AFIP."
                ),
            )
        porcentaje = porcentaje_desde_importes(iva_importe, neto)
        if porcentaje not in ws.IVA_ID_POR_ALICUOTA:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No se puede determinar la alícuota de IVA de la factura "
                    f"{factura.facturanumero} (neto {a_pesos(neto):.2f}, "
                    f"IVA {a_pesos(iva_importe):.2f} = "
                    f"{porcentaje:g}%). Cargue el comprobante con sus renglones."
                ),
            )
        bases[porcentaje] = neto

    # Comprobante clase C (monotributo): no discrimina IVA.
    if tipo_comprobante in ws.TIPOS_CLASE_C:
        total = a_pesos(abs(factura.total or 0))
        return {"neto": total, "iva": 0.0, "total": total, "alicuotas": []}

    alicuotas = []
    neto_total = 0   # centavos
    iva_total = 0    # centavos
    try:
        for alicuota, base in sorted(bases.items()):
            # `base` ya es un entero exacto de centavos; el IVA se redondea
            # una unica vez por alicuota, con el criterio de dinero.py.
            importe = aplicar_alicuota(base, alicuota)
            alicuotas.append({
                "Id": ws.id_iva(alicuota),
                # AFIP recibe decimales con 2 posiciones, no centavos.
                "BaseImp": a_pesos(base),
                "Importe": a_pesos(importe),
            })
            neto_total += base
            iva_total += importe
    except ws.AfipError as exc:
        raise HTTPException(status_code=400, detail=exc.mensaje)

    total_centavos = neto_total + iva_total

    # Control de coherencia: si lo que se le va a declarar a AFIP no coincide con
    # lo que dice la factura (y por lo tanto con lo que se le cobró al cliente),
    # se corta. Es plata: no se manda un importe distinto "redondeando".
    # La tolerancia queda en 5 centavos por compatibilidad con comprobantes
    # cargados a mano; con la aritmetica en centavos la diferencia deberia
    # ser 0 cuando la factura se emitio por el sistema.
    total_factura = abs(factura.total or 0)   # centavos
    if abs(total_centavos - total_factura) > 5:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Los importes de la factura {factura.facturanumero} no cierran: la suma de "
                f"sus renglones da {a_pesos(total_centavos):.2f} y la factura dice "
                f"{a_pesos(total_factura):.2f}. "
                "Corrija el comprobante antes de pedir el CAE."
            ),
        )
    # Salida hacia AFIP: pesos con 2 decimales exactos.
    return {
        "neto": a_pesos(neto_total),
        "iva": a_pesos(iva_total),
        "total": a_pesos(total_centavos),
        "alicuotas": alicuotas,
    }


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────

def _tipo_sugerido(db: Session, factura: Factura) -> Optional[int]:
    """Tipo de comprobante que corresponde por las condiciones frente al IVA.

    Emisor: la condicion del negocio (Configuracion 'negocio_iva').
    Receptor: la condicion de la ficha del cliente.
    Una nota de credito se detecta por el total negativo, que es como el sistema
    las registra.
    """
    from models import Cliente, Configuracion

    fila = db.query(Configuracion).filter(Configuracion.clave == "negocio_iva").first()
    cond_emisor = (fila.valor if fila else "") or "responsable_inscripto"

    cliente = db.query(Cliente).filter(Cliente.cuit == factura.cliente).first()
    cond_receptor = (getattr(cliente, "condicion_iva", None) or "consumidor_final")

    naturaleza = "nota_credito" if (factura.total or 0) < 0 else "factura"
    try:
        return ws.tipo_comprobante_sugerido(cond_emisor, cond_receptor, naturaleza)
    except ws.AfipError:
        return None


@router.get("/condiciones-iva")
def condiciones_iva():
    """Condiciones frente al IVA validas, para el formulario de clientes."""
    from schemas import CONDICIONES_IVA

    return [
        {"clave": clave, "nombre": datos["nombre"], "afip_id": datos["afip_id"]}
        for clave, datos in CONDICIONES_IVA.items()
    ]


@router.get("/facturas/{factura_num}/tipo-sugerido")
def tipo_sugerido_factura(factura_num: int, db: Session = Depends(get_db)):
    """Que comprobante corresponde emitir para esta factura, y por que."""
    from models import Cliente, Configuracion

    factura = db.query(Factura).filter(Factura.facturanumero == factura_num).first()
    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    fila = db.query(Configuracion).filter(Configuracion.clave == "negocio_iva").first()
    cond_emisor = (fila.valor if fila else "") or "responsable_inscripto"
    cliente = db.query(Cliente).filter(Cliente.cuit == factura.cliente).first()
    cond_receptor = (getattr(cliente, "condicion_iva", None) or "consumidor_final")

    tipo = _tipo_sugerido(db, factura)
    return {
        "factura": factura_num,
        "condicion_emisor": cond_emisor,
        "condicion_receptor": cond_receptor,
        "cliente_conocido": cliente is not None,
        "tipo_comprobante": tipo,
        "descripcion": ws.TIPOS_COMPROBANTE.get(tipo, "—"),
        "clase": ws.clase_comprobante(cond_emisor, cond_receptor),
    }


@router.get("/estado")
def estado(db: Session = Depends(get_db)):
    """Estado de la integración: configuración local + FEDummy de AFIP.

    Nunca lanza 500: la pantalla necesita poder mostrar "no configurado" o
    "AFIP no responde" sin romperse.
    """
    cfg = _config(db)
    salida = {
        "habilitado": cfg.habilitado,
        "configurado": cfg.configurado,
        "entorno": cfg.entorno,
        "cuit": cfg.cuit,
        "punto_venta": cfg.punto_venta,
        "tipo_comprobante_defecto": cfg.tipo_comprobante,
        "url_wsaa": cfg.url_wsaa,
        "url_wsfe": cfg.url_wsfe,
        "problemas": cfg.problemas,
        "certificado": None,
        "servidores": None,
        "ticket_acceso": None,
        "error": None,
        "mensaje": "",
    }

    if not cfg.habilitado:
        salida["mensaje"] = (
            "Facturación electrónica AFIP DESHABILITADA. El sistema factura de forma "
            "local, sin CAE. Para activarla hay que cargar el certificado de AFIP y "
            "poner AFIP_HABILITADO=si."
        )
        return salida

    if cfg.problemas:
        salida["mensaje"] = "AFIP no configurado: " + " ".join(cfg.problemas)
        return salida

    # Datos del certificado (local, no requiere internet).
    try:
        salida["certificado"] = ws.info_certificado(cfg)
    except ws.AfipError as exc:
        salida["error"] = exc.mensaje
        salida["mensaje"] = exc.mensaje
        return salida

    # FEDummy: salud de los servidores de AFIP. No requiere ticket de acceso.
    try:
        salida["servidores"] = ws.fe_dummy(cfg)
    except ws.AfipError as exc:
        salida["error"] = exc.mensaje
        salida["mensaje"] = f"No se pudo consultar el estado de AFIP: {exc.mensaje}"
        return salida

    # Ticket de acceso: acá se ve si el certificado está realmente habilitado.
    try:
        ta = ws.obtener_ticket_acceso(cfg)
        salida["ticket_acceso"] = {
            "vigente_hasta": ta.expiracion.isoformat(),
            "desde_cache": ta.desde_cache,
        }
        salida["mensaje"] = (
            f"AFIP operativo en {cfg.entorno.upper()} — CUIT {cfg.cuit}, "
            f"punto de venta {cfg.punto_venta}."
        )
    except ws.AfipError as exc:
        salida["error"] = exc.mensaje
        salida["mensaje"] = (
            "Los servidores de AFIP responden, pero el certificado todavía no permite "
            f"autenticarse: {exc.mensaje}"
        )
    return salida


@router.get("/tipos-comprobante")
def tipos_comprobante(db: Session = Depends(get_db)):
    """Tabla oficial de tipos de comprobante (FEParamGetTiposCbte)."""
    cfg = _config_operativa(db)
    try:
        return {"entorno": cfg.entorno, "tipos": ws.fe_param_tipos_cbte(cfg)}
    except ws.AfipError as exc:
        raise _error_afip(exc)


@router.get("/tipos-iva")
def tipos_iva(db: Session = Depends(get_db)):
    """Tabla oficial de alícuotas de IVA (FEParamGetTiposIva)."""
    cfg = _config_operativa(db)
    try:
        return {"entorno": cfg.entorno, "tipos": ws.fe_param_tipos_iva(cfg)}
    except ws.AfipError as exc:
        raise _error_afip(exc)


@router.get("/ultimo-autorizado")
def ultimo_autorizado(
    punto_venta: Optional[int] = Query(default=None),
    tipo_comprobante: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Último número autorizado por AFIP para un punto de venta y tipo (FECompUltimoAutorizado)."""
    cfg = _config_operativa(db)
    pv = punto_venta or cfg.punto_venta
    tipo = tipo_comprobante or cfg.tipo_comprobante
    try:
        ultimo = ws.fe_comp_ultimo_autorizado(cfg, pv, tipo)
    except ws.AfipError as exc:
        raise _error_afip(exc)
    return {
        "entorno": cfg.entorno,
        "punto_venta": pv,
        "tipo_comprobante": tipo,
        "descripcion": ws.TIPOS_COMPROBANTE.get(tipo, f"Tipo {tipo}"),
        "ultimo_autorizado": ultimo,
        "proximo": ultimo + 1,
    }


@router.get("/facturas/{factura_num}/qr")
def qr_comprobante(factura_num: int, db: Session = Depends(get_db)):
    """Codigo QR fiscal del comprobante (RG 4892/2020).

    Desde 2021 todo comprobante electronico impreso debe llevarlo: sin el QR el
    impreso no cumple la normativa aunque el CAE sea valido.

    Devuelve el SVG listo para incrustar y la URL que codifica, para que se pueda
    auditar que el contenido es el correcto.
    """
    factura = db.query(Factura).filter(Factura.facturanumero == factura_num).first()
    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    if not factura.cae:
        raise HTTPException(
            status_code=400,
            detail=(
                "La factura no tiene CAE: todavia no fue autorizada por AFIP, "
                "asi que no corresponde imprimir el QR fiscal."
            ),
        )

    cfg = _config(db)
    try:
        datos = ws.datos_qr(
            fecha=factura.fecha,
            cuit_emisor=cfg.cuit,
            punto_venta=factura.punto_venta or cfg.punto_venta,
            tipo_comprobante=factura.tipo_comprobante or cfg.tipo_comprobante,
            nro_comprobante=factura.nro_comprobante_afip or 0,
            # El QR lleva el importe en decimales: centavos -> pesos.
            importe_total=a_pesos(abs(factura.total or 0)),
            cae=factura.cae,
            nro_doc_receptor=factura.cliente or "",
        )
        return {
            "factura": factura_num,
            "url": ws.url_qr(datos),
            "svg": ws.qr_svg(datos),
            "datos": datos,
        }
    except ws.AfipError as exc:
        raise _error_afip(exc, status=400)


@router.post("/facturas/{factura_num}/solicitar-cae", response_model=CAEResponse)
def solicitar_cae(
    factura_num: int,
    datos: SolicitudCAE = SolicitudCAE(),
    db: Session = Depends(get_db),
):
    """Pide a AFIP el CAE de una factura YA emitida y guarda el resultado.

    Éxito  -> guarda cae, vencimiento, punto de venta, tipo, resultado 'A'/'P'
              y el número de comprobante que asignó AFIP.
    Rechazo -> guarda resultado 'R' con el motivo y devuelve HTTP 422.
    """
    cfg = _config_operativa(db)

    factura = db.query(Factura).filter(Factura.facturanumero == factura_num).first()
    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    if factura.cae:
        raise ErrorDeNegocio(
            "CAE_YA_EMITIDO",
            f"La factura {factura_num} ya tiene CAE {factura.cae} "
            f"(vence {factura.cae_vencimiento or 's/d'}). Pedir otro CAE para el mismo "
            "comprobante duplicaría la declaración ante AFIP.",
        )

    # Tipo de comprobante: se deriva de las condiciones frente al IVA del emisor
    # (configuración del negocio) y del receptor (ficha del cliente). Elegirlo a
    # mano es la causa mas comun de rechazo de AFIP. Si el pedido trae un tipo
    # explicito, ese manda: el usuario puede necesitar forzarlo.
    tipo_sugerido = _tipo_sugerido(db, factura)
    tipo = datos.tipo_comprobante or tipo_sugerido or cfg.tipo_comprobante
    if tipo not in ws.TIPOS_COMPROBANTE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tipo de comprobante {tipo} no soportado por este sistema. "
                f"Válidos: {', '.join(f'{k}={v}' for k, v in ws.TIPOS_COMPROBANTE.items())}"
            ),
        )
    punto_venta = datos.punto_venta or cfg.punto_venta

    # Receptor: por defecto el CUIT del cliente de la factura (ya validado con
    # dígito verificador al darlo de alta).
    doc_tipo = datos.doc_tipo or 80
    doc_nro_texto = (datos.doc_nro or factura.cliente or "").replace("-", "").strip()
    if doc_tipo == 99:
        doc_nro_texto = "0"
    if not doc_nro_texto.isdigit():
        raise HTTPException(
            status_code=400,
            detail=(
                f"La factura {factura_num} no tiene un CUIT/documento de cliente válido "
                f"({factura.cliente!r}): AFIP lo exige para autorizar el comprobante."
            ),
        )

    importes = _composicion_iva(db, factura, tipo)

    try:
        comprobante = ws.ComprobanteAFIP(
            punto_venta=punto_venta,
            tipo_comprobante=tipo,
            doc_tipo=doc_tipo,
            doc_nro=int(doc_nro_texto),
            fecha=ws.fecha_afip(factura.fecha),
            imp_neto=importes["neto"],
            imp_iva=importes["iva"],
            imp_total=importes["total"],
            alicuotas=importes["alicuotas"],
            concepto=datos.concepto or 1,
        )
        resultado = ws.solicitar_cae(cfg, comprobante)
    except ws.AfipRechazo as exc:
        # AFIP miró el comprobante y NO lo autorizó: queda registrado para que
        # nunca parezca autorizado, y se devuelve como error (nunca como éxito).
        factura.resultado = "R"
        factura.punto_venta = punto_venta
        factura.tipo_comprobante = tipo
        factura.afip_observaciones = exc.mensaje[:2000]
        db.commit()
        raise HTTPException(status_code=422, detail=exc.mensaje)
    except ws.AfipError as exc:
        # Problema de red, de certificado o de autenticación: AFIP no llegó a
        # evaluar el comprobante, así que NO se toca su estado fiscal.
        raise _error_afip(exc, status=502)

    factura.cae = resultado["cae"]
    factura.cae_vencimiento = ws.fecha_desde_afip(resultado["cae_vencimiento"])
    factura.punto_venta = resultado["punto_venta"]
    factura.tipo_comprobante = resultado["tipo_comprobante"]
    factura.resultado = resultado["resultado"]
    factura.nro_comprobante_afip = resultado["numero_comprobante"]
    factura.afip_observaciones = resultado["observaciones"] or None
    db.commit()

    aviso = ""
    if cfg.entorno == "homologacion":
        aviso = ("ATENCIÓN: entorno de HOMOLOGACIÓN (pruebas). Este CAE no tiene "
                 "validez fiscal. ")
    return CAEResponse(
        facturanumero=factura.facturanumero,
        resultado=resultado["resultado"],
        cae=resultado["cae"],
        cae_vencimiento=factura.cae_vencimiento,
        punto_venta=resultado["punto_venta"],
        tipo_comprobante=resultado["tipo_comprobante"],
        nro_comprobante_afip=resultado["numero_comprobante"],
        entorno=cfg.entorno,
        observaciones=resultado["observaciones"],
        mensaje=(
            f"{aviso}CAE {resultado['cae']} otorgado para "
            f"{ws.TIPOS_COMPROBANTE.get(resultado['tipo_comprobante'], 'comprobante')} "
            f"{resultado['punto_venta']:04d}-{resultado['numero_comprobante']:08d}."
        ),
    )
