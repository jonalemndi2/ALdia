"""
paises/ - Lo que cambia de un pais a otro, y NADA mas.

POR QUE UNA INTERFAZ ANGOSTA Y NO UN "PAQUETE DE PAIS" COMPLETO
===============================================================
La tentacion al internacionalizar es crear `countries/argentina/` y
`countries/usa/` con un archivo espejo para cada cosa: impuestos, facturacion,
identificadores, documentos fiscales. Suena ordenado y sale mal, porque hoy hay
UNA implementacion real (Argentina: WSAA, WSFEv1, CAE, QR fiscal, ~1600 lineas)
y una que casi no existe (Estados Unidos no tiene factura electronica
obligatoria). Una abstraccion diseñada desde un caso pesado y uno vacio termina
teniendo la forma exacta de Argentina, con un agujero del lado de EE.UU.

Asi que esto se define al reves: por lo que el NUCLEO necesita preguntar.

  * Como se llama y como se valida el identificador fiscal de una persona o
    empresa (CUIT / EIN).
  * Que impuesto se aplica sobre una venta, y que tasas son legitimas.
  * Si un comprobante necesita autorizacion de un organismo antes de ser valido.

Nada mas. Tres preguntas. Si manana hace falta una cuarta, se agrega cuando haya
DOS paises que la necesiten de verdad, no antes.

Lo que NO vive aca, porque no cambia entre paises: la auditoria, la
idempotencia, los permisos por rol, la numeracion de comprobantes, el manejo de
dinero en centavos enteros y el control de concurrencia. Esa es la mayor parte
del sistema, y es la razon por la que esto es un paquete de pais y no un fork.

COMO SE RESUELVE EL PAIS
========================
ALdia es MONOINQUILINO: un archivo de base de datos por comercio. Entonces el
pais no es un dato de cada operacion ni de cada empresa — es una propiedad de la
INSTALACION, igual que la clave de firma. Se lee una vez de la tabla
`configuracion` y se cachea en memoria; cambiarlo desde la pantalla de
configuracion invalida el cache.

Esto importa para las validaciones de Pydantic, que corren sin acceso a la base:
pueden preguntar por el pais sin recibir una sesion.
"""
from __future__ import annotations

import threading

from paises.base import PaisNoSoportado, ReglasDePais
from paises.argentina import ARGENTINA
from paises.estados_unidos import ESTADOS_UNIDOS

__all__ = [
    "ReglasDePais", "PaisNoSoportado", "PAISES",
    "reglas", "pais_configurado", "fijar_pais", "olvidar_pais",
    "CLAVE_CONFIG_PAIS", "PAIS_POR_DEFECTO",
]

PAISES: dict[str, ReglasDePais] = {
    ARGENTINA.codigo: ARGENTINA,
    ESTADOS_UNIDOS.codigo: ESTADOS_UNIDOS,
}

CLAVE_CONFIG_PAIS = "negocio_pais"

# Argentina por defecto, y a proposito: toda instalacion que ya existe se
# comporta exactamente igual que antes sin tocar nada.
PAIS_POR_DEFECTO = "AR"


def reglas(codigo: str) -> ReglasDePais:
    """Las reglas del pais pedido. Levanta PaisNoSoportado si no hay paquete."""
    pais = PAISES.get((codigo or "").strip().upper())
    if pais is None:
        raise PaisNoSoportado(
            f"No hay reglas para el pais {codigo!r}. "
            f"Soportados: {', '.join(sorted(PAISES))}."
        )
    return pais


# ─────────────────────────────────────────────────────────────────────────────
# El pais de ESTA instalacion.
#
# Se cachea porque lo consultan las validaciones de Pydantic, que corren en cada
# request y no reciben una sesion de base de datos. El candado protege la
# escritura desde el endpoint de configuracion mientras hay requests en vuelo.
# ─────────────────────────────────────────────────────────────────────────────
_cache: str | None = None
_candado = threading.Lock()


def pais_configurado() -> ReglasDePais:
    """Las reglas del pais de esta instalacion.

    Si la configuracion nombra un pais sin paquete, se cae a Argentina en vez de
    romper: es preferible que el sistema arranque y el comercio pueda facturar,
    a que un valor mal escrito en una pantalla de configuracion deje la caja sin
    poder operar. El aviso queda en el endpoint de configuracion, que es donde
    se puede corregir.
    """
    global _cache
    if _cache is None:
        with _candado:
            if _cache is None:
                _cache = _leer_de_la_base()
    try:
        return reglas(_cache)
    except PaisNoSoportado:
        return ARGENTINA


def _leer_de_la_base() -> str:
    # Import diferido: este modulo lo importan los schemas, que se cargan antes
    # de que exista la base en el primer arranque.
    try:
        from database import SessionLocal
        from models import Configuracion
        sesion = SessionLocal()
        try:
            fila = (
                sesion.query(Configuracion)
                .filter(Configuracion.clave == CLAVE_CONFIG_PAIS)
                .first()
            )
            return (fila.valor if fila and fila.valor else PAIS_POR_DEFECTO).upper()
        finally:
            sesion.close()
    except Exception:
        # Base todavia inexistente o inaccesible: el default no rompe nada.
        return PAIS_POR_DEFECTO


def fijar_pais(codigo: str) -> None:
    """Cambia el pais en memoria. La llama el endpoint de configuracion."""
    global _cache
    with _candado:
        _cache = (codigo or PAIS_POR_DEFECTO).strip().upper()


def olvidar_pais() -> None:
    """Vacia el cache para que se relea. Se usa en las pruebas y al reconfigurar."""
    global _cache
    with _candado:
        _cache = None
