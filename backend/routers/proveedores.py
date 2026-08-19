"""
proveedores.py - Router CRUD para Proveedores
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from migraciones import dependientes
from models import Proveedor
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
        raise ErrorDeNegocio("PROVEEDOR_NO_EXISTE", f"No existe el proveedor {cuit}")

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
