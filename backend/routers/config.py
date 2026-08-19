"""
config.py - Router para la configuración del negocio (clave-valor).

Permite personalizar la instalación para cada comercio/supermercado:
nombre, CUIT, dirección, condición IVA, punto de venta, etc.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict

from database import get_db
from models import Configuracion, Usuario
from errores import ErrorDeNegocio
from paises import (CLAVE_CONFIG_PAIS, PaisNoSoportado, fijar_pais,
                    pais_configurado, reglas)
from schemas import ConfigItem
from routers.auth import require_admin

router = APIRouter()


# Configuración por defecto del negocio.
# Son valores de arranque para que el sistema funcione sin configurar nada; el
# comerciante los reemplaza desde Menú → Configuración del Negocio.
CONFIG_DEFAULT = {
    # Pais de la INSTALACION. De el salen las reglas fiscales: como se valida el
    # identificador (CUIT / EIN), que impuesto se aplica sobre la venta y si un
    # comprobante necesita autorizacion de un organismo. Ver backend/paises/.
    #
    # "AR" por defecto para que toda instalacion que ya existe se comporte
    # exactamente igual que antes sin tocar nada.
    "negocio_pais": "AR",
    "negocio_nombre": "Mi Negocio",
    "negocio_cuit": "",
    "negocio_direccion": "",
    "negocio_localidad": "",
    "negocio_telefono": "",
    "negocio_iva": "Responsable Inscripto",
    "negocio_punto_venta": "0001",
    "negocio_moneda": "ARS",
}


def seed_config(db: Session) -> int:
    """Inserta las claves de configuración por defecto que falten."""
    creados = 0
    for clave, valor in CONFIG_DEFAULT.items():
        existing = db.query(Configuracion).filter(Configuracion.clave == clave).first()
        if not existing:
            db.add(Configuracion(clave=clave, valor=valor))
            creados += 1
    db.commit()
    return creados


@router.get("/")
def obtener_config(db: Session = Depends(get_db)) -> Dict[str, str]:
    """Obtener toda la configuración del negocio como diccionario (público para la UI)."""
    items = db.query(Configuracion).all()
    return {item.clave: item.valor for item in items}


@router.put("/")
def actualizar_config(
    cambios: Dict[str, str],
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Actualizar uno o varios valores de configuración (solo administrador)."""
    # Cambiar el pais cambia como se valida TODO lo que entra despues, asi que
    # se rechaza un pais sin paquete de reglas en vez de guardarlo y que el
    # sistema quede validando con las reglas de otro lado sin avisar.
    nuevo_pais = cambios.get(CLAVE_CONFIG_PAIS)
    if nuevo_pais is not None:
        try:
            reglas(nuevo_pais)
        except PaisNoSoportado as exc:
            raise ErrorDeNegocio("PAIS_NO_SOPORTADO", str(exc))

    for clave, valor in cambios.items():
        item = db.query(Configuracion).filter(Configuracion.clave == clave).first()
        if item:
            item.valor = valor
        else:
            db.add(Configuracion(clave=clave, valor=valor))
    db.commit()

    # El pais se cachea en memoria (lo consultan las validaciones de Pydantic,
    # que no reciben sesion). Si no se refresca aca, el cambio no tiene efecto
    # hasta reiniciar el servidor.
    if nuevo_pais is not None:
        fijar_pais(nuevo_pais)

    return {"message": "Configuración actualizada", "actualizados": len(cambios)}


@router.get("/pais")
def describir_pais() -> Dict[str, object]:
    """Las reglas fiscales vigentes en esta instalación.

    Es lo que necesita el frontend para rotular sus campos —no es lo mismo
    "CUIT" que "EIN", ni "Provincia" que "State"— y lo que necesita un agente
    para saber con qué reglas está operando antes de armar un comprobante.
    """
    p = pais_configurado()
    return {
        "codigo": p.codigo,
        "nombre": p.nombre,
        "moneda": p.moneda,
        "locale": p.locale,
        "identificador": {
            "nombre": p.identificador.nombre,
            "descripcion": p.identificador.descripcion,
            "ejemplo": p.identificador.ejemplo,
        },
        "impuesto": {
            "nombre": p.impuesto.nombre,
            "tasas_sugeridas": list(p.impuesto.tasas_sugeridas),
            "lista_cerrada": p.impuesto.es_cerrado,
        },
        "requiere_autorizacion_fiscal": p.requiere_autorizacion_fiscal,
        "organismo_fiscal": p.organismo_fiscal,
        "etiquetas": {
            "region": p.etiqueta_region,
            "codigo_postal": p.etiqueta_codigo_postal,
        },
        # Los limites conocidos se publican en vez de esconderse: quien opera
        # tiene que saber que la tasa de sales tax la carga a mano.
        "advertencias": list(p.notas),
    }
