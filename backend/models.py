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

INTEGRIDAD REFERENCIAL
======================
Hasta la version anterior este archivo tenia UNA sola ForeignKey y 28 comentarios
que decian "FK logica": la relacion existia en la cabeza del programador y en el
codigo de los routers, pero no en la base. Eso permitia grabar un remito de un
cliente inexistente (basta un CUIT mal tipeado o un import a medias) y borrar un
cliente dejando sus facturas colgando. Ahora las claves foraneas estan
DECLARADAS y la verificacion esta ENCENDIDA (`PRAGMA foreign_keys=ON` en el
evento `connect` del engine, ver database.py: SQLite la trae apagada).

El comportamiento al borrar se eligio caso por caso, no de forma uniforme:

  * RESTRICT  -> sobre las referencias a MAESTROS (clientes, proveedores,
    articulos). Un cliente con facturas, remitos o cobros NO se puede borrar:
    su historico es justamente lo que da sentido a la cuenta corriente y al
    libro de IVA. La ficha se da de baja logicamente, no se destruye.

  * CASCADE   -> sobre los RENGLONES de un comprobante hacia su cabecera
    (rementre/entregas -> remito, compras -> factprov, compragastos ->
    gastosfacturas, conscom -> factprov). Un renglon no tiene vida propia: no
    significa nada sin su comprobante, y dejarlo suelto es basura que despues
    aparece sumada en un reporte.

RELACIONES QUE A PROPOSITO NO SON ForeignKey
--------------------------------------------
Algunas columnas usan el valor 0 como centinela de "ninguno", herencia del
modelo de Access. Un 0 NO es NULL, asi que una FK las rechazaria en masa:

  * `ventas.nmov`      -> 0 significa "factura sin remito" (ver NMOV_SIN_REMITO).
  * `ventas.idfactura` -> 0 significa "todavia no facturado".
  * `remnofac.idfactura`, `remnofac.nmov`, `facnorem.nmov` -> idem.
  * `gastosfacturas.cdc` -> 0 significa "sin centro de costo".
  * `movimientos_sin_impuestos.ref_id` -> referencia polimorfica, apunta a
    tablas distintas segun el caso.
  * `chequera.cuit` -> puede ser el CUIT de un cliente O de un proveedor.

