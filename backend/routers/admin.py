"""
admin.py - Router para Administración y Dashboard
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, Any

import saldos
import secuencias
from database import get_db, engine, Base
from dinero import a_centavos, a_pesos
from migraciones import estado_claves_foraneas, verificar_huerfanos
from models import (
    Cliente, Proveedor, StockMercaderia, Caja, Remito, Factura, Usuario,
    Venta, Cobro, Pago, FacturaProveedor, Compra, GastoFactura
)
from routers.auth import current_user_dep, require_admin
from security import exigir_modulo, require_modulo

router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
# CONTROL DE ACCESO DE ESTE ROUTER
#
# main.py lo monta pidiendo solo estar autenticado, porque /dashboard lo
# consulta CUALQUIER usuario al entrar. Eso dejaba sin control TODO lo demas: un
# encargado de deposito, que no tiene acceso al modulo de cuentas corrientes, se
# bajaba con un GET la cartera completa de deudores del comercio -- nombre,
# CUIT, telefono y cuanto debe cada uno.
#
# La regla que se aplica aca es la misma que rige al resto del sistema: cada
# ruta pide el modulo del dato que devuelve, no el de la pantalla desde la que
# se la llama. Las rutas que ademas modifican algo o revelan el esquema siguen
# con require_admin.
# ─────────────────────────────────────────────────────────────────────────────


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

    # Cuanto de ese total esta REALMENTE en el cajon. El resto entro por
    # transferencia o tarjeta y esta en una cuenta: sumarlo al mismo numero hacia
    # que "saldo de caja" no cerrara nunca contra lo que hay al contarlo.
    efectivo = db.query(Caja).with_entities(
        func.coalesce(func.sum(Caja.debe), 0) - func.coalesce(func.sum(Caja.haber), 0)
    ).filter(Caja.cuenta == "efectivo").scalar() or 0
    
    return {
        "stock_count": stock_count,
        "cliente_count": cliente_count,
        "proveedor_count": prov_count,
        # Se conserva el nombre y el significado de siempre --el total-- para no
        # cambiarle el numero a nadie de golpe. La apertura va al lado.
        "caja_saldo": a_pesos(caja_saldo),
        "caja_efectivo": a_pesos(int(efectivo)),
        "caja_banco": a_pesos(caja_saldo - int(efectivo)),
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
@router.get("/morosos", dependencies=[Depends(require_modulo("cuentas_corrientes"))])
def get_morosos(db: Session = Depends(get_db)):
    """Clientes con saldo pendiente (los consume Admin.showMorosos del frontend).

    Exige el modulo de cuentas corrientes, igual que /api/cobros: es el mismo
    dato. Sin esto era la unica puerta del sistema por la que se podia sacar la
    lista de deudores con CUIT, telefono y saldo sin tener acceso al modulo que
    la administra.
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# Verificaciones de consistencia de la base.
#
# Son de SOLO LECTURA y no cambian nada: contestan "lo que dice la base, ¿sigue
# cerrando?". La correccion es un endpoint aparte y explicito (mas abajo), para
# que arreglar un saldo sea siempre una decision de alguien y no un efecto
# colateral de abrir una pantalla.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/verificar-saldos", dependencies=[Depends(require_modulo("administracion"))])
def verificar_saldos(db: Session = Depends(get_db)):
    """Recalcula cada saldo desde los movimientos y lo compara con el guardado.

    `clientes.saldo` y `proveedores.saldo` son datos DERIVADOS que ademas se
    guardan. Este endpoint es lo que impide que se desvien EN SILENCIO: informa
    cada diferencia con nombre, CUIT e importe. Ver backend/saldos.py para la
    definicion exacta del saldo y para el limite conocido del calculo.

    No modifica nada, pero devuelve nombre, CUIT y saldo de cada ficha
    descuadrada: es la misma cartera de clientes que /morosos, mirada desde otro
    lado. Va con el modulo de administracion, el mismo que la pantalla "Estado
    de la Base de Datos" desde la que se consulta.

    Para corregir: POST /api/admin/reparar-saldos.
    """
    informe = saldos.verificar(db)
    return {
        "consistente": informe["consistente"],
        "clientes_revisados": informe["clientes_revisados"],
        "proveedores_revisados": informe["proveedores_revisados"],
        "cantidad_diferencias": informe["cantidad_diferencias"],
        # Los importes salen en PESOS: el contrato de la API con el frontend es
        # en pesos, la base habla en centavos (ver backend/dinero.py).
        "desvio_total": a_pesos(informe["desvio_total"]),
        "diferencias": [
            {
                "tipo": d["tipo"],
                "cuit": d["cuit"],
                "nombre": d["nombre"],
                "saldo_guardado": a_pesos(d["saldo_guardado"]),
                "saldo_calculado": a_pesos(d["saldo_calculado"]),
                "diferencia": a_pesos(d["diferencia"]),
            }
            for d in informe["diferencias"]
        ],
    }


