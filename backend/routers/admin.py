"""
admin.py - Router para Administración y Dashboard
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, Any

from database import get_db, engine, Base
from dinero import a_centavos, a_pesos
from models import (
    Cliente, Proveedor, StockMercaderia, Caja, Remito, Factura, Usuario,
    Venta, Cobro, Pago, FacturaProveedor, Compra, GastoFactura
)
from routers.auth import require_admin

router = APIRouter()


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    """Obtener datos del dashboard"""
    stock_count = db.query(StockMercaderia).count()
    cliente_count = db.query(Cliente).count()
    prov_count = db.query(Proveedor).count()
    
    total_debe = db.query(Caja).with_entities(func.coalesce(func.sum(Caja.debe), 0)).scalar() or 0
    total_haber = db.query(Caja).with_entities(func.coalesce(func.sum(Caja.haber), 0)).scalar() or 0
    # debe/haber estan en centavos: la resta es exacta, y recien al salir
    # se convierte a pesos para el frontend.
    caja_saldo = int(total_debe) - int(total_haber)
    
    return {
        "stock_count": stock_count,
        "cliente_count": cliente_count,
        "proveedor_count": prov_count,
        "caja_saldo": a_pesos(caja_saldo)
    }


@router.get("/db-info")
def get_db_info(_: Usuario = Depends(require_admin)):
    """Obtener información de la base de datos (solo administrador).

    Revela la ruta del archivo de base de datos y el esquema completo: no debe
    quedar accesible a cualquier usuario.
    """
    return {
        "engine_url": str(engine.url),
        # keys() (KeysView) no es serializable a JSON: hay que materializar la lista.
        "tables": list(Base.metadata.tables.keys())
    }


# NOTA: las rutas con path fijo (/morosos, /resumen) deben declararse ANTES de
# cualquier ruta parametrica del mismo metodo, porque FastAPI resuelve por orden
# de declaracion y el parametro las capturaria.
@router.get("/morosos")
def get_morosos(db: Session = Depends(get_db)):
    """Clientes con saldo pendiente (los consume Admin.showMorosos del frontend)."""
    clientes = (
        db.query(Cliente)
        .filter(Cliente.saldo > 0)
        .order_by(Cliente.saldo.desc())
        .all()
    )
    return [
        {
            "cuit": c.cuit,
            "nombre": c.nombre,
            "telefono": c.telefono or "",
            "saldo": a_pesos(c.saldo),   # centavos -> pesos
        }
        for c in clientes
    ]


@router.get("/resumen")
def get_resumen(fecha_desde: str = None, fecha_hasta: str = None, db: Session = Depends(get_db)):
    """Resumen general por rango de fechas (los consume Admin.calcularResumen)."""

    def _rango(query, columna):
        if fecha_desde:
            query = query.filter(columna >= fecha_desde)
        if fecha_hasta:
            query = query.filter(columna <= fecha_hasta)
        return query

    ventas = _rango(db.query(func.coalesce(func.sum(Factura.total), 0)), Factura.fecha).scalar() or 0
    fact_count = _rango(db.query(func.count(Factura.facturanumero)), Factura.fecha).scalar() or 0
    compras = _rango(
        db.query(func.coalesce(func.sum(FacturaProveedor.total), 0)), FacturaProveedor.fecha
    ).scalar() or 0
    gastos = _rango(
        db.query(func.coalesce(func.sum(GastoFactura.total), 0)), GastoFactura.fecha
    ).scalar() or 0
    cobros = _rango(db.query(func.coalesce(func.sum(Cobro.monto), 0)), Cobro.fecha).scalar() or 0
    pagos = _rango(db.query(func.coalesce(func.sum(Pago.monto), 0)), Pago.fecha).scalar() or 0
    remitos = _rango(db.query(func.count(Remito.id)), Remito.fecha).scalar() or 0

    return {
        # Las sumas las hizo SQLite sobre enteros de centavos: son exactas.
        # Solo la salida se pasa a pesos. factCount y remitos son cantidades.
        "ventas": a_pesos(ventas),
        "factCount": fact_count,
        "compras": a_pesos(compras),
        "gastos": a_pesos(gastos),
        "cobros": a_pesos(cobros),
        "pagos": a_pesos(pagos),
        "remitos": remitos,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
    }


# Mapa tipo -> (modelo, columna PK, columna "titular")
_TIPOS_MOV = {
    "remito": (Remito, "id"),
    "factura": (Factura, "facturanumero"),
    "compra": (FacturaProveedor, "id"),
    "cobro": (Cobro, "ordcobro"),
    "pago": (Pago, "ordpago"),
}


def _modelo_mov(tipo: str):
    if tipo not in _TIPOS_MOV:
        raise HTTPException(status_code=400, detail=f"Tipo de movimiento inválido: {tipo}")
    modelo, pk = _TIPOS_MOV[tipo]
    return modelo, getattr(modelo, pk)


# Columnas de DINERO (centavos) de cada modelo buscable, para traducirlas a
# pesos en la respuesta de /movimientos/{tipo}.
_COLUMNAS_DINERO = {
    "remito": ("total", "iva"),
    "factura": ("subtotal", "iva", "total"),
    "compra": ("subtotal", "iva", "total"),
    "cobro": ("monto",),
    "pago": ("monto",),
}


@router.get("/movimientos/{tipo}")
def buscar_movimientos(tipo: str, numero: str = None, db: Session = Depends(get_db)):
    """Buscar movimientos por tipo y (opcionalmente) numero. Consumido por Admin.buscarMov."""
    modelo, pk_col = _modelo_mov(tipo)
    query = db.query(modelo)
    if numero:
        try:
            query = query.filter(pk_col == int(numero))
        except ValueError:
            raise HTTPException(status_code=400, detail="El número debe ser un valor numérico")
    filas = query.order_by(pk_col.desc()).limit(200).all()

    # Esta ruta no tiene response_model, asi que sin traducir devolveria los
    # centavos crudos y la grilla mostraria los importes multiplicados x100.
    dinero = _COLUMNAS_DINERO.get(tipo, ())
    salida = []
    for fila in filas:
        datos = {col.name: getattr(fila, col.name) for col in fila.__table__.columns}
        for campo in dinero:
            datos[campo] = a_pesos(datos.get(campo))
        salida.append(datos)
    return salida


@router.delete("/movimientos/{tipo}/{mov_id}")
def eliminar_movimiento(
    tipo: str,
    mov_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Eliminar un movimiento revirtiendo stock y saldos asociados."""
    modelo, pk_col = _modelo_mov(tipo)
    registro = db.query(modelo).filter(pk_col == mov_id).first()
    if not registro:
        raise HTTPException(status_code=404, detail=f"{tipo} N° {mov_id} no encontrado")

    if tipo == "remito":
        # Devolver al stock lo entregado y borrar los items del remito.
        for venta in db.query(Venta).filter(Venta.nmov == mov_id).all():
            item = db.query(StockMercaderia).filter(StockMercaderia.codigo == venta.codigo).first()
            if item:
                item.cantidad = (item.cantidad or 0) + (venta.cantidad or 0)
            db.delete(venta)

    elif tipo == "factura":
        # Los remitos vuelven a quedar pendientes de facturacion.
        # No se toca clientes.saldo: la creacion de la factura tampoco lo modifica,
        # revertirlo aca dejaria los saldos descuadrados.
        db.query(Venta).filter(Venta.idfactura == mov_id).update({Venta.idfactura: 0})

    elif tipo == "compra":
        # Descontar del stock lo ingresado y revertir el saldo del proveedor.
        for compra in db.query(Compra).filter(Compra.factprov_id == mov_id).all():
            item = db.query(StockMercaderia).filter(StockMercaderia.codigo == compra.codigo).first()
            if item:
                item.cantidad = (item.cantidad or 0) - (compra.cantidad or 0)
            db.delete(compra)
        proveedor = db.query(Proveedor).filter(Proveedor.cuit == registro.proveedor).first()
        if proveedor:
            proveedor.saldo = (proveedor.saldo or 0) - (registro.total or 0)

    # cobro / pago: solo se borra el registro. Los POST de /api/cobros/ y
    # /api/pagos/ no modifican clientes.saldo ni proveedores.saldo, asi que
    # revertirlos aca introduciria un descuadre.

    db.delete(registro)
    db.commit()
    return {"message": f"{tipo} N° {mov_id} eliminado correctamente"}


