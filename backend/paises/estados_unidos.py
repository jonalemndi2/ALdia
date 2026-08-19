"""
paises/estados_unidos.py - Reglas fiscales estadounidenses.

ADVERTENCIA IMPORTANTE SOBRE EL SALES TAX
=========================================
Este paquete NO calcula el sales tax de Estados Unidos. Deja que el comercio
cargue UNA tasa a mano y la aplica. Eso es correcto solo para el caso mas
simple: un comercio con una unica ubicacion, que vende presencialmente, y con
obligacion fiscal (nexus) en una sola jurisdiccion.

Lo que este paquete NO hace, y hace falta para cumplir de verdad:

  * Determinar la jurisdiccion. En EE.UU. el impuesto se compone del estado mas
    condado, ciudad y a veces distritos especiales. Hay del orden de 13.000
    combinaciones y cambian seguido.
  * Decidir el criterio de origen o destino (`sourcing`). Segun el estado, la
    tasa que corresponde es la de donde sale la mercaderia o la de donde llega.
  * Nexus economico. Vender por encima de cierto umbral en otro estado genera
    obligacion de cobrar y declarar ahi, aunque no haya presencia fisica.
  * Categorias exentas o con tasa distinta. Alimentos, ropa y medicamentos
    tributan diferente segun el estado.
  * Certificados de exencion de clientes mayoristas.

Nada de eso se puede codear adentro de ALdia y mantener actualizado. Por eso la
interfaz de impuestos existe: el dia que haga falta cumplimiento real, se
enchufa un proveedor especializado sin tocar el nucleo.

Y hay una tension que conviene tener a la vista antes de enchufarlo: ALdia es
AGPL, corre en la PC del comercio y funciona sin internet — a proposito. Un
proveedor de calculo fiscal es un servicio pago y en linea. La salida sana es
que sea OPCIONAL, con esta tasa manual como respaldo, y no que el sistema deje
de facturar si se cae la conexion.

SOBRE EL EIN
============
El EIN (Employer Identification Number) del IRS son 9 digitos, escritos como
XX-XXXXXXX. A diferencia del CUIT, NO tiene digito verificador: no hay forma de
saber si un EIN es real sin preguntarle al IRS. Lo unico verificable off-line es
el formato y que el prefijo pertenezca a una campana asignada.

Se valida solo eso, y se dice claramente en el mensaje de error. Fingir una
validacion fuerte donde no la hay es peor que no validar: da una confianza que
el dato no merece.

El SSN y el ITIN se usan para personas fisicas y son informacion sensible con
otro tratamiento; este paquete no los contempla todavia a proposito.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from paises.base import IdentificadorFiscal, ReglasDeImpuesto, ReglasDePais

# Prefijos de EIN nunca asignados por el IRS. La lista de prefijos validos
# cambia con el tiempo, asi que se rechaza solo lo que con certeza no existe
# --el 07, 08, 09, 17, 18, 19, 28, 29, 49, 78, 79 y 89 no estan en uso-- en vez
# de mantener una lista blanca que envejece y empieza a rechazar EIN legitimos.
PREFIJOS_INEXISTENTES = frozenset({
    "07", "08", "09", "17", "18", "19", "28", "29", "49", "78", "79", "89",
})


@dataclass(frozen=True)
class EIN(IdentificadorFiscal):
    def validar(self, valor: str) -> str:
        """Formato de 9 digitos y prefijo plausible. NO hay digito verificador."""
        if valor is None:
            raise ValueError("El EIN es obligatorio")

        limpio = re.sub(r"[^0-9]", "", str(valor))
        if not limpio:
            raise ValueError("El EIN es obligatorio: no puede quedar vacio")
        if len(limpio) != 9:
            raise ValueError(
                f"El EIN debe tener 9 digitos, con el formato XX-XXXXXXX "
                f"(recibido: {len(limpio)})"
            )
        if limpio[:2] in PREFIJOS_INEXISTENTES:
            raise ValueError(
                f"EIN invalido: el prefijo {limpio[:2]} no es un rango que el IRS "
                "haya asignado."
            )
        if limpio == "0" * 9:
            raise ValueError("EIN invalido: no puede ser todo ceros")
        return limpio

    def formatear(self, valor: str) -> str:
        limpio = re.sub(r"[^0-9]", "", str(valor or ""))
        if len(limpio) != 9:
            return valor or ""
        return f"{limpio[:2]}-{limpio[2:]}"


SALES_TAX = ReglasDeImpuesto(
    nombre="Sales tax",
    nombre_plural="tasas de sales tax",
    # Sin lista cerrada: la tasa depende de la jurisdiccion. Ver la advertencia
    # del encabezado.
    tasas_sugeridas=(),
    es_cerrado=False,
    # La combinada mas alta del pais ronda el 11-12%. Un 15% de techo deja
    # margen y sigue atajando el error de carga tipico: escribir el importe del
    # impuesto en el campo de la tasa.
    tasa_maxima=15.0,
)

ESTADOS_UNIDOS = ReglasDePais(
    codigo="US",
    nombre="Estados Unidos",
    moneda="USD",
    locale="en-US",
    identificador=EIN(
        nombre="EIN",
        descripcion="Employer Identification Number (IRS)",
        ejemplo="12-3456789",
    ),
    impuesto=SALES_TAX,
    # No existe autorizacion previa de un organismo: la factura vale por si
    # misma. Por eso todo el circuito de CAE queda apagado sin que el nucleo
    # tenga que saber que el CAE existe.
    requiere_autorizacion_fiscal=False,
    organismo_fiscal="",
    etiqueta_region="State",
    etiqueta_codigo_postal="ZIP code",
    notas=(
        "La tasa de sales tax se carga a mano y se aplica igual a todo. Sirve "
        "para un comercio con una sola ubicacion y obligacion en una sola "
        "jurisdiccion. No contempla nexus, sourcing, categorias exentas ni "
        "certificados de exencion.",
    ),
)
