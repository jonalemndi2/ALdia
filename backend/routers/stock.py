"""
stock.py - Router CRUD para Stock/Mercadería
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from errores import ErrorDeNegocio
from database import get_db
from dinero import ajustar_por_porcentaje
from migraciones import dependientes
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
        raise ErrorDeNegocio("PRODUCTO_NO_EXISTE", "Producto no encontrado")
    return item


@router.post("/", response_model=StockResponse)
def create_stock(item_data: StockCreate, db: Session = Depends(get_db)):
    existing = db.query(StockMercaderia).filter(StockMercaderia.codigo == item_data.codigo).first()
    if existing:
        raise ErrorDeNegocio("YA_EXISTE", "Ya existe un producto con ese código")
    
    new_item = StockMercaderia(**item_data.model_dump())
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item


@router.put("/{codigo}", response_model=StockResponse)
def update_stock(codigo: int, item_data: StockUpdate, db: Session = Depends(get_db)):
    item = db.query(StockMercaderia).filter(StockMercaderia.codigo == codigo).first()
    if not item:
        raise ErrorDeNegocio("PRODUCTO_NO_EXISTE", "Producto no encontrado")
    
    update_data = item_data.model_dump(exclude_unset=True)
    aumento = update_data.pop("aumento_pct", None)
    if aumento is not None:
        if update_data.get("preven") is not None:
            raise ErrorDeNegocio("DATOS_INVALIDOS", "Indique preven o aumento_pct, no los dos")
        if not item.preven:
            raise ErrorDeNegocio(
                "DATOS_INVALIDOS",
                f"'{item.producto}' no tiene precio de venta: no se le puede aplicar "
                "un aumento porcentual",
            )
        update_data["preven"] = ajustar_por_porcentaje(item.preven, aumento)
    for key, value in update_data.items():
        setattr(item, key, value)
    
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{codigo}")
def delete_stock(codigo: int, db: Session = Depends(get_db)):
    item = db.query(StockMercaderia).filter(StockMercaderia.codigo == codigo).first()
    if not item:
        raise ErrorDeNegocio("PRODUCTO_NO_EXISTE", "Producto no encontrado")
    
    # Un maestro con movimientos NO se borra: su historico es lo que sostiene la
    # cuenta corriente, el libro de IVA y los comprobantes ya emitidos. Ahora eso
    # lo garantiza la base (clave foranea RESTRICT, ver models.py); este control
    # esta antes para poder decir QUE lo impide, en vez de dejar que el motor
    # devuelva un error ilegible.
    usos = dependientes(db, "stockmercaderia", codigo)
    if usos:
        detalle = ", ".join(f"{u['cantidad']} en {u['tabla']}" for u in usos)
        raise ErrorDeNegocio(
            "TIENE_MOVIMIENTOS",
            "No se puede eliminar el producto porque tiene movimientos "
            f"registrados ({detalle}). Los comprobantes ya emitidos no se "
            "pueden dejar sin titular.",
            que="el producto", detalle=detalle,
        )

    db.delete(item)
    db.commit()
    return {"message": "Producto eliminado correctamente"}
