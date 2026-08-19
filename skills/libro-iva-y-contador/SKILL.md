---
name: libro-iva-y-contador
description: Cierre impositivo mensual en ALdia - armar el libro IVA de ventas y de compras del período, calcular la posición de IVA (a pagar o a favor), detectar comprobantes con problemas antes de mandarlos, y preparar el resumen para el contador. Usar cuando el usuario diga "libro IVA", "cierre del mes", "lo del contador", "cuánto tengo que pagar de IVA", "posición de IVA", "declaración jurada", "hay que presentar" o pida los datos de un mes cerrado.
---

# Libro IVA y cierre para el contador (ALdia)

Es una tarea **mensual** y de plazo fijo: si los datos salen mal, el comerciante
paga de más o presenta mal. Conviene ser conservador — ante la duda, señalar el
problema en vez de estimar.

## Paso 1 — Traer el período

```
get_vat_book(mes="2026-07")                          # mes completo
get_vat_book(fecha_desde="2026-07-01", fecha_hasta="2026-07-31")
```

Devuelve tres cosas:

- **IVA débito fiscal** — el IVA de lo que se **vendió** (facturas emitidas).
- **IVA crédito fiscal** — el IVA de lo que se **compró** (compras y gastos).
- **Posición** = débito − crédito.

Interprételo así, y dígalo con esas palabras:

- Posición **positiva** → hay que **pagar** esa diferencia.
- Posición **negativa** → queda **saldo a favor** para el mes siguiente.

## Paso 2 — Revisar antes de informar

Un total prolijo puede esconder comprobantes mal cargados. Antes de dar el
número por bueno, revise:

**a) Comprobantes de venta sin CAE.** Una factura sin CAE **no es una factura
electrónica válida**: está en el libro pero AFIP no la tiene.

```
get_einvoicing_status()          # ¿está habilitada la facturación electrónica?
```

Si hay facturas sin CAE en el período, list�elas y avise que hay que
regularizarlas antes de presentar. No las excluya del total por su cuenta.

**b) Compras y gastos sin CUIT de proveedor válido.** El crédito fiscal de un
comprobante mal identificado se puede impugnar.

**c) Alícuotas raras.** ALdia solo acepta las vigentes (0 · 2,5 · 5 · 10,5 · 21 ·
27 %), así que no debería haber sorpresas; si aparece algo llamativo (por ejemplo
todo al 21 % en un rubro con productos al 10,5 %), mencionelo.

**d) Que la contabilidad cierre.** Antes de un cierre mensual conviene verificar
que los saldos de cuenta corriente no se hayan desviado. Si el sistema reporta
diferencias, informelas: no las corrija por su cuenta, porque corregir un saldo
es una decisión contable.

## Paso 3 — Informar

El contador necesita números, no explicaciones. Pero el comerciante necesita
entender qué va a pagar. Dé las dos cosas:

```
Libro IVA — julio 2026

  VENTAS (débito fiscal)
    Comprobantes             34
    Neto gravado             $ 2.840.500,00
    IVA débito               $   596.505,00

  COMPRAS Y GASTOS (crédito fiscal)
    Comprobantes             21
    Neto                     $ 1.910.200,00
    IVA crédito              $   401.142,00

  POSICIÓN DEL MES         A PAGAR $ 195.363,00

  Para revisar antes de presentar:
    · 2 facturas sin CAE (N° 118 y 121)
```

Y agregue el contexto del negocio si ayuda a decidir: `get_business_summary()` da
ventas, compras, cobros y pagos del período.

## Paso 4 — Exportar

El usuario suele querer mandarle algo al contador. La pantalla de IVA del
sistema exporta a CSV; si pide "mandame el archivo", indíquele el camino
(**Menú → IVA → Exportar**) en vez de intentar generar el archivo desde el
asistente.

## Vocabulario, para hablar como el usuario

- **Débito fiscal** = IVA de las ventas. **Crédito fiscal** = IVA de las compras.
- **Posición** = lo que hay que pagar (o el saldo a favor).
- "IVA discriminado" = el comprobante muestra el IVA aparte (factura A).
- Una factura **B o C no discrimina IVA**: el consumidor final ve el total.
- **Monotributista**: no liquida IVA. Si el negocio es monotributo, la posición
  no aplica; el libro sirve igual como registro de comprobantes.

## Errores frecuentes

- **Dar la posición como definitiva cuando hay comprobantes sin CAE.** Avise
  primero.
- Confundir facturado con cobrado: el IVA se debe por la **factura emitida**,
  aunque el cliente todavía no haya pagado.
- Mezclar meses. Si el usuario dice "el mes pasado", confirme el período exacto
  en `YYYY-MM` antes de consultar.
- Sumar a mano lo que ya calculó el servidor: los totales del sistema son los
  autoritativos.
