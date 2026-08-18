---
name: facturacion
description: Ventas en ALdia - emitir remitos (entrega de mercadería), facturar con o sin entrega previa, y el circuito remito → factura de fin de mes. Usar cuando el usuario diga "hacele una factura a", "facturar", "hay que facturar lo del mes", "mandar un remito", "sale un pedido", "entregar mercadería", "vendí", "cobrale al cliente esto", "facturar sin entrega", "pasar los remitos a factura" o pregunte cuánto se facturó.
---

# Ventas: remitos y facturación (ALdia)

Herramientas MCP del servidor **aldia**. Lo primero es distinguir los dos
comprobantes, porque hacen cosas distintas:

| | `registrar_remito` | `emitir_factura` |
| --- | --- | --- |
| Qué documenta | la **entrega** de mercadería | la **venta** y su precio |
| Stock | lo **descuenta** | lo descuenta sólo si la línea no venía de un remito |
| Cuenta corriente del cliente | **no la toca** | **suma la deuda** por el total |
| Caja | no la toca | no la toca (la plata entra con el cobro) |
| AFIP | no lleva CAE | se le puede pedir el CAE |

La regla del comerciante: **el remito acompaña la mercadería, la factura acompaña
la deuda**. Un remito sin facturar es plata entregada que todavía no se reclamó.

## Antes de facturar: el cliente

```
buscar_cliente(texto="<nombre o CUIT>")
```

Tiene que existir y tener bien cargada la **condición frente al IVA**, porque de
ahí sale si el comprobante es A, B o C (ver la skill de alta de cliente o
proveedor). Si no existe, dele el alta antes: la factura exige un cliente
cargado.

## Caso 1 — Entrega ahora, factura después (remito)

Es el circuito clásico del reparto y del mayorista: sale la mercadería con
remito y a fin de mes se factura todo junto.

```
registrar_remito(
  cliente="<CUIT o nombre>",
  items=[{"codigo": 990001, "cantidad": 12}, {"codigo": 990002, "cantidad": 6, "precio": 3500}],
  fecha="YYYY-MM-DD",
  observaciones="Reparto zona norte"
)
```

- Si no indica `precio`, se usa el precio de venta del artículo. Indíquelo sólo
  cuando el usuario acordó otro precio con ese cliente.
- **Si no hay stock, la operación se rechaza** informando cuánto hay. No use
  `permitir_stock_negativo=true` por su cuenta: pregúntele al usuario si la
  mercadería salió igual (y entonces el stock queda en negativo, que hay que
  regularizar después con una compra o una toma de inventario).
- Devuelve `remito_numero`. Anótelo: es lo que el usuario escribe en el papel.

## Caso 2 — Facturar lo entregado (remito → factura)

```
ver_remitos_sin_facturar(cliente="<CUIT o nombre>")
```

Devuelve **líneas** (no remitos completos) con su `id`, número de remito,
producto, cantidad y precio. Ese `id` es lo que se factura.

1. Muéstrele al usuario las líneas pendientes agrupadas por cliente, con el
   total sin facturar.
2. Confirme **qué líneas entran** en la factura (todas las del mes, sólo un
   remito, etc.).
3. Emita:

```
emitir_factura(cliente="<CUIT o nombre>", lineas_remito_ids=[12, 13, 14], fecha="YYYY-MM-DD")
```

- **No se pueden mezclar clientes** en una factura: la herramienta lo rechaza.
- Esas líneas dejan de figurar como pendientes.
- El stock **no se vuelve a descontar** (ya lo descontó el remito).

## Caso 3 — Facturar sin entrega previa

Venta de mostrador a cuenta corriente, servicio, o mercadería que se lleva en el
momento y no pasó por remito:

```
emitir_factura(
  cliente="<CUIT o nombre>",
  items=[{"codigo": 990001, "cantidad": 3}, {"codigo": 990005, "cantidad": 1, "precio": 12000}],
  fecha="YYYY-MM-DD"
)
```

Acá **sí se descuenta el stock**, y ALdia rechaza la factura si no alcanza
(`Stock insuficiente de '...': se intentan facturar 5 y hay 2`). No fuerce nada:
avísele al usuario y decidan si baja la cantidad o si primero se carga la compra.

Se pueden combinar las dos formas en una sola factura: `lineas_remito_ids` para
lo ya entregado más `items` para lo que se agrega en el momento.

## Los importes los calcula el sistema

No pase subtotal, IVA ni total: `emitir_factura` los calcula con el precio y la
alícuota de cada artículo. Lo que sí tiene que hacer usted es **mostrar el
borrador antes de emitir**:

```
Cliente : Distribuidora del Litoral SRL (30-71234567-1) — Responsable Inscripto → Factura A
Fecha   : 18/08/2026
  12 × Fideos guiseros 500g        $  1.200,00   = $ 14.400,00  (IVA 21%)
   6 × Aceite girasol 1,5L         $  3.500,00   = $ 21.000,00  (IVA 21%)
Neto $ 35.400,00 | IVA $ 7.434,00 | Total $ 42.834,00
¿La emito?
```

Y espere el sí. Una factura emitida ya le generó deuda al cliente.

## Después de emitir

1. Informe **número de factura y total**, y que quedó cargado en la cuenta
   corriente del cliente.
2. Si el negocio factura electrónicamente, el paso siguiente es el **CAE**: sin
   CAE la factura no tiene validez fiscal (ver la skill de factura electrónica
   AFIP). Nunca dé por autorizado un comprobante que no lo esté.
3. Cuando el cliente pague, se registra el **cobro** (skill de cobranzas). La
   factura no mueve la caja.

Para ver cómo quedó un comprobante, incluido su estado ante AFIP:

```
ver_factura(numero=<n>)
```

## Errores frecuentes

| Situación | Qué significa | Qué hacer |
| --- | --- | --- |
| `La linea de remito X no existe o ya fue facturada` | otro usuario la facturó, o la lista está vieja | volver a pedir `ver_remitos_sin_facturar` |
| `La linea de remito X es del cliente ...` | se mezclaron clientes | emitir una factura por cliente |
| `Stock insuficiente de '...'` | no hay mercadería | ajustar cantidad o cargar la compra |
| `PERMISO DENEGADO (403) ... modulo 'ventas'` | el rol no factura (p. ej. `caja`) | decírselo al usuario; lo hace un usuario de ventas o el administrador |
| `La factura esta vacia` | no se pasaron ni líneas ni items | preguntar qué se factura |

## Corregir una factura

- **Sin CAE y recién emitida**: `anular_factura(numero=<n>, confirmar=true)`.
  Revierte la deuda, devuelve al stock lo facturado sin remito y deja los
  remitos otra vez como pendientes. Es **destructiva**: primero dígale al
  usuario número, cliente e importe, espere la autorización explícita y recién
  entonces pase `confirmar=true`.
- **Con CAE, o de un período ya cerrado**: no se anula. Se corrige con una
  **nota de crédito** (skill de notas de crédito y débito). Una factura
  autorizada por AFIP ya fue declarada: borrarla del sistema deja la declaración
  sin respaldo.

## Cuánto se vendió

```
resumen_negocio(fecha_desde="YYYY-MM-DD", fecha_hasta="YYYY-MM-DD")
```

Trae ventas facturadas, cantidad de facturas y remitos del período. Recuerde la
distinción al informar: **facturado no es cobrado**. Lo cobrado sale de
`ver_movimientos_del_dia` y de la skill de cobranzas.
