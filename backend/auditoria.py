"""
auditoria.py - Registro de auditoria de ALdia (quien hizo que y cuando).

PROBLEMA QUE RESUELVE
─────────────────────
En un comercio con varias cajas y empleados, saber quien anulo una factura,
quien cambio un precio o quien toco la caja es la diferencia entre detectar un
problema y no enterarse nunca. Hasta ahora el sistema no dejaba ningun rastro.

COMO SE GARANTIZA QUE NADA QUEDE SIN AUDITAR
────────────────────────────────────────────
El registro NO se escribe ruta por ruta (eso se olvida en la proxima ruta que
alguien agregue: es exactamente el agujero que este proyecto ya tuvo con la
autenticacion). Se apoya en dos mecanismos centralizados:

  1. `AuditoriaMiddleware`: middleware ASGI que ve TODAS las peticiones. Toda
     peticion POST / PUT / PATCH / DELETE a /api/* deja una fila, con o sin
     exito, haya o no llegado a ejecutarse el codigo de la ruta. Una ruta nueva
     nace auditada sin que su autor haga nada.
     Las lecturas (GET) NO se registran: serian ruido y un volumen enorme.

  2. Eventos de sesion de SQLAlchemy (`before_flush` / `after_flush`): capturan
     el valor ANTERIOR y el NUEVO de los campos sensibles (precio de un
     articulo, saldo de un cliente o proveedor, anulacion de comprobantes, alta
     y baja de usuarios, cambios de rol y de modulos). Se enganchan a la sesion,
     no a cada modelo importado, asi que funcionan aunque models.py cambie.

DATOS QUE NUNCA SE GUARDAN
──────────────────────────
Contrasenas, hashes de contrasena y tokens. El cuerpo de la peticion se
enmascara con `enmascarar()` antes de tocar la base, y `password_hash` no figura
en la lista de campos observados de la tabla `usuarios`.

INMUTABILIDAD (decision de diseno deliberada)
─────────────────────────────────────────────
Un log que el administrador puede borrar no sirve como auditoria: el primer
sospechoso de tapar un movimiento es justamente quien tiene todos los permisos.
Por eso:

  a) NO existe -- ni debe agregarse nunca -- ningun endpoint que borre, edite o
     "depure" el registro. routers/auditoria.py solo expone GET.
  b) Guardas a nivel ORM: cualquier intento de UPDATE o DELETE sobre una fila de
     auditoria desde el codigo de la aplicacion lanza una excepcion (ver
     `_bloquear_modificacion` mas abajo).
  c) La tabla vive en su PROPIO MetaData (`BaseAuditoria`), separado del
     `Base` de database.py. Esto es lo que impide que
     `POST /api/admin/reset-db` -- que hace `Base.metadata.drop_all()` -- se
     lleve puesto el historial: reset-db borra los datos del comercio y queda
     registrado en la auditoria, que sobrevive.

Borrar el historial requiere acceso al archivo aldia.db en el servidor. Eso es
intencional: la proteccion contra el administrador es fisica (backup del
archivo, permisos del sistema operativo), no logica.
"""
from __future__ import annotations

import json
import sys
from contextvars import ContextVar
from datetime import datetime
from typing import Any

import jwt
from sqlalchemy import Column, Integer, String, Text, Index, event
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm.attributes import get_history

from database import engine, SessionLocal
from security import SECRET_KEY

# El algoritmo del JWT lo define routers/auth.py; se repite aca para no importar
# ese modulo (importarlo desde el middleware crea un ciclo con security.py).
ALGORITHM = "HS256"

METODOS_DE_ESCRITURA = {"POST", "PUT", "PATCH", "DELETE"}

RESULTADO_EXITO = "exito"
RESULTADO_RECHAZADO = "rechazado"

# Roles que pueden CONSULTAR el registro. Va hardcodeado a proposito y no sale
# de la tabla `modulos`: quien audita no deberia poder ampliarse la lista de
# lectores editando una pantalla de configuracion.
ROLES_LECTURA_AUDITORIA = {"administrador", "auditor"}


# ═════════════════════════════════════════════════════════════
# 1. La tabla
# ═════════════════════════════════════════════════════════════

# MetaData propio: ver punto (c) del encabezado. NO usar el Base de database.py.
BaseAuditoria = declarative_base()


