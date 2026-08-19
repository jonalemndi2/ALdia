"""
schemas.py - Schemas Pydantic para validación de datos
"""
from pydantic import BaseModel, model_validator, field_validator, Field
from typing import Optional, List

# Capa de dinero: la base guarda CENTAVOS (enteros), la API habla PESOS.
# DineroEntrada convierte pesos -> centavos al validar el pedido;
# DineroSalida convierte centavos -> pesos al serializar la respuesta.
# Toda la conversion vive en dinero.py: aca solo se declara el tipo.
from dinero import (
    DineroEntrada, DineroEntradaOpc, DineroSalida, DineroSalidaOpc,
    multiplicar, aplicar_alicuota,
)
from datetime import datetime
import re


# ==================== VALIDADORES COMUNES ====================
# Los "flags" de validacion: el sistema NO debe guardar comprobantes ni fichas
# con datos fiscales invalidos, porque despues no se pueden facturar ante AFIP
# ni cuadrar contablemente.

# Alicuotas de IVA vigentes en Argentina.
from paises import pais_configurado


# Se conserva por compatibilidad: lo importan pruebas y codigo viejo. La
# lista real de cada pais vive en backend/paises/.
ALICUOTAS_IVA_VALIDAS = {0.0, 2.5, 5.0, 10.5, 21.0, 27.0}


def validar_cuit(cuit: str) -> str:
    """Valida el identificador fiscal segun el pais de la instalacion.

    Se sigue llamando `validar_cuit` porque es el nombre que usan decenas de
    schemas y renombrarlo no aporta nada: lo que cambio es a QUIEN le pregunta.
    En una instalacion argentina hace exactamente lo de siempre --formato y
    digito verificador modulo 11-- y en una estadounidense valida un EIN.

    La implementacion de cada pais vive en backend/paises/.
    """
    return pais_configurado().identificador.validar(cuit)


def validar_texto_obligatorio(valor: str, campo: str) -> str:
    if valor is None or not str(valor).strip():
        raise ValueError(f"{campo} es obligatorio: no puede quedar vacio")
    return str(valor).strip()


def validar_iva(valor: float) -> float:
    """Valida la tasa del impuesto sobre la venta, segun el pais.

    La diferencia entre los dos paises es conceptual y no cosmetica: el IVA
    argentino tiene un conjunto CERRADO de alicuotas legales, asi que una que no
    esta en la lista se rechaza. El sales tax estadounidense depende de la
    jurisdiccion y no hay lista posible, asi que solo se verifica que el numero
    sea plausible. Ver backend/paises/base.py.
    """
    return pais_configurado().impuesto.validar_tasa(valor)


# Condicion frente al IVA. La clave se guarda en la base; el id es el codigo
# que AFIP espera en el campo "Condicion IVA Receptor" (RG 5616).
CONDICIONES_IVA = {
    "responsable_inscripto": {"nombre": "Responsable Inscripto", "afip_id": 1},
    "monotributo":           {"nombre": "Monotributista",        "afip_id": 6},
    "exento":                {"nombre": "IVA Sujeto Exento",     "afip_id": 4},
    "consumidor_final":      {"nombre": "Consumidor Final",      "afip_id": 5},
    "no_responsable":        {"nombre": "IVA No Alcanzado",      "afip_id": 15},
}


def validar_condicion_iva(valor: str) -> str:
    if valor is None or not str(valor).strip():
        return "consumidor_final"
    clave = str(valor).strip().lower().replace(" ", "_")
    if clave not in CONDICIONES_IVA:
        validas = ", ".join(CONDICIONES_IVA)
        raise ValueError(f"Condicion frente al IVA invalida ('{valor}'). Validas: {validas}")
    return clave


# ==================== USUARIOS ====================

# Limite duro de bcrypt: ignora todo lo que pase de 72 bytes y desde la
# version 4 directamente lanza ValueError en vez de truncar en silencio. Una
# passphrase pegada desde un gestor de contrasenas lo pasa sin esfuerzo, y sin
# esta validacion el pedido moria en un 500 -- un error del servidor por un dato
# del usuario, que ademas no explica nada. Se mide en BYTES y no en caracteres
# porque el limite es de bytes: una enie ocupa dos, un emoji cuatro.
MAX_BYTES_PASSWORD = 72


def validar_largo_password(valor: str) -> str:
    if valor is None:
        raise ValueError("La contrasena es obligatoria")
    largo = len(str(valor).encode("utf-8"))
    if largo > MAX_BYTES_PASSWORD:
        raise ValueError(
            f"La contrasena no puede superar los {MAX_BYTES_PASSWORD} bytes "
            f"(la enviada ocupa {largo}). Es el limite del algoritmo bcrypt, no "
            "una eleccion del sistema. Las tildes y la enie ocupan dos bytes "
            "cada una."
        )
    return valor


