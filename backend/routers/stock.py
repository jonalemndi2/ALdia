"""
stock.py - Router CRUD para Stock/Mercadería
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import StockMercaderia
from schemas import StockCreate, StockUpdate, StockResponse

router = APIRouter()


@router.get("/", response_model=List[StockResponse])
def get_stock(search: str = None, db: Session = Depends(get_db)):
    query = db.query(StockMercaderia)
    if search:
        query = query.filter(StockMercaderia.producto.ilike(f"%{search}%"))
    return query.all()


@router.get("/{codigo}", response_model=StockResponse)
def get_stock_item(codigo: int, db: Session = Depends(get_db)):
    item = db.query(StockMercaderia).filter(StockMercaderia.codigo == codigo).first()
    if not item:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return item


@router.post("/", response_model=StockResponse)
def create_stock(item_data: StockCreate, db: Session = Depends(get_db)):
    existing = db.query(StockMercaderia).filter(StockMercaderia.codigo == item_data.codigo).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un producto con ese código")
    
    new_item = StockMercaderia(**item_data.model_dump())
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item


@router.put("/{codigo}", response_model=StockResponse)
def update_stock(codigo: int, item_data: StockUpdate, db: Session = Depends(get_db)):
    item = db.query(StockMercaderia).filter(StockMercaderia.codigo == codigo).first()
    if not item:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    update_data = item_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)
    
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{codigo}")
def delete_stock(codigo: int, db: Session = Depends(get_db)):
    item = db.query(StockMercaderia).filter(StockMercaderia.codigo == codigo).first()
    if not item:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    db.delete(item)
    db.commit()
    return {"message": "Producto eliminado correctamente"}