class RegistroAuditoria(BaseAuditoria):
    """Una fila por cada escritura intentada contra la API. Solo se inserta."""

    __tablename__ = "auditoria"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Fecha y hora con precision de segundos, hora local del servidor.
    # Se guarda como texto 'YYYY-MM-DD HH:MM:SS' (ordenable y filtrable por
    # rango tal cual, igual que el resto de las fechas del sistema).
    fecha_hora = Column(String(19), nullable=False)
    fecha = Column(String(10), nullable=False)  # 'YYYY-MM-DD', para filtrar rapido

    # Quien
    usuario = Column(String(80), default="")        # username; "anonimo" si no habia token
    usuario_id = Column(Integer, default=None)
    rol = Column(String(50), default="")            # rol AL MOMENTO de la accion

    # Que
    modulo = Column(String(50), default="")         # stock, facturas, caja, auth...
    accion = Column(String(50), default="")         # alta, modificacion, anulacion, login...
    metodo = Column(String(10), default="")         # POST / PUT / PATCH / DELETE
    ruta = Column(String(300), default="")          # /api/facturas/32
    tipo_registro = Column(String(50), default="")  # factura, articulo, cliente...
    numero_registro = Column(String(60), default="")  # 32, 20-12345678-9...
    descripcion = Column(String(1000), default="")  # texto legible para el duenio

    # Antes y despues (JSON) de los campos sensibles que cambiaron.
    valor_anterior = Column(Text, default=None)
    valor_nuevo = Column(Text, default=None)

    # Contexto y resultado
    ip = Column(String(80), default="")
    resultado = Column(String(20), default=RESULTADO_EXITO)  # exito | rechazado
    codigo_http = Column(Integer, default=None)

    # Origen: por donde entro la operacion y quien la pidio realmente.
    # `usuario` es la cuenta con la que se autentico; si esa cuenta la usa un
    # agente, `solicitante` dice que persona del otro lado la pidio.
    actor_tipo = Column(String(20), default="persona")   # persona | agente
    canal = Column(String(30), default="web")            # web | openclaw | whatsapp | telegram
    agente = Column(String(60), default="")              # nombre del agente que ejecuto
    solicitante = Column(String(80), default="")         # numero de WhatsApp, user_id de Telegram...


Index("ix_auditoria_fecha_hora", RegistroAuditoria.fecha_hora)
Index("ix_auditoria_usuario", RegistroAuditoria.usuario)
Index("ix_auditoria_modulo", RegistroAuditoria.modulo)
Index("ix_auditoria_accion", RegistroAuditoria.accion)
Index("ix_auditoria_canal", RegistroAuditoria.canal)


class AuditoriaInmutableError(RuntimeError):
    """Se intento modificar o borrar una fila del registro de auditoria."""


def _bloquear_modificacion(mapper, connection, target):  # noqa: ARG001
    raise AuditoriaInmutableError(
        "El registro de auditoria es inmutable: no se puede modificar ni eliminar. "
        "Esta guarda es deliberada; si alguien la remueve, el log deja de servir "
        "como auditoria (ver la nota de INMUTABILIDAD en backend/auditoria.py)."
    )


# Red de seguridad a nivel ORM: aunque alguien escriba manana un endpoint que
# haga db.delete(registro) o cambie un campo, la operacion falla.
event.listen(RegistroAuditoria, "before_update", _bloquear_modificacion)
event.listen(RegistroAuditoria, "before_delete", _bloquear_modificacion)


# ═════════════════════════════════════════════════════════════
# 2. Enmascarado de datos secretos
# ═════════════════════════════════════════════════════════════

# Fragmentos de nombre de campo cuyo valor NUNCA debe llegar al log.
# Ojo: "clave" NO esta en la lista a proposito -- en ALdia `clave` es el
# identificador de un modulo o de un item de configuracion, no una contrasena.
CLAVES_SECRETAS = (
    "password", "passwd", "contrasena", "contraseña", "pwd",
    "password_hash", "hash", "token", "secret", "authorization", "api_key", "apikey",
)

OCULTO = "***"


def enmascarar(valor: Any, profundidad: int = 0) -> Any:
    """Devuelve una copia del dato con los campos secretos reemplazados por ***."""
    if profundidad > 6:
        return "..."
    if isinstance(valor, dict):
        salida = {}
        for k, v in valor.items():
            nombre = str(k).lower()
            if any(sec in nombre for sec in CLAVES_SECRETAS):
                salida[k] = OCULTO
            else:
                salida[k] = enmascarar(v, profundidad + 1)
        return salida
    if isinstance(valor, (list, tuple)):
        return [enmascarar(v, profundidad + 1) for v in valor[:50]]
    if isinstance(valor, str) and len(valor) > 300:
        return valor[:300] + "..."
    return valor


# ═════════════════════════════════════════════════════════════
# 3. Captura del ANTES y el DESPUES (eventos de SQLAlchemy)
# ═════════════════════════════════════════════════════════════

