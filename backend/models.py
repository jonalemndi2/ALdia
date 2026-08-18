"""
models.py - Modelos SQLAlchemy de la base de datos SQLite real

CONVENCION DE DINERO
====================
TODO importe se guarda como ENTERO DE CENTAVOS (`Column(Integer)`): $1.234,56
se persiste como 123456. Los Float binarios no representan exactamente los
decimales y el error se acumula (sumar 0,10 diez veces daba 0.9999999999999999,
el IVA 21% de 1.234,56 daba 259.25759999999997), lo que descuadra saldos, caja
y libro de IVA. Ver backend/dinero.py para la capa de conversion y el criterio
de redondeo (ROUND_HALF_UP, una sola vez y explicito).

Lo que NO es dinero y sigue siendo Float:
  * `cantidad` de stock/renglones: puede ser fraccionaria (kilos, litros).
  * `iva` cuando es ALICUOTA (`stockmercaderia.iva`, `compragastos.iva`): es un
    porcentaje (21.0 = 21%). En facturas, remitos y gastos, en cambio, `iva` es
    el IMPORTE liquidado y por lo tanto SI es dinero.
"""
from sqlalchemy import Column, Integer, String, Float, Text, Boolean, ForeignKey, DateTime, func
from database import Base


class Cliente(Base):
    __tablename__ = "clientes"

    cuit = Column(String(20), primary_key=True)
    nombre = Column(String(200), nullable=False)
    domicilio = Column(String(300), default="")
    localidad = Column(String(100), default="")
    provincia = Column(String(50), default="")
    cp = Column(String(10), default="")
    telefono = Column(String(30), default="")
    mail = Column(String(100), default="")
    saldo = Column(Integer, default=0)  # centavos. Positivo = el cliente DEBE
    # Condicion frente al IVA del cliente. Determina si le corresponde factura
    # A, B o C: elegir mal hace que AFIP rechace el comprobante. Ademas, desde
    # la RG 5616 la condicion del receptor es obligatoria en el comprobante.
    # Valores validos en schemas.CONDICIONES_IVA.
    condicion_iva = Column(String(30), default="consumidor_final")


class Proveedor(Base):
    __tablename__ = "proveedores"

    cuit = Column(String(20), primary_key=True)
    nombre = Column(String(200), nullable=False)
    domicilio = Column(String(300), default="")
    localidad = Column(String(100), default="")
    provincia = Column(String(50), default="")
    cp = Column(String(10), default="")
    telefono = Column(String(30), default="")
    mail = Column(String(100), default="")
    saldo = Column(Integer, default=0)  # centavos. Positivo = se le DEBE al proveedor


class StockMercaderia(Base):
    __tablename__ = "stockmercaderia"

    codigo = Column(Integer, primary_key=True)
    producto = Column(String(200), nullable=False)
    cantidad = Column(Float, default=0.0)  # NO es dinero: puede ser fraccionaria (kg, litros)
    unidad = Column(String(10), default="UN")
    preven = Column(Integer, default=0)  # centavos. Precio de venta unitario
    iva = Column(Float, default=21.0)  # ALICUOTA en % (21.0 = 21%), NO es un importe
    precom = Column(Integer, default=0)  # centavos. Precio de compra unitario


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    rol = Column(String(50), nullable=False)


class CDC(Base):
    __tablename__ = "cdc"

    id = Column(Integer, primary_key=True)
    rubro = Column(String(100), nullable=False)
    total = Column(Integer, default=0)  # centavos


class Remito(Base):
    __tablename__ = "remito"

    id = Column(Integer, primary_key=True)
    cliente = Column(String(20))  # FK lógica a clientes.cuit
    fecha = Column(String(10))
    total = Column(Integer, default=0)  # centavos
    iva = Column(Integer, default=0)  # centavos. IMPORTE de IVA liquidado, no la alicuota


class Venta(Base):
    __tablename__ = "ventas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(Integer)  # FK lógica a stockmercaderia.codigo
    producto = Column(String(200))
    cantidad = Column(Float)
    precio = Column(Integer)  # centavos. Precio unitario
    unidad = Column(String(10))
    nmov = Column(Integer)  # FK lógica a remito.id
    idfactura = Column(Integer, default=0)  # FK lógica a facturas.facturanumero
    cliente = Column(String(20))  # FK lógica a clientes.cuit
    fecha = Column(String(10))


class RemEntre(Base):
    __tablename__ = "rementre"

    id = Column(Integer, primary_key=True, autoincrement=True)
    remito = Column(Integer)  # FK lógica a remito.id
    intermediario = Column(String(200))
    cantidad = Column(Float)