Convertir esos 0 a NULL es una migracion de datos con riesgo de cambiar el
significado de comprobantes ya emitidos, y el beneficio es chico comparado con
el de las FK que si se declararon. Queda anotado como deuda conocida.
"""
from sqlalchemy import Column, Integer, String, Float, Text, Boolean, ForeignKey, DateTime, func
from database import Base


class Cliente(Base):
    __tablename__ = "clientes"

    # IDENTIDAD SUBROGADA. Antes la clave primaria era el CUIT, y eso tenia una
    # consecuencia que se comia el comercio: un cliente cargado con el numero
    # mal tipeado que YA tenia facturas quedaba con ese numero para siempre. No
    # se podia editar (la identidad no se edita) ni borrar (tiene movimientos).
    #
    # Con un id propio, el identificador fiscal pasa a ser un ATRIBUTO --unico,
    # obligatorio y corregible-- en vez de ser quien es el cliente.
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Sigue llamandose `cuit` porque es el nombre que usan la API, el frontend y
    # las 44 herramientas del MCP; renombrar la columna es mecanico y se hara
    # aparte. Conceptualmente ya NO es "el CUIT": es el identificador fiscal que
    # corresponda al pais de la instalacion (CUIT en Argentina, EIN en Estados
    # Unidos). Ver backend/paises/ y `tax_id_type`.
    cuit = Column(String(20), unique=True, nullable=False)

    # De que tipo es el numero de arriba. Sin esto, una base no sabe decir si
    # "123456789" es un EIN o un CUIT a medio cargar.
    tax_id_type = Column(String(10), default="CUIT", nullable=False)
    nombre = Column(String(200), nullable=False)
    domicilio = Column(String(300), default="")
    localidad = Column(String(100), default="")
    provincia = Column(String(50), default="")
    cp = Column(String(10), default="")
    telefono = Column(String(30), default="")
    mail = Column(String(100), default="")

    # ── Direccion internacional ──────────────────────────────────────────
    # El modelo viejo (domicilio / localidad / provincia / cp) asume Argentina:
    # "provincia" no existe en Estados Unidos, donde la division es el estado, y
    # "codigo postal" y "ZIP code" no tienen el mismo formato.
    #
    # Las columnas viejas NO se borran: las usa el frontend, las usan los
    # comprobantes ya impresos y las usa el MCP. Se pueblan las dos en paralelo
    # (ver `sincronizar_direccion`), y el rename es una limpieza posterior.
    address_line_1 = Column(String(300), default="")
    address_line_2 = Column(String(300), default="")
    city = Column(String(120), default="")
    region = Column(String(80), default="")        # provincia / state
    postal_code = Column(String(20), default="")
    country_code = Column(String(2), default="")   # ISO 3166-1 alfa-2

    # DATO DERIVADO. Es la suma de facturas menos cobros. Se guarda aparte
    # porque listar deudores recalculando cliente por cliente no escala, pero
    # por eso mismo puede desviarse: NO se escribe a mano desde los routers,
    # solo a traves de backend/saldos.py, y hay una verificacion que lo
    # recalcula y compara (GET /api/admin/verificar-saldos).
    saldo = Column(Integer, default=0)  # centavos. Positivo = el cliente DEBE
    # Condicion frente al IVA del cliente. Determina si le corresponde factura
    # A, B o C: elegir mal hace que AFIP rechace el comprobante. Ademas, desde
    # la RG 5616 la condicion del receptor es obligatoria en el comprobante.
    # Valores validos en schemas.CONDICIONES_IVA.
    condicion_iva = Column(String(30), default="consumidor_final")

    @property
    def tax_id(self) -> str:
        """El identificador fiscal, con un nombre que sirve en cualquier pais.

        La columna se sigue llamando `cuit` por compatibilidad con el frontend y
        las herramientas del MCP. Hacia afuera la API expone las dos: `cuit`
        para lo que ya existe y `tax_id` para lo que se escriba de ahora en mas.
        """
        return self.cuit


class Proveedor(Base):
    __tablename__ = "proveedores"

    # Ver la nota de identidad subrogada en Cliente: vale igual aca.
    id = Column(Integer, primary_key=True, autoincrement=True)
    cuit = Column(String(20), unique=True, nullable=False)
    tax_id_type = Column(String(10), default="CUIT", nullable=False)

    # ── Datos que Estados Unidos necesita de un proveedor ────────────────
    # El IRS distingue la razon social de la que el proveedor usa comercialmente
    # (DBA, "doing business as"), y para las declaraciones informativas hay que
    # tener el nombre legal exacto junto con su numero. Se toman del formulario
    # W-9, que es lo que se le pide al proveedor cuando corresponde.
    #
    # DELIBERADAMENTE NO se genera ningun 1099 todavia: eso tiene reglas de
    # umbral, de tipo de proveedor y de plazos que cambian todos los anios, y
    # emitir una declaracion mal es peor que no emitirla. Lo que hay aca es el
    # MODELO PREPARADO para cuando se decida hacerlo bien.
    legal_name = Column(String(200), default="")   # razon social exacta
    dba = Column(String(200), default="")          # nombre de fantasia
    w9_recibido = Column(Boolean, default=False)
    w9_fecha = Column(String(10), default="")
    elegible_1099 = Column(Boolean, default=False)
    nombre = Column(String(200), nullable=False)
    domicilio = Column(String(300), default="")
    localidad = Column(String(100), default="")
    provincia = Column(String(50), default="")
    cp = Column(String(10), default="")
    telefono = Column(String(30), default="")
    mail = Column(String(100), default="")

    # ── Direccion internacional ──────────────────────────────────────────
    # El modelo viejo (domicilio / localidad / provincia / cp) asume Argentina:
    # "provincia" no existe en Estados Unidos, donde la division es el estado, y
    # "codigo postal" y "ZIP code" no tienen el mismo formato.
    #
    # Las columnas viejas NO se borran: las usa el frontend, las usan los
    # comprobantes ya impresos y las usa el MCP. Se pueblan las dos en paralelo
    # (ver `sincronizar_direccion`), y el rename es una limpieza posterior.
    address_line_1 = Column(String(300), default="")
    address_line_2 = Column(String(300), default="")
    city = Column(String(120), default="")
    region = Column(String(80), default="")        # provincia / state
    postal_code = Column(String(20), default="")
    country_code = Column(String(2), default="")   # ISO 3166-1 alfa-2

    # DATO DERIVADO, igual que clientes.saldo. Ver backend/saldos.py.
    saldo = Column(Integer, default=0)  # centavos. Positivo = se le DEBE al proveedor

    @property
    def tax_id(self) -> str:
        """Ver Cliente.tax_id."""
        return self.cuit

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
    # Obliga a cambiar la contrasena antes de poder usar el sistema. Se activa
    # en el admin que se siembra en el primer arranque y en todo usuario nuevo.
    # El caso que evita: la contrasena inicial esta documentada en el README
    # publico, asi que una instalacion que nunca la cambio queda con un acceso
    # conocido por cualquiera. Con esto, quedarse con la de fabrica es imposible.
    debe_cambiar_password = Column(Boolean, default=False, nullable=False)
    # Cuando cambio la contrasena por ultima vez. Es la linea de corte de los
    # tokens: todo JWT emitido ANTES de este instante deja de valer (ver
    # get_current_user en routers/auth.py). Sin esto, cambiar la clave porque
    # alguien la vio no servia de nada -- la sesion que ya la habia usado seguia
    # abierta hasta ocho horas mas. NULL = nunca la cambio desde que existe esta
    # columna, y entonces no hay nada que invalidar.
    password_cambiada_en = Column(DateTime, default=None)
    # Habilita a esta cuenta a declarar `X-Actor-User-ID`, o sea a ejecutar
    # operaciones a nombre de otra persona. APAGADO por defecto y a proposito:
    # es para la cuenta de servicio de un agente, no para una cuenta de persona.
    # Sin este permiso cualquier empleado mandaba la cabecera desde una consola
    # y su operacion quedaba asentada a nombre de un companero.
    puede_actuar_por = Column(Boolean, default=False, nullable=False)


class Secuencia(Base):
    """Numerador de comprobantes. Una fila por tipo, correlativa y sin reuso.

    POR QUE EXISTE
    --------------
    Antes cada router calculaba su numero leyendo el maximo y sumando 1. Eso
    tiene dos fallas distintas, y esta tabla resuelve la segunda (la primera la
    resuelve `BEGIN IMMEDIATE`, ver database.py):

      1. Con dos cajas facturando en el mismo segundo, las dos leen el mismo
         maximo. Medido: de 12 facturas simultaneas entraban 3 y se perdian 9
         con "UNIQUE constraint failed".
      2. `max+1` REUSA numeros. Si se anula la ultima factura, la siguiente sale
         con el numero de la anulada: dos comprobantes distintos con el mismo
         numero fiscal, sin ningun error a la vista. Este es el peor de los dos
         porque no falla, MIENTE. Un contador ya no puede reconstruir la serie.

    El contador vive aparte de la tabla del comprobante, asi que borrar filas no
    lo hace retroceder. Y `ultimo` es editable por el administrador, que es lo
    que hace falta al migrar desde el sistema viejo de VB6/Access para que la
    numeracion CONTINUE en vez de arrancar de 1.

    Ver backend/secuencias.py para el detalle de por que se eligio esto y no el
    autoincrement de SQLite.
    """
    __tablename__ = "secuencias"

    tipo = Column(String(40), primary_key=True)   # "factura", "remito", "cobro"...
    ultimo = Column(Integer, nullable=False, default=0)


class CDC(Base):
    __tablename__ = "cdc"

    id = Column(Integer, primary_key=True)
    rubro = Column(String(100), nullable=False)
    total = Column(Integer, default=0)  # centavos


class Remito(Base):
    __tablename__ = "remito"

    id = Column(Integer, primary_key=True)
    # RESTRICT: un cliente con remitos no se borra.
    cliente = Column(String(20), ForeignKey("clientes.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
    fecha = Column(String(10))
    total = Column(Integer, default=0)  # centavos
    iva = Column(Integer, default=0)  # centavos. IMPORTE de IVA liquidado, no la alicuota


class Venta(Base):
    __tablename__ = "ventas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # RESTRICT: no se borra un articulo que aparece en ventas ya emitidas.
    codigo = Column(Integer, ForeignKey("stockmercaderia.codigo", ondelete="RESTRICT"))
    producto = Column(String(200))
    cantidad = Column(Float)
    precio = Column(Integer)  # centavos. Precio unitario
    unidad = Column(String(10))
    # SIN FK a proposito: 0 = "factura sin remito". Ver encabezado del archivo.
    nmov = Column(Integer)
    # SIN FK a proposito: 0 = "todavia no facturado". Ver encabezado del archivo.
    idfactura = Column(Integer, default=0)
    cliente = Column(String(20), ForeignKey("clientes.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
    fecha = Column(String(10))


class RemEntre(Base):
    __tablename__ = "rementre"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # CASCADE: es un renglon del remito, no sobrevive sin el.
    remito = Column(Integer, ForeignKey("remito.id", ondelete="CASCADE"))
    intermediario = Column(String(200))
    cantidad = Column(Float)


class Entrega(Base):
    __tablename__ = "entregas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # CASCADE: es un renglon del remito.
    remito = Column(Integer, ForeignKey("remito.id", ondelete="CASCADE"))
    detalle = Column(String(500))
    fecha = Column(String(10))


class Factura(Base):
    __tablename__ = "facturas"

    facturanumero = Column(Integer, primary_key=True)
    # RESTRICT: este es el caso del enunciado -- un cliente con facturas NO se
    # puede borrar. Su historico es la cuenta corriente y el libro de IVA.
    cliente = Column(String(20), ForeignKey("clientes.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
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
    proveedor = Column(String(20), ForeignKey("proveedores.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
    fecha = Column(String(10))
    subtotal = Column(Integer, default=0)  # centavos
    iva = Column(Integer, default=0)  # centavos. IMPORTE de IVA
    total = Column(Integer, default=0)  # centavos


class Compra(Base):
    __tablename__ = "compras"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(Integer, ForeignKey("stockmercaderia.codigo", ondelete="RESTRICT"))
    producto = Column(String(200))
    cantidad = Column(Float)
    precio = Column(Integer)  # centavos. Precio unitario de compra
    # CASCADE: renglon de la factura de compra.
    factprov_id = Column(Integer, ForeignKey("factprov.id", ondelete="CASCADE"))
    fecha = Column(String(10))


class GastoFactura(Base):
    __tablename__ = "gastosfacturas"

    id = Column(Integer, primary_key=True)
    proveedor = Column(String(20), ForeignKey("proveedores.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
    numfactura = Column(String(50), default="")
    fecha = Column(String(10))
    subtotal = Column(Integer, default=0)  # centavos
    iva = Column(Integer, default=0)  # centavos. IMPORTE de IVA
    total = Column(Integer, default=0)  # centavos
    descripcion = Column(String(500), default="")
    # SIN FK a proposito: 0 = "sin centro de costo". Ver encabezado del archivo.
    cdc = Column(Integer, default=0)


class CompraGasto(Base):
    __tablename__ = "compragastos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # CASCADE: renglon de la factura de gasto.
    gastos_id = Column(Integer, ForeignKey("gastosfacturas.id", ondelete="CASCADE"))
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
    # SIN FK: referencia polimorfica. Ver encabezado del archivo.
    ref_id = Column(Integer)
    codigo = Column(Integer, ForeignKey("stockmercaderia.codigo", ondelete="RESTRICT"))
    producto = Column(String(200))
    cantidad = Column(Float)
    precio = Column(Integer)  # centavos. Precio unitario
    gasto = Column(String(100))


class NNCV(Base):
    __tablename__ = "nncv"

    id = Column(Integer, primary_key=True)
    cliente = Column(String(20), ForeignKey("clientes.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
    descripcion = Column(String(500))
    fecha = Column(String(10))


class NNDV(Base):
    __tablename__ = "nndv"

    id = Column(Integer, primary_key=True)
    cliente = Column(String(20), ForeignKey("clientes.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
    descripcion = Column(String(500))
    fecha = Column(String(10))


class NFAN(Base):
    __tablename__ = "nfan"

    id = Column(Integer, primary_key=True)
    proveedor = Column(String(20), ForeignKey("proveedores.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
    monto = Column(Integer, default=0)  # centavos
    fecha = Column(String(10))
    referencia = Column(String(100), default="")
    descripcion = Column(String(500), default="")


class NDProv(Base):
    __tablename__ = "ndprov"

    id = Column(Integer, primary_key=True)
    proveedor = Column(String(20), ForeignKey("proveedores.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
    monto = Column(Integer, default=0)  # centavos
    fecha = Column(String(10))
    referencia = Column(String(100), default="")
    descripcion = Column(String(500), default="")


class NCP(Base):
    """Nota de credito de proveedor (devolucion de mercaderia)."""
    __tablename__ = "ncp"

    id = Column(Integer, primary_key=True)
    proveedor = Column(String(20), ForeignKey("proveedores.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
    fecha = Column(String(10))
    descripcion = Column(String(500), default="")
    # Columna NUEVA. Antes una devolucion RESTABA del saldo del proveedor pero
    # solo dejaba un texto: el importe no quedaba en ningun lado, asi que el
    # saldo no se podia recalcular desde los movimientos y toda verificacion de
    # consistencia daba diferencia. Se agrega a bases existentes en
    # migraciones.py (ALTER TABLE ADD COLUMN, seguro).
    monto = Column(Integer, default=0)  # centavos


class Cobro(Base):
    __tablename__ = "cobros"

    ordcobro = Column(Integer, primary_key=True)
    cliente = Column(String(20), ForeignKey("clientes.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
    monto = Column(Integer)  # centavos
    fecha = Column(String(10))
    tipo = Column(String(50))
    referencia = Column(String(100), default="")


class Pago(Base):
    __tablename__ = "pagos"

    ordpago = Column(Integer, primary_key=True)
    proveedor = Column(String(20), ForeignKey("proveedores.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
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

    # DONDE esta ese dinero. Hasta ahora habia una sola cuenta implicita y todo
    # caia en ella: una transferencia recibida sumaba al mismo total que el
    # efectivo, asi que el numero que el duenio lee como "cuanta plata hay en el
    # cajon" incluia plata que estaba en el banco.
    #
    # Las filas que ya existen quedan en "efectivo", que es exactamente como se
    # venian tratando: la migracion no reinterpreta el pasado.
    cuenta = Column(String(20), default="efectivo", nullable=False)


class Chequera(Base):
    __tablename__ = "chequera"

    id = Column(Integer, primary_key=True, autoincrement=True)
    numcheque = Column(String(50), default="")
    tipo = Column(Integer, default=0)  # 0=emitido, 1=cobrado
    monto = Column(Integer, default=0)  # centavos
    vencimiento = Column(String(10), default="")
    banco = Column(String(100), default="")
    # SIN FK: puede ser el CUIT de un cliente O de un proveedor, y ademas un
    # cheque de un tercero que no es ninguno de los dos. Ver encabezado.
    cuit = Column(String(20), default="")
    nombre = Column(String(200), default="")
    descripcion = Column(String(500), default="")
    pagado = Column(String(20), default="")


class FacNoRem(Base):
    __tablename__ = "facnorem"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(Integer, ForeignKey("stockmercaderia.codigo", ondelete="RESTRICT"))
    producto = Column(String(200))
    cantnoretirada = Column(Float, default=0.0)
    cliente = Column(String(20), ForeignKey("clientes.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
    fecha = Column(String(10))
    nmov = Column(Integer)  # SIN FK: centinela 0. Ver encabezado del archivo.


class RemNoFac(Base):
    __tablename__ = "remnofac"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(Integer, ForeignKey("stockmercaderia.codigo", ondelete="RESTRICT"))
    producto = Column(String(200))
    cantidad = Column(Float)
    cliente = Column(String(20), ForeignKey("clientes.cuit", ondelete="RESTRICT", onupdate="CASCADE"))
    fecha = Column(String(10))
    idfactura = Column(Integer, default=0)  # SIN FK: centinela 0.
    nmov = Column(Integer)                  # SIN FK: centinela 0.


class ConsCom(Base):
    __tablename__ = "conscom"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # CASCADE: renglon de la factura de compra.
    factprov_id = Column(Integer, ForeignKey("factprov.id", ondelete="CASCADE"))
    codigo = Column(Integer, ForeignKey("stockmercaderia.codigo", ondelete="RESTRICT"))
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
