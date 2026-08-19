"""
paises/base.py - Las tres preguntas que el nucleo le hace a un pais.

Cada pais implementa esto y nada mas. Ver el encabezado de paises/__init__.py
para por que la interfaz es tan chica y por que no crece "por las dudas".
"""
from __future__ import annotations

from dataclasses import dataclass, field


class PaisNoSoportado(Exception):
    """Se pidio un pais para el que no hay paquete de reglas."""


@dataclass(frozen=True)
class IdentificadorFiscal:
    """Como identifica el fisco a una persona o empresa.

    En Argentina es el CUIT, con digito verificador modulo 11. En Estados Unidos
    es el EIN, que NO tiene digito verificador: solo formato y un prefijo de
    campana valido. Esa asimetria es justamente el punto — `validar` devuelve el
    valor normalizado o levanta ValueError, y al nucleo no le importa cual de
    las dos cosas paso adentro.
    """

    nombre: str                  # "CUIT", "EIN"
    descripcion: str             # para el mensaje de error y la UI
    ejemplo: str

    def validar(self, valor: str) -> str:  # pragma: no cover - lo hace cada pais
        raise NotImplementedError

    def formatear(self, valor: str) -> str:
        """Como se muestra. Por defecto, tal cual se guarda."""
        return valor


@dataclass(frozen=True)
class ReglasDeImpuesto:
    """El impuesto que se aplica sobre una venta.

    ATENCION a la diferencia conceptual, que es la mas grande entre los dos
    paises y la razon por la que esto es una interfaz y no una constante:

      * El IVA argentino es NACIONAL y tiene un conjunto CERRADO de alicuotas
        legales (0, 2,5, 5, 10,5, 21 y 27 %). Una alicuota fuera de esa lista es
        un error de carga, y por eso se rechaza.

      * El sales tax estadounidense es ESTATAL Y LOCAL. Depende de la
        jurisdiccion, de donde la empresa tiene obligacion (nexus) y a veces de
        la categoria del producto. No hay un conjunto cerrado que se pueda
        validar: hay miles de combinaciones.

    Por eso `tasas_sugeridas` puede estar vacio y `es_cerrado` dice si la lista
    es exhaustiva. Un pais con lista cerrada rechaza lo que no esta; uno abierto
    solo verifica que el numero sea razonable.
    """

    nombre: str                    # "IVA", "Sales tax"
    nombre_plural: str             # para etiquetas de la UI
    tasas_sugeridas: tuple[float, ...] = ()
    es_cerrado: bool = True
    tasa_maxima: float = 100.0

    def validar_tasa(self, valor: float) -> float:
        if valor is None:
            raise ValueError(f"La tasa de {self.nombre} es obligatoria")
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            raise ValueError(f"Tasa de {self.nombre} invalida: {valor!r}")

        if self.es_cerrado:
            if numero not in self.tasas_sugeridas:
                validas = ", ".join(f"{a:g}%" for a in sorted(self.tasas_sugeridas))
                raise ValueError(
                    f"Alicuota de {self.nombre} invalida ({numero:g}). Validas: {validas}"
                )
            return numero

        # Lista abierta: no se puede saber que tasa corresponde, pero si que un
        # numero negativo o absurdo es un error de carga y no una jurisdiccion.
        if numero < 0:
            raise ValueError(f"La tasa de {self.nombre} no puede ser negativa ({numero:g})")
        if numero > self.tasa_maxima:
            raise ValueError(
                f"Tasa de {self.nombre} improbable ({numero:g}%): el maximo aceptado "
                f"es {self.tasa_maxima:g}%. Verifique si cargo la tasa o el importe."
            )
        return numero


@dataclass(frozen=True)
class ReglasDePais:
    """Todo lo que el nucleo necesita saber de un pais."""

    codigo: str                    # ISO 3166-1 alfa-2: "AR", "US"
    nombre: str
    moneda: str                    # ISO 4217: "ARS", "USD"
    locale: str                    # "es-AR", "en-US"
    identificador: IdentificadorFiscal
    impuesto: ReglasDeImpuesto

    # Si un comprobante necesita que un organismo lo autorice ANTES de ser
    # valido. Argentina: si (CAE de ARCA/AFIP). Estados Unidos: no existe nada
    # equivalente, la factura vale por si misma.
    #
    # El nucleo solo pregunta esto para decidir si ofrecer el circuito de
    # autorizacion. NO sabe que es un CAE, ni deberia.
    requiere_autorizacion_fiscal: bool = False

    # Nombre del organismo, solo para los mensajes. Vacio si no aplica.
    organismo_fiscal: str = ""

    # Etiquetas de la division administrativa, que ni siquiera se llama igual.
    etiqueta_region: str = "Provincia"
    etiqueta_codigo_postal: str = "Codigo postal"

    notas: tuple[str, ...] = field(default_factory=tuple)