class UsuarioCreate(BaseModel):
    username: str
    password: str
    rol: str
    # Permiso para operar a nombre de otra persona (cabecera X-Actor-User-ID).
    # Apagado salvo que el administrador lo pida: es para la cuenta de servicio
    # de un agente. Ver security.resolver_actor().
    puede_actuar_por: bool = False

    @field_validator("password")
    @classmethod
    def _password_valida(cls, v):
        return validar_largo_password(v)


class UsuarioResponse(BaseModel):
    id: int
    username: str
    rol: str
    # True mientras el usuario siga con la contrasena inicial: puede iniciar
    # sesion, pero el sistema no lo deja operar hasta que la cambie.
    debe_cambiar_password: bool = False
    # True si esta cuenta puede declarar por quien actua. Se expone para que el
    # administrador vea de un vistazo quien tiene la llave de impersonacion.
    puede_actuar_por: bool = False

    class Config:
        from_attributes = True


class CambioPassword(BaseModel):
    password_actual: str
    password_nueva: str

    @field_validator("password_nueva")
    @classmethod
    def _nueva_valida(cls, v):
        return validar_largo_password(v)


class CambioActuarPor(BaseModel):
    """Alta o baja del permiso de impersonacion sobre una cuenta ya existente."""
    habilitado: bool


# ==================== CLIENTES ====================
class ClienteCreate(BaseModel):
    cuit: str
    nombre: str
    domicilio: str = ""
    localidad: str = ""
    provincia: str = ""
    cp: str = ""
    telefono: str = ""
    mail: str = ""
    condicion_iva: str = "consumidor_final"

    @field_validator("cuit")
    @classmethod
    def _cuit(cls, v):
        return validar_cuit(v)

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, v):
        return validar_texto_obligatorio(v, "El nombre del cliente")

    @field_validator("condicion_iva")
    @classmethod
    def _cond(cls, v):
        return validar_condicion_iva(v)

class ClienteUpdate(BaseModel):
    nombre: Optional[str] = None
    domicilio: Optional[str] = None
    localidad: Optional[str] = None
    provincia: Optional[str] = None
    cp: Optional[str] = None
    telefono: Optional[str] = None
    mail: Optional[str] = None
    condicion_iva: Optional[str] = None

    @field_validator("condicion_iva")
    @classmethod
    def _cond(cls, v):
        return v if v is None else validar_condicion_iva(v)

class ClienteResponse(BaseModel):
    cuit: str
    nombre: str
    domicilio: str
    localidad: str
    provincia: str
    cp: str
    telefono: str
    mail: str
    saldo: DineroSalida
    condicion_iva: Optional[str] = "consumidor_final"

    class Config:
        from_attributes = True


# ==================== PROVEEDORES ====================
class ProveedorCreate(BaseModel):
    cuit: str
    nombre: str
    domicilio: str = ""
    localidad: str = ""
    provincia: str = ""
    cp: str = ""
    telefono: str = ""
    mail: str = ""

    @field_validator("cuit")
    @classmethod
    def _cuit(cls, v):
        return validar_cuit(v)

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, v):
        return validar_texto_obligatorio(v, "El nombre del proveedor")

class ProveedorUpdate(BaseModel):
    nombre: Optional[str] = None
    domicilio: Optional[str] = None
    localidad: Optional[str] = None
    provincia: Optional[str] = None
    cp: Optional[str] = None
    telefono: Optional[str] = None
    mail: Optional[str] = None

class ProveedorResponse(BaseModel):
    cuit: str
    nombre: str
    domicilio: str
    localidad: str
    provincia: str
    cp: str
    telefono: str
    mail: str
    saldo: DineroSalida

    class Config:
        from_attributes = True


# ==================== STOCK ====================
class StockCreate(BaseModel):
    codigo: int
    producto: str
    # Cantidades y precios nunca pueden ser negativos: un stock o un precio en
    # negativo descuadra el inventario y la contabilidad.
    cantidad: float = Field(default=0.0, ge=0)   # NO es dinero: kilos, litros
    unidad: str = "UN"
    preven: DineroEntrada = Field(default=0, ge=0)    # pesos -> centavos
    iva: float = 21.0                                 # ALICUOTA %, no importe
    precom: DineroEntrada = Field(default=0, ge=0)    # pesos -> centavos

    @field_validator("producto")
    @classmethod
    def _producto(cls, v):
        return validar_texto_obligatorio(v, "La descripcion del producto")

    @field_validator("iva")
    @classmethod
    def _iva(cls, v):
        return validar_iva(v)

