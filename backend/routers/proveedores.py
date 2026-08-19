"""
proveedores.py - Router CRUD para Proveedores
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List

import direcciones
from paises import pais_configurado
from database import get_db
from migraciones import dependientes
from dinero import a_pesos
from models import Pago, Proveedor
from errores import ErrorDeNegocio
from schemas import (ProveedorCreate, ProveedorUpdate, ProveedorResponse,
                     CorreccionIdentificador)

router = APIRouter()


@router.get("/", response_model=List[ProveedorResponse])
def get_proveedores(search: str = None, db: Session = Depends(get_db)):
    query = db.query(Proveedor)
    if search:
        query = query.filter(
            Proveedor.nombre.ilike(f"%{search}%") |
            Proveedor.cuit.ilike(f"%{search}%")
        )
    return query.all()


@router.get("/informe-1099")
def informe_1099(anio: int, db: Session = Depends(get_db)):
    """Cuanto se le pago a cada proveedor en el anio, para preparar los 1099.

    ESTO NO ES UN 1099 NI LO REEMPLAZA
    ----------------------------------
    Es una PLANILLA DE TRABAJO: junta los datos que hay en el sistema para que
    quien liquida no tenga que sacarlos a mano. La declaracion la arma y la
    presenta un contador.

    Generar el formulario de verdad desde aca seria irresponsable: los umbrales,
    que tipo de proveedor queda excluido y los plazos cambian todos los anios, y
    una declaracion presentada mal es peor que no presentarla. Por eso este
    endpoint informa y no emite.

    Lo que el sistema NO puede saber, y por eso viaja en `advertencias`:

      * Si el pago fue por servicios (que se declara) o por mercaderia (que no).
        ALdia registra el importe, no el concepto fiscal.
      * Si el proveedor es una sociedad, que en general queda excluida.
      * Si hubo retenciones.
      * Los pagos hechos por fuera del sistema.

    Solo aparecen los proveedores marcados como elegibles Y con el W-9 recibido.
    Marcar uno sin tener el formulario seria inventarle una declaracion.
    """
    if anio < 2000 or anio > 2100:
        raise ErrorDeNegocio("DATOS_INVALIDOS", f"Anio invalido: {anio}")

    desde, hasta = f"{anio}-01-01", f"{anio}-12-31"
    filas = []
    for prov in db.query(Proveedor).filter(Proveedor.elegible_1099.is_(True)).all():
        total = db.query(func.coalesce(func.sum(Pago.monto), 0)).filter(
            Pago.proveedor == prov.cuit,
            Pago.fecha >= desde, Pago.fecha <= hasta,
        ).scalar() or 0
        if not total:
            continue
        filas.append({
            "proveedor_id": prov.id,
            "nombre": prov.nombre,
            # El IRS pide el nombre legal exacto, que puede no ser el de fantasia.
            "legal_name": prov.legal_name or prov.nombre,
            "dba": prov.dba or "",
            "tax_id": prov.cuit,
            "tax_id_type": prov.tax_id_type,
            "w9_recibido": bool(prov.w9_recibido),
            "w9_fecha": prov.w9_fecha or "",
            "total_pagado": a_pesos(int(total)),
            "direccion": direcciones.una_linea(prov),
            # Sin W-9 no se puede declarar: se lista igual para que se vea que
            # falta pedirlo, en vez de que el proveedor desaparezca del informe.
            "listo_para_declarar": bool(prov.w9_recibido),
        })

    filas.sort(key=lambda f: f["total_pagado"], reverse=True)
    sin_w9 = [f["nombre"] for f in filas if not f["listo_para_declarar"]]

    return {
        "anio": anio,
        "moneda": pais_configurado().moneda,
        "proveedores": filas,
        "sin_w9": sin_w9,
        "advertencias": [
            "Esta planilla NO es un formulario 1099 ni lo reemplaza: la "
            "declaracion la arma y la presenta un contador.",
            "El sistema registra importes, no conceptos fiscales: no puede "
            "distinguir un pago por servicios (declarable) de uno por "
            "mercaderia (no declarable).",
            "No contempla si el proveedor es una sociedad, ni retenciones, ni "
            "pagos hechos por fuera del sistema.",
            "Solo se listan proveedores marcados como elegibles. Marcar uno sin "
            "tener su W-9 seria inventarle una declaracion.",
        ] + ([f"Falta el W-9 de: {', '.join(sin_w9)}"] if sin_w9 else []),
    }


@router.get("/{cuit}", response_model=ProveedorResponse)
def get_proveedor(cuit: str, db: Session = Depends(get_db)):
    proveedor = db.query(Proveedor).filter(Proveedor.cuit == cuit).first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    return proveedor


@router.post("/", response_model=ProveedorResponse)
def create_proveedor(prov_data: ProveedorCreate, db: Session = Depends(get_db)):
    existing = db.query(Proveedor).filter(Proveedor.cuit == prov_data.cuit).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un proveedor con ese CUIT")
    
    new_prov = Proveedor(**prov_data.model_dump())
    # Las columnas de direccion viejas y las internacionales tienen que decir lo
    # mismo mientras convivan. Ver backend/direcciones.py.
    # El tipo de identificador lo decide el pais de la instalacion. Sin esto
    # queda el default de la columna ("CUIT") y una ficha estadounidense dice
    # que su EIN es un CUIT -- que es justo el dato que la columna existe para
    # responder.
    new_prov.tax_id_type = pais_configurado().identificador.nombre
    direcciones.sincronizar(new_prov, pais_configurado().codigo)
    db.add(new_prov)
    db.commit()
    db.refresh(new_prov)
    return new_prov


@router.put("/{cuit}", response_model=ProveedorResponse)
def update_proveedor(cuit: str, prov_data: ProveedorUpdate, db: Session = Depends(get_db)):
    proveedor = db.query(Proveedor).filter(Proveedor.cuit == cuit).first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    
    update_data = prov_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(proveedor, key, value)

    direcciones.sincronizar(proveedor, pais_configurado().codigo)
    db.commit()
    db.refresh(proveedor)
    return proveedor


@router.delete("/{cuit}")
def delete_proveedor(cuit: str, db: Session = Depends(get_db)):
    proveedor = db.query(Proveedor).filter(Proveedor.cuit == cuit).first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    
    # Un maestro con movimientos NO se borra: su historico es lo que sostiene la
    # cuenta corriente, el libro de IVA y los comprobantes ya emitidos. Ahora eso
    # lo garantiza la base (clave foranea RESTRICT, ver models.py); este control
    # esta antes para poder decir QUE lo impide, en vez de dejar que el motor
    # devuelva un error ilegible.
    usos = dependientes(db, "proveedores", cuit)
    if usos:
        detalle = ", ".join(f"{u['cantidad']} en {u['tabla']}" for u in usos)
        raise HTTPException(
            status_code=409,
            detail=(
                "No se puede eliminar el proveedor porque tiene movimientos "
                f"registrados ({detalle}). Los comprobantes ya emitidos no se "
                "pueden dejar sin titular."
            ),
        )

    db.delete(proveedor)
    db.commit()
    return {"message": "Proveedor eliminado correctamente"}


@router.post("/{cuit}/identificacion", response_model=ProveedorResponse)
def corregir_identificador(
    cuit: str,
    datos: CorreccionIdentificador,
    db: Session = Depends(get_db),
):
    """Corregir el identificador fiscal de un proveedor que YA tiene movimientos.

    Mismo problema y misma solucion que en clientes: hasta que la ficha tuvo
    identidad propia, un proveedor cargado con el numero mal quedaba asi para
    siempre --no se podia editar porque era la clave primaria, ni borrar porque
    tenia compras asociadas. El cambio se propaga a compras, pagos y notas de
    credito por ON UPDATE CASCADE.
    """
    proveedor = db.query(Proveedor).filter(Proveedor.cuit == cuit).first()
    if not proveedor:
        raise ErrorDeNegocio("PROVEEDOR_NO_EXISTE", f"No existe el proveedor {cuit}",
                             identificador=cuit)

    nuevo = datos.tax_id
    if nuevo == proveedor.cuit:
        raise ErrorDeNegocio(
            "DATOS_INVALIDOS",
            "El identificador nuevo es igual al actual: no hay nada que corregir.",
        )

    if db.query(Proveedor).filter(Proveedor.cuit == nuevo).first():
        raise ErrorDeNegocio(
            "YA_EXISTE", f"Ya hay otro proveedor con el identificador {nuevo}."
        )

    if datos.confirmar.strip() != nuevo:
        arrastre = dependientes(db, "proveedores", proveedor.cuit)
        detalle = ", ".join(f"{u['cantidad']} en {u['tabla']}" for u in arrastre)
        raise ErrorDeNegocio(
            "CONFIRMACION_REQUERIDA",
            f"Esto cambia el identificador fiscal de '{proveedor.nombre}' "
            f"({proveedor.cuit} -> {nuevo}) en comprobantes YA registrados"
            + (f": {detalle}. " if detalle else ". ")
            + f"Para confirmar, repita el valor nuevo en 'confirmar' "
            f"exactamente como {nuevo}.",
        )

    arrastrados = dependientes(db, "proveedores", proveedor.cuit)
    proveedor.cuit = nuevo
    db.commit()
    db.refresh(proveedor)

    print(f"[proveedores] identificador corregido: {cuit} -> {nuevo} "
          f"({proveedor.nombre}); arrastro {arrastrados}; motivo: {datos.motivo or 's/d'}")
    return proveedor
