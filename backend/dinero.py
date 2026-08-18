"""
dinero.py - Capa unica de manejo de importes del sistema.

POR QUE EXISTE ESTE ARCHIVO
===========================
Hasta la version anterior todos los importes se guardaban como `Float` (coma
flotante binaria IEEE-754). Eso NO puede representar exactamente valores
decimales como 0.10 o 1234.56, y el error se acumula:

    >>> sum([0.10] * 10)
    0.9999999999999999          # deberia ser 1.00
    >>> 1234.56 * 0.21
    259.25759999999997          # el IVA de una factura real

En un sistema que factura ante AFIP eso descuadra la cuenta corriente, el libro
de IVA y la caja. La solucion es la que usa cualquier sistema contable serio:
guardar el dinero como ENTEROS DE CENTAVOS. $1.234,56 se guarda como el entero
123456. La suma y la resta de enteros son EXACTAS por definicion, asi que
saldos, asientos de caja y totales cierran siempre al centavo.

CRITERIO DE REDONDEO
====================
Se usa ROUND_HALF_UP ("redondeo comercial": el medio centavo va para arriba)
sobre `decimal.Decimal`, y se redondea UNA SOLA VEZ y de forma EXPLICITA, en el
punto donde el importe deja de ser exacto (multiplicacion por cantidad,
aplicacion de una alicuota, conversion de pesos a centavos).

Por que HALF_UP y no el `round()` de Python:

  1. `round()` usa banker's rounding (ROUND_HALF_EVEN): round(0.5) == 0 y
     round(1.5) == 2. Es correcto estadisticamente pero NO es lo que espera un
     contador ni lo que hace la calculadora del cliente, y no es el criterio con
     el que se liquidan los comprobantes.
  2. `round()` opera sobre floats, asi que arrastra el error binario que
     justamente estamos tratando de eliminar: `round(2.675, 2) == 2.67`, porque
     2.675 en binario es 2.67499999999999982236431605997495353221893310546875.

Las conversiones desde `float` se hacen via `Decimal(str(valor))` a proposito:
`str(0.1)` es "0.1", asi que se interpreta el numero DECIMAL que el usuario
escribio y no la basura binaria que hay debajo (Decimal(0.1) daria
0.1000000000000000055511151231257827021181583404541015625).

QUE ES DINERO Y QUE NO
======================
  * Dinero -> entero de centavos: saldos, precios, montos, totales, subtotales,
    importes de IVA, debe/haber de caja, importes de cheques.
  * NO es dinero (siguen siendo float):
      - `cantidad` de stock: puede ser fraccionaria (kilos, litros).
      - `iva` cuando es ALICUOTA (21.0 = 21%): es un porcentaje, no un importe.
        Ojo: `iva` es DINERO en facturas/remitos/gastos (importe liquidado) y es
        ALICUOTA en `stockmercaderia.iva` y en `compragastos.iva`. Confundirlos
        rompe la facturacion.

CONTRATO DE LA API
==================
La base de datos habla en CENTAVOS; la API sigue hablando en PESOS con dos
decimales hacia afuera, para no romper el frontend (Web/js) ni el servidor MCP.
La traduccion es automatica y esta en un solo lugar: los tipos Pydantic
`DineroEntrada` / `DineroSalida` del final de este archivo.
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Annotated, Optional, Union

from pydantic import BeforeValidator, PlainSerializer

__all__ = [
    "a_centavos", "a_centavos_opcional", "a_pesos", "a_pesos_opcional",
    "pesos_decimal", "multiplicar", "aplicar_alicuota", "porcentaje_desde_importes",
    "DineroEntrada", "DineroEntradaOpc", "DineroSalida", "DineroSalidaOpc",
    "CENTAVOS_POR_PESO",
]

CENTAVOS_POR_PESO = Decimal(100)
_UN_ENTERO = Decimal(1)
_DOS_DECIMALES = Decimal("0.01")

Numero = Union[int, float, str, Decimal, None]


def _decimal(valor: Numero, campo: str = "importe") -> Decimal:
    """Convierte cualquier entrada razonable a Decimal SIN perder precision.

    Desde float se pasa por `str()` para leer el decimal que el usuario escribio
    y no su aproximacion binaria (ver la nota de arriba).
    """
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, bool):  # bool es subclase de int: casi seguro es un bug
        raise ValueError(f"{campo}: se recibio un booleano donde va un importe")
    if isinstance(valor, int):
        return Decimal(valor)
    if isinstance(valor, float):
        if valor != valor or valor in (float("inf"), float("-inf")):
            raise ValueError(f"{campo}: importe no numerico ({valor})")
        return Decimal(str(valor))
    if isinstance(valor, str):
        texto = valor.strip().replace(" ", "")
        if not texto:
            raise ValueError(f"{campo}: importe vacio")
        try:
            return Decimal(texto)
        except InvalidOperation:
            raise ValueError(f"{campo}: '{valor}' no es un importe valido")
    raise ValueError(f"{campo}: tipo de importe no soportado ({type(valor).__name__})")


def a_centavos(pesos: Numero, campo: str = "importe") -> int:
    """Pesos -> centavos. Unico punto donde un importe externo se redondea.

        a_centavos(1234.56) -> 123456
        a_centavos(0.005)   -> 1        (medio centavo va para arriba)
        a_centavos("10.10") -> 1010
    """
    if pesos is None:
        raise ValueError(f"{campo}: el importe es obligatorio")
    exacto = _decimal(pesos, campo) * CENTAVOS_POR_PESO
    return int(exacto.quantize(_UN_ENTERO, rounding=ROUND_HALF_UP))


def a_centavos_opcional(pesos: Numero, campo: str = "importe") -> Optional[int]:
    """Igual que `a_centavos` pero deja pasar el None (campos opcionales)."""
    return None if pesos is None else a_centavos(pesos, campo)


def pesos_decimal(centavos: Optional[Union[int, float]]) -> Decimal:
    """Centavos -> Decimal con 2 decimales EXACTOS.

    Es la forma correcta de sacar un importe hacia afuera cuando el destino
    exige precision decimal (AFIP, impresion de comprobantes, comparaciones).
    """
    if centavos is None:
        return Decimal("0.00")
    # Se acepta float por si una base vieja quedo con la columna en REAL: los
    # centavos siempre son enteros, asi que redondear aca no pierde nada.
    entero = int(round(float(centavos))) if isinstance(centavos, float) else int(centavos)
    return (Decimal(entero) / CENTAVOS_POR_PESO).quantize(_DOS_DECIMALES)


def a_pesos(centavos: Optional[Union[int, float]]) -> float:
    """Centavos -> pesos como float de 2 decimales, para serializar en JSON.

    El float de salida es SOLO transporte: 123456 -> 1234.56. Del lado del
    servidor nadie hace aritmetica con este valor.
    """
    return float(pesos_decimal(centavos))


def a_pesos_opcional(centavos) -> Optional[float]:
    return None if centavos is None else a_pesos(centavos)


def multiplicar(precio_centavos: Optional[int], cantidad: Numero) -> int:
    """Importe de un renglon: precio unitario (centavos) x cantidad.

    La cantidad puede ser fraccionaria (2,5 kg), asi que el producto puede caer
    entre dos centavos. Se redondea ACA, una sola vez, con HALF_UP.

        multiplicar(1050, 3)    -> 3150     ($10,50 x 3   = $31,50)
        multiplicar(333, 2.5)   -> 833      ($3,33  x 2,5 = $8,325 -> $8,33)
    """
    if not precio_centavos or cantidad is None:
        return 0
    exacto = Decimal(int(precio_centavos)) * _decimal(cantidad, "cantidad")
    return int(exacto.quantize(_UN_ENTERO, rounding=ROUND_HALF_UP))


def aplicar_alicuota(base_centavos: Optional[int], alicuota_pct: Numero) -> int:
    """IVA (u otra alicuota) sobre una base imponible. Redondeo unico, HALF_UP.

        aplicar_alicuota(123456, 21)   -> 25926    (IVA de $1.234,56 = $259,26)
        aplicar_alicuota(10000, 10.5)  -> 1050

    Con Float esto daba 259.25759999999997, que despues arrastraba el error a
    todos los totales del periodo.
    """
    if not base_centavos or not alicuota_pct:
        return 0
    exacto = (Decimal(int(base_centavos)) * _decimal(alicuota_pct, "alicuota")) / Decimal(100)
    return int(exacto.quantize(_UN_ENTERO, rounding=ROUND_HALF_UP))


def porcentaje_desde_importes(iva_centavos: int, base_centavos: int) -> float:
    """Deduce la alicuota (%) a partir del importe de IVA y la base imponible.

    Se usa solo para comprobantes cargados sin renglones, donde hay que deducir
    que alicuota se aplico. Devuelve float con 2 decimales porque una alicuota
    ES un porcentaje, no dinero.
    """
    if not base_centavos:
        return 0.0
    pct = (Decimal(int(iva_centavos)) * Decimal(100)) / Decimal(int(base_centavos))
    return float(pct.quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Adaptadores Pydantic: la conversion pesos <-> centavos, en un solo lugar.
#
#   DineroEntrada  -> en los schemas *Create / *Update. El JSON trae PESOS
#                     (1234.56) y el modelo queda con CENTAVOS (123456), listo
#                     para asignarse directo a la columna Integer.
#   DineroSalida   -> en los schemas *Response. El atributo del ORM ya viene en
#                     CENTAVOS y se serializa a PESOS al escribir el JSON.
#
# Los constraints de Pydantic (`Field(gt=0)`, `Field(ge=0)`) se evaluan DESPUES
# del BeforeValidator, o sea sobre los centavos: "mayor que 0" sigue
# significando lo mismo, con la ventaja de que ahora rechaza tambien los
# importes que redondean a cero.
# ---------------------------------------------------------------------------

DineroEntrada = Annotated[int, BeforeValidator(a_centavos)]
DineroEntradaOpc = Annotated[Optional[int], BeforeValidator(a_centavos_opcional)]

DineroSalida = Annotated[int, PlainSerializer(a_pesos, return_type=float)]
DineroSalidaOpc = Annotated[
    Optional[int], PlainSerializer(a_pesos_opcional, return_type=Optional[float])
]
