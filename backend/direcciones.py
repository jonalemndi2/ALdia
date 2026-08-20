"""
direcciones.py - Una direccion que sirve en cualquier pais.

EL PROBLEMA
===========
El modelo de direccion de ALdia asume Argentina sin decirlo:

    domicilio / localidad / provincia / cp

"Provincia" no existe en Estados Unidos --la division es el estado-- y un
"codigo postal" argentino y un ZIP code no tienen ni el mismo formato ni la
misma funcion. Guardar "FL" en una columna llamada `provincia` anda, y es la
clase de cosa que despues nadie entiende.

EL MODELO NUEVO
===============
El que usa cualquier sistema internacional, y que sirve igual para los dos:

    address_line_1 / address_line_2 / city / region / postal_code / country_code

    Del Campillo, Cordoba, AR      ->  city=Del Campillo region=Cordoba
    Miami, FL, US                    ->  city=Miami          region=FL

POR QUE CONVIVEN LOS DOS
========================
Las columnas viejas NO se borran, y no es pereza: las usa el frontend, las usan
las 44 herramientas del MCP y figuran en los comprobantes ya impresos. Borrarlas
de golpe romperia las tres cosas a la vez.

Asi que se escriben LAS DOS, siempre, desde este unico lugar. Mientras convivan,
la unica forma de que no se contradigan es que nadie las escriba por separado:
si manana alguien actualiza `localidad` sin pasar por aca, la ficha queda con dos
ciudades distintas y gana la que lea quien consulte. Por eso `sincronizar` se
llama desde el alta y desde la modificacion, y no desde el router de turno.

El rename definitivo --tirar las viejas-- es una limpieza posterior que se puede
hacer sin apuro, cuando el frontend y el MCP hablen los nombres nuevos.
"""
from __future__ import annotations

__all__ = ["sincronizar", "como_dict", "una_linea"]

# viejo -> nuevo
EQUIVALENCIAS = (
    ("domicilio", "address_line_1"),
    ("localidad", "city"),
    ("provincia", "region"),
    ("cp", "postal_code"),
)


def sincronizar(ficha, pais_por_defecto: str = "") -> None:
    """Deja las columnas viejas y las nuevas diciendo lo mismo.

    Gana el que tenga dato: si vino por el nombre nuevo se copia al viejo y al
    reves. Si vinieron los dos y difieren, gana el NUEVO, porque es el que
    escribe quien ya conoce el modelo internacional.
    """
    for viejo, nuevo in EQUIVALENCIAS:
        v = (getattr(ficha, viejo, "") or "").strip()
        n = (getattr(ficha, nuevo, "") or "").strip()
        if n:
            setattr(ficha, viejo, n)
        elif v:
            setattr(ficha, nuevo, v)

    # El pais no existia en el modelo viejo: se toma el de la instalacion, que
    # es el correcto para el 99 % de las fichas de un comercio.
    if not (getattr(ficha, "country_code", "") or "").strip():
        ficha.country_code = (pais_por_defecto or "").upper()[:2]


def como_dict(ficha) -> dict:
    return {
        "address_line_1": getattr(ficha, "address_line_1", "") or "",
        "address_line_2": getattr(ficha, "address_line_2", "") or "",
        "city": getattr(ficha, "city", "") or "",
        "region": getattr(ficha, "region", "") or "",
        "postal_code": getattr(ficha, "postal_code", "") or "",
        "country_code": getattr(ficha, "country_code", "") or "",
    }


def una_linea(ficha) -> str:
    """La direccion en una linea, para comprobantes y listados."""
    d = como_dict(ficha)
    partes = [d["address_line_1"], d["address_line_2"], d["city"]]
    cola = " ".join(p for p in (d["region"], d["postal_code"]) if p)
    if cola:
        partes.append(cola)
    return ", ".join(p for p in partes if p)