# tabla -> (columna clave, campos observados, nombre legible, campos que son DINERO)
#
# `password_hash` NO figura en `usuarios`: el hash no se audita jamas.
#
# El cuarto elemento importa: la base guarda los importes en CENTAVOS enteros
# (ver backend/dinero.py), pero un log que dice "preven: 15000 -> 22000" no se
# lee. Esos campos se convierten a pesos antes de guardarse en la auditoria.
# Ojo con `iva`: en `stockmercaderia` es una ALICUOTA (21.0 = 21%) y NO se
# convierte; en `facturas`, `factprov` y `remito` es un IMPORTE y si.
CAMPOS_SENSIBLES: dict[str, tuple[str, tuple[str, ...], str, frozenset]] = {
    "stockmercaderia": ("codigo", ("producto", "cantidad", "unidad", "preven", "precom", "iva"),
                        "articulo", frozenset({"preven", "precom"})),
    "clientes": ("cuit", ("nombre", "saldo", "condicion_iva", "telefono", "mail"),
                 "cliente", frozenset({"saldo"})),
    "proveedores": ("cuit", ("nombre", "saldo", "telefono", "mail"),
                    "proveedor", frozenset({"saldo"})),
    "facturas": ("facturanumero", ("cliente", "fecha", "subtotal", "iva", "total", "cae", "resultado"),
                 "factura", frozenset({"subtotal", "iva", "total"})),
    "factprov": ("id", ("proveedor", "fecha", "subtotal", "iva", "total"),
                 "factura de proveedor", frozenset({"subtotal", "iva", "total"})),
    "remito": ("id", ("cliente", "fecha", "total", "iva"),
               "remito", frozenset({"total", "iva"})),
    "cobros": ("ordcobro", ("cliente", "monto", "fecha", "tipo", "referencia"),
               "cobro", frozenset({"monto"})),
    "pagos": ("ordpago", ("proveedor", "monto", "fecha", "tipo", "referencia"),
              "pago", frozenset({"monto"})),
    "caja": ("id", ("referencia", "fecha", "debe", "haber", "descripcion"),
             "movimiento de caja", frozenset({"debe", "haber"})),
    "chequera": ("id", ("numcheque", "tipo", "monto", "banco", "vencimiento", "pagado"),
                 "cheque", frozenset({"monto"})),
    "gastosfacturas": ("id", ("proveedor", "numfactura", "fecha", "total", "descripcion"),
                       "gasto", frozenset({"total"})),
    "usuarios": ("id", ("username", "rol"), "usuario", frozenset()),
    "modulos": ("clave", ("nombre", "habilitado", "roles"), "modulo", frozenset()),
    "configuracion": ("clave", ("valor",), "configuracion", frozenset()),
}


def _a_pesos(valor):
    """Centavos enteros -> pesos, para que el log se lea en la moneda del duenio."""
    if valor is None:
        return None
    try:
        from dinero import a_pesos  # import local: dinero.py lo mantiene otro flujo
        return a_pesos(valor)
    except Exception:
        return valor

# Contexto de la peticion en curso. Lo crea el middleware y lo mutan los eventos
# de SQLAlchemy. Es un dict mutable compartido, asi que funciona aunque FastAPI
# ejecute la ruta en el threadpool (contextvars se copian, el objeto no).
_contexto: ContextVar[dict | None] = ContextVar("auditoria_contexto", default=None)


def _clave_entidad(obj) -> tuple[str, str, str] | None:
    """(tabla, nombre legible, valor de la clave primaria) si la tabla es sensible."""
    tabla = getattr(obj, "__tablename__", None)
    ficha = CAMPOS_SENSIBLES.get(tabla)
    if not ficha:
        return None
    col_pk, _campos, legible = ficha[0], ficha[1], ficha[2]
    try:
        pk = getattr(obj, col_pk, None)
    except Exception:  # objeto en estado raro: no vale la pena romper la peticion
        pk = None
    return tabla, legible, "" if pk is None else str(pk)


def _snapshot(obj, campos: tuple[str, ...], dinero: frozenset = frozenset()) -> dict:
    datos = {}
    for campo in campos:
        try:
            valor = getattr(obj, campo, None)
        except Exception:
            continue
        datos[campo] = _a_pesos(valor) if campo in dinero else valor
    return enmascarar(datos)