class Entrega(Base):
    __tablename__ = "entregas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    remito = Column(Integer)  # FK lógica a remito.id
    detalle = Column(String(500))
    fecha = Column(String(10))


class Factura(Base):
    __tablename__ = "facturas"

    facturanumero = Column(Integer, primary_key=True)
    cliente = Column(String(20))  # FK lógica a clientes.cuit
    fecha = Column(String(10))
    subtotal = Column(Integer, default=0)  # centavos. Neto gravado
    iva = Column(Integer, default=0)  # centavos. IMPORTE de IVA, no la alicuota
    total = Column(Integer, default=0)  # centavos

    # ── Datos fiscales de AFIP (factura electrónica, WSFEv1) ──────────────
    # Quedan en NULL mientras el comprobante no esté autorizado. Se completan
    # únicamente con lo que devuelve AFIP: si no hay CAE, es que AFIP no lo dio.
    # Las columnas se agregan a bases ya existentes desde migraciones.py.
    cae = Column(String(20), default=None)                  # Código de Autorización Electrónico
    cae_vencimiento = Column(String(10), default=None)      # YYYY-MM-DD
    punto_venta = Column(Integer, default=None)             # punto de venta habilitado en AFIP
    tipo_comprobante = Column(Integer, default=None)        # 1=Factura A, 6=B, 11=C...
    resultado = Column(String(1), default=None)             # A aprobado / R rechazado / P parcial
    nro_comprobante_afip = Column(Integer, default=None)    # numeración propia de AFIP
    afip_observaciones = Column(Text, default=None)         # motivo textual informado por AFIP


class FacturaProveedor(Base):
    __tablename__ = "factprov"

    id = Column(Integer, primary_key=True)
    proveedor = Column(String(20))  # FK lógica a proveedores.cuit
    fecha = Column(String(10))
    subtotal = Column(Integer, default=0)  # centavos
    iva = Column(Integer, default=0)  # centavos. IMPORTE de IVA
    total = Column(Integer, default=0)  # centavos


class Compra(Base):
    __tablename__ = "compras"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(Integer)  # FK lógica a stockmercaderia.codigo
    producto = Column(String(200))
    cantidad = Column(Float)
    precio = Column(Integer)  # centavos. Precio unitario de compra
    factprov_id = Column(Integer)  # FK lógica a factprov.id
    fecha = Column(String(10))


class GastoFactura(Base):
    __tablename__ = "gastosfacturas"

    id = Column(Integer, primary_key=True)
    proveedor = Column(String(20))  # FK lógica a proveedores.cuit
    numfactura = Column(String(50), default="")
    fecha = Column(String(10))
    subtotal = Column(Integer, default=0)  # centavos
    iva = Column(Integer, default=0)  # centavos. IMPORTE de IVA
    total = Column(Integer, default=0)  # centavos
    descripcion = Column(String(500), default="")
    cdc = Column(Integer, default=0)  # FK lógica a cdc.id


class CompraGasto(Base):
    __tablename__ = "compragastos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    gastos_id = Column(Integer)  # FK lógica a gastosfacturas.id
    descripcion = Column(String(500))
    monto = Column(Integer, default=0)  # centavos
    iva = Column(Float, default=0.0)  # ALICUOTA en % (21.0 = 21%), NO es un importe


class MovimientoSinImpuestos(Base):
    """Renglones de movimientos sin comprobante fiscal (no gravados).

    Antes esta tabla se llamaba `compranegro`. Se renombro a una terminologia
    neutra y presentable, ya que el sistema se publica como software abierto.
    """
    __tablename__ = "movimientos_sin_impuestos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ref_id = Column(Integer)
    codigo = Column(Integer)  # FK lógica a stockmercaderia.codigo
    producto = Column(String(200))
    cantidad = Column(Float)
    precio = Column(Integer)  # centavos. Precio unitario
    gasto = Column(String(100))


class NNCV(Base):
    __tablename__ = "nncv"

    id = Column(Integer, primary_key=True)
    cliente = Column(String(20))  # FK lógica a clientes.cuit
    descripcion = Column(String(500))
    fecha = Column(String(10))


class NNDV(Base):
    __tablename__ = "nndv"

    id = Column(Integer, primary_key=True)
    cliente = Column(String(20))  # FK lógica a clientes.cuit
    descripcion = Column(String(500))
    fecha = Column(String(10))


