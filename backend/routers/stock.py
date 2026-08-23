"""
stock.py - Router CRUD para Stock/Mercadería
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from typing import List
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import hashlib
import json
import uuid

from errores import ErrorDeNegocio
from database import get_db
from migraciones import dependientes
from models import StockMercaderia, ImportacionCatalogo, Usuario
from schemas import StockCreate, StockUpdate, StockResponse
from routers.auth import current_user_dep
from importadores.eikon import leer_lista, hash_preview, ArchivoEikonInvalido

router = APIRouter()


def _solo_deposito(user: Usuario) -> None:
    # El importador cambia catálogo. No es una puerta alternativa para compras,
    # caja ni administración: la cuenta de servicio debe ser acotada.
    if (user.rol or "").lower() != "encargado_deposito":
        raise HTTPException(status_code=403, detail="El importador Eikon requiere rol encargado_deposito")


def _presentar(imp: ImportacionCatalogo) -> dict:
    data = json.loads(imp.resumen_json)
    return {"id": imp.id, "estado": imp.estado, "hash_original": imp.hash_original,
            "preview_hash": imp.hash_preview, "politica": {"precio_origen": imp.precio_origen,
            "tipo_cambio_ars_por_usd": imp.tipo_cambio_ars_por_usd, "fecha_tc": imp.fecha_tc,
            "actualizar_existentes": imp.actualizar_existentes, "cantidad_propia": 0},
            "resumen": data, "creado_en": imp.creado_en, "confirmado_en": imp.confirmado_en}


@router.post("/importaciones/preview")
async def preview_importacion_eikon(
    archivo: UploadFile = File(...), precio_origen: str = Form(...),
    tipo_cambio_ars_por_usd: str = Form(...), fecha_tc: str = Form(...),
    actualizar_existentes: bool = Form(False), cantidad_propia: float = Form(0),
    db: Session = Depends(get_db), user: Usuario = Depends(current_user_dep),
):
    """Valida y muestra diff; deliberadamente no toca stockmercaderia."""
    _solo_deposito(user)
    if cantidad_propia != 0:
        raise HTTPException(status_code=422, detail="Este origen nunca modifica stock propio; cantidad_propia debe ser 0")
    if archivo.content_type not in {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Solo se admite XLSX")
    try:
        tc = Decimal(tipo_cambio_ars_por_usd)
        datetime.strptime(fecha_tc, "%Y-%m-%d")
        datos = await archivo.read()
        filas, errores = leer_lista(datos, precio_origen, tc)
    except (ArchivoEikonInvalido, InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    original = hashlib.sha256(datos).hexdigest()
    politica = {"precio_origen": precio_origen, "tc": str(tc), "fecha_tc": fecha_tc,
                "actualizar_existentes": actualizar_existentes}
    previo = db.query(ImportacionCatalogo).filter(
        ImportacionCatalogo.hash_original == original,
        ImportacionCatalogo.precio_origen == precio_origen,
        ImportacionCatalogo.tipo_cambio_ars_por_usd == str(tc),
        ImportacionCatalogo.fecha_tc == fecha_tc,
        ImportacionCatalogo.actualizar_existentes == actualizar_existentes,
    ).first()
    if previo:
        return _presentar(previo)
    existentes = {p.sku_proveedor: p for p in db.query(StockMercaderia).filter(StockMercaderia.sku_proveedor.isnot(None)).all()}
    altas, cambios, sin_cambio = [], [], []
    for fila in filas:
        item = existentes.get(fila["sku"])
        if not item:
            altas.append(fila["sku"])
        elif (item.producto == fila["producto"] and item.precio_proveedor_usd == fila["precio_usd"]
              and item.stock_proveedor == fila["stock_proveedor"]):
            sin_cambio.append(fila["sku"])
        else:
            cambios.append(fila["sku"])
    resumen = {"total": len(filas), "altas": len(altas), "actualizaciones": len(cambios),
               "sin_cambios": len(sin_cambio), "rechazadas": len(errores),
               "muestras": {"altas": altas[:20], "actualizaciones": cambios[:20], "sin_cambios": sin_cambio[:20]},
               "errores": errores[:100]}
    imp = ImportacionCatalogo(id=str(uuid.uuid4()), hash_original=original,
        hash_preview=hash_preview(filas, politica), usuario=user.username, precio_origen=precio_origen,
        tipo_cambio_ars_por_usd=str(tc), fecha_tc=fecha_tc, actualizar_existentes=actualizar_existentes,
        resumen_json=json.dumps(resumen), filas_json=json.dumps(filas, ensure_ascii=False))
    db.add(imp); db.commit(); db.refresh(imp)
    return _presentar(imp)


@router.get("/importaciones/{importacion_id}")
def obtener_importacion(importacion_id: str, db: Session = Depends(get_db)):
    imp = db.get(ImportacionCatalogo, importacion_id)
    if not imp: raise HTTPException(status_code=404, detail="Importación no encontrada")
    return _presentar(imp)


@router.get("/importaciones/{importacion_id}/errores")
def errores_importacion(importacion_id: str, db: Session = Depends(get_db)):
    imp = db.get(ImportacionCatalogo, importacion_id)
    if not imp: raise HTTPException(status_code=404, detail="Importación no encontrada")
    return {"errores": json.loads(imp.resumen_json).get("errores", [])}


@router.post("/importaciones/{importacion_id}/confirmar")
def confirmar_importacion(importacion_id: str, cuerpo: dict, request: Request,
    db: Session = Depends(get_db), user: Usuario = Depends(current_user_dep)):
    _solo_deposito(user)
    if not request.headers.get("X-Operation-Id"):
        raise HTTPException(status_code=400, detail="X-Operation-Id es obligatorio")
    imp = db.get(ImportacionCatalogo, importacion_id)
    if not imp: raise HTTPException(status_code=404, detail="Importación no encontrada")
    if cuerpo.get("confirmar") is not True or cuerpo.get("preview_hash") != imp.hash_preview:
        raise HTTPException(status_code=409, detail="Preview vencido o confirmación incompleta")
    if imp.estado == "confirmada": return _presentar(imp)
    if imp.estado != "preview": raise HTTPException(status_code=409, detail="Importación no confirmable")
    filas = json.loads(imp.filas_json)
    # Es una sola transacción. Cualquier SKU que colisione o falle aborta TODA
    # la importación; `cantidad` jamás se asigna en este flujo.
    try:
        max_codigo = db.query(StockMercaderia.codigo).order_by(StockMercaderia.codigo.desc()).first()
        siguiente = (max_codigo[0] if max_codigo else 0) + 1
        existentes = {p.sku_proveedor: p for p in db.query(StockMercaderia).filter(StockMercaderia.sku_proveedor.isnot(None)).all()}
        for fila in sorted(filas, key=lambda x: x["sku"]):
            item = existentes.get(fila["sku"])
            if item is None:
                item = StockMercaderia(codigo=siguiente, producto=fila["producto"], cantidad=0.0,
                    preven=fila["precio_ars_centavos"], iva=fila["iva"], sku_proveedor=fila["sku"],
                    categoria_proveedor=fila["categoria"], subcategoria_proveedor=fila["subcategoria"],
                    precio_proveedor_usd=fila["precio_usd"], stock_proveedor=fila["stock_proveedor"],
                    fuente_actualizada_en=datetime.now(timezone.utc))
                siguiente += 1; db.add(item)
            elif not imp.actualizar_existentes:
                continue
            item.producto = fila["producto"]; item.preven = fila["precio_ars_centavos"]; item.iva = fila["iva"]
            item.categoria_proveedor = fila["categoria"]; item.subcategoria_proveedor = fila["subcategoria"]
            item.precio_proveedor_usd = fila["precio_usd"]; item.stock_proveedor = fila["stock_proveedor"]
            item.fuente_actualizada_en = datetime.now(timezone.utc)
        imp.estado = "confirmada"; imp.confirmado_en = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback(); raise
    return _presentar(imp)


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