class StockUpdate(BaseModel):
    producto: Optional[str] = None
    cantidad: Optional[float] = Field(default=None, ge=0)
    unidad: Optional[str] = None
    preven: DineroEntradaOpc = Field(default=None, ge=0)
    iva: Optional[float] = None                       # ALICUOTA %
    precom: DineroEntradaOpc = Field(default=None, ge=0)

    @field_validator("iva")
    @classmethod
    def _iva(cls, v):
        return v if v is None else validar_iva(v)

class StockResponse(BaseModel):
    codigo: int
    producto: str
    cantidad: float
    unidad: str
    preven: DineroSalida
    iva: float          # ALICUOTA %
    precom: DineroSalida

    class Config:
        from_attributes = True


# ==================== FACTURAS ====================
class FacturaItemRef(BaseModel):
    """Linea de una factura.

    Admite dos formas:
    - Con `id`: referencia a un renglon de venta YA existente (viene de un
      remito) que queda asociado a la factura.
    - Sin `id` y con `producto`/`cantidad`/`precio`: renglon NUEVO (factura sin
      entrega). En ese caso el servidor lo crea y descuenta el stock, todo en la
      misma transaccion. Antes esto lo hacia el navegador con GET+PUT sobre
      /stock/, que no era atomico y bajo concurrencia perdia descuentos.
    """
    id: Optional[int] = None
    codigo: Optional[int] = None
    producto: Optional[str] = None
    cantidad: Optional[float] = None
    precio: DineroEntradaOpc = None
    unidad: Optional[str] = None


class FacturaCreate(BaseModel):
    # El frontend (facturas.js) envia "cuit" e "ivaTotal"; se aceptan como alias
    # de "cliente" e "iva" para que el contrato sea compatible en ambos sentidos.
    cliente: Optional[str] = None
    cuit: Optional[str] = None
    fecha: str
    subtotal: DineroEntrada = 0
    iva: DineroEntradaOpc = None        # IMPORTE de IVA, no la alicuota
    ivaTotal: DineroEntradaOpc = None   # alias que manda facturas.js
    total: DineroEntrada = 0
    tipoEmision: Optional[str] = None
    items: List[FacturaItemRef] = []

    @model_validator(mode="after")
    def _normalizar(self):
        if not self.cliente:
            self.cliente = self.cuit
        if not self.cliente:
            raise ValueError("Se requiere 'cliente' (o 'cuit')")
        if self.iva is None:
            self.iva = self.ivaTotal if self.ivaTotal is not None else 0
        return self

class FacturaResponse(BaseModel):
    facturanumero: int
    cliente: str
    fecha: str
    subtotal: DineroSalida
    iva: DineroSalida
    total: DineroSalida
    # Datos fiscales de AFIP. Van en None mientras el comprobante no tenga CAE:
    # ausencia de CAE significa "no autorizado por AFIP", nunca se completa solo.
    cae: Optional[str] = None
    cae_vencimiento: Optional[str] = None
    punto_venta: Optional[int] = None
    tipo_comprobante: Optional[int] = None
    resultado: Optional[str] = None
    nro_comprobante_afip: Optional[int] = None
    afip_observaciones: Optional[str] = None

    class Config:
        from_attributes = True


# ==================== AFIP (factura electrónica) ====================
class SolicitudCAE(BaseModel):
    """Parámetros opcionales del pedido de CAE.

    Si no se envían, se usan los de la configuración (punto de venta y tipo de
    comprobante por defecto) y el CUIT del cliente de la factura.
    """
    tipo_comprobante: Optional[int] = None   # 1=Factura A, 6=B, 11=C, 3=NC A...
    punto_venta: Optional[int] = None
    concepto: Optional[int] = None           # 1=Productos, 2=Servicios, 3=Ambos
    doc_tipo: Optional[int] = None           # 80=CUIT, 96=DNI, 99=Consumidor Final
    doc_nro: Optional[str] = None

    @field_validator("concepto")
    @classmethod
    def _concepto(cls, v):
        if v is not None and v not in (1, 2, 3):
            raise ValueError("Concepto inválido: 1=Productos, 2=Servicios, 3=Productos y Servicios")
        return v