def _registrar_cambio(tipo_op: str, obj, antes: dict | None, despues: dict | None) -> None:
    ctx = _contexto.get()
    if ctx is None:
        return  # fuera de una peticion HTTP (seed inicial, scripts): no se audita
    ficha = _clave_entidad(obj)
    if not ficha:
        return
    _tabla, legible, pk = ficha
    ctx["cambios"].append({
        "op": tipo_op,
        "tipo": legible,
        "numero": pk,
        "antes": antes,
        "despues": despues,
    })


def _antes_del_flush(session, flush_context, instances):  # noqa: ARG001
    """Capta modificaciones (valor viejo vs nuevo) y bajas (foto previa)."""
    if _contexto.get() is None:
        return

    for obj in session.deleted:
        ficha = _clave_entidad(obj)
        if not ficha:
            continue
        _pk, campos, _legible, dinero = CAMPOS_SENSIBLES[obj.__tablename__]
        _registrar_cambio("baja", obj, _snapshot(obj, campos, dinero), None)

    for obj in session.dirty:
        ficha = _clave_entidad(obj)
        if not ficha:
            continue
        _pk, campos, _legible, dinero = CAMPOS_SENSIBLES[obj.__tablename__]
        antes, despues = {}, {}
        for campo in campos:
            try:
                hist = get_history(obj, campo)
            except Exception:
                continue
            if not hist.has_changes():
                continue
            previo = hist.deleted[0] if hist.deleted else None
            actual = hist.added[0] if hist.added else None
            if previo == actual:
                continue
            if campo in dinero:
                previo, actual = _a_pesos(previo), _a_pesos(actual)
            antes[campo] = previo
            despues[campo] = actual
        if antes or despues:
            _registrar_cambio("modificacion", obj, enmascarar(antes), enmascarar(despues))


def _despues_del_flush(session, flush_context):  # noqa: ARG001
    """Capta altas. Se hace DESPUES del flush porque recien ahi hay clave primaria."""
    if _contexto.get() is None:
        return
    for obj in session.new:
        ficha = _clave_entidad(obj)
        if not ficha:
            continue
        _pk, campos, _legible, dinero = CAMPOS_SENSIBLES[obj.__tablename__]
        _registrar_cambio("alta", obj, None, _snapshot(obj, campos, dinero))


event.listen(SessionLocal, "before_flush", _antes_del_flush)
event.listen(SessionLocal, "after_flush", _despues_del_flush)


# ═════════════════════════════════════════════════════════════
# 4. Traduccion de la peticion HTTP a lenguaje del negocio
# ═════════════════════════════════════════════════════════════

# Segmento de la URL -> (nombre del modulo, nombre en singular del registro)
MODULOS_POR_RUTA = {
    "auth": ("autenticacion", "usuario"),
    "clientes": ("clientes", "cliente"),
    "proveedores": ("proveedores", "proveedor"),
    "stock": ("stock", "articulo"),
    "remitos": ("ventas", "remito"),
    "facturas": ("ventas", "factura"),
    "afip": ("ventas", "factura"),
    "cobros": ("cuentas_corrientes", "cobro"),
    "pagos": ("proveedores", "pago"),
    "caja": ("caja", "movimiento de caja"),
    "gastos": ("gastos", "gasto"),
    "iva": ("iva", "libro iva"),
    "admin": ("administracion", "registro"),
    "modulos": ("administracion", "modulo"),
    "config": ("administracion", "configuracion"),
    "compras": ("proveedores", "compra"),
    "devoluciones": ("proveedores", "devolucion"),
    "auditoria": ("auditoria", "registro de auditoria"),
}

ACCION_POR_METODO = {
    "POST": "alta",
    "PUT": "modificacion",
    "PATCH": "modificacion",
    "DELETE": "baja",
}

# Casos donde el nombre generico no dice lo que realmente paso.
ACCIONES_ESPECIALES = {
    ("POST", "auth", "login"): "login",
    ("POST", "auth", "register"): "alta de usuario",
    ("DELETE", "auth", "usuarios"): "baja de usuario",
    ("POST", "auth", "migrate-passwords"): "migracion de contrasenas",
    ("DELETE", "facturas", None): "anulacion de factura",
    ("DELETE", "cobros", None): "anulacion de cobro",
    ("DELETE", "pagos", None): "anulacion de pago",
    ("DELETE", "gastos", None): "anulacion de gasto",
    ("DELETE", "caja", None): "baja de movimiento de caja",
    ("DELETE", "admin", "movimientos"): "anulacion de movimiento",
    ("POST", "admin", "reset-db"): "RESETEO TOTAL DE LA BASE",
    ("POST", "admin", "seed-data"): "carga de datos de ejemplo",
    ("POST", "afip", None): "solicitud de CAE a AFIP",
    ("POST", "facturas", None): "emision de factura",
    ("POST", "remitos", "ventas"): "alta de renglon de remito",
    ("POST", "remitos", None): "emision de remito",
    ("POST", "cobros", None): "registro de cobro",
    ("POST", "pagos", None): "registro de pago",
    ("POST", "caja", None): "movimiento de caja",
    ("POST", "gastos", None): "carga de gasto",
    ("PUT", "modulos", None): "cambio de permisos de modulo",
    ("PUT", "config", None): "cambio de configuracion del negocio",
}