class NFAN(Base):
    __tablename__ = "nfan"

    id = Column(Integer, primary_key=True)
    proveedor = Column(String(20))  # FK lógica a proveedores.cuit
    monto = Column(Integer, default=0)  # centavos
    fecha = Column(String(10))
    referencia = Column(String(100), default="")
    descripcion = Column(String(500), default="")


class NDProv(Base):
    __tablename__ = "ndprov"

    id = Column(Integer, primary_key=True)
    proveedor = Column(String(20))  # FK lógica a proveedores.cuit
    monto = Column(Integer, default=0)  # centavos
    fecha = Column(String(10))
    referencia = Column(String(100), default="")
    descripcion = Column(String(500), default="")


class NCP(Base):
    __tablename__ = "ncp"

    id = Column(Integer, primary_key=True)
    proveedor = Column(String(20))  # FK lógica a proveedores.cuit
    fecha = Column(String(10))
    descripcion = Column(String(500), default="")


class Cobro(Base):
    __tablename__ = "cobros"

    ordcobro = Column(Integer, primary_key=True)
    cliente = Column(String(20))  # FK lógica a clientes.cuit
    monto = Column(Integer)  # centavos
    fecha = Column(String(10))
    tipo = Column(String(50))
    referencia = Column(String(100), default="")


class Pago(Base):
    __tablename__ = "pagos"

    ordpago = Column(Integer, primary_key=True)
    proveedor = Column(String(20))  # FK lógica a proveedores.cuit
    monto = Column(Integer)  # centavos
    fecha = Column(String(10))
    tipo = Column(String(50))
    referencia = Column(String(100), default="")


class Caja(Base):
    __tablename__ = "caja"

    id = Column(Integer, primary_key=True, autoincrement=True)
    referencia = Column(String(200), default="")
    fecha = Column(String(10))
    debe = Column(Integer, default=0)  # centavos. Ingreso
    haber = Column(Integer, default=0)  # centavos. Egreso
    descripcion = Column(String(500), default="")


class Chequera(Base):
    __tablename__ = "chequera"

    id = Column(Integer, primary_key=True, autoincrement=True)
    numcheque = Column(String(50), default="")
    tipo = Column(Integer, default=0)  # 0=emitido, 1=cobrado
    monto = Column(Integer, default=0)  # centavos
    vencimiento = Column(String(10), default="")
    banco = Column(String(100), default="")
    cuit = Column(String(20), default="")
    nombre = Column(String(200), default="")
    descripcion = Column(String(500), default="")
    pagado = Column(String(20), default="")


class FacNoRem(Base):
    __tablename__ = "facnorem"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(Integer)  # FK lógica a stockmercaderia.codigo
    producto = Column(String(200))
    cantnoretirada = Column(Float, default=0.0)
    cliente = Column(String(20))  # FK lógica a clientes.cuit
    fecha = Column(String(10))
    nmov = Column(Integer)


class RemNoFac(Base):
    __tablename__ = "remnofac"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(Integer)  # FK lógica a stockmercaderia.codigo
    producto = Column(String(200))
    cantidad = Column(Float)
    cliente = Column(String(20))  # FK lógica a clientes.cuit
    fecha = Column(String(10))
    idfactura = Column(Integer, default=0)
    nmov = Column(Integer)


class ConsCom(Base):
    __tablename__ = "conscom"

    id = Column(Integer, primary_key=True, autoincrement=True)
    factprov_id = Column(Integer)  # FK lógica a factprov.id
    codigo = Column(Integer)  # FK lógica a stockmercaderia.codigo
    producto = Column(String(200))
    cantidad = Column(Float)
    precio = Column(Integer)  # centavos. Precio unitario


class Modulo(Base):
    """Catalogo de modulos del sistema, habilitables por instalacion/licencia.
    Permite vender el sistema con distintos modulos activos por cliente."""
    __tablename__ = "modulos"

    clave = Column(String(50), primary_key=True)       # ej: "caja", "cuentas_corrientes"
    nombre = Column(String(100), nullable=False)        # ej: "Caja"
    descripcion = Column(String(300), default="")
    icono = Column(String(50), default="bi-grid")       # icono bootstrap
    categoria = Column(String(50), default="general")   # ventas, compras, finanzas, admin
    habilitado = Column(Boolean, default=True)           # activo en esta instalacion
    roles = Column(String(400), default="administrador") # CSV de roles con acceso
    orden = Column(Integer, default=0)


class Configuracion(Base):
    """Configuracion clave-valor del negocio (nombre, CUIT, direccion, etc.).
    Permite personalizar la instalacion para cada supermercado."""
    __tablename__ = "configuracion"

    clave = Column(String(60), primary_key=True)
    valor = Column(String(500), default="")