@router.post("/reset-db")
def reset_db(
    confirmacion: str = "",
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Resetear la base de datos: BORRA TODO. Solo administrador.

    Antes esta ruta no pedia autenticacion: un unico POST anonimo destruia toda
    la facturacion. Ahora exige ser administrador Y enviar una confirmacion
    explicita, para que no se dispare por accidente ni por un enlace malicioso
    abierto en el navegador de un admin logueado (CSRF).
    """
    if confirmacion != "BORRAR TODOS LOS DATOS":
        raise HTTPException(
            status_code=400,
            detail="Operacion destructiva: repita exactamente confirmacion='BORRAR TODOS LOS DATOS'",
        )
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    # Volver a sembrar usuario administrador, modulos y configuracion.
    # Sin esto la tabla `usuarios` quedaba VACIA y nadie podia volver a entrar:
    # el sistema quedaba inutilizable hasta reiniciar el servidor a mano.
    # (La tabla de auditoria vive en su propio MetaData y no se borra aca: el
    #  historial de quien hizo que debe sobrevivir al borrado de datos.)
    from main import inicializar_datos
    inicializar_datos()

    return {
        "message": "Base de datos reseteada correctamente",
        "aviso": (
            "Se recreo el usuario 'admin' con la contrasena por defecto. "
            "Cambiela antes de volver a usar el sistema."
        ),
        "auditoria_conservada": True,
    }


@router.post("/seed-data")
def seed_data(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Insertar datos de ejemplo (solo administrador).

    Creaba usuarios con contrasenas conocidas (caja1/1234, ventas1/1234) sin
    pedir credenciales: era una puerta de entrada directa.
    """
    import bcrypt
    
    # Usuarios
    users = [
        {"username": "admin", "password": "admin123", "rol": "administrador"},
        {"username": "caja1", "password": "1234", "rol": "caja"},
        {"username": "ventas1", "password": "1234", "rol": "encargado_ventas"}
    ]
    
    for u in users:
        existing = db.query(Usuario).filter(Usuario.username == u["username"]).first()
        if not existing:
            hashed_pw = bcrypt.hashpw(u["password"].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            new_user = Usuario(username=u["username"], password_hash=hashed_pw, rol=u["rol"])
            db.add(new_user)
    
    # Stock
    stock_items = [
        {"codigo": 1, "producto": "Trigo Pan", "cantidad": 5000, "unidad": "Kg", "preven": 150.00, "iva": 10.5, "precom": 100.00},
        {"codigo": 2, "producto": "Maíz", "cantidad": 8000, "unidad": "Kg", "preven": 120.00, "iva": 10.5, "precom": 80.00},
        {"codigo": 3, "producto": "Soja", "cantidad": 3000, "unidad": "Kg", "preven": 280.00, "iva": 10.5, "precom": 200.00},
        {"codigo": 4, "producto": "Girasol", "cantidad": 2000, "unidad": "Kg", "preven": 200.00, "iva": 10.5, "precom": 140.00},
        {"codigo": 5, "producto": "Sorgo", "cantidad": 4000, "unidad": "Kg", "preven": 95.00, "iva": 10.5, "precom": 65.00},
        {"codigo": 6, "producto": "Fertilizante NPK", "cantidad": 500, "unidad": "Kg", "preven": 450.00, "iva": 21, "precom": 320.00},
        {"codigo": 7, "producto": "Herbicida Glifosato", "cantidad": 200, "unidad": "Lt", "preven": 800.00, "iva": 21, "precom": 580.00},
        {"codigo": 8, "producto": "Semilla Trigo Certif.", "cantidad": 1000, "unidad": "Kg", "preven": 350.00, "iva": 10.5, "precom": 250.00}
    ]
    
    # preven/precom estan escritos arriba en PESOS por legibilidad y se
    # convierten a centavos al insertarlos. `iva` es la ALICUOTA (%) y
    # `cantidad` son kilos/litros: ninguno de los dos es dinero.
    for item in stock_items:
        existing = db.query(StockMercaderia).filter(StockMercaderia.codigo == item["codigo"]).first()
        if not existing:
            fila = dict(item)
            fila["preven"] = a_centavos(fila["preven"])
            fila["precom"] = a_centavos(fila["precom"])
            db.add(StockMercaderia(**fila))
    
    # Clientes
    clientes = [
        {"cuit": "20-12345678-9", "nombre": "Juan Pérez - Estancia La Gloria", "domicilio": "Ruta 5 Km 120", "localidad": "Junín", "provincia": "Buenos Aires", "cp": "6000", "telefono": "0236-4441234", "mail": "jperez@mail.com"},
        {"cuit": "30-98765432-1", "nombre": "Cooperativa del Sur", "domicilio": "Av. San Martín 450", "localidad": "Trenque Lauquen", "provincia": "Buenos Aires", "cp": "6400", "telefono": "02392-421000", "mail": "info@coopsur.com"}
    ]
    
    for c in clientes:
        existing = db.query(Cliente).filter(Cliente.cuit == c["cuit"]).first()
        if not existing:
            db.add(Cliente(**c))
    
    # Proveedores
    proveedores = [
        {"cuit": "30-55555555-1", "nombre": "Agroquímicos del Oeste S.A.", "domicilio": "Parque Industrial Lt 8", "localidad": "Pergamino", "provincia": "Buenos Aires", "cp": "2700", "telefono": "02477-430000", "mail": "ventas@aqoeste.com"},
        {"cuit": "30-66666666-2", "nombre": "Semillas del Litoral SRL", "domicilio": "Ruta 12 Km 45", "localidad": "Paraná", "provincia": "Entre Ríos", "cp": "3100", "telefono": "0343-4250000", "mail": "contacto@semlitoral.com"}
    ]
    
    for p in proveedores:
        existing = db.query(Proveedor).filter(Proveedor.cuit == p["cuit"]).first()
        if not existing:
            db.add(Proveedor(**p))
    
    db.commit()
    return {"message": "Datos de ejemplo insertados correctamente"}
