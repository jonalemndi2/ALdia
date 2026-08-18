---
name: control-de-stock
description: Control de stock y precios en ALdia - saber qué falta reponer, qué mercadería no rota, armar el pedido a proveedores y actualizar precios (uno por uno o remarcación porcentual por lista). Usar cuando el usuario diga "qué me falta", "hay que reponer", "armar el pedido", "cuánto tengo de X", "aumentar los precios", "remarcar", "lista de precios" o "qué no se vende".
---

# Control de stock y precios (ALdia)

Herramientas MCP del servidor **aldia**. Todo el stock se identifica por
`codigo` (número entero); es el dato con el que operan casi todas las
herramientas de mercadería.

## A. Qué falta reponer

```
buscar_producto(solo_faltantes=true, minimo=<umbral>)
```

`minimo` es el punto de pedido. ALdia **no guarda un stock mínimo por
artículo** (ver "Limitaciones"), así que hay que fijarlo:

- Si el usuario no dice nada, empiece con `minimo=0`: eso trae lo agotado o en
  negativo, que es lo urgente.
- Para un kiosco o almacén, un barrido con `minimo=5` o `minimo=10` suele
  mostrar lo que está por cortarse.
- Si el usuario tiene un criterio por rubro ("de bebidas quiero 24 mínimo"),
  filtre con `buscar_producto(texto="gaseosa")` y aplique el umbral usted.

Un stock **negativo** no es un error de la herramienta: significa que se entregó
o facturó más de lo que había cargado. Señálelo — suele indicar mercadería que
entró sin registrarse como compra.

## B. Armar el pedido al proveedor

1. Liste los faltantes con el paso A.
2. Para cada artículo proponga una cantidad a pedir. Un criterio simple y
   defendible: `cantidad_a_pedir = objetivo − stock_actual`, donde el objetivo
   lo confirma el usuario (por bulto, por caja cerrada, por lo que entra en la
   góndola).
3. Muestre la lista con **código, descripción, stock actual, cantidad sugerida y
   precio de compra** (`precio_compra` viene en la respuesta) y el total
   estimado del pedido.
4. **Espere la confirmación del usuario.** Recién cuando la mercadería llegue se
   registra con `registrar_compra`, que suma al stock y genera la deuda con el
   proveedor (ver la skill de carga de comprobantes).

Nunca use `actualizar_producto(cantidad=...)` para "cargar" mercadería comprada:
ese parámetro **pisa** el stock, no lo suma, y además deja la compra sin
comprobante ni deuda registrada.

## C. Qué no rota

ALdia no expone un endpoint de rotación por artículo (ver "Limitaciones"), así
que la aproximación honesta es:

1. `buscar_producto()` sin filtros para tener el inventario completo.
2. Señale como candidatos a "no rota" los artículos con **stock alto y precio de
   compra alto** (capital inmovilizado), ordenados por `stock × precio_compra`.
3. Aclare al usuario que es una estimación por inventario, no por ventas, y
   ofrezca verificar los que le interesen mirando las facturas del período con
   `resumen_negocio` o preguntándole desde cuándo no vende ese artículo.

No invente cifras de rotación ni de "unidades vendidas por mes": el sistema hoy
no las devuelve.

## D. Actualizar precios

**Un artículo puntual:**

```
actualizar_producto(codigo=990001, precio_venta=2800)
```

**Remarcación porcentual (lista o rubro):**

```
buscar_producto(texto="gaseosa")            # 1. ver a qué artículos afecta
actualizar_producto(codigo=..., aumento_pct=12)   # 2. uno por artículo
```

`aumento_pct=12` sube el precio de venta un 12 % sobre el precio actual,
redondeado a 2 decimales. No se puede combinar con `precio_venta` en la misma
llamada. **No existe una actualización masiva en la API**: hay que iterar
artículo por artículo, así que antes de empezar:

1. Muestre la lista de artículos afectados con precio actual y precio resultante.
2. Pida confirmación explícita al usuario.
3. Recién entonces ejecute las llamadas, y al terminar informe cuántos
   artículos se actualizaron y si alguno falló.

Un artículo con precio de venta 0 no se puede remarcar por porcentaje: la
herramienta devuelve un error pidiendo un `precio_venta` explícito. Es
frecuente en artículos recién dados de alta.

**Margen.** Con `precio_venta` y `precio_compra` puede calcular el margen:
`margen_% = (precio_venta − precio_compra) / precio_compra × 100`. Si el usuario
pide "venderlo con 40 % de margen sobre el costo", el precio es
`precio_compra × 1.40`. Confirme siempre si el margen es sobre costo o sobre
venta antes de calcular.

**IVA.** `iva_pct` es la alícuota del artículo, y las únicas válidas en ALdia
son 0, 2.5, 5, 10.5, 21 y 27. Los precios de venta se manejan como netos: el IVA
lo agrega la factura.

## E. Alta de artículos nuevos

```
alta_producto(codigo=..., producto="...", cantidad=0, unidad="UN",
              precio_venta=..., precio_compra=..., iva=21)
```

- El `codigo` debe ser único; si ya existe, la operación falla.
- Deje `cantidad=0` y cargue el stock inicial con `registrar_compra`, así queda
  el comprobante y la deuda con el proveedor.
- `unidad`: "UN", "Kg", "Lt", "Caja"... según cómo se venda.

## Limitaciones a tener presentes

- No hay punto de pedido por artículo: el umbral lo define el usuario en cada
  consulta.
- No hay endpoint de rotación ni de unidades vendidas por artículo.
- No hay actualización masiva de precios: la remarcación es artículo por
  artículo.
- Los listados no tienen paginación: en un catálogo grande, filtre con `texto`
  en vez de traer todo.
