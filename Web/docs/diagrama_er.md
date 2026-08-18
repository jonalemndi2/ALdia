# Diagrama ER - ALdia (SQLite)
# Base de datos en memoria con sql.js, persistida en localStorage como "aldia_db"

erDiagram

    %% ==========================================
    %% ENTIDADES PRINCIPALES
    %% ==========================================

    clientes {
        TEXT cuit PK "CUIT del cliente"
        TEXT nombre "Razón social"
        TEXT domicilio "Dirección"
        TEXT localidad "Ciudad"
        TEXT provincia "Provincia"
        TEXT cp "Código postal"
        TEXT telefono "Teléfono"
        TEXT mail "Email"
        REAL saldo "Saldo adeudado"
    }

    proveedores {
        TEXT cuit PK "CUIT del proveedor"
        TEXT nombre "Razón social"
        TEXT domicilio "Dirección"
        TEXT localidad "Ciudad"
        TEXT provincia "Provincia"
        TEXT cp "Código postal"
        TEXT telefono "Teléfono"
        TEXT mail "Email"
        REAL saldo "Saldo adeudado"
    }

    stockmercaderia {
        INTEGER codigo PK "Código producto"
        TEXT producto "Nombre del producto"
        REAL cantidad "Stock actual (Kg/Lt/UN)"
        TEXT unidad "Unidad de medida"
        REAL preven "Precio de venta"
        REAL iva "Alícuota IVA %"
        REAL precom "Precio de compra"
    }

    usuarios {
        INTEGER id PK "ID autoincremental"
        TEXT username UK "Nombre de usuario"
        TEXT password "Contraseña (texto plano)"
        TEXT rol "administrador, caja, ventas..."
    }

    cdc {
        INTEGER id PK "Centro de Costo ID"
        TEXT rubro "Administración, Logística..."
        REAL total "Total acumulado"
    }

    %% ==========================================
    %% REMITOS Y VENTAS
    %% ==========================================

    remito {
        INTEGER id PK "N° de Remito"
        TEXT cliente FK "CUIT del cliente"
        TEXT fecha "Fecha emisión"
        REAL total "Total del remito"
        REAL iva "IVA del remito"
    }

    ventas {
        INTEGER id PK "ID autoincremental"
        INTEGER codigo FK "Código producto"
        TEXT producto "Nombre producto"
        REAL cantidad "Cantidad vendida"
        REAL precio "Precio unitario"
        TEXT unidad "Unidad de medida"
        INTEGER nmov FK "N° de remito"
        INTEGER idfactura FK "N° factura (0=pendiente)"
        TEXT cliente FK "CUIT del cliente"
        TEXT fecha "Fecha venta"
    }

    rementre {
        INTEGER id PK "ID autoincremental"
        INTEGER remito FK "N° de remito"
        TEXT intermediario "Intermediario"
        REAL cantidad "Cantidad entregada"
    }

    entregas {
        INTEGER id PK "ID autoincremental"
        INTEGER remito FK "N° de remito"
        TEXT detalle "Detalle entrega"
        TEXT fecha "Fecha entrega"
    }

    %% ==========================================
    %% FACTURAS DE CLIENTES
    %% ==========================================

    facturas {
        INTEGER facturanumero PK "N° de Factura"
        TEXT cliente FK "CUIT del cliente"
        TEXT fecha "Fecha emisión"
        REAL subtotal "Subtotal sin IVA"
        REAL iva "Monto IVA"
        REAL total "Total factura"
    }

    nncv {
        INTEGER id PK "Nota de Crédito Venta ID"
        TEXT cliente FK "CUIT del cliente"
        TEXT descripcion "Motivo"
        TEXT fecha "Fecha emisión"
    }

    nndv {
        INTEGER id PK "Nota de Débito Venta ID"
        TEXT cliente FK "CUIT del cliente"
        TEXT descripcion "Motivo"
        TEXT fecha "Fecha emisión"
    }

    %% ==========================================
    %% FACTURAS DE PROVEEDORES Y COMPRAS
    %% ==========================================

    factprov {
        INTEGER id PK "N° Factura Proveedor"
        TEXT proveedor FK "CUIT del proveedor"
        TEXT fecha "Fecha factura"
        REAL subtotal "Subtotal sin IVA"
        REAL iva "Monto IVA"
        REAL total "Total factura"
    }

    compras {
        INTEGER id PK "ID autoincremental"
        INTEGER codigo FK "Código producto"
        TEXT producto "Nombre producto"
        REAL cantidad "Cantidad comprada"
        REAL precio "Precio unitario"
        INTEGER factprov_id FK "N° factura proveedor"
        TEXT fecha "Fecha compra"
    }

    conscom {
        INTEGER id PK "ID autoincremental"
        INTEGER factprov_id FK "N° factura proveedor"
        INTEGER codigo FK "Código producto"
        TEXT producto "Nombre producto"
        REAL cantidad "Cantidad"
        REAL precio "Precio unitario"
    }

    nfan {
        INTEGER id PK "Nota Débito Proveedor ID"
        TEXT proveedor FK "CUIT del proveedor"
        REAL monto "Monto nota"
        TEXT fecha "Fecha emisión"
        TEXT referencia "Referencia"
        TEXT descripcion "Descripción"
    }

    ndprov {
        INTEGER id PK "Nota Crédito Proveedor ID"
        TEXT proveedor FK "CUIT del proveedor"
        REAL monto "Monto nota"
        TEXT fecha "Fecha emisión"
        TEXT referencia "Referencia"
        TEXT descripcion "Descripción"
    }

    ncp {
        INTEGER id PK "Nota Cargo Proveedor ID"
        TEXT proveedor FK "CUIT del proveedor"
        TEXT fecha "Fecha"
        TEXT descripcion "Descripción"
    }

    %% ==========================================
    %% GASTOS
    %% ==========================================

    gastosfacturas {
        INTEGER id PK "N° Factura de Gasto"
        TEXT proveedor FK "CUIT del proveedor"
        TEXT numfactura "N° factura externa"
        TEXT fecha "Fecha gasto"
        REAL subtotal "Subtotal sin IVA"
        REAL iva "Monto IVA"
        REAL total "Total gasto"
        TEXT descripcion "Descripción general"
        INTEGER cdc FK "Centro de Costo"
    }

    compragastos {
        INTEGER id PK "ID autoincremental"
        INTEGER gastos_id FK "N° factura de gasto"
        TEXT descripcion "Concepto del gasto"
        REAL monto "Monto neto"
        REAL iva "Monto IVA"
    }

    movimientos_sin_impuestos {
        INTEGER id PK "ID autoincremental"
        INTEGER ref_id FK "Referencia (remito/factura)"
        INTEGER codigo FK "Código producto"
        TEXT producto "Nombre producto"
        REAL cantidad "Cantidad"
        REAL precio "Precio"
        TEXT gasto "Tipo de gasto"
    }

    %% ==========================================
    %% COBROS Y PAGOS
    %% ==========================================

    cobros {
        INTEGER ordcobro PK "Orden de cobro"
        TEXT cliente FK "CUIT del cliente"
        REAL monto "Monto cobrado"
        TEXT fecha "Fecha cobro"
        TEXT tipo "Efectivo, Cheque, Transferencia"
        TEXT referencia "N° cheque/comprobante"
    }

    pagos {
        INTEGER ordpago PK "Orden de pago"
        TEXT proveedor FK "CUIT del proveedor"
        REAL monto "Monto pagado"
        TEXT fecha "Fecha pago"
        TEXT tipo "Efectivo, Cheque, Transferencia"
        TEXT referencia "N° cheque/comprobante"
    }

    %% ==========================================
    %% CAJA Y CHEQUERA
    %% ==========================================

    caja {
        INTEGER id PK "ID autoincremental"
        TEXT referencia "Referencia operación"
        TEXT fecha "Fecha operación"
        REAL debe "Cargo a caja"
        REAL haber "Abono a caja"
        TEXT descripcion "Descripción"
    }

    chequera {
        INTEGER id PK "ID autoincremental"
        TEXT numcheque "N° de cheque"
        INTEGER tipo "0=emitido, 1=cobrado"
        REAL monto "Monto del cheque"
        TEXT vencimiento "Fecha de vencimiento"
        TEXT banco "Banco emisor"
        TEXT cuit FK "CUIT (cliente/proveedor)"
        TEXT nombre "Nombre titular"
        TEXT descripcion "Descripción"
        TEXT pagado "Estado: pagado/no pagado"
    }

    %% ==========================================
    %% FACTURAS SIN REMITO / REMITOS SIN FACTURA
    %% ==========================================

    facnorem {
        INTEGER id PK "ID autoincremental"
        INTEGER codigo FK "Código producto"
        TEXT producto "Nombre producto"
        REAL cantnoretirada "Cantidad no retirada"
        TEXT cliente FK "CUIT del cliente"
        TEXT fecha "Fecha"
        INTEGER nmov "N° movimiento"
    }

    remnofac {
        INTEGER id PK "ID autoincremental"
        INTEGER codigo FK "Código producto"
        TEXT producto "Nombre producto"
        REAL cantidad "Cantidad"
        TEXT cliente FK "CUIT del cliente"
        TEXT fecha "Fecha"
        INTEGER idfactura FK "N° factura (0=pendiente)"
        INTEGER nmov "N° movimiento"
    }

    %% ==========================================
    %% RELACIONES (Foreign Keys lógicas)
    %% ==========================================

    clientes ||--o{ remito : "emite"
    clientes ||--o{ ventas : "realiza"
    clientes ||--o{ facturas : "recibe"
    clientes ||--o{ cobros : "abona"
    clientes ||--o{ nncv : "nota crédito"
    clientes ||--o{ nndv : "nota débito"
    clientes ||--o{ facnorem : "factura sin remito"
    clientes ||--o{ remnofac : "remito sin factura"

    proveedores ||--o{ factprov : "factura a"
    proveedores ||--o{ pagos : "recibe pago"
    proveedores ||--o{ nfan : "nota débito"
    proveedores ||--o{ ndprov : "nota crédito"
    proveedores ||--o{ ncp : "nota cargo"
    proveedores ||--o{ gastosfacturas : "gasto de"

    stockmercaderia ||--o{ ventas : "se vende en"
    stockmercaderia ||--o{ compras : "se compra en"
    stockmercaderia ||--o{ movimientos_sin_impuestos : "movimiento sin impuestos"
    stockmercaderia ||--o{ conscom : "consignación"
    stockmercaderia ||--o{ facnorem : "factura sin remito"
    stockmercaderia ||--o{ remnofac : "remito sin factura"

    remito ||--o{ ventas : "contiene"
    remito ||--o{ rementre : "entregas parciales"
    remito ||--o{ entregas : "entregas"

    facturas ||--o{ ventas : "factura venta"

    factprov ||--o{ compras : "contiene"
    factprov ||--o{ conscom : "consignación"

    gastosfacturas ||--o{ compragastos : "detalla"
    gastosfacturas }o--|| cdc : "pertenece a"
