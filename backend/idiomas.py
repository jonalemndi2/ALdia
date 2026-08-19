"""
idiomas.py - El sistema hablando el idioma de quien lo usa.

POR QUE NO SE TRADUJERON LOS 68 MENSAJES A MANO
===============================================
La forma obvia de internacionalizar es envolver cada string en una funcion de
traduccion y armar un catalogo con 68 entradas. Funciona, y tiene dos problemas
que se ven recien despues:

  1. Cada mensaje nuevo nace SIN traducir, y no hay nada que lo detecte. A los
     seis meses el catalogo cubre la mitad de los errores y nadie sabe cual.
  2. El mensaje es texto libre, asi que traducirlo bien exige que quien traduce
     entienda el contexto de negocio de cada uno.

Aca ya existia una costura mejor, construida para otra cosa: los CODIGOS DE
ERROR (ver backend/errores.py). `codigo` y `accion` no dependen del idioma —
`STOCK_INSUFICIENTE` significa lo mismo en Villa Huidobro y en Miami. Asi que la
traduccion se cuelga del codigo, no del texto.

COMO FUNCIONA
=============
Un error viaja con tres cosas ademas del mensaje:

    {
      "detail": "Stock insuficiente de 'Coca 2.25': se piden 12 y hay 5",
      "codigo": "STOCK_INSUFICIENTE",
      "accion": "corregir",
      "params": {"producto": "Coca 2.25", "pedido": 12, "disponible": 5}
    }

`params` es la novedad. Con el codigo y los parametros, CUALQUIER cliente puede
armar el mensaje en el idioma que quiera sin que el servidor traduzca nada. El
navegador lo hace con Web/js/i18n.js; un agente ni siquiera necesita prosa.

Y `detail` sigue viniendo siempre, renderizado en el idioma de la instalacion:
es lo que leen las personas, lo que queda en la auditoria y lo que ya consume
todo el codigo que existe. Nada se rompe.

DEGRADACION HONESTA
===================
Si un codigo no tiene plantilla en el idioma pedido, se devuelve el texto que
escribio quien levanto el error, en castellano. Es preferible un mensaje util en
otro idioma a un `errors.stock.insufficient` sin traducir en la cara del cajero.
`faltantes()` dice exactamente cuales son, para que la deuda sea medible en vez
de invisible.
"""
from __future__ import annotations

import threading

__all__ = [
    "IDIOMAS", "IDIOMA_POR_DEFECTO", "CLAVE_CONFIG_IDIOMA",
    "traducir", "idioma_configurado", "fijar_idioma", "olvidar_idioma",
    "faltantes", "textos_de",
]

CLAVE_CONFIG_IDIOMA = "negocio_locale"
IDIOMA_POR_DEFECTO = "es-AR"

IDIOMAS = ("es-AR", "en-US")


# ─────────────────────────────────────────────────────────────────────────────
# Plantillas por codigo de error.
#
# Las llaves {} son los `params` que manda quien levanta el error. Una plantilla
# que pide un parametro que no llego NO rompe: se cae al texto original (ver
# `traducir`), porque un error a medio armar es peor que un error en castellano.
# ─────────────────────────────────────────────────────────────────────────────
MENSAJES: dict[str, dict[str, str]] = {
    "es-AR": {
        "STOCK_INSUFICIENTE":
            "Stock insuficiente de '{producto}': se intentan facturar "
            "{pedido} y hay {disponible}",
        "TIENE_MOVIMIENTOS":
            "No se puede eliminar {que} porque tiene movimientos registrados "
            "({detalle}). Los comprobantes ya emitidos no se pueden dejar sin titular.",
        "CLIENTE_NO_EXISTE": "No existe el cliente {identificador}",
        "PROVEEDOR_NO_EXISTE": "No existe el proveedor {identificador}",
        "PRODUCTO_NO_EXISTE": "Producto no encontrado",
        "YA_EXISTE": "Ya existe un registro con la clave {clave}: no se puede duplicar",
        "CREDENCIALES_INVALIDAS": "Usuario o contraseña incorrectos",
        "NO_AUTENTICADO": "No autenticado",
        "SESION_VENCIDA":
            "La sesión ya no es válida. Vuelva a iniciar sesión.",
        "SIN_PERMISO":
            "{usuario} ({rol}) no tiene acceso al módulo '{modulo}'",
        "SOLO_LECTURA":
            "{usuario} tiene rol auditor, de solo consulta: no puede modificar datos",
        "CAE_YA_EMITIDO":
            "La factura {numero} ya tiene CAE {cae}. Pedir otro duplicaría la "
            "declaración ante AFIP.",
        "OPERACION_NO_APLICA_EN_ESTE_PAIS":
            "Esta instalación está configurada para {pais}, donde los comprobantes "
            "no requieren autorización previa de ningún organismo.",
        "PAIS_NO_SOPORTADO": "No hay reglas fiscales para el país {pais}.",
    },
    "en-US": {
        "STOCK_INSUFICIENTE":
            "Not enough stock for '{producto}': {pedido} requested, {disponible} on hand",
        "TIENE_MOVIMIENTOS":
            "{que} cannot be deleted because it has recorded activity ({detalle}). "
            "Documents already issued cannot be left without a counterparty.",
        "CLIENTE_NO_EXISTE": "No such customer: {identificador}",
        "PROVEEDOR_NO_EXISTE": "No such vendor: {identificador}",
        "PRODUCTO_NO_EXISTE": "Item not found",
        "YA_EXISTE": "A record with key {clave} already exists: duplicates are not allowed",
        "CREDENCIALES_INVALIDAS": "Incorrect username or password",
        "NO_AUTENTICADO": "Not authenticated",
        "SESION_VENCIDA": "This session is no longer valid. Please sign in again.",
        "SIN_PERMISO": "{usuario} ({rol}) does not have access to the '{modulo}' module",
        "SOLO_LECTURA":
            "{usuario} has the auditor role, which is read-only: data cannot be changed",
        "CAE_YA_EMITIDO":
            "Invoice {numero} already has authorization code {cae}. Requesting another "
            "would duplicate the tax filing.",
        "OPERACION_NO_APLICA_EN_ESTE_PAIS":
            "This installation is configured for {pais}, where documents do not require "
            "prior authorization from any agency.",
        "PAIS_NO_SOPORTADO": "There are no tax rules for country {pais}.",
    },
}