def _partes(ruta: str) -> list[str]:
    return [p for p in ruta.split("/") if p]


def _describir_ruta(metodo: str, ruta: str) -> tuple[str, str, str, str]:
    """Devuelve (modulo, accion, tipo_registro, numero_registro) deducidos de la URL."""
    partes = _partes(ruta)          # ['api', 'facturas', '32']
    seccion = partes[1] if len(partes) > 1 else ""
    resto = partes[2:]

    modulo, tipo = MODULOS_POR_RUTA.get(seccion, (seccion or "desconocido", "registro"))

    accion = ACCIONES_ESPECIALES.get((metodo, seccion, resto[0] if resto else None))
    if accion is None:
        accion = ACCIONES_ESPECIALES.get((metodo, seccion, None))
    if accion is None:
        accion = ACCION_POR_METODO.get(metodo, metodo.lower())

    # Numero del registro afectado: ultimo segmento de la URL que PAREZCA un
    # identificador. Se exige que contenga algun digito para no confundir el
    # nombre de la operacion con el numero del comprobante ("/auth/login" no
    # afecta al registro llamado "login", y "/admin/reset-db" no al "reset-db").
    numero = ""
    for parte in reversed(resto):
        if parte and any(c.isdigit() for c in parte) and parte not in ("db-info",):
            numero = parte
            break
    return modulo, accion, tipo, numero


def _usuario_del_token(cabeceras: dict[bytes, bytes]) -> str:
    """Username que viaja en el Bearer, sin tocar la base. '' si no hay token valido."""
    bruto = cabeceras.get(b"authorization", b"").decode("latin-1")
    if not bruto.lower().startswith("bearer "):
        return ""
    token = bruto[7:].strip()
    if not token:
        return ""
    try:
        # El token se valida igual en la dependencia de autenticacion; aca solo
        # nos interesa saber A NOMBRE DE QUIEN se hizo el intento.
        datos = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return str(datos.get("sub") or "")
    except jwt.PyJWTError:
        return ""


# ─────────────────────────────────────────────────────────────
# Origen de la operacion: por que canal entro y quien la pidio.
#
# ALdia se opera por varios caminos — el navegador, un asistente propio, un
# canal de consulta por WhatsApp o Telegram. Sin esto, TODO lo que entra por un
# agente queda registrado como la cuenta con la que ese agente se autentica: si
# tres personas usan el mismo asistente, las tres identidades colapsan en una.
#
# REGLA DE SEGURIDAD:
#   Estas cabeceras sirven para ATRIBUIR, nunca para AUTORIZAR. Los permisos se
#   siguen resolviendo contra el usuario del token (ver security.py). Aunque
#   alguien falsee una cabecera no gana ningun acceso: como mucho ensucia la
#   atribucion de una operacion que su rol ya tenia permitida.
#
#   Por eso la identidad del solicitante tiene que venir del CANAL, que es lo
#   unico verificable — el numero lo verifica WhatsApp, el user_id lo verifica
#   Telegram, la sesion la verifica ALdia — y nunca de algo que el modelo
#   deduzca de la conversacion. "Soy el dueño, carga esto" no es una identidad.
# ─────────────────────────────────────────────────────────────

CANAL_WEB = "web"
ACTOR_PERSONA = "persona"
ACTOR_AGENTE = "agente"

# Columnas de origen agregadas despues de la primera version de la tabla. Los
# registros viejos quedan como 'persona' por el navegador, que es lo que eran:
# antes de esto no habia ningun otro canal.
_COLUMNAS_DE_ORIGEN = [
    ("actor_tipo", "VARCHAR(20) DEFAULT 'persona'"),
    ("canal", "VARCHAR(30) DEFAULT 'web'"),
    ("agente", "VARCHAR(60) DEFAULT ''"),
    ("solicitante", "VARCHAR(80) DEFAULT ''"),
]


