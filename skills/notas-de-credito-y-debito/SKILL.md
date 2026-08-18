---
name: notas-de-credito-y-debito
description: Notas de crédito y de débito a clientes en ALdia - devoluciones de mercadería, facturas emitidas de más o de menos, bonificaciones, intereses por mora y gastos que no entraron en la factura. Usar cuando el usuario diga "me devolvieron mercadería", "hay que hacer una nota de crédito", "facturé de más", "le facturé mal", "le tengo que descontar", "cobrarle intereses", "nota de débito", "le facturé de menos" o "la factura ya tiene CAE y está mal".
---

# Notas de crédito y de débito (ALdia)

Herramientas MCP del servidor **aldia**. Una nota corrige una factura **ya
emitida**, sin borrarla.

| | `emitir_nota_credito` | `emitir_nota_debito` |
| --- | --- | --- |
| Efecto en la cuenta del cliente | **baja** la deuda | **sube** la deuda |
| Cuándo | devolución, facturé de más, bonificación, algo que no se entregó | intereses por mora, flete o envase que faltó facturar, facturé de menos |
| Stock | opcional: `reingresa_stock=true` si la mercadería volvió | no toca stock |
| Signo en ALdia | comprobante con importes **negativos** | comprobante positivo |

## Primero: ¿nota o anulación?

| La factura... | Qué corresponde |
| --- | --- |
| se emitió recién, **no tiene CAE** y está mal de punta a punta | **anularla** y rehacerla (`anular_factura`, skill de facturación) |
| **ya tiene CAE** | **nota de crédito**: no se anula un comprobante declarado a AFIP |
| es de un período ya presentado al contador | **nota de crédito**, aunque no tenga CAE: el libro IVA de ese mes ya se cerró |
| está bien, pero hay que agregarle algo | **nota de débito** |

Ante la duda, nota de crédito: deja rastro de los dos comprobantes, que es lo
que un contador y AFIP esperan ver.

## Paso 1 — Mirar la factura original

```
ver_factura(numero=<n>)
```

Confirme con el usuario: cliente, fecha, importe, renglones, y si tiene CAE. Con
eso decide (tabla de arriba) y sabe qué importe acreditar.

## Paso 2a — Nota de crédito por mercadería devuelta

```
emitir_nota_credito(
  cliente="<CUIT o nombre>",
  items=[{"codigo": 990001, "cantidad": 2}],
  motivo="Devolución: mercadería fallada",
  factura_original=12,
  reingresa_stock=true
)
```

- `reingresa_stock=true` **sólo si la mercadería volvió físicamente al
  depósito**. Si el cliente se la quedó (por ejemplo, una bonificación por
  producto en mal estado), va en `false`: si no, el stock del sistema queda por
  encima del real.
- Si no indica `precio`, se usa el precio de venta actual del artículo. **Si el
  precio cambió desde la factura, indíquelo**: se acredita lo que se facturó, no
  lo que vale hoy.
- **Una alícuota de IVA por nota.** Si los artículos devueltos tienen alícuotas
  distintas, la herramienta lo rechaza y hay que emitir una nota por alícuota.
  Es una limitación real del comprobante, no un capricho.

## Paso 2b — Nota de crédito por importe (bonificación o error de precio)

```
emitir_nota_credito(
  cliente="<CUIT o nombre>",
  importe_neto=15000, iva_pct=21,
  motivo="Bonificación comercial s/factura 12",
  factura_original=12
)
```

El importe va **en positivo y sin IVA**: el signo negativo y el IVA los pone el
sistema. Si el usuario le dice el total con IVA de un producto al 21 %,
`neto = total / 1,21`; diga en voz alta el neto y el IVA antes de emitir.

## Paso 2c — Nota de débito

```
emitir_nota_debito(
  cliente="<CUIT o nombre>",
  concepto="Intereses por mora s/factura 12",
  importe_neto=8000, iva_pct=21,
  factura_original=12
)
```

El `concepto` es lo que va escrito en el comprobante: sea específico ("Flete
entrega 15/08", "Intereses 30 días s/factura 12"), no ponga "ajuste".

## Paso 3 — Confirmar antes de emitir

Es una operación de dinero. Muestre el borrador y espere el sí:

```
Nota de crédito B a Distribuidora del Litoral SRL (30-71234567-1)
  Motivo : Devolución mercadería fallada — s/factura 12
  2 × Fideos guiseros 500g  $ 1.200,00  = $ 2.400,00 + IVA 21%
  Total a acreditar: $ 2.904,00
  La mercadería vuelve al depósito: sí
  Saldo del cliente: $ 42.834,00 → $ 39.930,00
¿La emito?
```

## Paso 4 — Después de emitir

1. Informe **número de comprobante** y cómo quedó el saldo del cliente.
2. **Pida el CAE** si el negocio factura electrónicamente, con el tipo que
   devuelve la respuesta en `tipo_comprobante_para_cae`:
   `solicitar_cae(numero=<n>, tipo_comprobante=8)` (skill de factura electrónica
   AFIP). Para las notas de débito ese parámetro es **obligatorio**.
3. **Anote la factura original en el comprobante impreso.** ALdia no guarda ese
   vínculo: la nota queda como un comprobante suelto de importe negativo. Es una
   limitación conocida; avísele al usuario para que lo escriba a mano.
4. La nota **no mueve la caja**. Si además hay que devolverle plata al cliente,
   eso es un egreso aparte (`registrar_movimiento_caja` con concepto claro), y
   sólo si el usuario lo confirma.

## Cómo se ve después

- `ver_saldo_cliente(cliente="...")` — el saldo ya tiene la nota aplicada.
- `ver_factura(numero=<n>)` — la nota aparece con `es_nota_de_credito: true`.
- `consultar_libro_iva(mes="YYYY-MM")` — el IVA de la nota de crédito **resta**
  del débito fiscal del mes; el de la nota de débito suma. Por eso importa
  cargarle bien la alícuota.

## Errores frecuentes

| Situación | Qué hacer |
| --- | --- |
| `Los articulos ... tienen alicuotas distintas` | emitir una nota por cada alícuota |
| `El importe ... va en POSITIVO` | pasar el importe sin signo: el sistema lo pone |
| `Falta el concepto de la nota de debito` | preguntarle al usuario qué se está debitando |
| El cliente no existe | la nota necesita ficha de cliente: darla de alta primero |
| `PERMISO DENEGADO (403) ... modulo 'ventas'` | el rol no emite comprobantes; decírselo y no reintentar |

## Lo que esta skill NO hace

- No corrige el stock por su cuenta más allá de `reingresa_stock`.
- No compensa automáticamente la nota contra la factura: en ALdia la cuenta
  corriente es un saldo único por cliente, no una imputación comprobante por
  comprobante.
- No emite notas de crédito **a proveedores**: eso es una devolución de compra
  (skill de carga de comprobantes).
