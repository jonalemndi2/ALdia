---
name: cierre-de-caja
description: Cierre de caja diario en ALdia - cuadrar los ingresos y egresos del día, comparar el saldo del sistema contra el dinero físico contado, detectar y explicar diferencias, y registrar el ajuste o el retiro. Usar cuando el usuario diga "cerrar la caja", "cierre del día", "cuánto hizo hoy", "arqueo", "cuadrar caja", "me sobra/me falta plata en la caja" o pida el resumen de un día ya pasado.
---

# Cierre de caja diario (ALdia)

Esta skill usa las herramientas MCP del servidor **aldia**. El objetivo del
cierre es responder tres preguntas: **cuánto entró y salió hoy**, **cuánto
debería haber en la caja**, y **si eso coincide con la plata contada**.

## Antes de empezar

Si es la primera operación de la sesión, ejecute `check_connection`. Ahí ve
con qué usuario y rol está operando. Si el rol no incluye `caja`, avise: sin ese
módulo no va a poder registrar el ajuste.

## Paso 1 — Traer el movimiento del día

```
get_daily_cash_movements(fecha="YYYY-MM-DD")   # omitir fecha = hoy
```

Devuelve, para esa fecha: movimientos de caja, cobros, pagos, gastos, facturas,
los totales de cada grupo y el saldo acumulado de caja.

Trabaje con estos campos:

- `totales.ingresos_caja` — todo lo que entró a la caja.
- `totales.egresos_caja` — todo lo que salió.
- `totales.neto_caja_del_dia` = ingresos − egresos.
- `saldo_acumulado_de_caja` — el saldo total del sistema (histórico, no del día).

## Paso 2 — Entender cómo se arma ese neto (clave para explicar diferencias)

ALdia genera movimientos de caja **automáticamente**; no hay que cargarlos a
mano:

| Operación registrada       | Efecto en caja                                     |
| -------------------------- | -------------------------------------------------- |
| Cobro **sin** cheque       | ingreso `COBRO n`                                   |
| Cobro **con cheque**       | **ninguno** — el cheque va a la chequera            |
| Pago sin cheque            | egreso `PAGO n`                                     |
| Pago con cheque propio o endoso | **ninguno**                                    |
| Gasto                      | egreso `GASTO n` por el total                       |
| Factura emitida            | **ninguno** — sólo genera deuda del cliente         |
| Remito                     | **ninguno**                                         |

Por eso el neto de caja casi nunca es "cobros − pagos". Si no cierra, mire
primero `totales.cobros_con_cheque_no_entran_a_caja` y confirme con
`list_checks(solo_pendientes=true)`.

**Una factura no es plata cobrada.** Si el usuario pregunta "cuánto vendí",
`totales.facturado_total` es la venta; el dinero efectivamente recibido es
`totales.cobros_total`.

## Paso 3 — Arqueo: comparar con el dinero contado

Pregunte al usuario cuánto contó físicamente en la caja al cerrar (y cuánto
había al abrir, si maneja fondo fijo).

```
esperado_en_caja = efectivo_inicial + ingresos_caja − egresos_caja
diferencia       = contado_real − esperado_en_caja
```

- `diferencia == 0` → informe "caja cuadrada" con el detalle.
- `diferencia > 0` → sobra plata. Causas típicas: una venta de mostrador que no
  se cargó, o un cobro cobrado y no registrado.
- `diferencia < 0` → falta plata. Causas típicas: un gasto chico pagado de la
  caja sin comprobante, un vuelto mal dado, un retiro no registrado.

Antes de registrar cualquier ajuste, **revise los movimientos uno por uno** con
el usuario (la lista `movimientos_de_caja` trae `descripcion` y `referencia`) y
busque la operación faltante. Un ajuste es el último recurso, no el primero.

## Paso 4 — Registrar lo que falte

Según lo que se descubra:

- **Venta o cobro no registrado** → `record_payment(cliente=..., monto=...,
  tipo="efectivo")` si era de un cliente de cuenta corriente; si fue venta de
  mostrador sin cliente, `record_cash_movement(concepto="Venta de
  mostrador", ingreso=...)`.
- **Gasto chico pagado de la caja** → si hay comprobante del proveedor,
  `record_expense(...)` (deja el IVA para el libro); si no lo hay,
  `record_cash_movement(concepto="...", egreso=...)`.
- **Retiro del dueño** → `record_cash_movement(concepto="Retiro de
  efectivo", egreso=...)`.
- **Diferencia que no se pudo explicar** → sólo con el visto bueno del usuario:
  `record_cash_movement(concepto="Ajuste por arqueo de caja del
  DD/MM", ingreso=... | egreso=...)` por el valor de la diferencia.

Nunca cargue un movimiento de caja para "duplicar" un cobro, un pago o un gasto:
esos ya generaron su asiento y lo estaría contando dos veces.

## Paso 5 — Informar

Cierre con un resumen corto, en pesos y en prosa, no un volcado de JSON:

```
Cierre del 17/08/2026
  Ingresos de caja      $ 1.734,56
  Egresos de caja       $ 57.200,00
  Neto del día         -$ 55.465,44
  Saldo de caja         $ ...

  Cobros del día        $ 500,00  (de los cuales $ 0 en cheques, no entraron a caja)
  Pagos a proveedores   $ 30.000,00
  Gastos                $ 27.200,00
  Facturado             $ 18.150,00

  Contado en caja       $ ...      → diferencia $ ...
```

Y agregue lo que haya que hacer mañana: cheques a depositar
(`list_checks(solo_pendientes=true)`) y clientes que prometieron pagar.

## Errores frecuentes

- Cerrar sin preguntar la fecha cuando el usuario habla de "ayer": pásela
  explícita en formato `YYYY-MM-DD`.
- Confundir `saldo_acumulado_de_caja` (histórico) con el neto del día.
- Registrar el ajuste antes de buscar la causa.
- Anular movimientos para "arreglar" el cierre. `delete_cash_movement` y
  `void_payment` son destructivas: pida autorización explícita al usuario y
  recién entonces pase `confirmar=true`.