@router.get("/verificar-integridad", dependencies=[Depends(require_modulo("administracion"))])
def verificar_integridad(db: Session = Depends(get_db)):
    """Estado de la integridad referencial y de los numeradores de comprobantes.

    Tres cosas en una sola consulta, que son las tres que pueden estar mal sin
    que se note:

      * si la verificacion de claves foraneas esta realmente ENCENDIDA (SQLite
        la trae apagada: ver database.py),
      * que tablas quedaron sin sus claves foraneas y por que,
      * si hay filas HUERFANAS, o sea que apuntan a un cliente, proveedor o
        articulo que no existe.

    No modifica nada, pero describe el esquema de la base y lista valores reales
    de las filas huerfanas (CUIT de clientes, codigos de articulos). Es
    informacion de mantenimiento, no de operacion: va con el modulo de
    administracion.
    """
    esquema = estado_claves_foraneas(engine)
    huerfanos = verificar_huerfanos(engine)
    return {
        "verificacion_fk_activa": esquema["verificacion_activa"],
        "claves_declaradas": esquema["claves_declaradas"],
        "tablas_con_fk": esquema["tablas_con_fk"],
        "tablas_sin_fk": esquema["tablas_sin_fk"],
        "integra": not huerfanos and not esquema["tablas_sin_fk"],
        "filas_huerfanas": sum(h["filas_huerfanas"] for h in huerfanos),
        "huerfanos": huerfanos,
        "numeradores": secuencias.estado(db),
    }


