# Servidor MCP de ALdia

Capa de integración que expone la gestión comercial de **ALdia** (stock,
clientes, proveedores, remitos, facturas, cobros, pagos, caja, chequera, gastos,
libro IVA) como herramientas **MCP**, para que un asistente de IA pueda operar el
negocio: llevar la caja diaria de un kiosco, controlar el stock de un almacén,
gestionar cobranzas, cargar comprobantes.

El servidor es un proceso independiente que habla con la **API REST** de ALdia
por HTTP. **No importa el backend ni toca la base de datos**, así que funciona
igual contra una instalación local (`http://127.0.0.1:8000`) o contra un
servidor remoto de otra sucursal.

```
Asistente de IA  ──MCP (stdio)──►  aldia_mcp  ──HTTP + JWT──►  ALdia API  ──►  SQLite
```

---

## ⚠️ Advertencia de seguridad — leer antes de conectar

Conectar este servidor le da al asistente la capacidad de **crear comprobantes y
mover dinero real**: emitir facturas, registrar cobros y pagos, cargar gastos,
mover la caja y —con confirmación explícita— anular comprobantes.

Recomendaciones:

1. **No use el usuario `admin`.** Cree en ALdia un usuario de rol acotado
   (por ejemplo `caja`) desde *Administración → Usuarios*, y use ese. El rol
   `caja` tiene acceso a Clientes, Cuentas Corrientes y Caja, pero **no** puede
   borrar movimientos ni tocar la configuración del sistema. Si sólo quiere
   consultas, use un usuario de rol `auditor`: puede leer todo y el servidor
   rechaza cualquier escritura.
2. **Las credenciales van en variables de entorno**, nunca en el código ni en un
   archivo versionado. `.env.example` es una plantilla sin datos reales.
3. **Revise lo que el asistente hizo.** Todo queda registrado en ALdia con su
   número de comprobante; el módulo Administración permite buscar y auditar
   movimientos.
4. Si expone el backend a Internet, configure `ALDIA_SECRET_KEY`,
   `ALDIA_ORIGINS` y HTTPS del lado del servidor (ver `backend/security.py`).

| Rol en ALdia       | Puede consultar                   | Puede registrar                             |
| ------------------- | --------------------------------- | ------------------------------------------- |
| `auditor`           | todo                              | nada (sólo lectura, forzado por el backend) |
| `caja`              | clientes, cuentas corrientes, caja| cobros, movimientos de caja                 |
| `encargado_ventas`  | stock, clientes, ventas           | remitos, facturas, altas de cliente         |
| `encargado_compras` | stock, proveedores, gastos        | compras, pagos, gastos                      |
| `finanzas`          | caja, cuentas corrientes, gastos, IVA | cobros, pagos, gastos                   |
| `administrador`     | todo                              | todo, incluidas las anulaciones             |

---

## Requisitos

- Python 3.10 o superior.
- El backend de ALdia corriendo y accesible (`./iniciar_web.sh` en Linux y macOS,
  `iniciar_web.bat` en Windows, o `python backend/main.py`).
- Un usuario y contraseña válidos de ALdia.

## Instalación

El servidor MCP vive en su propio entorno, aparte del backend.

**Linux y macOS**

```bash
cd "/ruta/a/ALdia/mcp"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**Windows**

```bat
cd "ruta\a\ALdia\mcp"
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Variables de entorno

| Variable           | Obligatoria | Descripción                                                        |
| ------------------ | ----------- | ------------------------------------------------------------------ |
| `ALDIA_URL`       | no          | URL del backend. Por defecto `http://127.0.0.1:8000`.              |
| `ALDIA_USER`      | **sí**      | Usuario de ALdia con el que opera el asistente.                   |
| `ALDIA_PASSWORD`  | **sí**      | Contraseña de ese usuario.                                          |
| `ALDIA_TIMEOUT`   | no          | Timeout HTTP en segundos (por defecto 30).                         |

