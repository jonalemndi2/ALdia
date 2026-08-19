"""
medios_de_pago.py - Con que se cobra y se paga, sin que el router lo adivine.

EL PROBLEMA
===========
Hasta ahora el medio de pago era un texto libre en la columna `tipo`, y quien
decidia que hacer con el era una funcion de dos lineas repetida en dos routers:

    def _es_cheque(tipo: str) -> bool:
        return "cheque" in (tipo or "").strip().lower()

Funciona para "efectivo" y "cheque", y se rompe apenas aparece cualquier otra
cosa. Todo lo que no dijera literalmente "cheque" caia en la misma rama sin que
nadie lo hubiera decidido: una transferencia, una tarjeta y un texto vacio se
trataban igual que el efectivo, por descarte y no por criterio.

Ademas la regla estaba DUPLICADA en cobros.py y en pagos.py, asi que cualquier
medio nuevo habia que acordarse de contemplarlo en los dos lados.

QUE PREGUNTA EL NUCLEO
======================
Lo mismo que con los paises: una interfaz definida por lo que el sistema
necesita saber, y no por lo que cada medio tiene de particular.

  * `entra_a_caja`  -> ¿el importe se asienta en el libro de dinero? El
                       efectivo si. Un cheque NO: es un valor a depositar y por
                       eso va a la chequera.

    LIMITE CONOCIDO, y es una decision deliberada: una transferencia o una
    tarjeta tambien asientan en `caja`, aunque el dinero este en el banco y no
    en el cajon. Corresponderia separarlos, PERO `caja` es hoy el unico libro de
    dinero del sistema --no existe el concepto de cuenta bancaria--, asi que no
    asentarlos ahi los haria desaparecer: la plata entro, el cliente ya no debe,
    y no quedaria registrada en ningun lado. Una caja imprecisa es mucho menos
    grave que plata que no figura.

    El dia que exista un libro de banco, esta es la unica bandera que hay que
    cambiar, y `medios_de_pago.py` es el unico archivo que hay que tocar. Por eso
    la pregunta vive aca y no repartida en los routers.
  * `es_valor`      -> ¿genera un documento que se guarda, endosa o deposita?
                       Solo los cheques.
  * `necesita_referencia` -> ¿sirve de algo el numero suelto? Una transferencia
                       sin comprobante no se puede conciliar despues.

POR QUE LOS CHEQUES NO SE TIRAN
===============================
Es la tentacion obvia al internacionalizar, y esta mal: en Estados Unidos los
cheques comerciales siguen siendo moneda corriente entre empresas. Lo que cambia
no es que existan sino como se llaman y que datos llevan. El modulo de chequera
queda igual; lo que se generaliza es el catalogo que lo alimenta.

Aclaracion que conviene dejar escrita: que un comercio RECIBA un cheque como
pago de una factura no lo convierte en un negocio de cambio de cheques. Son dos
cosas distintas y la segunda tiene regulacion propia; ALdia hace la primera.
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["MedioDePago", "MEDIOS", "medios_de", "resolver", "es_cheque",
           "entra_a_caja", "en_el_banco"]


@dataclass(frozen=True)
class MedioDePago:
    clave: str
    nombre: str
    nombre_en: str
    entra_a_caja: bool
    # El dinero esta en una cuenta y no en el cajon. Hoy solo informativo --se
    # asienta igual, ver el encabezado-- y es el dato que va a necesitar el
    # libro de banco cuando exista.
    en_el_banco: bool = False
    es_valor: bool = False
    necesita_referencia: bool = False
    # Paises donde tiene sentido ofrecerlo. Vacio = en todos.
    paises: tuple[str, ...] = field(default_factory=tuple)

    def disponible_en(self, pais: str) -> bool:
        return not self.paises or pais in self.paises


# El catalogo. `clave` es lo que se guarda en la columna `tipo` y es estable:
# cambiarla rompe los comprobantes ya registrados.
MEDIOS: dict[str, MedioDePago] = {
    "efectivo": MedioDePago(
        clave="efectivo", nombre="Efectivo", nombre_en="Cash",
        entra_a_caja=True,
    ),
    "cheque": MedioDePago(
        clave="cheque", nombre="Cheque", nombre_en="Check",
        # No entra a caja: es un valor a depositar. Va a la chequera.
        entra_a_caja=False, es_valor=True, necesita_referencia=True,
    ),
    "transferencia": MedioDePago(
        clave="transferencia", nombre="Transferencia bancaria",
        nombre_en="Bank transfer",
        # El dinero esta en el banco y no en el cajon, pero se asienta igual:
        # ver el LIMITE CONOCIDO del encabezado. Es el comportamiento que ya
        # tenia el sistema y cambiarlo haria desaparecer la plata del unico
        # libro que hay.
        entra_a_caja=True, en_el_banco=True, necesita_referencia=True,
    ),
    "ach": MedioDePago(
        clave="ach", nombre="ACH", nombre_en="ACH transfer",
        entra_a_caja=True, en_el_banco=True, necesita_referencia=True,
        # La red ACH es estadounidense. En Argentina el equivalente entra por
        # "transferencia".
        paises=("US",),
    ),
    "tarjeta_credito": MedioDePago(
        clave="tarjeta_credito", nombre="Tarjeta de crédito",
        nombre_en="Credit card",
        # El procesador lo acredita dias despues y con retencion, asi que el
        # importe asentado no es lo que finalmente entra. Se marca `en_el_banco`
        # para que un informe futuro pueda separarlo.
        entra_a_caja=True, en_el_banco=True, necesita_referencia=True,
    ),
    "tarjeta_debito": MedioDePago(
        clave="tarjeta_debito", nombre="Tarjeta de débito",
        nombre_en="Debit card",
        entra_a_caja=True, en_el_banco=True, necesita_referencia=True,
    ),
    "otro": MedioDePago(
        clave="otro", nombre="Otro", nombre_en="Other",
        # Se asienta, por el mismo motivo que los demas: que la plata figure.
        entra_a_caja=True,
    ),
}


def medios_de(pais: str) -> list[MedioDePago]:
    """Los medios que tiene sentido ofrecer en ese pais."""
    return [m for m in MEDIOS.values() if m.disponible_en((pais or "").upper())]


def resolver(tipo: str) -> MedioDePago:
    """El medio que corresponde al texto guardado en `tipo`.

    Tolerante a proposito con lo que ya esta en la base: hay instalaciones con
    "Efectivo", "EFECTIVO", "cheque de tercero" y "Cheque 3ros" guardados como
    texto libre desde el sistema anterior. Reinterpretarlos mal cambiaria el
    saldo de caja de comprobantes ya registrados.
    """
    limpio = (tipo or "").strip().lower()
    if not limpio:
        return MEDIOS["otro"]
    if limpio in MEDIOS:
        return MEDIOS[limpio]
    # Coincidencia por contenido, del mas especifico al mas general: "tarjeta de
    # credito" tiene que ganarle a un hipotetico "tarjeta" suelto.
    for clave in ("tarjeta_credito", "tarjeta_debito", "cheque", "transferencia",
                  "ach", "efectivo"):
        medio = MEDIOS[clave]
        if clave.replace("_", " ") in limpio or medio.nombre.lower() in limpio:
            return medio
    if "credito" in limpio or "credit" in limpio:
        return MEDIOS["tarjeta_credito"]
    if "debito" in limpio or "debit" in limpio:
        return MEDIOS["tarjeta_debito"]
    if "cash" in limpio:
        return MEDIOS["efectivo"]
    if "check" in limpio:
        return MEDIOS["cheque"]
    if "transfer" in limpio or "wire" in limpio:
        return MEDIOS["transferencia"]
    return MEDIOS["otro"]


def es_cheque(tipo: str) -> bool:
    """Reemplaza la funcion de dos lineas que estaba repetida en dos routers."""
    return resolver(tipo).es_valor


def entra_a_caja(tipo: str) -> bool:
    """Si el importe se asienta en el libro de dinero. Ver el encabezado."""
    return resolver(tipo).entra_a_caja


def en_el_banco(tipo: str) -> bool:
    """Si el dinero quedo en una cuenta y no en el cajon.

    Hoy no cambia el asiento; existe para que un informe pueda separar "cuanto
    hay en el cajon" de "cuanto entro por banco" sin volver a interpretar textos.
    """
    return resolver(tipo).en_el_banco