# Textos sueltos de la interfaz y de las respuestas que no son errores.
TEXTOS: dict[str, dict[str, str]] = {
    "es-AR": {
        "accion.reintentar": "El pedido estaba bien y puede salir solo. Esperar y repetir.",
        "accion.corregir": "Falta o sobra un dato que el agente puede arreglar.",
        "accion.preguntar": "Hace falta una decisión que el agente no puede tomar.",
        "accion.abortar": "No va a funcionar por más que se insista.",
        "identificador.CUIT": "CUIT",
        "identificador.EIN": "EIN",
        "impuesto.IVA": "IVA",
        "impuesto.Sales tax": "Impuesto a las ventas",
    },
    "en-US": {
        "accion.reintentar": "The request was fine and may succeed on its own. Wait and retry.",
        "accion.corregir": "A field is missing or wrong and the agent can fix it.",
        "accion.preguntar": "A decision is needed that the agent must not make alone.",
        "accion.abortar": "Retrying will not help.",
        "identificador.CUIT": "Argentine Tax ID (CUIT)",
        "identificador.EIN": "EIN",
        "impuesto.IVA": "VAT",
        "impuesto.Sales tax": "Sales tax",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# El idioma de ESTA instalacion.
#
# Mismo criterio que el pais (ver paises/__init__.py): ALdia es monoinquilino,
# asi que el idioma es una propiedad de la instalacion y no de cada peticion.
# Se cachea porque lo consulta el manejador de errores en cada respuesta.
# ─────────────────────────────────────────────────────────────────────────────
_cache: str | None = None
_candado = threading.Lock()


def normalizar(codigo: str) -> str:
    """'en_US', 'en-us', 'en' -> 'en-US'. Devuelve el default si no se reconoce."""
    if not codigo:
        return IDIOMA_POR_DEFECTO
    limpio = str(codigo).strip().replace("_", "-").lower()
    for disponible in IDIOMAS:
        if disponible.lower() == limpio:
            return disponible
    # Solo el idioma, sin region: 'en' -> 'en-US'.
    for disponible in IDIOMAS:
        if disponible.lower().split("-")[0] == limpio.split("-")[0]:
            return disponible
    return IDIOMA_POR_DEFECTO


def idioma_configurado() -> str:
    global _cache
    if _cache is None:
        with _candado:
            if _cache is None:
                _cache = _leer_de_la_base()
    return _cache


def _leer_de_la_base() -> str:
    try:
        from database import SessionLocal
        from models import Configuracion
        sesion = SessionLocal()
        try:
            fila = (
                sesion.query(Configuracion)
                .filter(Configuracion.clave == CLAVE_CONFIG_IDIOMA)
                .first()
            )
            if fila and fila.valor:
                return normalizar(fila.valor)
        finally:
            sesion.close()
    except Exception:
        pass

    # Sin idioma configurado, se hereda del pais: una instalacion estadounidense
    # habla ingles salvo que alguien diga lo contrario.
    try:
        from paises import pais_configurado
        return normalizar(pais_configurado().locale)
    except Exception:
        return IDIOMA_POR_DEFECTO


def fijar_idioma(codigo: str) -> None:
    global _cache
    with _candado:
        _cache = normalizar(codigo)


def olvidar_idioma() -> None:
    global _cache
    with _candado:
        _cache = None


# ─────────────────────────────────────────────────────────────────────────────

def traducir(codigo: str, respaldo: str, idioma: str | None = None, **params) -> str:
    """El mensaje del error `codigo` en el idioma pedido.

    `respaldo` es el texto que escribio quien levanto el error. Se devuelve tal
    cual cuando no hay plantilla, o cuando la plantilla pide un parametro que no
    llego: un mensaje util en otro idioma es mejor que uno roto en el propio.
    """
    plantilla = MENSAJES.get(idioma or idioma_configurado(), {}).get(codigo)
    if not plantilla:
        return respaldo
    try:
        return plantilla.format(**params)
    except (KeyError, IndexError):
        return respaldo


def textos_de(idioma: str | None = None) -> dict[str, str]:
    """Los textos sueltos del idioma pedido, con respaldo en el por defecto."""
    elegido = idioma or idioma_configurado()
    base = dict(TEXTOS.get(IDIOMA_POR_DEFECTO, {}))
    base.update(TEXTOS.get(elegido, {}))
    return base


def faltantes(idioma: str) -> list[str]:
    """Codigos del catalogo de errores sin plantilla en ese idioma.

    Existe para que la deuda de traduccion sea MEDIBLE. Sin esto, la unica forma
    de saber que falta es que un usuario se encuentre un mensaje en el idioma
    equivocado. Lo consume una prueba, asi que agregar un codigo nuevo sin su
    plantilla se ve en la suite y no seis meses despues.
    """
    from errores import CATALOGO
    tiene = set(MENSAJES.get(normalizar(idioma), {}))
    return sorted(set(CATALOGO) - tiene)
