"""
dinero.py - Importes en el servidor MCP: centavos enteros, nunca float.

Toda cuenta que REDONDEA la hace el backend: renglones, IVA, porcentajes (ver
backend/dinero.py y backend/importes.py). Este servidor no multiplica ni aplica
alicuotas: pide el calculo (POST /api/facturas/cotizar) o manda los datos y
muestra lo que el backend devolvio.

Aca solo se SUMAN y COMPARAN importes que ya vienen redondeados de la API, y se
normalizan los que escribe el usuario. La API habla en pesos como numeros JSON
con dos decimales (1234.56); pasar ese float por str() da exactamente
"1234.56", asi que llevarlo a centavos es exacto, y sumar centavos enteros
tambien: el resultado es el mismo que obtendria el backend sumando su columna.

Por que importa: 0.1 + 0.2 da 0.30000000000000004 (y acumulado con += el error
crece), y round(2.675, 2) da 2.67. El asistente le lee esos numeros a una
persona que despues los compara contra su resumen del banco.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable

from aldia_mcp.client import ALdiaError

_UN_CENTAVO = Decimal("0.01")


def centavos(valor: Any) -> int:
    """Pesos (numero o texto) -> centavos enteros. Vacio cuenta como 0.

    Mismo criterio que backend/dinero.a_centavos: si viene con mas de dos
    decimales, el medio centavo va para arriba.
    """
    if valor is None or valor == "":
        return 0
    if isinstance(valor, bool):
        raise ALdiaError("Se recibio verdadero/falso donde va un importe.")
    try:
        exacto = Decimal(str(valor).strip()) * 100
    except InvalidOperation:
        raise ALdiaError(f"'{valor}' no es un importe valido.") from None
    if not exacto.is_finite():
        raise ALdiaError(f"'{valor}' no es un importe valido.")
    return int(exacto.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pesos(cantidad_centavos: int) -> float:
    """Centavos -> pesos con dos decimales, para la respuesta JSON (igual que la API)."""
    return float((Decimal(int(cantidad_centavos)) / 100).quantize(_UN_CENTAVO))


def sumar(valores: Iterable[Any]) -> int:
    """Suma exacta, en centavos, de importes en pesos."""
    return sum(centavos(v) for v in valores)


def importe(valor: Any) -> float:
    """Un importe que dio el usuario, con dos decimales, para mandarlo a la API."""
    return pesos(centavos(valor))
