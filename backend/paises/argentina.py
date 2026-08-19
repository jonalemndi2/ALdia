"""
paises/argentina.py - Reglas fiscales argentinas.

El grueso de la implementacion argentina NO esta aca: la factura electronica
(WSAA, WSFEv1, CAE, QR fiscal) sigue viviendo en backend/afip.py, que son unas
1600 lineas y no tiene sentido mover. Aca esta solo lo que el nucleo pregunta,
mas el interruptor `requiere_autorizacion_fiscal` que le dice al nucleo que ese
circuito existe.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from paises.base import IdentificadorFiscal, ReglasDeImpuesto, ReglasDePais


@dataclass(frozen=True)
class CUIT(IdentificadorFiscal):
    def validar(self, valor: str) -> str:
        """Formato y digito verificador (modulo 11 con pesos fijos).

        Es la misma validacion que ALdia tuvo siempre, movida aca sin cambios:
        un CUIT con el verificador mal es un error de tipeo, y aceptarlo hace
        que AFIP rechace el comprobante mucho despues, cuando ya se emitio.
        """
        if valor is None:
            raise ValueError("El CUIT es obligatorio")

        limpio = re.sub(r"[^0-9]", "", str(valor))
        if not limpio:
            raise ValueError("El CUIT es obligatorio: no puede quedar vacio")
        if len(limpio) != 11:
            raise ValueError(f"El CUIT debe tener 11 digitos (recibido: {len(limpio)})")

        pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
        suma = sum(int(d) * p for d, p in zip(limpio[:10], pesos))
        resto = suma % 11
        verificador = 11 - resto
        if verificador == 11:
            verificador = 0
        elif verificador == 10:
            verificador = 9

        if verificador != int(limpio[10]):
            raise ValueError(
                f"CUIT invalido: el digito verificador no corresponde ({valor})"
            )
        return limpio

    def formatear(self, valor: str) -> str:
        limpio = re.sub(r"[^0-9]", "", str(valor or ""))
        if len(limpio) != 11:
            return valor or ""
        return f"{limpio[:2]}-{limpio[2:10]}-{limpio[10]}"


IVA = ReglasDeImpuesto(
    nombre="IVA",
    nombre_plural="alicuotas de IVA",
    # Conjunto CERRADO: son las alicuotas legales. Cualquier otra es un error de
    # carga que hay que atajar antes de emitir.
    tasas_sugeridas=(0.0, 2.5, 5.0, 10.5, 21.0, 27.0),
    es_cerrado=True,
)

ARGENTINA = ReglasDePais(
    codigo="AR",
    nombre="Argentina",
    moneda="ARS",
    locale="es-AR",
    identificador=CUIT(
        nombre="CUIT",
        descripcion="Clave Unica de Identificacion Tributaria",
        ejemplo="20-12345678-9",
    ),
    impuesto=IVA,
    # ARCA (ex AFIP) tiene que autorizar el comprobante y devolver un CAE antes
    # de que sea valido. Ver backend/afip.py.
    requiere_autorizacion_fiscal=True,
    organismo_fiscal="ARCA (ex AFIP)",
    etiqueta_region="Provincia",
    etiqueta_codigo_postal="Codigo postal",
)