El servidor hace el login solo, guarda el token JWT en memoria y lo **renueva
automáticamente** antes de que venza (el token de ALdia dura 8 horas). Si el
backend invalida el token, reintenta el login una vez de forma transparente.

## Probar desde la consola

**Linux y macOS**

```bash
export ALDIA_URL=http://127.0.0.1:8000
export ALDIA_USER=caja
export ALDIA_PASSWORD=****
.venv/bin/python -m aldia_mcp
```

**Windows**

```bat
set ALDIA_URL=http://127.0.0.1:8000
set ALDIA_USER=caja
set ALDIA_PASSWORD=****
.venv\Scripts\python -m aldia_mcp
```

El proceso queda esperando mensajes MCP por stdin (es lo normal: lo maneja el
cliente MCP, no una persona). Si las credenciales o la URL están mal, el error
aparece recién en la primera herramienta que se ejecute, con un mensaje claro.

---

## Conectarlo a un asistente

### Claude Desktop

Editar `claude_desktop_config.json`:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

**Linux y macOS** — `command` y `cwd` van con la ruta absoluta real; el `~` no se
expande dentro del JSON, hay que escribir `/home/usuario/...` o
`/Users/usuario/...`:

```json
{
  "mcpServers": {
    "aldia": {
      "command": "/ruta/a/ALdia/mcp/.venv/bin/python",
      "args": ["-m", "aldia_mcp"],
      "cwd": "/ruta/a/ALdia/mcp",
      "env": {
        "ALDIA_URL": "http://127.0.0.1:8000",
        "ALDIA_USER": "caja",
        "ALDIA_PASSWORD": "la-contrasena-del-usuario-caja"
      }
    }
  }
}
```

**Windows** — las barras invertidas van dobles, porque el JSON las usa como
carácter de escape:

```json
{
  "mcpServers": {
    "aldia": {
      "command": "C:\\ruta\\a\\ALdia\\mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "aldia_mcp"],
      "cwd": "C:\\ruta\\a\\ALdia\\mcp",
      "env": {
        "ALDIA_URL": "http://127.0.0.1:8000",
        "ALDIA_USER": "caja",
        "ALDIA_PASSWORD": "la-contrasena-del-usuario-caja"
      }
    }
  }
}
```

Reiniciar Claude Desktop. Las herramientas aparecen con el prefijo `aldia`.

### Claude Code

```bash
claude mcp add aldia \
  --env ALDIA_URL=http://127.0.0.1:8000 \
  --env ALDIA_USER=caja \
  --env ALDIA_PASSWORD='la-contrasena' \
  -- "/ruta/a/ALdia/mcp/.venv/bin/python" -m aldia_mcp
```

o, equivalente, en `.mcp.json` del proyecto:

```json
{
  "mcpServers": {
    "aldia": {
      "command": "./mcp/.venv/bin/python",
      "args": ["-m", "aldia_mcp"],
      "cwd": "./mcp",
      "env": {
        "ALDIA_URL": "http://127.0.0.1:8000",
        "ALDIA_USER": "caja",
        "ALDIA_PASSWORD": "la-contrasena"
      }
    }
  }
}
```

> Si prefiere no escribir la contraseña en el archivo de configuración, expórtela
> en el entorno del sistema y omita esa clave: el servidor la lee igual.

### OpenClaw

OpenClaw 2026.6.11 o posterior puede registrar este servidor MCP directamente.
Use rutas absolutas: así funciona igual si ALdia está dentro de una carpeta con
espacios y no depende del directorio desde el que arrancó el Gateway.

```bash
openclaw mcp add aldia \
  --command "/ruta/a/ALdia/mcp/.venv/bin/python" \
  --arg -m --arg aldia_mcp \
  --cwd "/ruta/a/ALdia/mcp" \
  --env ALDIA_URL=http://127.0.0.1:8000 \
  --env ALDIA_USER=caja \
  --env ALDIA_PASSWORD='la-contrasena-del-usuario-caja' \
  --env ALDIA_CANAL=openclaw
```

