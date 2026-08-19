# ALdía — Motor de gestión comercial operable por agentes

**ALdía lleva la gestión de un comercio y expone cada operación como una capacidad
segura, validada y auditable, para que un asistente de IA pueda ejecutarla por vos.**

Stock, clientes, proveedores, remitos, facturación electrónica, cuentas corrientes,
caja, chequera, gastos y libro IVA — para comercios, kioscos y supermercados pequeños
de Argentina.

La diferencia no está en los módulos, sino en dónde viven las reglas: **toda la lógica
de negocio está en el servidor**, así que da lo mismo si la operación entra por el
navegador o por un agente. Las dos puertas pasan por las mismas validaciones, la misma
transacción y el mismo registro de auditoría.

```
Usuario
  │  "José me pagó la factura de las cámaras con este cheque."  [adjunta la foto]
  ▼
Asistente ── interpreta, extrae los datos, pregunta lo que falta
  │
  ▼  MCP
ALdía ── valida, ejecuta y registra
  │       ✓ cobro registrado          ✓ cheque ingresado a cartera
  │       ✓ cuenta corriente al día   ✓ operación auditada
  ▼
Navegador ── donde mirás exactamente qué pasó, y corregís si hace falta
```

El asistente **interpreta**. ALdía **valida y ejecuta**. La web **supervisa**.
Ninguna regla contable vive en el prompt de un modelo, y el agente nunca escribe SQL:
solo puede pedir las operaciones comerciales que ALdía expone.

Podés usarlo perfectamente sin ningún agente: la interfaz web es completa y funciona
sola. Ver [docs/AGENTES.md](docs/AGENTES.md) para el estado de la integración y su
hoja de ruta.