@router.post("/reparar-saldos")
def reparar_saldos(
    confirmacion: str = "",
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Pisa los saldos guardados con los recalculados. Solo administrador.

    Es explicito a proposito y por partida triple: exige rol administrador, exige
    repetir una confirmacion (para que no lo dispare un enlace abierto por
    descuido en el navegador de un admin logueado), y es un POST separado de la
    verificacion. Corregir un saldo es una decision contable.

    QUEDA REGISTRADO EN LA AUDITORIA sin hacer nada especial: el middleware de
    backend/auditoria.py asienta todo POST a /api/*, y los eventos ORM ya
    observan el campo `saldo` de clientes y proveedores, asi que en el registro
    queda el valor anterior y el nuevo de CADA ficha corregida.
    """
    if confirmacion != "RECALCULAR SALDOS":
        raise HTTPException(
            status_code=400,
            detail=(
                "Esta operacion sobrescribe los saldos de clientes y proveedores. "
                "Repita exactamente confirmacion='RECALCULAR SALDOS'"
            ),
        )
    resultado = saldos.reparar(db)
    db.commit()
    return {
        "message": f"Se corrigieron {resultado['corregidos']} saldo(s)",
        "corregidos": resultado["corregidos"],
        "desvio_corregido": a_pesos(resultado["desvio_corregido"]),
        "detalle": [
            {
                "tipo": d["tipo"],
                "cuit": d["cuit"],
                "nombre": d["nombre"],
                "saldo_anterior": a_pesos(d["saldo_guardado"]),
                "saldo_corregido": a_pesos(d["saldo_calculado"]),
            }
            for d in resultado["detalle"]
        ],
    }


@router.get("/resumen", dependencies=[Depends(require_modulo("administracion"))])
def get_resumen(fecha_desde: str = None, fecha_hasta: str = None, db: Session = Depends(get_db)):
    """Resumen general por rango de fechas (los consume Admin.calcularResumen).

    Devuelve la facturacion, las compras, los gastos y la cobranza del comercio
    en un rango: es el estado del negocio en seis numeros. No es un dato de
    operacion diaria y no corresponde que lo vea cualquier usuario logueado.
    """

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


# A que modulo pertenece cada tipo de comprobante. Es el mismo mapeo que usa
# main.py para los routers propios de cada uno: buscar una factura por aca no
# puede ser mas facil que buscarla en /api/facturas/.
_MODULO_DE_MOV = {
    "remito": "ventas",
    "factura": "ventas",
    "compra": "proveedores",
    "cobro": "cuentas_corrientes",
    "pago": "proveedores",
}


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
def buscar_movimientos(
    tipo: str,
    request: Request,
    numero: str = None,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(current_user_dep),
):
    """Buscar movimientos por tipo y (opcionalmente) numero. Consumido por Admin.buscarMov.

    El modulo que se exige depende del tipo pedido, asi que el control no se
    puede declarar en el decorador: se resuelve adentro con exigir_modulo(). Sin
    el, esta ruta devolvia facturas, cobros y pagos completos a cualquier usuario
    logueado, salteando por completo el permiso de los routers de cada uno.
    """
    modelo, pk_col = _modelo_mov(tipo)
    exigir_modulo(request, db, usuario, _MODULO_DE_MOV[tipo])
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
        # Los remitos vuelven a quedar pendientes de facturacion, y la deuda que
        # la factura genero se cancela.
        #
        # CORRECCION: antes esta rama NO tocaba clientes.saldo, con el comentario
        # de que "la creacion de la factura tampoco lo modifica". Eso dejo de ser
        # cierto (POST /api/facturas/ suma el total al saldo), asi que anular por
        # aca dejaba la deuda viva para siempre mientras anular por
        # DELETE /api/facturas/{n} si la cancelaba: dos caminos para la misma
        # operacion con dos resultados distintos. Ese es exactamente el desvio
        # que ahora detecta GET /api/admin/verificar-saldos.
        db.query(Venta).filter(Venta.idfactura == mov_id).update({Venta.idfactura: 0})
        saldos.aplicar_a_cliente(db, registro.cliente, -(registro.total or 0))

    elif tipo == "compra":
        # Descontar del stock lo ingresado y revertir el saldo del proveedor.
        for compra in db.query(Compra).filter(Compra.factprov_id == mov_id).all():
            item = db.query(StockMercaderia).filter(StockMercaderia.codigo == compra.codigo).first()
            if item:
                item.cantidad = (item.cantidad or 0) - (compra.cantidad or 0)
            db.delete(compra)
        saldos.aplicar_a_proveedor(db, registro.proveedor, -(registro.total or 0))

    elif tipo == "cobro":
        # Anular un cobro devuelve la deuda al cliente (misma regla que
        # DELETE /api/cobros/{n}).
        saldos.aplicar_a_cliente(db, registro.cliente, +(registro.monto or 0))

    elif tipo == "pago":
        # Anular un pago devuelve la deuda con el proveedor.
        saldos.aplicar_a_proveedor(db, registro.proveedor, +(registro.monto or 0))

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
    """Insertar datos de ejemplo para probar el sistema (solo administrador).

    NO CREA USUARIOS, a proposito. Antes daba de alta `caja1/1234` y
    `ventas1/1234`: contrasenas debiles, publicadas en el codigo fuente y sin la
    marca de cambio obligatorio, o sea cuentas permanentes de acceso conocido
    que saltaban por completo el control de `debe_cambiar_password`.

    Los usuarios los crea el administrador desde Menu -> Usuarios, uno por
    persona, y cada uno define su propia contrasena al entrar.

    Los datos de ejemplo son ficticios y estan marcados como tales para que no
    se confundan con clientes reales del comercio.
    """
    
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
    
    # Clientes de ejemplo.
    # Nombres genericos y marcados como EJEMPLO a proposito: los datos anteriores
    # (personas, estancias, cooperativas con telefono y correo) parecian clientes
    # reales de un comercio y no corresponde publicarlos ni que alguien los
    # confunda con su propia cartera. Los CUIT tienen digito verificador valido
    # porque el sistema los valida de verdad.
    clientes = [
        {"cuit": "20123456786", "nombre": "EJEMPLO - Cliente de mostrador",
         "domicilio": "Calle 1 N° 100", "localidad": "Ciudad", "provincia": "Provincia",
         "cp": "1000", "telefono": "", "mail": "", "condicion_iva": "consumidor_final"},
        {"cuit": "30500010912", "nombre": "EJEMPLO - Comercio S.A.",
         "domicilio": "Av. Principal 500", "localidad": "Ciudad", "provincia": "Provincia",
         "cp": "1000", "telefono": "", "mail": "", "condicion_iva": "responsable_inscripto"},
    ]
    
    for c in clientes:
        existing = db.query(Cliente).filter(Cliente.cuit == c["cuit"]).first()
        if not existing:
            db.add(Cliente(**c))
    
    # Proveedores de ejemplo (mismo criterio que los clientes).
    proveedores = [
        {"cuit": "30710120338", "nombre": "EJEMPLO - Distribuidora S.R.L.",
         "domicilio": "Parque Industrial", "localidad": "Ciudad", "provincia": "Provincia",
         "cp": "1000", "telefono": "", "mail": ""},
        {"cuit": "27230938607", "nombre": "EJEMPLO - Mayorista",
         "domicilio": "Ruta 1 Km 10", "localidad": "Ciudad", "provincia": "Provincia",
         "cp": "1000", "telefono": "", "mail": ""},
    ]
    
    for p in proveedores:
        existing = db.query(Proveedor).filter(Proveedor.cuit == p["cuit"]).first()
        if not existing:
            db.add(Proveedor(**p))
    
    db.commit()
    return {"message": "Datos de ejemplo insertados correctamente"}