class CAEResponse(BaseModel):
    """Resultado del pedido de CAE tal como lo devolvió AFIP."""
    facturanumero: int
    resultado: str
    cae: str
    cae_vencimiento: str
    punto_venta: int
    tipo_comprobante: int
    nro_comprobante_afip: int
    entorno: str
    observaciones: str = ""
    mensaje: str = ""


# ==================== REMITOS ====================
class RemitoItem(BaseModel):
    """Linea de mercaderia de un remito (se persiste en la tabla ventas)."""
    codigo: int
    producto: str = ""
    cantidad: float = 0.0
    precio: DineroEntrada = 0
    unidad: str = "UN"
    iva: float = 21.0        # ALICUOTA % del renglon, no un importe


class RemitoCreate(BaseModel):
    # El frontend (remitos.js) envia "cliente_cuit" + "items"; se aceptan como
    # alias/extension de "cliente" para que el contrato sea compatible.
    cliente: Optional[str] = None
    cliente_cuit: Optional[str] = None
    fecha: str
    total: DineroEntradaOpc = None   # neto del remito, en centavos
    iva: DineroEntradaOpc = None     # IMPORTE de IVA, en centavos
    intermediario: Optional[str] = None
    observaciones: Optional[str] = None
    items: List[RemitoItem] = []

    @model_validator(mode="after")
    def _normalizar(self):
        if not self.cliente:
            self.cliente = self.cliente_cuit
        if not self.cliente:
            raise ValueError("Se requiere 'cliente' (o 'cliente_cuit')")
        # Aritmetica EN CENTAVOS: `precio` ya llego convertido por
        # DineroEntrada. Cada renglon se redondea UNA sola vez (en
        # multiplicar / aplicar_alicuota) y despues solo se suman enteros,
        # que es exacto. Antes esto se hacia con floats y el remito no
        # cerraba contra la factura que salia de el.
        if self.items:
            lineas = [multiplicar(i.precio, i.cantidad) for i in self.items]
            if self.total is None:
                self.total = sum(lineas)
            if self.iva is None:
                self.iva = sum(
                    aplicar_alicuota(base, item.iva)
                    for base, item in zip(lineas, self.items)
                )
        if self.total is None:
            self.total = 0
        if self.iva is None:
            self.iva = 0
        return self


class RemitoResponse(BaseModel):
    id: int
    cliente: Optional[str]
    fecha: Optional[str]
    total: DineroSalida
    iva: DineroSalida

    class Config:
        from_attributes = True


class RemitoNoFacturadoResponse(BaseModel):
    """Linea de remito sin facturar, tal como la muestra la grilla del frontend."""
    id: Optional[int] = None
    nmov: Optional[int] = None
    codigo: Optional[int] = None
    producto: Optional[str] = None
    cantidad: Optional[float] = None
    precio: DineroSalidaOpc = None
    unidad: Optional[str] = None
    cliente: Optional[str] = None
    fecha: Optional[str] = None

    class Config:
        from_attributes = True


# ==================== VENTAS ====================
class VentaCreate(BaseModel):
    codigo: int
    producto: str
    cantidad: float
    precio: DineroEntrada
    unidad: str
    nmov: int
    idfactura: int = 0
    cliente: str
    fecha: str

class VentaResponse(BaseModel):
    id: int
    codigo: int
    producto: str
    cantidad: float
    precio: DineroSalida
    unidad: str
    nmov: int
    idfactura: int
    cliente: str
    fecha: str

    class Config:
        from_attributes = True


# ==================== COMPRAS / DEVOLUCIONES ====================
class CompraItem(BaseModel):
    codigo: int
    producto: str = ""
    cantidad: float = 0.0
    precio: DineroEntrada = 0


class CompraCreate(BaseModel):
    # Payload que envia proveedores.js (guardarCompra).
    proveedor: Optional[str] = None
    proveedor_cuit: Optional[str] = None
    fecha: str
    num_factura: str = ""
    items: List[CompraItem] = []

    @model_validator(mode="after")
    def _normalizar(self):
        if not self.proveedor:
            self.proveedor = self.proveedor_cuit
        if not self.proveedor:
            raise ValueError("Se requiere 'proveedor' (o 'proveedor_cuit')")
        return self


class DevolucionCreate(BaseModel):
    # Payload que envia proveedores.js (guardarDevolucion).
    proveedor: Optional[str] = None
    proveedor_cuit: Optional[str] = None
    fecha: str
    items: List[CompraItem] = []

    @model_validator(mode="after")
    def _normalizar(self):
        if not self.proveedor:
            self.proveedor = self.proveedor_cuit
        if not self.proveedor:
            raise ValueError("Se requiere 'proveedor' (o 'proveedor_cuit')")
        return self


