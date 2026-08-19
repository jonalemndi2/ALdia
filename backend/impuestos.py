"""
impuestos.py - Calcular el impuesto de una venta, con enchufe para un tercero.

POR QUE HACE FALTA UN ENCHUFE
=============================
En Argentina el IVA se puede calcular adentro del sistema y quedarse tranquilo:
las alicuotas son nacionales, son seis, y no cambian de un municipio a otro.

En Estados Unidos no. El sales tax se compone de estado, condado, ciudad y a
veces distritos especiales; hay del orden de 13.000 combinaciones y cambian
seguido. Ademas hay que decidir si aplica la tasa de donde sale la mercaderia o
la de donde llega (`sourcing`), si el comercio tiene obligacion en ese estado
(`nexus`), si la categoria del producto esta exenta y si el cliente presento un
certificado de exencion.

Eso NO se puede codear adentro de ALdia y mantener actualizado. Cualquier
intento de hacerlo termina en una tabla desactualizada que da numeros
plausibles y equivocados, que es la peor forma de estar mal.

LA TENSION, QUE NO SE PUEDE RESOLVER SOLA CON CODIGO
====================================================
El calculo correcto lo venden servicios externos, pagos y en linea. Y ALdia es
AGPL, corre en la PC del comercio y funciona sin internet a proposito --tanto
que en este mismo repositorio se le saco la dependencia de un CDN justamente
para lograrlo.

La salida es que el proveedor externo sea OPCIONAL y NUNCA bloqueante:

  * Si esta configurado y responde, se usa su numero.
  * Si no esta configurado, o no responde, o tarda, se usa la tasa manual.
  * El sistema NUNCA deja de facturar porque se cayo la conexion.

Y cada calculo dice DE DONDE salio (`fuente`), porque un importe de impuesto sin
saber quien lo calculo no se puede auditar ni corregir despues.

QUE HAY HOY
===========
El calculador local, y el enchufe. No hay ninguna integracion concreta con un
proveedor: escribirla sin una cuenta real contra la cual probarla seria escribir
codigo que nadie ejecuto nunca. `CalculadorExterno` es la interfaz que hay que
implementar, y son dos metodos.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dinero import aplicar_alicuota

__all__ = ["Impuesto", "calcular", "CalculadorExterno", "registrar_calculador",
           "FUENTE_LOCAL", "FUENTE_EXTERNA", "CLAVE_TASA"]

FUENTE_LOCAL = "tasa_manual"
FUENTE_EXTERNA = "proveedor_externo"

# Tasa que carga el comercio a mano, en la configuracion.
CLAVE_TASA = "negocio_tasa_impuesto"


@dataclass(frozen=True)
class Impuesto:
    """El resultado de calcular. `fuente` importa tanto como el importe."""

    base_centavos: int
    importe_centavos: int
    tasa: float
    fuente: str
    jurisdiccion: str = ""
    # Lo que el calculo NO contempla. Se publica en vez de esconderse.
    advertencias: tuple[str, ...] = ()


class CalculadorExterno:
    """Interfaz de un proveedor de calculo fiscal. Dos metodos, ninguno mas.

    Quien la implemente tiene que respetar dos reglas:

      1. `calcular` NO puede tardar indefinidamente. Si el servicio no responde
         en pocos segundos hay que levantar una excepcion: el comercio esta con
         un cliente adelante esperando el ticket.
      2. Cualquier excepcion se traduce en "usar la tasa manual". No se propaga.
    """

    nombre = "sin nombre"

    def disponible(self) -> bool:  # pragma: no cover - lo implementa cada uno
        raise NotImplementedError

    def calcular(self, base_centavos: int, destino: dict) -> Impuesto:  # pragma: no cover
        raise NotImplementedError


_externo: CalculadorExterno | None = None


def registrar_calculador(calculador: CalculadorExterno | None) -> None:
    """Enchufa (o desenchufa) un proveedor externo."""
    global _externo
    _externo = calculador


def _tasa_manual(db=None) -> float:
    """La tasa que cargo el comercio. 0 si no cargo ninguna."""
    if db is None:
        return float(os.getenv("ALDIA_TASA_IMPUESTO", "0") or 0)
    try:
        from models import Configuracion
        fila = db.query(Configuracion).filter(Configuracion.clave == CLAVE_TASA).first()
        return float(fila.valor) if fila and fila.valor else 0.0
    except (ValueError, TypeError, AttributeError):
        return 0.0


def calcular(base_centavos: int, tasa: float | None = None, db=None,
             destino: dict | None = None) -> Impuesto:
    """El impuesto sobre una base imponible.

    Orden de preferencia: la tasa que se pase explicitamente (es la que eligio
    quien carga el comprobante), despues el proveedor externo, y por ultimo la
    tasa manual de la configuracion.
    """
    from paises import pais_configurado
    pais = pais_configurado()

    if tasa is not None:
        return Impuesto(
            base_centavos=base_centavos,
            importe_centavos=aplicar_alicuota(base_centavos, tasa),
            tasa=float(tasa),
            fuente=FUENTE_LOCAL,
            advertencias=pais.notas,
        )

    if _externo is not None:
        try:
            if _externo.disponible():
                return _externo.calcular(base_centavos, destino or {})
        except Exception:
            # Deliberadamente amplio: NINGUN problema del proveedor externo
            # puede impedir que el comercio emita el comprobante. Se sigue con
            # la tasa manual y el `fuente` del resultado deja ver que paso.
            pass

    manual = _tasa_manual(db)
    return Impuesto(
        base_centavos=base_centavos,
        importe_centavos=aplicar_alicuota(base_centavos, manual),
        tasa=manual,
        fuente=FUENTE_LOCAL,
        advertencias=pais.notas,
    )
