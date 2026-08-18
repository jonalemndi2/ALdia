"""
clientes.py - Router CRUD para Clientes
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import Cliente
from schemas import ClienteCreate, ClienteUpdate, ClienteResponse

router = APIRouter()


@router.get("/", response_model=List[ClienteResponse])
def get_clientes(search: str = None, db: Session = Depends(get_db)):
    """Obtener todos los clientes (con búsqueda opcional)"""
    query = db.query(Cliente)
    if search:
        query = query.filter(
            Cliente.nombre.ilike(f"%{search}%") |
            Cliente.cuit.ilike(f"%{search}%")
        )
    return query.all()


@router.get("/{cuit}", response_model=ClienteResponse)
def get_cliente(cuit: str, db: Session = Depends(get_db)):
    """Obtener un cliente por CUIT"""
    cliente = db.query(Cliente).filter(Cliente.cuit == cuit).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente


@router.post("/", response_model=ClienteResponse)
def create_cliente(cliente_data: ClienteCreate, db: Session = Depends(get_db)):
    """Crear nuevo cliente"""
    existing = db.query(Cliente).filter(Cliente.cuit == cliente_data.cuit).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un cliente con ese CUIT")
    
    new_cliente = Cliente(**cliente_data.model_dump())
    db.add(new_cliente)
    db.commit()
    db.refresh(new_cliente)
    return new_cliente


@router.put("/{cuit}", response_model=ClienteResponse)
def update_cliente(cuit: str, cliente_data: ClienteUpdate, db: Session = Depends(get_db)):
    """Actualizar cliente"""
    cliente = db.query(Cliente).filter(Cliente.cuit == cuit).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    update_data = cliente_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(cliente, key, value)
    
    db.commit()
    db.refresh(cliente)
    return cliente


@router.delete("/{cuit}")
def delete_cliente(cuit: str, db: Session = Depends(get_db)):
    """Eliminar cliente"""
    cliente = db.query(Cliente).filter(Cliente.cuit == cuit).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    db.delete(cliente)
    db.commit()
    return {"message": "Cliente eliminado correctamente"}
