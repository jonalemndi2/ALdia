"""
proveedores.py - Router CRUD para Proveedores
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import Proveedor
from schemas import ProveedorCreate, ProveedorUpdate, ProveedorResponse

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
    
    db.delete(proveedor)
    db.commit()
    return {"message": "Proveedor eliminado correctamente"}
