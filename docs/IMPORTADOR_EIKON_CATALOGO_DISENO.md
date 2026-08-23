# Importador seguro de catálogo Eikon

El archivo Eikon es una **lista de proveedor**, no un inventario del comercio.
Por eso su columna `stock` se persiste únicamente como `stock_proveedor`; el
campo `stockmercaderia.cantidad` nunca se escribe por esta ruta.

## Contrato

1. `POST /api/stock/importaciones/preview` recibe XLSX y una política explícita:
   precio especial/regular, tipo de cambio ARS/USD, fecha de TC y si puede
   actualizar SKU existentes. Requiere `encargado_deposito` y genera evidencia,
   pero no cambia el catálogo.
2. Se acepta exclusivamente `LISTA DE PRECIOS`, cabecera de fila 5 y 494 filas.
   `NOTEBOOK` no es una segunda fuente porque duplica SKU. Fórmulas, archivos
   comprimidos desproporcionados, números negativos, IVA inválido o SKU
   duplicados se rechazan.
3. `POST /{id}/confirmar` exige `confirmar=true`, el `preview_hash` exacto y
   `X-Operation-Id`. Es la única operación que escribe y corre dentro de una
   transacción total. Un preview confirmado se devuelve de forma idempotente.

Los SKU alfanuméricos se conservan textualmente y en mayúscula en
`sku_proveedor`; no se fuerzan al código interno numérico. Para altas nuevas el
código interno se asigna de forma determinista por SKU ordenado desde el máximo
libre, y cualquier error de integridad revierte todo.

## Moneda y trazabilidad

Los precios USD se preservan como fuente y el precio de venta interno se calcula
con `Decimal` y `ROUND_HALF_UP` usando el TC ingresado explícitamente. No se
consulta una cotización automática. La política, hashes de archivo/preview,
usuario, fecha y resumen quedan en `importaciones_catalogo`; la auditoría HTTP
existente registra el POST de confirmación.

## MCP

El MCP no lee paths locales ni abre XLSX. Cuando se exponga, solo invocará estas
rutas API y deberá enviar el mismo flujo preview → revisión humana → confirmar.
