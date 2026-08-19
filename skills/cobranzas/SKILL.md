---
name: cobranzas
description: Gestión de cobranzas en ALdia - saber quién debe y desde hace cuánto, priorizar la deuda, preparar el mensaje de recordatorio para cada cliente y registrar el cobro cuando pagan (efectivo, transferencia o cheque). Usar cuando el usuario diga "quién me debe", "deudores", "morosos", "cobranzas", "mandar recordatorio", "reclamar la deuda", "cuánto debe X", "me pagó X" o "registrar un cobro".
---

# Cobranzas (ALdia)

Herramientas MCP del servidor **aldia**. En ALdia, el saldo del cliente
**positivo significa deuda**: sube cuando se emite una factura y baja cuando se
registra un cobro. Un remito no genera deuda hasta que se factura.

## Paso 1 — Quién debe

```
list_debtors(monto_minimo=0, con_antiguedad=true)
```

Devuelve los clientes con saldo pendiente ordenados de mayor a menor, con CUIT,
nombre, teléfono y saldo. Con `con_antiguedad=true` agrega, por cliente, la
fecha de su última factura, la de su último cobro y los días transcurridos —
más lento (consulta cliente por cliente), pero es lo que permite priorizar.

Use `monto_minimo` para no perder tiempo con saldos irrelevantes (por ejemplo
`monto_minimo=1000` en un kiosco).

## Paso 2 — Priorizar

Ordene el trabajo por riesgo, no sólo por monto:

| Prioridad | Criterio                                                        |
| --------- | --------------------------------------------------------------- |
| Alta      | Deuda grande **y** más de 60 días sin ningún cobro               |
| Alta      | Cliente que nunca registró un cobro (`ultimo_cobro` vacío)       |
| Media     | Deuda grande pero con cobros recientes (cliente que va pagando)  |
| Baja      | Saldos chicos, o facturas emitidas hace pocos días               |

Antes de reclamarle a alguien, mire su historial:

```
get_customer_balance(cliente="<CUIT o nombre>", limite=10)
```

Trae saldo, facturas recientes y cobros recientes. Sirve para dos cosas: no
reclamarle a un cliente que pagó ayer, y detectar saldos raros (por ejemplo, un
saldo que no baja aunque haya cobros: puede haber facturas duplicadas — mírelas
con el usuario antes de sacar conclusiones).

## Paso 3 — Preparar el recordatorio

Redacte un mensaje **por cliente**, listo para copiar y pegar en WhatsApp o
mail. Tono cordial y comercial argentino, sin amenazas, con el dato concreto:

```
Hola {nombre}, ¿cómo estás? Te escribo de {negocio}.
Te queda un saldo pendiente de $ {saldo} correspondiente a la factura N° {n}
del {fecha}. ¿Lo podés pasar esta semana? Cualquier cosa avisame y lo vemos.
¡Gracias!
```

Reglas:

- Un solo monto y una sola fecha por mensaje: si hay varias facturas, use el
  saldo total y mencione la más antigua.
- No prometa descuentos, planes de pago ni intereses salvo que el usuario lo
  indique.
- **Usted no envía nada.** Entregue los mensajes al usuario junto al teléfono o
  mail de cada cliente (vienen en `list_debtors` / `find_customer`) y que él
  decida.
- Si el cliente no tiene teléfono cargado, señálelo: es un dato que conviene
  completar con `create_customer` o desde el sistema.

## Paso 4 — Registrar el cobro cuando pagan

```
record_payment(cliente="<CUIT o nombre>", monto=..., tipo="efectivo",
                referencia="<recibo u operación>", fecha="YYYY-MM-DD")
```

Antes de ejecutar, **confirme con el usuario cliente e importe**. Es una
operación de dinero: baja el saldo del cliente y genera el ingreso de caja.

Según la forma de pago:

- **Efectivo / transferencia / tarjeta**: `tipo="efectivo"`,
  `tipo="transferencia"`, `tipo="tarjeta"`. Entra a caja en el momento.
- **Cheque**: `tipo="cheque"` más `referencia=<número de cheque>`,
  `banco="<banco>"` y `vencimiento="YYYY-MM-DD"`. **El cheque NO entra a la
  caja**: queda en la chequera como valor a depositar. Avísele esto al usuario,
  porque es la causa número uno de que después "no cuadre" la caja.
- **Pago parcial**: registre el monto realmente recibido. La herramienta
  devuelve `saldo_cliente_ahora`; informe cuánto le queda debiendo.

Si el nombre que dio el usuario coincide con varios clientes, la herramienta
devuelve un error listándolos: pregúntele cuál es en vez de adivinar.

## Paso 5 — Cerrar el circuito

Después de una tanda de cobranzas:

- `list_checks(solo_pendientes=true)` — cheques recibidos, con vencimiento, que
  hay que depositar. Avise los que vencen esta semana.
- `list_debtors()` de nuevo — para mostrar cómo quedó la deuda total.

## Corregir un cobro mal cargado

```
void_payment(orden_de_cobro=<n>, confirmar=true)
```

Devuelve el importe al saldo del cliente y borra el ingreso de caja. Es
**destructiva**: primero dígale al usuario qué cobro va a anular (orden, cliente
e importe), espere su autorización explícita y recién entonces pase
`confirmar=true`. Después registre el cobro correcto.

## Limitaciones a tener presentes

- No hay un endpoint de cuenta corriente unificado: la antigüedad se estima
  cruzando facturas y cobros, y `con_antiguedad=true` hace una consulta por
  deudor.
- No hay estados de "reclamado" ni recordatorios automáticos: el seguimiento de
  a quién ya se le escribió lo lleva el usuario (o usted, dentro de la
  conversación).