def _migrar_columnas_de_origen(engine) -> None:
    """Agrega las columnas de origen si la tabla ya existia sin ellas."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "auditoria" not in set(inspector.get_table_names()):
        return
    existentes = {c["name"] for c in inspector.get_columns("auditoria")}
    faltantes = [(n, t) for n, t in _COLUMNAS_DE_ORIGEN if n not in existentes]
    if not faltantes:
        return
    with engine.begin() as con:
        for nombre, tipo in faltantes:
            con.execute(text(f"ALTER TABLE auditoria ADD COLUMN {nombre} {tipo}"))


def _origen_de(cabeceras: dict[bytes, bytes]) -> dict:
    """Canal, agente y solicitante externo declarados por quien llama."""
    def _cab(nombre: str, limite: int) -> str:
        return cabeceras.get(nombre.encode(), b"").decode("latin-1").strip()[:limite]

    canal = _cab("x-aldia-canal", 30) or CANAL_WEB
    agente = _cab("x-aldia-agente", 60)
    solicitante = _cab("x-aldia-solicitante", 80)

    return {
        "actor_tipo": ACTOR_AGENTE if (agente or canal != CANAL_WEB) else ACTOR_PERSONA,
        "canal": canal,
        "agente": agente,
        "solicitante": solicitante,
    }


def _ip_de(scope: dict, cabeceras: dict[bytes, bytes]) -> str:
    cliente = scope.get("client")
    directa = cliente[0] if cliente else "desconocida"
    reenviada = cabeceras.get(b"x-forwarded-for", b"").decode("latin-1").split(",")[0].strip()
    if reenviada and reenviada != directa:
        return f"{directa} (X-Forwarded-For: {reenviada[:40]})"
    return directa


def _json_o_none(datos) -> str | None:
    if not datos:
        return None
    try:
        return json.dumps(datos, ensure_ascii=False, default=str)[:4000]
    except (TypeError, ValueError):
        return str(datos)[:4000]


def _cambio_principal(cambios: list[dict], tipo_de_la_ruta: str) -> dict | None:
    """Cual de los registros tocados es EL protagonista de la operacion.

    Una sola peticion mueve varias tablas: emitir una factura crea la factura,
    descuenta el stock y sube el saldo del cliente. La fila de auditoria tiene
    que decir "factura 7", no "articulo 901", asi que se prefiere la entidad que
    corresponde al modulo de la URL (/api/facturas/ -> factura) y, dentro de
    ella, un alta o una baja antes que una modificacion colateral.
    """
    if not cambios:
        return None
    del_tipo = [c for c in cambios if c["tipo"] == tipo_de_la_ruta and c["numero"]]
    for grupo in (del_tipo, cambios):
        for op in ("alta", "baja", "modificacion"):
            for c in grupo:
                if c["op"] == op and c["numero"]:
                    return c
    return cambios[0]


def _resumen_legible(cambios: list[dict], limite: int = 3) -> str:
    """'preven 150.0 -> 220.0' — el antes y el despues en una linea."""
    partes = []
    for cambio in cambios[:limite]:
        etiqueta = f"{cambio['tipo']} {cambio['numero']}".strip()
        if cambio["op"] == "modificacion":
            antes, despues = cambio.get("antes") or {}, cambio.get("despues") or {}
            detalle = ", ".join(
                f"{c}: {antes.get(c)} -> {despues.get(c)}" for c in list(despues)[:4]
            )
            partes.append(f"{etiqueta} [{detalle}]")
        elif cambio["op"] == "alta":
            partes.append(f"alta de {etiqueta}")
        else:
            partes.append(f"baja de {etiqueta}")
    if len(cambios) > limite:
        partes.append(f"(+{len(cambios) - limite} cambios mas)")
    return "; ".join(partes)


# ═════════════════════════════════════════════════════════════
# 5. Escritura de la fila
# ═════════════════════════════════════════════════════════════

def _guardar(fila: dict) -> None:
    """Inserta la fila en su propia sesion. Nunca propaga errores a la respuesta:
    que falle la auditoria no debe romperle la operacion al usuario, pero si
    tiene que dejarse ver en la consola del servidor."""
    sesion = SessionLocal()
    try:
        sesion.add(RegistroAuditoria(**fila))
        sesion.commit()
    except Exception as exc:  # pragma: no cover - defensivo
        sesion.rollback()
        print(f"[auditoria] NO se pudo registrar {fila.get('metodo')} "
              f"{fila.get('ruta')}: {exc}", file=sys.stderr)
    finally:
        sesion.close()


def _identidad(username: str) -> dict:
    """(usuario, id, rol) del que hace la peticion.

    Se resuelve ANTES de ejecutar la ruta, por dos motivos: el rol que se guarda
    tiene que ser el que el usuario tenia AL MOMENTO de la accion (si la propia
    peticion le cambia el rol o borra el usuario, el registro debe conservar el
    de antes), y asi la fila queda completa aunque la operacion elimine la ficha
    del usuario -- por ejemplo un reset total de la base.
    """
    if not username:
        return {"usuario": "anonimo", "usuario_id": None, "rol": ""}
    datos = {"usuario": username, "usuario_id": None, "rol": ""}
    sesion = SessionLocal()
    try:
        from models import Usuario  # import local: models.py lo edita otro flujo
        u = sesion.query(Usuario).filter(Usuario.username == username).first()
        if u:
            datos["usuario_id"] = u.id
            datos["rol"] = u.rol or ""
    except Exception:
        pass
    finally:
        sesion.close()
    return datos


# ═════════════════════════════════════════════════════════════
# 6. El middleware
# ═════════════════════════════════════════════════════════════

class AuditoriaMiddleware:
    """Middleware ASGI puro que audita toda escritura contra /api/*.

    Se implementa a nivel ASGI y no con `@app.middleware("http")` porque
    necesita leer el cuerpo de la peticion y devolverselo intacto a la ruta;
    controlando el canal `receive` eso es exacto y no depende de detalles
    internos de Starlette.
    """

    LIMITE_CUERPO = 64 * 1024      # no guardamos cargas gigantes
    LIMITE_RESPUESTA = 8 * 1024    # solo para leer el motivo de un rechazo

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        metodo = scope.get("method", "")
        ruta = scope.get("path", "")
        if metodo not in METODOS_DE_ESCRITURA or not ruta.startswith("/api/"):
            # Las lecturas (GET) y los archivos estaticos no se auditan.
            await self.app(scope, receive, send)
            return

        cabeceras = {k.lower(): v for k, v in scope.get("headers", [])}

        # ── Cuerpo de la peticion (se lee entero y se reinyecta) ──
        cuerpo = b""
        while True:
            mensaje = await receive()
            if mensaje.get("type") == "http.disconnect":
                break
            cuerpo += mensaje.get("body", b"")
            if not mensaje.get("more_body", False):
                break

        entregado = False

        async def receive_replay():
            nonlocal entregado
            if entregado:
                return {"type": "http.disconnect"}
            entregado = True
            return {"type": "http.request", "body": cuerpo, "more_body": False}

        # ── Respuesta: solo nos interesa el estado y, si falla, el motivo ──
        estado = 500
        cuerpo_respuesta = b""

        async def send_espia(mensaje):
            nonlocal estado, cuerpo_respuesta
            if mensaje.get("type") == "http.response.start":
                estado = mensaje.get("status", 500)
            elif mensaje.get("type") == "http.response.body" and estado >= 400:
                if len(cuerpo_respuesta) < self.LIMITE_RESPUESTA:
                    cuerpo_respuesta += mensaje.get("body", b"") or b""
            await send(mensaje)

        # Cuerpo enviado, ya enmascarado. NUNCA se guarda tal cual.
        payload = self._payload(cuerpo)

        # Quien. En el login todavia no hay token: el usuario sale del cuerpo.
        username = _usuario_del_token(cabeceras)
        if not username and isinstance(payload, dict) and payload.get("username"):
            username = str(payload["username"])[:80]
        identidad = _identidad(username)

        ctx = {"cambios": []}
        testigo = _contexto.set(ctx)
        try:
            await self.app(scope, receive_replay, send_espia)
        except Exception:
            estado = 500
            raise
        finally:
            _contexto.reset(testigo)
            try:
                self._anotar(scope, metodo, ruta, cabeceras, identidad, payload,
                             ctx["cambios"], estado, cuerpo_respuesta)
            except Exception as exc:  # pragma: no cover - defensivo
                print(f"[auditoria] fallo al anotar {metodo} {ruta}: {exc}", file=sys.stderr)

    def _payload(self, cuerpo: bytes):
        if not cuerpo or len(cuerpo) > self.LIMITE_CUERPO:
            return None
        try:
            return enmascarar(json.loads(cuerpo.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            return {"_cuerpo_no_json": f"{len(cuerpo)} bytes"}

    # ─────────────────────────────────────────────────────────
    def _anotar(self, scope, metodo, ruta, cabeceras, identidad, payload,
                cambios, estado, respuesta):
        modulo, accion, tipo, numero = _describir_ruta(metodo, ruta)
        exito = estado < 400
        ahora = datetime.now()

        fila = {
            "fecha_hora": ahora.strftime("%Y-%m-%d %H:%M:%S"),
            "fecha": ahora.strftime("%Y-%m-%d"),
            **identidad,
            "modulo": modulo,
            "accion": accion,
            "metodo": metodo,
            "ruta": ruta[:300],
            "tipo_registro": tipo,
            "numero_registro": str(numero)[:60],
            "ip": _ip_de(scope, cabeceras),
            **_origen_de(cabeceras),
            "resultado": RESULTADO_EXITO if exito else RESULTADO_RECHAZADO,
            "codigo_http": estado,
            "valor_anterior": None,
            "valor_nuevo": None,
        }

        if exito and cambios:
            # El antes y el despues reales, tomados del ORM.
            fila["valor_anterior"] = _json_o_none({
                f"{c['tipo']} {c['numero']}".strip(): c["antes"]
                for c in cambios if c.get("antes")
            })
            fila["valor_nuevo"] = _json_o_none({
                f"{c['tipo']} {c['numero']}".strip(): c["despues"]
                for c in cambios if c.get("despues")
            })
            principal = _cambio_principal(cambios, tipo)
            if principal and principal["numero"]:
                fila["tipo_registro"] = principal["tipo"]
                fila["numero_registro"] = str(principal["numero"])[:60]
                # El protagonista va primero para que la descripcion se lea sola.
                cambios = [principal] + [c for c in cambios if c is not principal]
            fila["descripcion"] = f"{accion.capitalize()}: {_resumen_legible(cambios)}"[:1000]
        elif exito:
            # Escritura correcta sobre algo que no vigilamos campo a campo:
            # dejamos al menos constancia de lo que se envio (enmascarado).
            fila["valor_nuevo"] = _json_o_none({"datos_enviados": payload} if payload else None)
            fila["descripcion"] = f"{accion.capitalize()} en {modulo} ({metodo} {ruta})"[:1000]
        else:
            # Los intentos FALLIDOS son lo mas interesante de una auditoria:
            # se guarda el motivo del rechazo y lo que se quiso hacer.
            motivo = self._motivo(respuesta)
            fila["valor_nuevo"] = _json_o_none({"intento_rechazado": payload} if payload else None)
            fila["descripcion"] = (
                f"RECHAZADO ({estado}) al intentar {accion} en {modulo}"
                + (f": {motivo}" if motivo else "")
            )[:1000]

        _guardar(fila)

    @staticmethod
    def _motivo(respuesta: bytes) -> str:
        if not respuesta:
            return ""
        try:
            cuerpo = json.loads(respuesta.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return ""
        detalle = cuerpo.get("detail") if isinstance(cuerpo, dict) else None
        if isinstance(detalle, str):
            return detalle[:400]
        if detalle is not None:
            return str(detalle)[:400]
        return ""


# ═════════════════════════════════════════════════════════════
# 7. Instalacion (un solo punto de enganche desde main.py)
# ═════════════════════════════════════════════════════════════

MODULO_AUDITORIA = {
    "clave": "auditoria",
    "nombre": "Auditoría",
    "descripcion": "Registro inmutable de quién hizo qué y cuándo",
    "icono": "bi-clipboard-check",
    "categoria": "admin",
    "habilitado": True,
    # Solo lectura, y solo para estos dos roles. El servidor lo vuelve a exigir
    # en require_lectura_auditoria(): tocar esta lista no alcanza para entrar.
    "roles": "administrador,auditor",
    "orden": 95,
}


def _sembrar_modulo() -> None:
    """Da de alta el modulo 'auditoria' para que aparezca en el menu del rol auditor."""
    sesion = SessionLocal()
    try:
        from models import Modulo
        if not sesion.query(Modulo).filter(Modulo.clave == "auditoria").first():
            sesion.add(Modulo(**MODULO_AUDITORIA))
            sesion.commit()
    except Exception as exc:  # pragma: no cover
        sesion.rollback()
        print(f"[auditoria] no se pudo sembrar el modulo: {exc}", file=sys.stderr)
    finally:
        sesion.close()


def instalar_auditoria(app) -> None:
    """Crea la tabla, engancha el middleware y publica el router de consulta.

    Es el UNICO punto que main.py necesita tocar. Todo lo demas vive en este
    archivo y en routers/auditoria.py.
    """
    # Tabla en su propio MetaData: reset-db no puede llevarsela puesta.
    BaseAuditoria.metadata.create_all(bind=engine)
    _migrar_columnas_de_origen(engine)
    _sembrar_modulo()

    from routers import auditoria as router_auditoria
    app.include_router(router_auditoria.router, prefix="/api/auditoria", tags=["Auditoría"])

    # Se agrega al final para que envuelva a todo el resto de la aplicacion.
    app.add_middleware(AuditoriaMiddleware)

