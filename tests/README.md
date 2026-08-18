# Pruebas automatizadas

```bash
.venv\Scripts\python.exe -m pytest tests/ -q      # todas
.venv\Scripts\python.exe -m pytest tests/ -v      # con el nombre de cada una
.venv\Scripts\python.exe -m pytest tests/test_negocio.py::TestFactura -v
```

Requiere `pytest` y `httpx`:

```bash
.venv\Scripts\python.exe -m pip install pytest httpx
```

**No hace falta levantar el servidor.** Las pruebas montan la aplicación en
memoria y usan una **base de datos temporal** que se borra al terminar: nunca
tocan `backend/aldia.db` ni los datos del comercio.

## Qué cubre cada archivo

### `test_dinero.py` — exactitud de los importes
Los importes se guardan como enteros de centavos. Estas pruebas fallan si se
vuelve a decimales flotantes: sumar diez veces $0,10 debe dar exactamente $1,00,
y el IVA de $1.234,56 debe ser $259,26 (con floats daba `259.25759999999997`).
También fija el criterio de redondeo: **comercial**, no bancario — `2,675`
redondea a `2,68`, no a `2,67`.

### `test_seguridad.py` — autenticación, roles y validación fiscal
Cubre los agujeros que el sistema tuvo y que no deben volver:

- Ningún endpoint de datos responde sin token, ni para leer ni para escribir.
- `reset-db` exige administrador (llegó a borrar toda la base sin pedir nada).
- Un token firmado con la vieja clave hardcodeada se rechaza.
- Los roles se validan **en el servidor**: `caja` no escribe en stock ni emite
  facturas; `auditor` lee todo y no modifica nada.
- CUIT con dígito verificador, alícuotas de IVA vigentes, importes no negativos.

### `test_negocio.py` — el circuito comercial
Que cada operación tenga **todos** sus efectos y que anularla los revierta:

- Un remito descuenta stock; una factura suma la deuda del cliente.
- Un cobro en efectivo baja el saldo y genera el asiento de caja; **con cheque
  no entra a caja**, va a la chequera.
- Anular revierte stock, saldo y caja.
- La numeración **no reusa** el número de un comprobante anulado.
- Los saldos guardados cierran contra los movimientos, y no hay filas huérfanas.

## Al agregar funcionalidad

Si toca dinero, stock o saldos, agregue la prueba que lo demuestre. El patrón es
siempre el mismo: **medir antes, operar, medir después**, en vez de confiar en
que la respuesta HTTP diga 200.

Las fixtures de `conftest.py` dan un cliente autenticado como administrador
(`admin`) y un generador de CUIT válidos (`cuit`), porque el sistema valida el
dígito verificador y un CUIT inventado se rechaza.