En macOS la primera ruta normalmente empieza con `/Users/usuario/`; en Linux,
con `/home/usuario/`. Luego valide la definición y la conexión real:

```bash
openclaw mcp doctor aldia --probe
openclaw mcp tools aldia
openclaw gateway restart
```

El backend debe estar corriendo antes del `--probe`. Si OpenClaw se ejecuta como
servicio, no confíe en variables definidas solamente en `.zshrc` o `.bashrc`:
los servicios de macOS y Linux normalmente no las heredan. Las variables
guardadas con `openclaw mcp add --env` pertenecen a la configuración local de
OpenClaw y no deben versionarse ni copiarse al repositorio.

En Windows, cambie `command` por la ruta absoluta a
`mcp\\.venv\\Scripts\\python.exe`; el resto de los argumentos es igual.

### Skills

En `skills/` (raíz del proyecto) hay cuatro skills que enseñan al asistente a
usar estas herramientas para tareas reales: cierre de caja diario, control de
stock, cobranzas y carga de comprobantes. Copiar ese directorio donde el
asistente busque skills (por ejemplo `~/.claude/skills/` o `.claude/skills/`).

---

## Herramientas expuestas

### Consulta (sólo lectura)

| Herramienta                | Qué hace                                                                       |
| -------------------------- | ------------------------------------------------------------------------------ |
| `check_connection`       | Comprueba el servidor y las credenciales; informa usuario, rol y módulos.       |
| `find_product`          | Busca artículos por texto o código; opción "sólo faltantes" para reposición.    |
| `find_customer`           | Busca clientes por nombre o CUIT; devuelve ficha y saldo.                       |
| `find_vendor`         | Busca proveedores por nombre o CUIT; devuelve ficha y saldo a pagar.            |
| `get_customer_balance`        | Saldo de un cliente más sus facturas y cobros recientes.                        |
| `list_debtors`             | Clientes con deuda, ordenados; opción de antigüedad (días sin pagar).           |
| `get_cash_balance`           | Saldo acumulado de caja (ingresos menos egresos).                               |
| `get_daily_cash_movements`  | Caja, cobros, pagos, gastos y facturas de una fecha, con totales. Base del cierre. |
| `list_checks`             | Cheques recibidos a depositar y cheques propios emitidos.                       |
| `get_vat_book`      | IVA débito, crédito y saldo del período (acepta `mes` en formato YYYY-MM).      |
| `get_business_summary`          | Ventas, compras, gastos, cobros y pagos de un rango, más el estado actual.      |
| `list_uninvoiced_delivery_notes` | Líneas de mercadería entregada pendientes de facturación.                       |

### Operación (crean comprobantes / mueven dinero)

| Herramienta                 | Qué hace                                                                    |
| --------------------------- | --------------------------------------------------------------------------- |
| `create_product`             | Crea un artículo nuevo en el stock.                                         |
| `update_product`       | Cambia precios (incluido aumento por porcentaje), descripción, IVA o stock. |
| `create_customer`              | Crea la ficha de un cliente (valida CUIT).                                  |
| `create_vendor`            | Crea la ficha de un proveedor (valida CUIT).                                |
| `create_delivery_note`          | Venta con entrega: guarda el remito y descuenta stock.                      |
| `create_invoice`            | Factura remitos pendientes y/o artículos sin remito; calcula IVA y totales; carga la deuda al cliente. |
| `record_payment`           | Cobro de cliente: baja el saldo y entra a caja (o a la chequera si es cheque). |
| `record_vendor_payment`            | Pago a proveedor: baja la deuda y sale de caja (o emite/endosa cheque).      |
| `record_cash_movement` | Ingreso o egreso manual de caja (fondo fijo, retiro, ajuste de arqueo).      |
| `record_expense`              | Factura de gasto con conceptos; suma deuda al proveedor y egresa de caja.    |
| `record_purchase`          | Compra a proveedor: ingresa mercadería al stock y suma la deuda.             |

