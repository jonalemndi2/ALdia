---
name: carga-de-comprobantes
description: Carga de comprobantes en ALdia - facturas de gasto (luz, alquiler, fletes, servicios), compras de mercadería a proveedores que ingresan al stock, y los pagos correspondientes. Usar cuando el usuario diga "cargar una factura", "llegó la factura de", "vino mercadería", "entró un pedido", "cargar un gasto", "pagué a X", "remito del proveedor" o dicte los datos de un comprobante recibido.
---

# Carga de comprobantes de compra y gasto (ALdia)

Herramientas MCP del servidor **aldia**. Lo primero es decidir **qué tipo de
comprobante** es, porque cada uno tiene efectos distintos:

| Es...                                              | Herramienta          | Efectos                                                              |
| -------------------------------------------------- | -------------------- | -------------------------------------------------------------------- |
| Mercadería para revender (entra al depósito)        | `registrar_compra`   | **suma stock**, actualiza precio de compra, suma deuda al proveedor. No toca la caja. |
| Un servicio o insumo que no va al stock (luz, flete, alquiler, limpieza) | `cargar_gasto` | guarda conceptos con su IVA, suma deuda al proveedor y **genera egreso de caja** por el total. |
| El pago de cualquiera de los dos                   | `registrar_pago`     | baja la deuda del proveedor y sale de caja (o emite/endosa un cheque). |

Si el usuario duda, la pregunta que decide es: **¿esto se revende?** Si sí, es
compra; si no, es gasto.

## Paso 0 — Identificar al proveedor

```
buscar_proveedor(texto="<nombre o CUIT>")
```

Si no existe, deles de alta antes (los dos endpoints exigen un proveedor ya
cargado):

```
alta_proveedor(cuit="30-71234567-1", nombre="Distribuidora ...", telefono="...")
```

El CUIT se acepta con o sin guiones, pero ALdia **valida el dígito
verificador**: si está mal tipeado devuelve un error diciéndolo. En ese caso
pídale al usuario que relea el CUIT del comprobante, no lo invente ni lo
"corrija" usted.

## Paso 1a — Compra de mercadería

```
registrar_compra(
  proveedor="<CUIT o nombre>",
  numero_factura="A-0001-00000123",
  fecha="YYYY-MM-DD",
  items=[{"codigo": 990001, "cantidad": 24, "precio": 1800}]
)
```

- `precio` es el **costo unitario neto, sin IVA**. Si el usuario dicta el precio
  con IVA incluido, divídalo por la alícuota del artículo (`1 + iva/100`) y
  aclárele que lo hizo.
- Los artículos deben existir. Si vino algo nuevo, `alta_producto` primero (con
  `cantidad=0`) y después la compra: así el ingreso queda documentado.
- El IVA lo calcula ALdia con la alícuota de cada artículo, y el total va a la
  deuda del proveedor. **No genera egreso de caja**: el pago se registra aparte.
- Verifique con `buscar_producto(codigo=...)` que el stock quedó como esperaba y
  muéstreselo al usuario.

Si el precio de compra subió, el sistema actualiza `precio_compra` solo. Avise
al usuario cuánto subió: es el momento natural para revisar el precio de venta
(ver la skill de control de stock).

## Paso 1b — Factura de gasto

```
cargar_gasto(
  proveedor="<CUIT o nombre>",
  numero_factura="B-0002-00000045",
  fecha="YYYY-MM-DD",
  conceptos=[
    {"descripcion": "Flete reparto", "monto": 20000, "iva": 21},
    {"descripcion": "Peaje",         "monto": 3000,  "iva": 0}
  ],
  descripcion="Logística semana 33"
)
```

- Cada `monto` es el **neto sin IVA** de ese renglón; la alícuota va aparte.
  Las válidas en ALdia son 0, 2.5, 5, 10.5, 21 y 27.
- Si el usuario sólo tiene el total con IVA de un servicio al 21 %:
  `neto = total / 1.21`. Diga en voz alta el neto y el IVA que va a cargar antes
  de ejecutar, así lo puede corregir.
- Cargar bien el IVA importa: es lo que después aparece como **crédito fiscal**
  en `consultar_libro_iva`. Un gasto cargado como un solo renglón "total" con
  IVA 0 le hace perder crédito fiscal al negocio.
- Ojo: el gasto **genera el egreso de caja automáticamente**. Si además lo carga
  con `registrar_movimiento_caja`, la caja queda descontada dos veces.

## Paso 2 — Registrar el pago

```
registrar_pago(proveedor="<CUIT o nombre>", monto=..., tipo="transferencia",
               referencia="TRF-99881", fecha="YYYY-MM-DD")
```

- `tipo="efectivo"` o `"transferencia"` → sale de la caja.
- `tipo="cheque"` + `banco` + `vencimiento` → registra un **cheque propio
  emitido**; no sale de caja hasta que se debita.
- `cheque_id=<id>` → endosa un cheque de tercero que ya está en la chequera
  (véalos con `ver_chequera(solo_pendientes=true)`); tampoco sale plata de caja
  y el cheque queda marcado como usado.
- **Pago parcial**: registre lo que realmente se pagó. La respuesta trae
  `saldo_proveedor_ahora`; informe el resto adeudado.

Confirme proveedor e importe con el usuario antes de ejecutar: es una operación
de dinero.

## Paso 3 — Controlar

Después de cargar una tanda:

- `buscar_proveedor(texto="...")` → cómo quedó el saldo a pagar.
- `ver_movimientos_del_dia()` → los egresos generados hoy.
- `consultar_libro_iva(mes="YYYY-MM")` → el crédito fiscal acumulado del mes.

## Dictado desde una foto o un texto de la factura

Cuando el usuario le pase los datos de un comprobante, arme un borrador y
**muéstrelo antes de cargar**:

```
Proveedor : Distribuidora MCP SRL (30-71234567-1)
Comprobante: B-0002-00000045   Fecha: 17/08/2026
Conceptos : Flete reparto   $ 20.000,00  + IVA 21%
            Peaje           $  3.000,00  + IVA 0%
Neto $ 23.000,00 | IVA $ 4.200,00 | Total $ 27.200,00
¿Lo cargo así?
```

Si algún dato no está en el comprobante (número, fecha, CUIT), **pregunte**; no
lo complete por su cuenta. Un comprobante mal cargado descuadra el libro IVA y
la cuenta del proveedor.

## Corregir un comprobante mal cargado

- `anular_gasto(gasto_id=<id>, confirmar=true)` — borra el gasto, revierte la
  deuda y el egreso de caja.
- `anular_pago(orden_de_pago=<n>, confirmar=true)` — borra el pago, devuelve la
  deuda y libera el cheque endosado si lo hubo.
- Las compras **no** tienen anulación propia en la API: para revertir una,
  avísele al usuario que hay que hacerlo desde el módulo Administración con un
  usuario administrador.

Las anulaciones son destructivas: primero informe qué va a borrar (número,
proveedor, importe), espere la autorización explícita del usuario y recién
entonces pase `confirmar=true`. Después vuelva a cargar el comprobante correcto.