# ==================== COBROS ====================
class CobroCreate(BaseModel):
    cliente: str
    monto: DineroEntrada = Field(gt=0)
    fecha: str
    tipo: str
    referencia: str = ""
    # Datos del cheque recibido. Se ignoran si el cobro no es con cheque.
    banco: str = ""
    vencimiento: str = ""
    # Si el cobro se hace con un cheque de tercero ya existente en la chequera,
    # su id: se marca como usado para que no se pueda endosar dos veces.
    cheque_id: Optional[int] = None

class CobroResponse(BaseModel):
    ordcobro: int
    cliente: str
    monto: DineroSalida
    fecha: str
    tipo: str
    referencia: str

    class Config:
        from_attributes = True


# ==================== PAGOS ====================
class PagoCreate(BaseModel):
    proveedor: str
    monto: DineroEntrada = Field(gt=0)
    fecha: str
    tipo: str
    referencia: str = ""
    # Datos del cheque propio emitido. Se ignoran si el pago no es con cheque.
    banco: str = ""
    vencimiento: str = ""
    # Si se paga endosando un cheque de tercero ya existente en la chequera,
    # su id: se marca como usado para que no se pueda endosar dos veces.
    cheque_id: Optional[int] = None

class PagoResponse(BaseModel):
    ordpago: int
    proveedor: str
    monto: DineroSalida
    fecha: str
    tipo: str
    referencia: str

    class Config:
        from_attributes = True


# ==================== CAJA ====================
class CajaCreate(BaseModel):
    referencia: str = ""
    fecha: str
    # Un movimiento de caja se registra como ingreso (debe) o egreso (haber),
    # siempre en positivo. Un importe negativo invertiria el signo del asiento
    # y descuadraria el saldo.
    debe: DineroEntrada = Field(default=0, ge=0)
    haber: DineroEntrada = Field(default=0, ge=0)
    descripcion: str = ""

    @model_validator(mode="after")
    def _validar_asiento(self):
        if self.debe == 0 and self.haber == 0:
            raise ValueError("El movimiento debe tener un importe en Debe o en Haber")
        if self.debe > 0 and self.haber > 0:
            raise ValueError("Un movimiento no puede ser ingreso y egreso a la vez")
        return self

class CajaResponse(BaseModel):
    id: int
    referencia: str
    fecha: str
    debe: DineroSalida
    haber: DineroSalida
    descripcion: str

    class Config:
        from_attributes = True


# ==================== GASTOS ====================
class GastoConceptoCreate(BaseModel):
    """Un renglon de la factura de gasto (tabla compragastos)."""
    descripcion: str = ""
    monto: DineroEntrada = Field(default=0, ge=0)   # pesos -> centavos
    iva: float = 0.0                                # ALICUOTA %, la valida validar_iva

    @field_validator("iva")
    @classmethod
    def _iva(cls, v):
        return validar_iva(v)


class GastoCreate(BaseModel):
    proveedor: str
    numfactura: str = ""
    fecha: str
    subtotal: DineroEntrada = Field(default=0, ge=0)
    iva: DineroEntrada = Field(default=0, ge=0)      # IMPORTE de IVA del comprobante
    total: DineroEntrada = Field(default=0, ge=0)
    descripcion: str = ""
    cdc: int = 0
    # Renglones del gasto. Antes se perdian: el detalle se guardaba concatenado
    # como texto en `descripcion` y la tabla compragastos quedaba vacia.
    items: List[GastoConceptoCreate] = []

class GastoResponse(BaseModel):
    id: int
    proveedor: str
    numfactura: str
    fecha: str
    subtotal: DineroSalida
    iva: DineroSalida
    total: DineroSalida
    descripcion: str
    cdc: int

    class Config:
        from_attributes = True


# ==================== LOGIN ====================
class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UsuarioResponse


# ==================== MODULOS ====================
class ModuloBase(BaseModel):
    clave: str
    nombre: str
    descripcion: str = ""
    icono: str = "bi-grid"
    categoria: str = "general"
    habilitado: bool = True
    roles: str = "administrador"
    orden: int = 0

class ModuloUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    icono: Optional[str] = None
    categoria: Optional[str] = None
    habilitado: Optional[bool] = None
    roles: Optional[str] = None
    orden: Optional[int] = None

class ModuloResponse(ModuloBase):
    class Config:
        from_attributes = True


# ==================== CONFIGURACION ====================
class ConfigItem(BaseModel):
    clave: str
    valor: str = ""

class ConfigUpdate(BaseModel):
    valor: str