### Anulaciones (destructivas — exigen `confirmar=true`)

| Herramienta              | Qué hace                                                                |
| ------------------------ | ----------------------------------------------------------------------- |
| `void_invoice`         | Borra la factura, revierte la deuda y libera los remitos.                |
| `void_payment`           | Borra el cobro, devuelve el saldo al cliente y quita el ingreso de caja. |
| `void_vendor_payment`            | Borra el pago, devuelve la deuda y libera el cheque endosado.            |
| `void_expense`           | Borra el gasto, revierte la deuda y el egreso de caja.                   |
| `delete_cash_movement` | Borra un movimiento manual de caja.                                      |

Estas cinco devuelven un error si se las llama sin `confirmar=true`, con un
texto que le indica al asistente que primero debe pedir autorización al usuario.

---

## Manejo de errores

Los errores de la API llegan al asistente con el mensaje real del sistema, para
que pueda corregir en vez de reintentar a ciegas:

| Situación                        | Ejemplo de mensaje que recibe el asistente                                                        |
| -------------------------------- | -------------------------------------------------------------------------------------------------- |
| CUIT con dígito verificador malo | `DATOS INVALIDOS (422) en POST /api/clientes/: cuit: CUIT invalido: el digito verificador no corresponde (20-12345678-0)` |
| Rol sin permiso                  | `PERMISO DENEGADO (403) ...: Su rol (caja) no tiene acceso al modulo 'ventas'. ...`                 |
| Stock insuficiente               | `REGLA DE NEGOCIO (400) en POST /api/facturas/: Stock insuficiente de 'PRUEBA REMITO': se intentan facturar 5000.0 y hay 93.0` |
| Servidor caído                   | `No se pudo conectar con ALdia en http://127.0.0.1:8000: ... Verifique que el servidor este levantado` |

---

## Endpoints que faltan en la API

Estos son los huecos detectados al construir la integración. Ninguno impide
operar, pero limitan lo que el asistente puede hacer o lo obligan a traer más
datos de los necesarios:

1. **Filtros por rango de fechas.** `/api/caja/`, `/api/cobros/`, `/api/pagos/`,
   `/api/gastos/` y `/api/facturas/` sólo aceptan `fecha` exacta. Falta
   `fecha_desde` / `fecha_hasta` para poder pedir "la semana" sin hacer siete
   llamadas.
2. **Paginación y límites.** Ningún listado acepta `limit`/`offset`; con muchos
   registros el asistente recibe todo el histórico.
3. **Historial de cuenta corriente unificado.** No hay
   `/api/clientes/{cuit}/cuenta-corriente`: hay que cruzar facturas y cobros del
   lado del cliente HTTP para reconstruir el saldo en el tiempo.
4. **Fecha de última operación por cliente.** `/api/admin/morosos` no devuelve
   antigüedad de la deuda; calcularla exige una consulta por deudor.
5. **Stock mínimo por artículo.** El modelo de stock no tiene punto de pedido;
   el "qué falta reponer" se aproxima con un umbral que fija el usuario.
6. **Rotación de artículos.** No hay endpoint que devuelva unidades vendidas por
   período y por artículo; sin eso no se puede detectar lo que no rota sin leer
   todas las ventas.
7. **Actualización masiva de precios.** No existe un `PUT /api/stock/precios`
   por lista o rubro: una remarcación general se hace artículo por artículo.
8. **Alta de proveedor desde el gasto.** `/api/gastos/` exige un proveedor ya
   existente; no hay alta en una sola operación.
9. **Anulación de compras.** `/api/compras/` no tiene `DELETE` propio; sólo se
   puede revertir desde `/api/admin/movimientos/compra/{id}`, que exige rol
   administrador.
10. **Facturación electrónica AFIP.** En desarrollo por otro equipo. Cuando
    exista (CAE, tipo de comprobante, punto de venta), habrá que ampliar
    `create_invoice` para exponer esos datos.

---

## Licencia

Apache-2.0, igual que el resto del proyecto ALdia.
