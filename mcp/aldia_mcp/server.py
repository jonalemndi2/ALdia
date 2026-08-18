"""
server.py - Servidor MCP de ALdia.

Expone la gestion comercial de ALdia (stock, clientes, proveedores, remitos,
facturas, cobros, pagos, caja, gastos, libro IVA) como herramientas MCP.

Convenciones que valen para TODAS las herramientas:

  * Fechas: siempre en formato YYYY-MM-DD (ej. 2026-08-17). Si se omite, se usa
    la fecha de hoy del equipo donde corre este servidor.
  * CUIT: 11 digitos. Se acepta con o sin guiones; ALdia valida el digito
    verificador y rechaza los CUIT mal formados.
  * Importes: pesos argentinos, numeros decimales, SIEMPRE en positivo.
  * Alicuotas de IVA validas en ALdia: 0, 2.5, 5, 10.5, 21 y 27.
  * Codigo de producto: numero entero, es la clave del articulo en el stock.

Las herramientas que crean comprobantes o mueven dinero estan marcadas en su
descripcion con [OPERACION DE DINERO]; las de borrado, con [DESTRUCTIVA] y
exigen el parametro confirmar=true, que el asistente solo debe usar despues de
que el usuario lo autorice explicitamente.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from aldia_mcp.client import ALdiaClient, ALdiaError

servidor = MCPServer(
    name="aldia",
    instructions=(
        "Herramientas para operar ALdia, un sistema de gestion comercial argentino "
        "(kiosco, almacen, supermercado, agro). Permite consultar stock, clientes, "
        "proveedores, saldos, caja y libro IVA, y registrar ventas, facturas, cobros, "
        "pagos, gastos y movimientos de caja.\n\n"
        "Reglas de uso:\n"
        "- Fechas en formato YYYY-MM-DD; si el usuario dice 'hoy', omita la fecha.\n"
        "- Antes de registrar un cobro, un pago o una factura, identifique al cliente o "
        "proveedor con las herramientas de busqueda: no invente CUIT.\n"
        "- Toda herramienta marcada [OPERACION DE DINERO] deja asientos contables reales. "
        "Confirme importe, fecha y contraparte con el usuario antes de ejecutarla.\n"
        "- Toda herramienta marcada [DESTRUCTIVA] borra comprobantes. Pida autorizacion "
        "explicita del usuario y recien entonces pase confirmar=true.\n"
        "- Si una herramienta devuelve un error, leale el mensaje al usuario: viene del "
        "sistema (permisos de rol, validacion de CUIT, stock insuficiente) y suele decir "
        "exactamente que corregir."
    ),
)

_cliente_api: ALdiaClient | None = None

SOLO_LECTURA = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
ESCRITURA = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
DESTRUCTIVA = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)

ALICUOTAS_IVA = (0.0, 2.5, 5.0, 10.5, 21.0, 27.0)


def api() -> ALdiaClient:
    """Cliente HTTP compartido (login perezoso, token renovado solo)."""
    global _cliente_api
    if _cliente_api is None:
        _cliente_api = ALdiaClient()
    return _cliente_api


# ─────────────────────────────────────────────────────────────
# Utilidades internas
# ─────────────────────────────────────────────────────────────

_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _fecha(valor: str | None) -> str:
    """Normaliza una fecha YYYY-MM-DD; si viene vacia, devuelve la de hoy."""
    if valor in (None, ""):
        return date.today().isoformat()
    valor = str(valor).strip()
    if not _RE_FECHA.match(valor):
        raise ALdiaError(
            f"Fecha invalida: '{valor}'. Use el formato YYYY-MM-DD (ejemplo: "
            f"{date.today().isoformat()})."
        )
    return valor


def _redondear(valor: float) -> float:
    return round(float(valor or 0.0) + 0.0, 2)


def _validar_iva(valor: float) -> float:
    if float(valor) not in ALICUOTAS_IVA:
        validas = ", ".join(f"{a:g}%" for a in ALICUOTAS_IVA)
        raise ALdiaError(f"Alicuota de IVA invalida ({valor}). Validas en ALdia: {validas}.")
    return float(valor)


def _exigir_confirmacion(confirmar: bool, que: str) -> None:
    if not confirmar:
        raise ALdiaError(
            f"Operacion NO ejecutada. {que} es una accion destructiva: pida al usuario que "
            "la autorice explicitamente y recien entonces vuelva a llamar con confirmar=true."
        )


def _resumen_producto(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "codigo": p.get("codigo"),
        "producto": p.get("producto"),
        "stock": p.get("cantidad"),
        "unidad": p.get("unidad"),
        "precio_venta": p.get("preven"),
        "precio_compra": p.get("precom"),
        "iva_pct": p.get("iva"),
    }


# ═════════════════════════════════════════════════════════════
# 1. CONSULTA
# ═════════════════════════════════════════════════════════════


@servidor.tool(
    title="Verificar conexion con ALdia",
    annotations=SOLO_LECTURA,
    description=(
        "Comprueba que el servidor de ALdia responda y que las credenciales configuradas "
        "sean validas. Devuelve el usuario con el que opera el asistente, su rol y la lista "
        "de modulos a los que ese rol tiene acceso (stock, ventas, caja, etc.).\n\n"
        "Uselo al empezar una sesion, o cuando otra herramienta falle con un error de "
        "permisos, para saber que puede y que no puede hacer este usuario."
    ),
)
def verificar_conexion() -> dict[str, Any]:
    cli = api()
    usuario = cli.usuario_actual
    try:
        modulos = cli.get("/api/modulos/activos") or []
        claves = [m.get("clave") for m in modulos]
    except ALdiaError:
        claves = []
    return {
        "servidor": cli.base_url,
        "conectado": True,
        "usuario": usuario.get("username"),
        "rol": usuario.get("rol"),
        "modulos_accesibles": claves,
        "fecha_de_hoy": date.today().isoformat(),
    }


@servidor.tool(
    title="Buscar producto y ver stock",
    annotations=SOLO_LECTURA,
    description=(
        "Busca articulos en el stock y devuelve, para cada uno: codigo, descripcion, "
        "cantidad disponible, unidad, precio de venta, precio de compra y alicuota de IVA.\n\n"
        "Parametros:\n"
        "- texto: parte del nombre del producto (ej. 'coca', 'harina'). Opcional.\n"
        "- codigo: codigo exacto del articulo (numero entero). Opcional.\n"
        "- solo_faltantes: si es true, devuelve unicamente los articulos cuyo stock esta "
        "por debajo de 'minimo'. Util para armar la lista de reposicion.\n"
        "- minimo: umbral de stock para solo_faltantes (por defecto 0, es decir, articulos "
        "agotados o en negativo).\n\n"
        "Sin ningun parametro devuelve el listado completo de articulos."
    ),
)
def buscar_producto(
    texto: str | None = None,
    codigo: int | None = None,
    solo_faltantes: bool = False,
    minimo: float = 0.0,
) -> dict[str, Any]:
    cli = api()
    if codigo is not None:
        items = [cli.producto(int(codigo))]
    else:
        items = cli.get("/api/stock/", search=texto) or []

    if solo_faltantes:
        items = [i for i in items if float(i.get("cantidad") or 0) <= float(minimo)]

    items = sorted(items, key=lambda i: float(i.get("cantidad") or 0))
    return {
        "cantidad_de_articulos": len(items),
        "criterio": {"texto": texto, "codigo": codigo, "solo_faltantes": solo_faltantes, "minimo": minimo},
        "articulos": [_resumen_producto(i) for i in items],
    }


@servidor.tool(
    title="Buscar cliente",
    annotations=SOLO_LECTURA,
    description=(
        "Busca clientes por nombre o por CUIT (con o sin guiones) y devuelve su ficha: "
        "CUIT, nombre, domicilio, localidad, telefono, mail y saldo de cuenta corriente.\n\n"
        "El saldo es lo que el cliente DEBE: positivo = deuda pendiente, 0 = al dia.\n"
        "Sin parametros devuelve todos los clientes."
    ),
)
def buscar_cliente(texto: str | None = None) -> dict[str, Any]:
    clientes = api().get("/api/clientes/", search=texto) or []
    return {
        "cantidad": len(clientes),
        "clientes": [
            {
                "cuit": c.get("cuit"),
                "nombre": c.get("nombre"),
                "telefono": c.get("telefono"),
                "mail": c.get("mail"),
                "localidad": c.get("localidad"),
                "saldo_debe": c.get("saldo"),
            }
            for c in clientes
        ],
    }


@servidor.tool(
    title="Buscar proveedor",
    annotations=SOLO_LECTURA,
    description=(
        "Busca proveedores por nombre o por CUIT (con o sin guiones) y devuelve su ficha "
        "y el saldo de la cuenta corriente.\n\n"
        "El saldo es lo que el negocio LE DEBE al proveedor: positivo = deuda propia "
        "pendiente de pago.\n"
        "Sin parametros devuelve todos los proveedores."
    ),
)
def buscar_proveedor(texto: str | None = None) -> dict[str, Any]:
    provs = api().get("/api/proveedores/", search=texto) or []
    return {
        "cantidad": len(provs),
        "proveedores": [
            {
                "cuit": p.get("cuit"),
                "nombre": p.get("nombre"),
                "telefono": p.get("telefono"),
                "mail": p.get("mail"),
                "localidad": p.get("localidad"),
                "saldo_a_pagar": p.get("saldo"),
            }
            for p in provs
        ],
    }


@servidor.tool(
    title="Ver saldo y cuenta corriente de un cliente",
    annotations=SOLO_LECTURA,
    description=(
        "Devuelve el saldo actual de un cliente (lo que debe) junto con su historial "
        "reciente: facturas emitidas y cobros recibidos.\n\n"
        "Parametros:\n"
        "- cliente: CUIT (con o sin guiones) o nombre del cliente. Si el texto coincide con "
        "varios clientes, la herramienta devuelve un error listandolos para que elija.\n"
        "- limite: cuantos comprobantes recientes traer de cada tipo (por defecto 10)."
    ),
)
def ver_saldo_cliente(cliente: str, limite: int = 10) -> dict[str, Any]:
    cli = api()
    ficha = cli.resolver_cliente(cliente)
    cuit = ficha.get("cuit")

    facturas = cli.get("/api/facturas/", cliente=cuit) or []
    cobros = cli.get("/api/cobros/", cliente=cuit) or []

    return {
        "cuit": cuit,
        "nombre": ficha.get("nombre"),
        "telefono": ficha.get("telefono"),
        "saldo_debe": ficha.get("saldo"),
        "estado": "AL DIA" if float(ficha.get("saldo") or 0) <= 0 else "CON DEUDA",
        "facturas_recientes": [
            {
                "numero": f.get("facturanumero"),
                "fecha": f.get("fecha"),
                "total": f.get("total"),
            }
            for f in facturas[: int(limite)]
        ],
        "cobros_recientes": [
            {
                "orden": c.get("ordcobro"),
                "fecha": c.get("fecha"),
                "monto": c.get("monto"),
                "tipo": c.get("tipo"),
                "referencia": c.get("referencia"),
            }
            for c in cobros[: int(limite)]
        ],
    }


@servidor.tool(
    title="Ver deudores (clientes con saldo pendiente)",
    annotations=SOLO_LECTURA,
    description=(
        "Lista todos los clientes con saldo pendiente, ordenados de mayor a menor deuda, "
        "con CUIT, nombre, telefono y monto adeudado. Es la base para una gestion de "
        "cobranzas.\n\n"
        "Parametros:\n"
        "- monto_minimo: ignora deudas menores a este importe (por defecto 0, trae todas).\n"
        "- con_antiguedad: si es true, agrega para cada deudor la fecha de su ultima factura "
        "y la de su ultimo cobro, para estimar hace cuanto no paga. Es mas lento porque "
        "consulta el historial de cada cliente."
    ),
)
def ver_deudores(monto_minimo: float = 0.0, con_antiguedad: bool = False) -> dict[str, Any]:
    cli = api()
    morosos = cli.get("/api/admin/morosos") or []
    morosos = [m for m in morosos if float(m.get("saldo") or 0) >= float(monto_minimo)]

    hoy = date.today()
    for m in morosos if con_antiguedad else []:
        cuit = m.get("cuit")
        facturas = cli.get("/api/facturas/", cliente=cuit) or []
        cobros = cli.get("/api/cobros/", cliente=cuit) or []
        ult_fac = max((f.get("fecha") or "" for f in facturas), default="")
        ult_cob = max((c.get("fecha") or "" for c in cobros), default="")
        m["ultima_factura"] = ult_fac or None
        m["ultimo_cobro"] = ult_cob or None
        try:
            if ult_cob:
                m["dias_desde_ultimo_cobro"] = (hoy - date.fromisoformat(ult_cob)).days
            elif ult_fac:
                m["dias_desde_ultima_factura"] = (hoy - date.fromisoformat(ult_fac)).days
        except ValueError:
            pass

    return {
        "cantidad_de_deudores": len(morosos),
        "total_adeudado": _redondear(sum(float(m.get("saldo") or 0) for m in morosos)),
        "deudores": morosos,
    }


@servidor.tool(
    title="Ver saldo de caja",
    annotations=SOLO_LECTURA,
    description=(
        "Devuelve el saldo acumulado de la caja: la suma de todos los ingresos (debe) "
        "menos todos los egresos (haber) desde que se usa el sistema. No es el saldo del "
        "dia: para eso use la herramienta de movimientos del dia."
    ),
)
def ver_saldo_caja() -> dict[str, Any]:
    datos = api().get("/api/caja/saldo") or {}
    return {"saldo_acumulado": datos.get("saldo"), "moneda": "ARS"}


@servidor.tool(
    title="Ver movimientos del dia (cierre de caja)",
    annotations=SOLO_LECTURA,
    description=(
        "Trae TODO lo que se movio en una fecha: movimientos de caja (ingresos y egresos), "
        "cobros de clientes, pagos a proveedores, gastos cargados y facturas emitidas; y "
        "calcula los totales del dia y el resultado neto de caja.\n\n"
        "Es la herramienta base del cierre de caja diario. Tenga en cuenta como registra "
        "ALdia el dinero:\n"
        "- un cobro EN EFECTIVO genera automaticamente un ingreso de caja 'COBRO n';\n"
        "- un cobro CON CHEQUE no entra a caja: va a la chequera hasta que se deposita;\n"
        "- un pago en efectivo genera un egreso 'PAGO n' y un gasto un egreso 'GASTO n'.\n"
        "Por eso el neto de caja del dia puede no coincidir con la suma de cobros menos "
        "pagos: la diferencia suele ser cheques.\n\n"
        "Parametro fecha: YYYY-MM-DD; si se omite, el dia de hoy."
    ),
)
def ver_movimientos_del_dia(fecha: str | None = None) -> dict[str, Any]:
    cli = api()
    dia = _fecha(fecha)

    caja = cli.get("/api/caja/", fecha=dia) or []
    cobros = cli.get("/api/cobros/", fecha=dia) or []
    pagos = cli.get("/api/pagos/", fecha=dia) or []
    gastos = cli.get("/api/gastos/", fecha=dia) or []
    facturas = cli.get("/api/facturas/", fecha=dia) or []

    ingresos = _redondear(sum(float(m.get("debe") or 0) for m in caja))
    egresos = _redondear(sum(float(m.get("haber") or 0) for m in caja))

    cobros_efectivo = [c for c in cobros if "cheque" not in (c.get("tipo") or "").lower()]
    cobros_cheque = [c for c in cobros if "cheque" in (c.get("tipo") or "").lower()]

    return {
        "fecha": dia,
        "totales": {
            "ingresos_caja": ingresos,
            "egresos_caja": egresos,
            "neto_caja_del_dia": _redondear(ingresos - egresos),
            "cobros_total": _redondear(sum(float(c.get("monto") or 0) for c in cobros)),
            "cobros_en_efectivo_u_otros": _redondear(
                sum(float(c.get("monto") or 0) for c in cobros_efectivo)
            ),
            "cobros_con_cheque_no_entran_a_caja": _redondear(
                sum(float(c.get("monto") or 0) for c in cobros_cheque)
            ),
            "pagos_total": _redondear(sum(float(p.get("monto") or 0) for p in pagos)),
            "gastos_total": _redondear(sum(float(g.get("total") or 0) for g in gastos)),
            "facturado_total": _redondear(sum(float(f.get("total") or 0) for f in facturas)),
        },
        "movimientos_de_caja": caja,
        "cobros": cobros,
        "pagos": pagos,
        "gastos": gastos,
        "facturas": facturas,
        "saldo_acumulado_de_caja": (cli.get("/api/caja/saldo") or {}).get("saldo"),
    }


@servidor.tool(
    title="Ver chequera",
    annotations=SOLO_LECTURA,
    description=(
        "Lista los cheques registrados: los recibidos de clientes (tipo 1, a depositar) y "
        "los propios emitidos a proveedores (tipo 0). Incluye numero, banco, monto, "
        "vencimiento, titular y si ya fueron utilizados o endosados.\n\n"
        "Parametro solo_pendientes: si es true, deja solo los cheques que todavia no se "
        "usaron ni depositaron."
    ),
)
def ver_chequera(solo_pendientes: bool = False) -> dict[str, Any]:
    cheques = api().get("/api/caja/chequera") or []
    if solo_pendientes:
        cheques = [c for c in cheques if not (c.get("pagado") or "").strip()]
    recibidos = [c for c in cheques if int(c.get("tipo") or 0) == 1]
    emitidos = [c for c in cheques if int(c.get("tipo") or 0) == 0]
    return {
        "cantidad": len(cheques),
        "total_recibidos_a_cobrar": _redondear(sum(float(c.get("monto") or 0) for c in recibidos)),
        "total_emitidos": _redondear(sum(float(c.get("monto") or 0) for c in emitidos)),
        "cheques_recibidos_de_clientes": recibidos,
        "cheques_propios_emitidos": emitidos,
    }


@servidor.tool(
    title="Consultar libro IVA de un periodo",
    annotations=SOLO_LECTURA,
    description=(
        "Calcula el IVA de un periodo: IVA debito fiscal (percibido en las facturas "
        "emitidas), IVA credito fiscal (pagado en compras a proveedores y en gastos) y el "
        "saldo a pagar o a favor.\n\n"
        "Parametros:\n"
        "- fecha_desde / fecha_hasta: YYYY-MM-DD. Si se omiten, toma toda la historia.\n"
        "- mes: alternativa comoda, en formato YYYY-MM (ej. 2026-08); calcula el periodo "
        "completo de ese mes e ignora fecha_desde/fecha_hasta.\n\n"
        "Un 'iva_a_pagar' positivo significa que el negocio debe ingresar esa diferencia; "
        "negativo, que le queda saldo tecnico a favor."
    ),
)
def consultar_libro_iva(
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    mes: str | None = None,
) -> dict[str, Any]:
    if mes:
        if not re.match(r"^\d{4}-\d{2}$", str(mes).strip()):
            raise ALdiaError(f"Mes invalido: '{mes}'. Use el formato YYYY-MM (ej. 2026-08).")
        anio, m = (int(x) for x in str(mes).split("-"))
        if not 1 <= m <= 12:
            raise ALdiaError(f"Mes invalido: '{mes}'. El numero de mes va de 01 a 12.")
        primero = date(anio, m, 1)
        siguiente = date(anio + 1, 1, 1) if m == 12 else date(anio, m + 1, 1)
        ultimo = date.fromordinal(siguiente.toordinal() - 1)
        fecha_desde = primero.isoformat()
        fecha_hasta = ultimo.isoformat()

    datos = api().get(
        "/api/iva/consulta",
        fecha_desde=_fecha(fecha_desde) if fecha_desde else None,
        fecha_hasta=_fecha(fecha_hasta) if fecha_hasta else None,
    )
    return datos


@servidor.tool(
    title="Resumen del negocio",
    annotations=SOLO_LECTURA,
    description=(
        "Panorama general del negocio en un rango de fechas: total facturado, cantidad de "
        "facturas, compras, gastos, cobros, pagos y remitos; mas el estado actual "
        "(saldo de caja, cantidad de articulos, clientes y proveedores).\n\n"
        "Parametros fecha_desde / fecha_hasta en YYYY-MM-DD. Si se omiten, el resumen del "
        "rango abarca toda la historia cargada."
    ),
)
def resumen_negocio(fecha_desde: str | None = None, fecha_hasta: str | None = None) -> dict[str, Any]:
    cli = api()
    resumen = cli.get(
        "/api/admin/resumen",
        fecha_desde=_fecha(fecha_desde) if fecha_desde else None,
        fecha_hasta=_fecha(fecha_hasta) if fecha_hasta else None,
    ) or {}
    tablero = cli.get("/api/admin/dashboard") or {}
    return {
        "periodo": {"desde": resumen.get("fecha_desde"), "hasta": resumen.get("fecha_hasta")},
        "ventas_facturadas": resumen.get("ventas"),
        "cantidad_facturas": resumen.get("factCount"),
        "compras_a_proveedores": resumen.get("compras"),
        "gastos": resumen.get("gastos"),
        "cobros_recibidos": resumen.get("cobros"),
        "pagos_realizados": resumen.get("pagos"),
        "remitos_emitidos": resumen.get("remitos"),
        "estado_actual": {
            "saldo_caja": tablero.get("caja_saldo"),
            "articulos_en_stock": tablero.get("stock_count"),
            "clientes": tablero.get("cliente_count"),
            "proveedores": tablero.get("proveedor_count"),
        },
    }


@servidor.tool(
    title="Ver remitos sin facturar",
    annotations=SOLO_LECTURA,
    description=(
        "Lista las lineas de mercaderia ya entregadas (remitos) que todavia no fueron "
        "facturadas, con su id de linea, numero de remito, cliente, producto, cantidad y "
        "precio.\n\n"
        "El campo 'id' de cada linea es el que se pasa en lineas_remito_ids al emitir la "
        "factura correspondiente."
    ),
)
def ver_remitos_sin_facturar(cliente: str | None = None) -> dict[str, Any]:
    cli = api()
    lineas = cli.get("/api/remitos/nofacturados") or []
    if cliente:
        cuit = cli.resolver_cliente(cliente).get("cuit")
        lineas = [l for l in lineas if l.get("cliente") == cuit]
    total = _redondear(
        sum(float(l.get("cantidad") or 0) * float(l.get("precio") or 0) for l in lineas)
    )
    return {"cantidad_de_lineas": len(lineas), "total_sin_facturar": total, "lineas": lineas}


@servidor.tool(
    title="Ver registro de auditoria (quien hizo que y cuando)",
    annotations=SOLO_LECTURA,
    description=(
        "Consulta el registro de auditoria de ALdia: quien hizo cada movimiento, cuando, "
        "desde que direccion IP, y con que resultado. Es la herramienta para responder "
        "preguntas del tipo 'quien anulo la factura 32', 'quien cambio el precio del "
        "articulo 5', 'que toco Juan ayer' o 'hubo intentos rechazados esta semana'.\n\n"
        "El registro guarda TODA escritura contra el sistema (altas, modificaciones, "
        "anulaciones, cobros, pagos, cambios de precio, altas y bajas de usuario, cambios "
        "de rol) y tambien los INTENTOS RECHAZADOS por falta de permisos, que suelen ser "
        "lo mas revelador. Las consultas (lecturas) no se registran.\n\n"
        "Cada fila trae:\n"
        "- fecha_hora (con segundos), usuario, y rol que tenia AL MOMENTO de la accion;\n"
        "- modulo y accion, tipo y numero del registro afectado;\n"
        "- descripcion legible, y valor_anterior / valor_nuevo con el antes y el despues "
        "de los campos sensibles (precios, saldos, roles, comprobantes anulados);\n"
        "- ip de origen y resultado ('exito' o 'rechazado', con el codigo HTTP).\n\n"
        "Parametros de filtro (todos opcionales; se combinan entre si):\n"
        "- fecha_desde / fecha_hasta: YYYY-MM-DD, ambas inclusive.\n"
        "- usuario: nombre de usuario exacto (ej. 'caja1').\n"
        "- modulo: 'stock', 'ventas', 'caja', 'clientes', 'proveedores', "
        "'cuentas_corrientes', 'gastos', 'iva', 'administracion', 'autenticacion'.\n"
        "- accion: 'alta', 'modificacion', 'baja', 'login', 'emision de factura', "
        "'anulacion de factura', 'registro de cobro', 'alta de usuario', etc.\n"
        "- resultado: 'exito' o 'rechazado'.\n"
        "- texto: busqueda libre en la descripcion, el numero de registro y la ruta. "
        "Para 'quien anulo la factura 32' conviene texto='32' junto con "
        "accion='anulacion de factura'.\n"
        "- limite: cuantas filas devolver (por defecto 50, maximo 500), ordenadas de la "
        "mas reciente a la mas antigua.\n\n"
        "SOLO CONSULTA: el registro es inmutable. No existe ninguna herramienta ni "
        "endpoint que lo borre o lo edite, ni siquiera para el administrador; si el "
        "usuario pide 'limpiar el log', explique que es a proposito y que no se puede.\n\n"
        "Requiere un usuario con rol 'administrador' o 'auditor'. Con cualquier otro rol "
        "la llamada devuelve un error de permisos."
    ),
)
def ver_auditoria(
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    usuario: str | None = None,
    modulo: str | None = None,
    accion: str | None = None,
    resultado: str | None = None,
    texto: str | None = None,
    limite: int = 50,
) -> dict[str, Any]:
    limite = max(1, min(int(limite or 50), 500))
    if resultado and str(resultado).lower() not in ("exito", "rechazado"):
        raise ALdiaError(
            f"resultado invalido ('{resultado}'). Valores validos: 'exito' o 'rechazado'."
        )

    datos = api().get(
        "/api/auditoria/",
        desde=_fecha(fecha_desde) if fecha_desde else None,
        hasta=_fecha(fecha_hasta) if fecha_hasta else None,
        usuario=usuario,
        modulo=modulo,
        accion=accion,
        resultado=(resultado or "").lower() or None,
        texto=texto,
        pagina=1,
        por_pagina=limite,
    ) or {}

    filas = datos.get("filas") or []
    rechazados = sum(1 for f in filas if f.get("resultado") == "rechazado")
    return {
        "total_que_coincide_con_el_filtro": datos.get("total", 0),
        "movimientos_devueltos": len(filas),
        "intentos_rechazados_en_lo_devuelto": rechazados,
        "orden": "de la mas reciente a la mas antigua",
        "nota": (
            "Registro inmutable y de solo consulta: no hay forma de borrarlo ni editarlo "
            "desde el sistema. Solo se registran escrituras; las lecturas no dejan rastro."
        ),
        "movimientos": filas,
    }


# ═════════════════════════════════════════════════════════════
# 2. OPERACION
# ═════════════════════════════════════════════════════════════


@servidor.tool(
    title="Alta de producto",
    annotations=ESCRITURA,
    description=(
        "Da de alta un articulo nuevo en el stock.\n\n"
        "Parametros:\n"
        "- codigo: numero entero unico. Si ya existe, la operacion falla.\n"
        "- producto: descripcion del articulo (obligatoria).\n"
        "- cantidad: stock inicial (no puede ser negativo). Por defecto 0.\n"
        "- unidad: unidad de medida ('UN', 'Kg', 'Lt', 'Caja'...). Por defecto 'UN'.\n"
        "- precio_venta / precio_compra: importes en pesos, no negativos.\n"
        "- iva: alicuota en porcentaje. Validas: 0, 2.5, 5, 10.5, 21, 27. Por defecto 21.\n\n"
        "Para modificar un articulo existente use la herramienta de actualizacion de precio."
    ),
)
def alta_producto(
    codigo: int,
    producto: str,
    cantidad: float = 0.0,
    unidad: str = "UN",
    precio_venta: float = 0.0,
    precio_compra: float = 0.0,
    iva: float = 21.0,
) -> dict[str, Any]:
    _validar_iva(iva)
    creado = api().post(
        "/api/stock/",
        {
            "codigo": int(codigo),
            "producto": producto,
            "cantidad": float(cantidad),
            "unidad": unidad or "UN",
            "preven": float(precio_venta),
            "iva": float(iva),
            "precom": float(precio_compra),
        },
    )
    return {"creado": True, "articulo": _resumen_producto(creado)}


@servidor.tool(
    title="Actualizar precio o datos de un producto",
    annotations=ESCRITURA,
    description=(
        "Modifica un articulo ya existente: precio de venta, precio de compra, descripcion, "
        "unidad, alicuota de IVA o cantidad en stock. Solo se cambian los campos que se "
        "envian; el resto queda como estaba.\n\n"
        "Para una remarcacion por lista use aumento_pct: por ejemplo aumento_pct=12 sube el "
        "precio de venta un 12% sobre el precio actual (redondeado a 2 decimales). No se "
        "puede combinar aumento_pct con precio_venta en la misma llamada.\n\n"
        "Ojo: 'cantidad' PISA el stock, no lo suma. Para ingresar mercaderia comprada use "
        "la herramienta de registro de compra a proveedor, que ademas deja el comprobante y "
        "la deuda con el proveedor."
    ),
)
def actualizar_producto(
    codigo: int,
    precio_venta: float | None = None,
    aumento_pct: float | None = None,
    precio_compra: float | None = None,
    producto: str | None = None,
    unidad: str | None = None,
    iva: float | None = None,
    cantidad: float | None = None,
) -> dict[str, Any]:
    cli = api()
    if precio_venta is not None and aumento_pct is not None:
        raise ALdiaError("Indique precio_venta o aumento_pct, no ambos.")

    actual = cli.producto(int(codigo))
    cambios: dict[str, Any] = {}

    if aumento_pct is not None:
        base = float(actual.get("preven") or 0.0)
        if base <= 0:
            raise ALdiaError(
                f"El articulo {codigo} ('{actual.get('producto')}') no tiene precio de venta "
                "cargado: no se le puede aplicar un aumento porcentual. Fije precio_venta."
            )
        cambios["preven"] = _redondear(base * (1 + float(aumento_pct) / 100.0))
    if precio_venta is not None:
        cambios["preven"] = float(precio_venta)
    if precio_compra is not None:
        cambios["precom"] = float(precio_compra)
    if producto is not None:
        cambios["producto"] = producto
    if unidad is not None:
        cambios["unidad"] = unidad
    if iva is not None:
        cambios["iva"] = _validar_iva(iva)
    if cantidad is not None:
        cambios["cantidad"] = float(cantidad)

    if not cambios:
        raise ALdiaError("No se indico ningun cambio para el articulo.")

    nuevo = cli.put(f"/api/stock/{int(codigo)}", cambios)
    return {
        "actualizado": True,
        "antes": _resumen_producto(actual),
        "ahora": _resumen_producto(nuevo),
    }


@servidor.tool(
    title="Alta de cliente",
    annotations=ESCRITURA,
    description=(
        "Crea la ficha de un cliente nuevo.\n\n"
        "Parametros:\n"
        "- cuit: 11 digitos, con o sin guiones. ALdia valida el digito verificador y "
        "rechaza los CUIT inventados o mal tipeados.\n"
        "- nombre: razon social o nombre del cliente (obligatorio).\n"
        "- domicilio, localidad, provincia, cp, telefono, mail: opcionales.\n\n"
        "Si el CUIT ya existe, la operacion falla: busque primero al cliente."
    ),
)
def alta_cliente(
    cuit: str,
    nombre: str,
    domicilio: str = "",
    localidad: str = "",
    provincia: str = "",
    cp: str = "",
    telefono: str = "",
    mail: str = "",
) -> dict[str, Any]:
    creado = api().post(
        "/api/clientes/",
        {
            "cuit": cuit,
            "nombre": nombre,
            "domicilio": domicilio,
            "localidad": localidad,
            "provincia": provincia,
            "cp": cp,
            "telefono": telefono,
            "mail": mail,
        },
    )
    return {"creado": True, "cliente": creado}


@servidor.tool(
    title="Alta de proveedor",
    annotations=ESCRITURA,
    description=(
        "Crea la ficha de un proveedor nuevo. Mismas reglas que el alta de cliente: el CUIT "
        "debe tener 11 digitos y digito verificador valido, y el nombre es obligatorio."
    ),
)
def alta_proveedor(
    cuit: str,
    nombre: str,
    domicilio: str = "",
    localidad: str = "",
    provincia: str = "",
    cp: str = "",
    telefono: str = "",
    mail: str = "",
) -> dict[str, Any]:
    creado = api().post(
        "/api/proveedores/",
        {
            "cuit": cuit,
            "nombre": nombre,
            "domicilio": domicilio,
            "localidad": localidad,
            "provincia": provincia,
            "cp": cp,
            "telefono": telefono,
            "mail": mail,
        },
    )
    return {"creado": True, "proveedor": creado}


@servidor.tool(
    title="Registrar venta / remito (entrega de mercaderia)",
    annotations=ESCRITURA,
    description=(
        "[OPERACION DE DINERO] Registra una venta con entrega de mercaderia (remito): crea "
        "el comprobante, guarda las lineas y DESCUENTA el stock de cada articulo.\n\n"
        "El remito NO genera factura ni deuda en la cuenta corriente: queda pendiente de "
        "facturar y se puede facturar despues con la herramienta de emision de factura, "
        "pasando los ids de linea que devuelve 'ver remitos sin facturar'.\n\n"
        "Parametros:\n"
        "- cliente: CUIT o nombre del cliente (debe existir).\n"
        "- items: lista de articulos, cada uno {codigo, cantidad} y, opcionalmente, "
        "{precio}. Si no se indica precio, se usa el precio de venta del articulo.\n"
        "- fecha: YYYY-MM-DD; si se omite, hoy.\n"
        "- observaciones: texto libre opcional.\n"
        "- permitir_stock_negativo: por defecto false; si algun articulo no alcanza, la "
        "operacion se rechaza informando cuanto hay. Poner true solo si el usuario acepta "
        "explicitamente dejar el stock en negativo."
    ),
)
def registrar_remito(
    cliente: str,
    items: list[dict[str, Any]],
    fecha: str | None = None,
    observaciones: str = "",
    permitir_stock_negativo: bool = False,
) -> dict[str, Any]:
    cli = api()
    if not items:
        raise ALdiaError("El remito no tiene items: indique al menos un articulo.")

    ficha = cli.resolver_cliente(cliente)
    dia = _fecha(fecha)

    lineas: list[dict[str, Any]] = []
    avisos: list[str] = []
    for it in items:
        if "codigo" not in it:
            raise ALdiaError(f"Falta 'codigo' en el item {it}.")
        art = cli.producto(int(it["codigo"]))
        cantidad = float(it.get("cantidad") or 0)
        if cantidad <= 0:
            raise ALdiaError(f"La cantidad del articulo {art.get('codigo')} debe ser mayor a 0.")
        disponible = float(art.get("cantidad") or 0)
        if cantidad > disponible and not permitir_stock_negativo:
            raise ALdiaError(
                f"Stock insuficiente de '{art.get('producto')}' (codigo {art.get('codigo')}): "
                f"se quieren entregar {cantidad} {art.get('unidad')} y hay {disponible}. "
                "Reponga el articulo, baje la cantidad, o repita con "
                "permitir_stock_negativo=true si el usuario acepta dejar stock negativo."
            )
        if cantidad > disponible:
            avisos.append(
                f"'{art.get('producto')}' queda con stock negativo: {disponible} - {cantidad}"
            )
        precio = float(it["precio"]) if it.get("precio") is not None else float(art.get("preven") or 0)
        lineas.append(
            {
                "codigo": int(art["codigo"]),
                "producto": art.get("producto") or "",
                "cantidad": cantidad,
                "precio": precio,
                "unidad": art.get("unidad") or "UN",
                "iva": float(art.get("iva") or 21.0),
            }
        )

    cuerpo = {
        "cliente_cuit": ficha.get("cuit"),
        "fecha": dia,
        "observaciones": observaciones,
        "items": lineas,
    }
    remito = cli.post("/api/remitos/", cuerpo)

    subtotal = _redondear(sum(l["cantidad"] * l["precio"] for l in lineas))
    return {
        "registrado": True,
        "remito_numero": remito.get("id"),
        "cliente": ficha.get("nombre"),
        "cuit": ficha.get("cuit"),
        "fecha": dia,
        "subtotal_neto_sin_iva": subtotal,
        "iva_estimado": remito.get("iva"),
        "total_con_iva_estimado": _redondear(subtotal + float(remito.get("iva") or 0)),
        "items": lineas,
        "avisos": avisos,
        "nota": "El remito solo entrega mercaderia: NO genera deuda en la cuenta corriente ni "
                "movimiento de caja, y queda PENDIENTE DE FACTURAR. Para facturarlo use "
                "'ver remitos sin facturar' y luego la emision de factura con los ids de linea.",
    }


@servidor.tool(
    title="Emitir factura",
    annotations=ESCRITURA,
    description=(
        "[OPERACION DE DINERO] Emite una factura de venta. Suma el total a la cuenta "
        "corriente del cliente (le genera deuda) y, si la factura incluye articulos sin "
        "remito previo, descuenta el stock de esos articulos.\n\n"
        "Dos formas de armarla (se pueden combinar):\n"
        "1. lineas_remito_ids: lista de ids de lineas de remito ya entregadas y sin "
        "facturar (los devuelve 'ver remitos sin facturar'). Esas lineas quedan asociadas a "
        "la factura y el remito deja de figurar como pendiente.\n"
        "2. items: articulos que se facturan sin entrega previa, cada uno {codigo, cantidad} "
        "y opcionalmente {precio}. ALdia valida el stock y rechaza la factura si no "
        "alcanza.\n\n"
        "Los importes (subtotal, IVA y total) los calcula esta herramienta a partir de los "
        "precios y alicuotas de cada articulo; no hay que pasarlos.\n\n"
        "Parametros: cliente (CUIT o nombre) y fecha (YYYY-MM-DD, por defecto hoy)."
    ),
)
def emitir_factura(
    cliente: str,
    lineas_remito_ids: list[int] | None = None,
    items: list[dict[str, Any]] | None = None,
    fecha: str | None = None,
) -> dict[str, Any]:
    cli = api()
    lineas_remito_ids = list(lineas_remito_ids or [])
    items = list(items or [])
    if not lineas_remito_ids and not items:
        raise ALdiaError(
            "La factura esta vacia: pase lineas_remito_ids (de remitos pendientes) y/o items."
        )

    ficha = cli.resolver_cliente(cliente)
    dia = _fecha(fecha)

    subtotal = 0.0
    iva_total = 0.0
    detalle: list[dict[str, Any]] = []
    payload_items: list[dict[str, Any]] = []

    if lineas_remito_ids:
        pendientes = {int(l["id"]): l for l in (cli.get("/api/remitos/nofacturados") or []) if l.get("id")}
        for lid in lineas_remito_ids:
            linea = pendientes.get(int(lid))
            if not linea:
                raise ALdiaError(
                    f"La linea de remito {lid} no existe o ya fue facturada. Vuelva a consultar "
                    "'ver remitos sin facturar'."
                )
            if linea.get("cliente") != ficha.get("cuit"):
                raise ALdiaError(
                    f"La linea de remito {lid} es del cliente {linea.get('cliente')}, no de "
                    f"{ficha.get('cuit')}. No se pueden mezclar clientes en una factura."
                )
            neto = float(linea.get("cantidad") or 0) * float(linea.get("precio") or 0)
            try:
                alicuota = float((cli.producto(int(linea.get("codigo"))) or {}).get("iva") or 21.0)
            except ALdiaError:
                alicuota = 21.0
            subtotal += neto
            iva_total += neto * alicuota / 100.0
            detalle.append(
                {
                    "origen": f"remito {linea.get('nmov')}",
                    "producto": linea.get("producto"),
                    "cantidad": linea.get("cantidad"),
                    "precio": linea.get("precio"),
                    "neto": _redondear(neto),
                    "iva_pct": alicuota,
                }
            )
            payload_items.append({"id": int(lid)})

    for it in items:
        if "codigo" not in it:
            raise ALdiaError(f"Falta 'codigo' en el item {it}.")
        art = cli.producto(int(it["codigo"]))
        cantidad = float(it.get("cantidad") or 0)
        if cantidad <= 0:
            raise ALdiaError(f"La cantidad del articulo {art.get('codigo')} debe ser mayor a 0.")
        precio = float(it["precio"]) if it.get("precio") is not None else float(art.get("preven") or 0)
        alicuota = float(art.get("iva") or 21.0)
        neto = cantidad * precio
        subtotal += neto
        iva_total += neto * alicuota / 100.0
        detalle.append(
            {
                "origen": "sin remito",
                "producto": art.get("producto"),
                "cantidad": cantidad,
                "precio": precio,
                "neto": _redondear(neto),
                "iva_pct": alicuota,
            }
        )
        payload_items.append(
            {
                "codigo": int(art["codigo"]),
                "producto": art.get("producto"),
                "cantidad": cantidad,
                "precio": precio,
                "unidad": art.get("unidad") or "UN",
            }
        )

    subtotal = _redondear(subtotal)
    iva_total = _redondear(iva_total)
    total = _redondear(subtotal + iva_total)

    factura = cli.post(
        "/api/facturas/",
        {
            "cliente": ficha.get("cuit"),
            "fecha": dia,
            "subtotal": subtotal,
            "iva": iva_total,
            "total": total,
            "items": payload_items,
        },
    )

    return {
        "emitida": True,
        "factura_numero": factura.get("facturanumero"),
        "cliente": ficha.get("nombre"),
        "cuit": ficha.get("cuit"),
        "fecha": dia,
        "subtotal": subtotal,
        "iva": iva_total,
        "total": total,
        "detalle": detalle,
        "nota": "El total quedo cargado en la cuenta corriente del cliente. Cuando el cliente "
                "pague, registre el cobro.",
    }


@servidor.tool(
    title="Registrar cobro de un cliente",
    annotations=ESCRITURA,
    description=(
        "[OPERACION DE DINERO] Registra que un cliente pago. Efectos automaticos en ALdia:\n"
        "- baja el saldo de la cuenta corriente del cliente por el importe cobrado;\n"
        "- si el tipo NO es cheque, genera un ingreso de caja 'COBRO n';\n"
        "- si el tipo contiene 'cheque', NO entra a caja: el cheque se guarda en la chequera "
        "como valor a depositar.\n\n"
        "Parametros:\n"
        "- cliente: CUIT o nombre (debe existir).\n"
        "- monto: importe cobrado, mayor a 0.\n"
        "- tipo: 'efectivo', 'transferencia', 'tarjeta', 'cheque'... (texto libre; la palabra "
        "'cheque' es la que dispara el circuito de chequera).\n"
        "- fecha: YYYY-MM-DD, por defecto hoy.\n"
        "- referencia: numero de recibo, de operacion o de cheque.\n"
        "- banco y vencimiento: solo para cheques (vencimiento en YYYY-MM-DD).\n\n"
        "Confirme con el usuario el cliente y el importe antes de ejecutar."
    ),
)
def registrar_cobro(
    cliente: str,
    monto: float,
    tipo: str = "efectivo",
    fecha: str | None = None,
    referencia: str = "",
    banco: str = "",
    vencimiento: str | None = None,
) -> dict[str, Any]:
    cli = api()
    if float(monto) <= 0:
        raise ALdiaError("El monto del cobro debe ser mayor a 0.")
    ficha = cli.resolver_cliente(cliente)
    saldo_antes = float(ficha.get("saldo") or 0)

    cobro = cli.post(
        "/api/cobros/",
        {
            "cliente": ficha.get("cuit"),
            "monto": float(monto),
            "fecha": _fecha(fecha),
            "tipo": tipo,
            "referencia": referencia,
            "banco": banco,
            "vencimiento": _fecha(vencimiento) if vencimiento else "",
        },
    )
    es_cheque = "cheque" in (tipo or "").lower()
    return {
        "registrado": True,
        "orden_de_cobro": cobro.get("ordcobro"),
        "cliente": ficha.get("nombre"),
        "cuit": ficha.get("cuit"),
        "monto": cobro.get("monto"),
        "tipo": cobro.get("tipo"),
        "fecha": cobro.get("fecha"),
        "saldo_cliente_antes": _redondear(saldo_antes),
        "saldo_cliente_ahora": _redondear(saldo_antes - float(monto)),
        "entro_a_caja": not es_cheque,
        "nota": (
            "Cheque registrado en la chequera; NO suma al saldo de caja hasta que se deposite."
            if es_cheque
            else "Ingreso registrado en caja."
        ),
    }


@servidor.tool(
    title="Registrar pago a un proveedor",
    annotations=ESCRITURA,
    description=(
        "[OPERACION DE DINERO] Registra un pago a un proveedor. Efectos automaticos:\n"
        "- baja el saldo que el negocio le debe al proveedor;\n"
        "- si el tipo NO es cheque, genera un egreso de caja 'PAGO n';\n"
        "- si el tipo contiene 'cheque', registra un cheque propio emitido (no sale de caja "
        "hasta que se debita);\n"
        "- si se pasa cheque_id, se endosa un cheque de tercero ya existente en la chequera "
        "(no sale plata de caja) y ese cheque queda marcado como usado.\n\n"
        "Parametros: proveedor (CUIT o nombre), monto (> 0), tipo, fecha (YYYY-MM-DD, por "
        "defecto hoy), referencia, banco y vencimiento (cheques propios), cheque_id "
        "(endoso).\n\n"
        "Confirme proveedor e importe con el usuario antes de ejecutar."
    ),
)
def registrar_pago(
    proveedor: str,
    monto: float,
    tipo: str = "efectivo",
    fecha: str | None = None,
    referencia: str = "",
    banco: str = "",
    vencimiento: str | None = None,
    cheque_id: int | None = None,
) -> dict[str, Any]:
    cli = api()
    if float(monto) <= 0:
        raise ALdiaError("El monto del pago debe ser mayor a 0.")
    ficha = cli.resolver_proveedor(proveedor)
    saldo_antes = float(ficha.get("saldo") or 0)

    cuerpo: dict[str, Any] = {
        "proveedor": ficha.get("cuit"),
        "monto": float(monto),
        "fecha": _fecha(fecha),
        "tipo": tipo,
        "referencia": referencia,
        "banco": banco,
        "vencimiento": _fecha(vencimiento) if vencimiento else "",
    }
    if cheque_id is not None:
        cuerpo["cheque_id"] = int(cheque_id)

    pago = cli.post("/api/pagos/", cuerpo)
    es_cheque = "cheque" in (tipo or "").lower() or cheque_id is not None
    return {
        "registrado": True,
        "orden_de_pago": pago.get("ordpago"),
        "proveedor": ficha.get("nombre"),
        "cuit": ficha.get("cuit"),
        "monto": pago.get("monto"),
        "tipo": pago.get("tipo"),
        "fecha": pago.get("fecha"),
        "saldo_proveedor_antes": _redondear(saldo_antes),
        "saldo_proveedor_ahora": _redondear(saldo_antes - float(monto)),
        "salio_de_caja": not es_cheque,
    }


@servidor.tool(
    title="Registrar movimiento de caja",
    annotations=ESCRITURA,
    description=(
        "[OPERACION DE DINERO] Carga un movimiento manual de caja: un ingreso o un egreso "
        "que no proviene de un cobro, un pago o un gasto (por ejemplo: fondo fijo del dia, "
        "retiro del dueno, ajuste por diferencia de arqueo, venta de mostrador sin "
        "comprobante).\n\n"
        "Parametros:\n"
        "- concepto: descripcion de que es el movimiento (obligatorio).\n"
        "- ingreso: importe que ENTRA a la caja (positivo).\n"
        "- egreso: importe que SALE de la caja (positivo).\n"
        "  Hay que informar uno de los dos, nunca los dos a la vez, y siempre en positivo.\n"
        "- fecha: YYYY-MM-DD, por defecto hoy.\n"
        "- referencia: numero de comprobante o etiqueta corta, opcional.\n\n"
        "Ojo: los cobros, pagos y gastos YA generan su movimiento de caja automaticamente. "
        "Cargarlos tambien por aca duplicaria el importe."
    ),
)
def registrar_movimiento_caja(
    concepto: str,
    ingreso: float = 0.0,
    egreso: float = 0.0,
    fecha: str | None = None,
    referencia: str = "",
) -> dict[str, Any]:
    cli = api()
    ingreso = float(ingreso or 0)
    egreso = float(egreso or 0)
    if ingreso < 0 or egreso < 0:
        raise ALdiaError("Los importes van siempre en positivo: use 'ingreso' o 'egreso'.")
    if ingreso == 0 and egreso == 0:
        raise ALdiaError("Indique un importe: 'ingreso' (entra plata) o 'egreso' (sale plata).")
    if ingreso > 0 and egreso > 0:
        raise ALdiaError("Un movimiento no puede ser ingreso y egreso a la vez.")
    if not (concepto or "").strip():
        raise ALdiaError("Falta el concepto del movimiento de caja.")

    mov = cli.post(
        "/api/caja/",
        {
            "referencia": referencia,
            "fecha": _fecha(fecha),
            "debe": ingreso,
            "haber": egreso,
            "descripcion": concepto,
        },
    )
    saldo = (cli.get("/api/caja/saldo") or {}).get("saldo")
    return {
        "registrado": True,
        "movimiento_id": mov.get("id"),
        "fecha": mov.get("fecha"),
        "concepto": mov.get("descripcion"),
        "ingreso": mov.get("debe"),
        "egreso": mov.get("haber"),
        "saldo_de_caja_luego": saldo,
    }


@servidor.tool(
    title="Cargar factura de gasto",
    annotations=ESCRITURA,
    description=(
        "[OPERACION DE DINERO] Carga una factura de gasto (luz, alquiler, fletes, servicios, "
        "insumos). Efectos automaticos:\n"
        "- guarda la cabecera y el detalle de conceptos;\n"
        "- SUMA el total al saldo que se le debe al proveedor;\n"
        "- genera un egreso de caja 'GASTO n' por el total.\n\n"
        "Parametros:\n"
        "- proveedor: CUIT o nombre del proveedor (debe existir; si no, dele de alta antes).\n"
        "- conceptos: lista de renglones, cada uno {descripcion, monto} y opcionalmente "
        "{iva} con la alicuota en porcentaje (0, 2.5, 5, 10.5, 21 o 27; por defecto 21). "
        "El monto es el NETO sin IVA.\n"
        "- numero_factura: numero del comprobante del proveedor (ej. 'A-0001-00012345').\n"
        "- fecha: YYYY-MM-DD del comprobante, por defecto hoy.\n"
        "- descripcion: texto general del gasto, opcional.\n\n"
        "El subtotal, el IVA y el total se calculan a partir de los conceptos: el IVA cargado "
        "aca es el que despues aparece como credito fiscal en el libro IVA."
    ),
)
def cargar_gasto(
    proveedor: str,
    conceptos: list[dict[str, Any]],
    numero_factura: str = "",
    fecha: str | None = None,
    descripcion: str = "",
) -> dict[str, Any]:
    cli = api()
    if not conceptos:
        raise ALdiaError("El gasto no tiene conceptos: indique al menos uno {descripcion, monto}.")
    ficha = cli.resolver_proveedor(proveedor)

    items: list[dict[str, Any]] = []
    subtotal = 0.0
    iva_total = 0.0
    for c in conceptos:
        monto = float(c.get("monto") or 0)
        if monto < 0:
            raise ALdiaError("Los montos de los conceptos no pueden ser negativos.")
        alicuota = _validar_iva(float(c.get("iva", 21.0)))
        subtotal += monto
        iva_total += monto * alicuota / 100.0
        items.append(
            {"descripcion": c.get("descripcion", ""), "monto": monto, "iva": alicuota}
        )

    subtotal = _redondear(subtotal)
    iva_total = _redondear(iva_total)
    total = _redondear(subtotal + iva_total)

    gasto = cli.post(
        "/api/gastos/",
        {
            "proveedor": ficha.get("cuit"),
            "numfactura": numero_factura,
            "fecha": _fecha(fecha),
            "subtotal": subtotal,
            "iva": iva_total,
            "total": total,
            "descripcion": descripcion,
            "items": items,
        },
    )
    return {
        "cargado": True,
        "gasto_id": gasto.get("id"),
        "proveedor": ficha.get("nombre"),
        "numero_factura": gasto.get("numfactura"),
        "fecha": gasto.get("fecha"),
        "subtotal": subtotal,
        "iva": iva_total,
        "total": total,
        "conceptos": items,
        "nota": "Se genero el egreso de caja y se sumo la deuda con el proveedor.",
    }


@servidor.tool(
    title="Registrar compra a proveedor (ingreso de mercaderia)",
    annotations=ESCRITURA,
    description=(
        "[OPERACION DE DINERO] Registra una compra de mercaderia a un proveedor. Efectos "
        "automaticos:\n"
        "- SUMA la cantidad comprada al stock de cada articulo y actualiza su precio de "
        "compra;\n"
        "- suma el total (neto + IVA segun la alicuota de cada articulo) a la deuda con el "
        "proveedor.\n"
        "No genera egreso de caja: el pago se registra aparte con la herramienta de pago.\n\n"
        "Parametros:\n"
        "- proveedor: CUIT o nombre.\n"
        "- items: lista de {codigo, cantidad, precio}, donde precio es el costo unitario "
        "NETO sin IVA. Los articulos deben existir en el stock (si es un producto nuevo, "
        "dele de alta primero).\n"
        "- numero_factura: comprobante del proveedor.\n"
        "- fecha: YYYY-MM-DD, por defecto hoy."
    ),
)
def registrar_compra(
    proveedor: str,
    items: list[dict[str, Any]],
    numero_factura: str = "",
    fecha: str | None = None,
) -> dict[str, Any]:
    cli = api()
    if not items:
        raise ALdiaError("La compra no tiene items: indique al menos un articulo.")
    ficha = cli.resolver_proveedor(proveedor)

    lineas: list[dict[str, Any]] = []
    for it in items:
        if "codigo" not in it:
            raise ALdiaError(f"Falta 'codigo' en el item {it}.")
        art = cli.producto(int(it["codigo"]))
        cantidad = float(it.get("cantidad") or 0)
        if cantidad <= 0:
            raise ALdiaError(f"La cantidad del articulo {art.get('codigo')} debe ser mayor a 0.")
        precio = float(it.get("precio") if it.get("precio") is not None else art.get("precom") or 0)
        lineas.append(
            {
                "codigo": int(art["codigo"]),
                "producto": art.get("producto") or "",
                "cantidad": cantidad,
                "precio": precio,
            }
        )

    compra = cli.post(
        "/api/compras/",
        {
            "proveedor_cuit": ficha.get("cuit"),
            "fecha": _fecha(fecha),
            "num_factura": numero_factura,
            "items": lineas,
        },
    )
    return {
        "registrada": True,
        "compra_id": compra.get("id"),
        "proveedor": ficha.get("nombre"),
        "numero_factura": numero_factura,
        "fecha": compra.get("fecha"),
        "subtotal": compra.get("subtotal"),
        "iva": compra.get("iva"),
        "total": compra.get("total"),
        "items": lineas,
        "nota": "Stock actualizado y deuda con el proveedor incrementada. El pago se registra "
                "aparte.",
    }


# ═════════════════════════════════════════════════════════════
# 3. ANULACIONES (destructivas)
# ═════════════════════════════════════════════════════════════


@servidor.tool(
    title="Anular factura",
    annotations=DESTRUCTIVA,
    description=(
        "[DESTRUCTIVA] Anula una factura emitida: la borra, revierte la deuda del cliente, "
        "devuelve al stock los articulos facturados sin remito y deja los remitos asociados "
        "otra vez como pendientes de facturar.\n\n"
        "NO se puede deshacer. El asistente debe pedirle al usuario que confirme "
        "explicitamente que quiere anular esa factura, indicandole numero, cliente e "
        "importe, y recien entonces llamar de nuevo con confirmar=true."
    ),
)
def anular_factura(numero: int, confirmar: bool = False) -> dict[str, Any]:
    cli = api()
    factura = cli.get(f"/api/facturas/{int(numero)}")
    _exigir_confirmacion(
        confirmar,
        f"Anular la factura Nro {numero} (cliente {factura.get('cliente')}, "
        f"total {factura.get('total')})",
    )
    cli.delete(f"/api/facturas/{int(numero)}")
    return {"anulada": True, "factura": factura}


@servidor.tool(
    title="Anular cobro",
    annotations=DESTRUCTIVA,
    description=(
        "[DESTRUCTIVA] Anula un cobro registrado: lo borra, devuelve el importe al saldo del "
        "cliente y elimina el ingreso de caja que habia generado.\n\n"
        "Uselo para corregir un cobro cargado por error. Requiere confirmacion explicita del "
        "usuario: primero informe orden, cliente e importe, y recien despues llame con "
        "confirmar=true."
    ),
)
def anular_cobro(orden_de_cobro: int, confirmar: bool = False) -> dict[str, Any]:
    cli = api()
    _exigir_confirmacion(confirmar, f"Anular el cobro Nro {orden_de_cobro}")
    cli.delete(f"/api/cobros/{int(orden_de_cobro)}")
    return {"anulado": True, "orden_de_cobro": int(orden_de_cobro)}


@servidor.tool(
    title="Anular pago a proveedor",
    annotations=DESTRUCTIVA,
    description=(
        "[DESTRUCTIVA] Anula un pago a proveedor: lo borra, devuelve el importe al saldo del "
        "proveedor, elimina el egreso de caja y, si se habia endosado un cheque de tercero, "
        "lo deja otra vez disponible en la chequera.\n\n"
        "Requiere confirmacion explicita del usuario antes de llamar con confirmar=true."
    ),
)
def anular_pago(orden_de_pago: int, confirmar: bool = False) -> dict[str, Any]:
    cli = api()
    _exigir_confirmacion(confirmar, f"Anular el pago Nro {orden_de_pago}")
    cli.delete(f"/api/pagos/{int(orden_de_pago)}")
    return {"anulado": True, "orden_de_pago": int(orden_de_pago)}


@servidor.tool(
    title="Borrar movimiento de caja",
    annotations=DESTRUCTIVA,
    description=(
        "[DESTRUCTIVA] Borra un movimiento de caja por su id (el que devuelve la consulta de "
        "movimientos del dia). Cambia el saldo de caja.\n\n"
        "No lo use para revertir un cobro, un pago o un gasto: para eso estan las "
        "herramientas de anulacion correspondientes, que ademas corrigen los saldos de "
        "cuenta corriente. Requiere confirmacion explicita del usuario."
    ),
)
def borrar_movimiento_caja(movimiento_id: int, confirmar: bool = False) -> dict[str, Any]:
    cli = api()
    _exigir_confirmacion(confirmar, f"Borrar el movimiento de caja id {movimiento_id}")
    cli.delete(f"/api/caja/{int(movimiento_id)}")
    saldo = (cli.get("/api/caja/saldo") or {}).get("saldo")
    return {"borrado": True, "movimiento_id": int(movimiento_id), "saldo_de_caja_luego": saldo}


@servidor.tool(
    title="Anular gasto",
    annotations=DESTRUCTIVA,
    description=(
        "[DESTRUCTIVA] Anula una factura de gasto: la borra junto con sus conceptos, revierte "
        "la deuda con el proveedor y elimina el egreso de caja asociado. Requiere "
        "confirmacion explicita del usuario."
    ),
)
def anular_gasto(gasto_id: int, confirmar: bool = False) -> dict[str, Any]:
    cli = api()
    _exigir_confirmacion(confirmar, f"Anular el gasto id {gasto_id}")
    cli.delete(f"/api/gastos/{int(gasto_id)}")
    return {"anulado": True, "gasto_id": int(gasto_id)}


def main() -> None:
    """Punto de entrada: arranca el servidor MCP sobre stdio."""
    servidor.run()


if __name__ == "__main__":
    main()