> Antes de exponerlo a internet leé la sección [Seguridad](#seguridad): **hace falta HTTPS**.

## Índice

- [Arquitectura](#arquitectura)
- [Instalación](#instalación)
- [Roles y módulos](#roles-y-módulos)
- [Facturación electrónica AFIP](#facturación-electrónica-afip)
- [Integración con asistentes de IA](#integración-con-asistentes-de-ia)
- [Seguridad](#seguridad)
- [Registro de auditoría](#registro-de-auditoría)
- [Copias de seguridad](#copias-de-seguridad)
- [Pruebas](#pruebas)
- [Otros países](#otros-países)
- [Licencia](#licencia)

## Arquitectura

- **Backend:** API REST con FastAPI + SQLAlchemy + SQLite (un solo archivo de base de datos).
- **Frontend:** SPA en HTML/CSS/JavaScript (Bootstrap 5) servida por el mismo servidor.
- **Autenticación:** JWT + contraseñas cifradas con bcrypt.
- **Autorización:** por rol y módulo, **validada en el servidor** (no solo en el menú).
- **Módulos habilitables:** el administrador activa/desactiva módulos y define qué roles
  acceden a cada uno, para instalar el sistema con distintas configuraciones.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Caja 1     │     │  Caja 2     │     │ Depósito    │   ← Terminales (navegador)
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       └───────────────────┼───────────────────┘
                  Red local │ (http://IP-SERVIDOR:8000)
                     ┌──────┴───────┐
                     │   SERVIDOR   │   ← PC con Python + ALdia
                     │  FastAPI +   │
                     │   SQLite     │
                     └──────────────┘
```

Toda la lógica de negocio vive en el servidor y es **transaccional**: emitir un remito
descuenta el stock, facturar suma la deuda del cliente, un cobro baja el saldo y genera
el asiento de caja — todo en una sola operación que no puede quedar a medias. Anular
cualquier comprobante revierte sus efectos.

## Instalación

En la PC que va a actuar como servidor:

1. Instalar **Python 3.10 o superior** desde <https://www.python.org/downloads/>
   (marcar *"Add Python to PATH"*).
2. Ejecutar **`instalar.bat`** (solo la primera vez): crea el entorno e instala las dependencias.
   Para una instalación productiva conviene fijar las versiones exactas ya verificadas:
   `.venv\Scripts\python.exe -m pip install -r backend\requirements.lock.txt`.
3. Ejecutar **`iniciar_web.bat`** para arrancar el sistema.

El script muestra la dirección para conectarse desde otras PCs:

```
En esta PC (servidor):   http://localhost:8000
Desde otras PCs:         http://192.168.0.10:8000
```

### Primer ingreso

- **Usuario:** `admin` · **Contraseña:** `admin123`

El sistema **te obliga a cambiarla** antes de dejarte hacer nada: esta contraseña
es pública (está en este README), así que una instalación que la conserve tiene un
acceso conocido por cualquiera. Lo mismo vale para cada empleado que des de alta:
la contraseña que le pongas es provisoria y él la reemplaza al entrar, así el
registro de auditoría refleja a personas y no a una clave compartida.

### Con qué te encontrás la primera vez

ALdia arranca con la **base vacía**: no trae datos de ejemplo ni de ningún otro
comercio. En el primer arranque solo se crea lo mínimo para poder entrar y empezar
a cargar tu negocio.

| | Estado inicial |
|---|---|
| Clientes, proveedores, artículos | **0** |
| Facturas, remitos, cobros, movimientos de caja | **0** |
| Usuarios | **1** (`admin`) |
| Módulos del sistema | **10**, todos habilitados |
| Facturación electrónica AFIP | **Deshabilitada** (requiere tu certificado) |
| Registro de auditoría | **Activo desde el primer arranque** |

Primeros pasos recomendados:

1. Cambiar la contraseña de `admin` (**Menú → Usuarios**).
2. Cargar los datos de tu comercio: nombre, CUIT, condición frente al IVA y punto
   de venta (**Menú → Configuración del Negocio**). El nombre aparece en la barra
   superior y en los comprobantes.
3. Crear los usuarios reales con su rol (caja, ventas, depósito…) en vez de que
   todos compartan `admin`. **El registro de auditoría solo sirve si cada persona
   entra con su propio usuario.**
4. Cargar artículos, clientes y proveedores, o empezar a operar directamente.

### Otras terminales

En cualquier PC de la misma red, abrir el navegador en la dirección del servidor.
No hay que instalar nada. Si no conecta, permitir el puerto 8000 en el Firewall de Windows.

## Roles y módulos

| Rol | Uso típico |
|-----|-----------|
| `administrador` | Acceso total, gestión de módulos, usuarios y configuración |
| `caja` | Cobros, caja, clientes |
| `encargado_ventas` | Ventas, remitos, facturación, stock |
| `encargado_compras` | Proveedores, compras, gastos, stock |
| `encargado_deposito` | Stock / inventario |
| `finanzas` | Caja, cuentas corrientes, IVA, gastos |
| `auditor` | Consulta de todos los módulos, **sin poder modificar nada** |

Los permisos se validan en el servidor contra la tabla `modulos`, la misma que edita el
administrador desde **Menú → Módulos del Sistema**. Ocultar un menú no alcanza: un rol
sin permiso recibe `403` aunque llame la API directamente.

**Módulos:** Stock · Clientes · Ventas · Proveedores · Gastos · Cuentas Corrientes ·
Caja · IVA · Administración.

## Facturación electrónica AFIP

El sistema integra los web services de AFIP (WSAA + WSFEv1) para obtener el **CAE** de
las facturas. Está **desactivada por defecto** y requiere tramitar un certificado digital.

Ver **[docs/AFIP.md](docs/AFIP.md)** para el procedimiento completo.

> El certificado y la clave privada son tu **identidad fiscal**: con ellos un tercero
> puede facturar en tu nombre. Nunca los subas a un repositorio — el `.gitignore` de este
> proyecto ya los excluye.

## Integración con asistentes de IA

ALdia incluye un **servidor MCP** que permite a un asistente personal operar el sistema:
consultar stock y saldos, registrar ventas, cobros y gastos, cerrar la caja del día.

Ver **[mcp/README.md](mcp/README.md)** para instalarlo y conectarlo.

### Errores que un agente puede interpretar

Cada error trae, además del mensaje para la persona, un **código estable** y una
**acción sugerida**, para que el agente no tenga que deducir del texto si conviene
reintentar:

```json
{
  "detail": "Stock insuficiente de 'Coca 2.25': se intentan facturar 12 y hay 5",
  "codigo": "STOCK_INSUFICIENTE",
  "accion": "corregir"
}
```

`accion` es uno de cuatro: **`reintentar`** (era transitorio, sale solo),
**`corregir`** (falta un dato que el agente puede arreglar), **`preguntar`** (hace
falta una decisión que no le corresponde tomar) o **`abortar`** (insistir no va a
cambiar nada). Es lo que evita los dos errores caros: reintentar para siempre algo
que nunca va a andar, o darse por vencido con algo que iba a entrar.

El catálogo completo está en **`GET /api/errores`** y se puede consultar sin
autenticarse — un agente que recibe un `401` tiene que poder averiguar qué significa.

> Un asistente conectado puede **crear comprobantes y mover dinero real**. Creá un
> usuario con rol acotado (por ejemplo `caja`) en vez de darle las credenciales de `admin`.

Si el agente atiende a varias personas, puede declarar por cuál está actuando con la
cabecera `X-Actor-User-Id`, y la operación queda atribuida a esa persona en la auditoría.
Los permisos efectivos son la **intersección**: la operación tiene que estar permitida
para la cuenta del agente **y** para la persona declarada.

Ese permiso **no viene de fábrica**: la impersonación tiene que ser una decisión de
alguien. Se otorga cuenta por cuenta, y solo el administrador puede hacerlo:

```
POST /api/auth/usuarios/{id}/actuar-por     {"habilitado": true}
```

> **Si ya tenías un agente andando**, después de actualizar tenés que otorgarle este
> permiso: hasta que lo hagas, sus llamadas con `X-Actor-User-Id` reciben `403`. Sin la
> cabecera sigue funcionando como siempre, atribuyendo todo a la cuenta del agente.

## Seguridad

El sistema aplica autenticación en toda la API, autorización por rol, límite de intentos
de login (por IP **y por usuario**), validación fiscal y una clave de firma única por
instalación (se genera sola en el primer arranque; no hay claves por defecto en el código).

Cambiar la contraseña **cierra todas las sesiones abiertas** con esa cuenta: el motivo
más común para cambiarla es que alguien la vio, así que un token viejo que siguiera
sirviendo ocho horas más haría inútil el cambio. La respuesta del cambio trae un token
nuevo, así que quien la cambia no se queda afuera.

La interfaz web **no depende de internet**: Bootstrap y sus iconos se sirven desde el
propio servidor (`Web/vendor/`). Un comercio sin conexión sigue facturando.

### Antes de exponerlo a internet

**Es obligatorio poner HTTPS.** Sin certificado, el usuario, la contraseña y el token de
sesión viajan en texto plano y se puede interceptar todo. Usá un proxy inverso con
certificado — [Caddy](https://caddyserver.com/) lo resuelve en pocas líneas, o Nginx con
Let's Encrypt.

Además:

- Cambiá la contraseña de `admin`.
- Definí una clave de sesión propia: `set ALDIA_SECRET_KEY=una-clave-larga-y-secreta`
  (si no, se genera una aleatoria por instalación, que también es segura).
- **Declará tu proxy inverso**: `set ALDIA_PROXIES=127.0.0.1`. Sin esto, el servidor ve
  todas las peticiones como si vinieran del proxy: el límite de intentos deja de
  distinguir atacantes y ocho fallos bastan para bloquear a todo el comercio. Solo se
  confía en `X-Forwarded-For` si la conexión llega desde una IP de esta lista.
- Restringí orígenes si servís el frontend aparte: `ALDIA_ORIGINS=https://tudominio`.
- La documentación interactiva de la API está deshabilitada; se habilita con `ALDIA_DOCS=1`
  solo si la necesitás.

### Reportar una vulnerabilidad

Ver **[SECURITY.md](SECURITY.md)**. En resumen: si es explotable, usá un aviso de
seguridad privado en vez de un issue público; y en cualquier caso, **sin datos reales**
de ningún comercio.

## Otros países

ALdía tiene un **núcleo comercial común y paquetes de país**: no hay un fork por
país. Cambiando `negocio_pais` en la configuración, la misma instalación valida
un EIN en vez de un CUIT, aplica sales tax en vez de IVA y deja de pedir el CAE.

Argentina está completa y en producción. **Estados Unidos es una rebanada
exploratoria**: factura de punta a punta, pero su cálculo de sales tax es una
tasa manual que no contempla nexus, sourcing ni exenciones — no sirve para
cumplir. El propio sistema lo declara en `GET /api/config/pais`.

Ver **[docs/INTERNACIONALIZACION.md](docs/INTERNACIONALIZACION.md)** para el
estado real, lo que falta y en qué orden conviene hacerlo.

## Copias de seguridad

Toda la información se guarda en **`backend/aldia.db`**: clientes, comprobantes,
cuentas corrientes y el registro de auditoría.

**El sistema se hace la copia solo.** Al arrancar, una vez por día, deja un archivo
fechado en `backend/copias/` y conserva los últimos 7. No hay que configurar nada.

| | |
|---|---|
| Dónde | `backend/copias/aldia-AAAA-MM-DD.db` (cambiable con `ALDIA_BACKUP_DIR`) |
| Cuándo | Al arrancar, si no se hizo ya la de hoy |
| Cuántas | 7 días (cambiable con `ALDIA_COPIAS`) |
| Apagarlo | `ALDIA_SIN_RESPALDO=1` |

**Para restaurar:** parar el servidor, copiar el archivo del día que quieras sobre
`backend/aldia.db`, borrar `aldia.db-wal` y `aldia.db-shm` si están, y arrancar.

Dos detalles que hacen que esto sea un respaldo de verdad y no una copia que parece
existir:

- Se usa la **API de respaldo de SQLite**, no un copiar y pegar. La base corre en modo
  WAL, así que las operaciones más recientes viven en `aldia.db-wal` y **no** dentro de
  `aldia.db`: copiar el archivo con el servidor andando produce un respaldo sin las
  últimas ventas del día. La copia que hace el sistema es coherente aunque se esté
  facturando en ese momento, y queda en un archivo único que se restaura solo.
- Cada copia se verifica con `PRAGMA integrity_check` apenas se hace. Un respaldo que
  nadie comprobó es una suposición, y el día que hace falta es tarde para averiguarlo.

> **Esto no te salva del disco que se rompe.** La copia queda en la misma máquina:
> protege contra un borrado accidental o una base corrupta, no contra un incendio ni
> contra ransomware. Sincronizá `backend/copias/` a un pendrive o a la nube — ahora es
> una sola carpeta, y el sistema te lo recuerda por consola en cada arranque.

## Registro de auditoría

Cada operación que **modifica** datos queda asentada automáticamente: quién la hizo,
con qué rol, cuándo, desde qué dirección, sobre qué registro, y —en los cambios
sensibles— **el valor anterior y el nuevo**. También se registran los intentos
**rechazados**, que suelen ser los más reveladores.

```
18/08 10:22  admin     administrador  stock       modificación   artículo 901   [precio: 15.000,00 → 22.500,50]
18/08 10:22  caja1     caja           cta. cte.   cobro          cobro 1        [saldo: 54.451,21 → 34.451,21]
18/08 10:22  caja1     caja           stock       modificación   artículo 901   RECHAZADO (sin permiso)
18/08 10:22  admin     administrador  ventas      anulación      factura 2      [stock: 98 → 100]
```

Se consulta desde **Menú → Auditoría** (administrador y auditor), con filtros por
fecha, usuario, módulo y resultado, y exportación a CSV.

**Es inmutable**: no existe ningún endpoint que lo borre ni lo edite — tampoco para el
administrador. Vive en un esquema separado, de modo que sobrevive incluso al borrado
completo de la base.

> **Límites honestos.** Quien tenga acceso al archivo `backend/aldia.db` puede editarlo
> por fuera de la aplicación sin dejar rastro: ahí la protección son los permisos del
> sistema operativo y las copias de seguridad. Y solo se registran las escrituras, no
> las consultas.

## Estructura del proyecto

```
backend/            API FastAPI
  main.py           arranque, montaje de routers y control de acceso
  security.py       clave de sesión, permisos por rol, anti fuerza bruta
  auditoria.py      registro inmutable de operaciones
  dinero.py         importes en centavos enteros y redondeo comercial
  idempotencia.py   que un reintento no ejecute la operacion dos veces
  errores.py        codigos de error estables para agentes
  paises/           lo que cambia de un pais a otro (AR / US)
  respaldo.py       copia de seguridad automatica y verificada
  tiempo.py         el instante actual, en un solo formato
  afip.py           factura electrónica (WSAA + WSFEv1) y QR fiscal
  models.py         tablas (SQLAlchemy)
  schemas.py        validación (Pydantic): CUIT, IVA, importes
  routers/          un archivo por módulo
Web/                frontend (SPA)
  js/api.js         cliente HTTP de la API
  js/modules/       un archivo por módulo de la interfaz
  vendor/           Bootstrap e iconos servidos localmente (sin CDN)
mcp/                servidor MCP para asistentes de IA
skills/             skills de tareas comerciales
docs/               documentación (AFIP, etc.)
certificados/       certificados de AFIP (ignorado por git)
```

## Pruebas

```bash
.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.venv\Scripts\python.exe -m pytest tests/ -q
```

**169 pruebas** que cubren la exactitud de los importes, la autenticación y los
permisos por rol, la validación fiscal, la idempotencia bajo concurrencia real, el respaldo automatico, y el
circuito comercial completo con sus anulaciones. No hace falta levantar el servidor ni
tocan los datos del comercio: usan una base temporal. Ver [tests/README.md](tests/README.md).

Corren solas en cada push y cada *pull request* (Linux, Python 3.10 y 3.13), y además
una vez con las versiones exactas de `backend/requirements.lock.txt`.

## Contribuir

Las contribuciones son bienvenidas. Ver **[CONTRIBUTING.md](CONTRIBUTING.md)** para
levantar el entorno y correr las pruebas. Las tres reglas que no se negocian:

- No incluyas datos reales de ningún comercio (CUIT, clientes, facturación).
- Si tocás lógica de dinero o stock, explicá cómo lo verificaste.
- Mantené la validación del lado del servidor: el navegador no es una barrera de seguridad.

## Licencia

**GNU Affero General Public License v3.0** — ver [LICENSE](LICENSE).

En términos prácticos:

- ✅ Podés **usarlo gratis**, incluso para tu comercio.
- ✅ Podés **modificarlo** y adaptarlo a tus necesidades.
- ✅ Podés **cobrar** por instalarlo, soportarlo o adaptarlo.
- ⚠️ Si lo modificás y lo ofrecés **como servicio a terceros** (por ejemplo, un SaaS de
  gestión), estás **obligado a publicar el código** de tu versión bajo la misma licencia.

Es decir: el sistema es libre y siempre va a seguir siéndolo. Nadie puede tomar este
código, cerrarlo y venderlo como producto propietario.
