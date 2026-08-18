# ALdia — Sistema de Gestión Comercial

Sistema de gestión comercial libre, pensado para **comercios, kioscos y supermercados
pequeños** de Argentina. Funciona en red local con un servidor central: varias
terminales (cajas, administración, depósito) acceden desde el navegador a un único
servidor que guarda todos los datos.

Incluye stock, clientes, proveedores, remitos, facturación, cuentas corrientes, caja,
chequera, gastos y libro IVA — con **control de acceso por rol** y **validación fiscal
argentina** (CUIT con dígito verificador, alícuotas de IVA vigentes).

> **Estado del proyecto.** El sistema está funcionando y auditado (ver [BITACORA.md](BITACORA.md)).
> Antes de exponerlo a internet leé la sección [Seguridad](#seguridad): **hace falta HTTPS**.

## Índice

- [Arquitectura](#arquitectura)
- [Instalación](#instalación)
- [Roles y módulos](#roles-y-módulos)
- [Facturación electrónica AFIP](#facturación-electrónica-afip)
- [Integración con asistentes de IA](#integración-con-asistentes-de-ia)
- [Seguridad](#seguridad)
- [Copias de seguridad](#copias-de-seguridad)
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
3. Ejecutar **`iniciar_web.bat`** para arrancar el sistema.

El script muestra la dirección para conectarse desde otras PCs:

```
En esta PC (servidor):   http://localhost:8000
Desde otras PCs:         http://192.168.0.10:8000
```

### Primer ingreso

- **Usuario:** `admin` · **Contraseña:** `admin123`

> ⚠️ **Cambiá la contraseña del administrador apenas ingreses.** Es pública en esta
> documentación y en el código.

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

> Un asistente conectado puede **crear comprobantes y mover dinero real**. Creá un
> usuario con rol acotado (por ejemplo `caja`) en vez de darle las credenciales de `admin`.

## Seguridad

El sistema aplica autenticación en toda la API, autorización por rol, límite de intentos
de login, validación fiscal y una clave de firma única por instalación (se genera sola en
el primer arranque; no hay claves por defecto en el código).

### Antes de exponerlo a internet

**Es obligatorio poner HTTPS.** Sin certificado, el usuario, la contraseña y el token de
sesión viajan en texto plano y se puede interceptar todo. Usá un proxy inverso con
certificado — [Caddy](https://caddyserver.com/) lo resuelve en pocas líneas, o Nginx con
Let's Encrypt.

Además:

- Cambiá la contraseña de `admin`.
- Definí una clave de sesión propia: `set ALDIA_SECRET_KEY=una-clave-larga-y-secreta`
  (si no, se genera una aleatoria por instalación, que también es segura).
- Restringí orígenes si servís el frontend aparte: `ALDIA_ORIGINS=https://tudominio`.
- La documentación interactiva de la API está deshabilitada; se habilita con `ALDIA_DOCS=1`
  solo si la necesitás.

### Reportar una vulnerabilidad

Abrí un *issue* describiendo el problema **sin incluir datos reales** de ningún comercio.

## Copias de seguridad

Toda la información se guarda en **`backend/aldia.db`**. Para respaldar, copiá ese
archivo (preferentemente con el servidor detenido). Para restaurar, reemplazalo.

Automatizar esta copia es responsabilidad de quien instala el sistema: una tarea
programada que copie el archivo a otro disco o a la nube.

## Estructura del proyecto

```
backend/            API FastAPI
  main.py           arranque, montaje de routers y control de acceso
  security.py       clave de sesión, permisos por rol, anti fuerza bruta
  models.py         tablas (SQLAlchemy)
  schemas.py        validación (Pydantic): CUIT, IVA, importes
  routers/          un archivo por módulo
Web/                frontend (SPA)
  js/api.js         cliente HTTP de la API
  js/modules/       un archivo por módulo de la interfaz
mcp/                servidor MCP para asistentes de IA
skills/             skills de tareas comerciales
docs/               documentación (AFIP, etc.)
BITACORA.md         registro de la auditoría y las correcciones
```

## Contribuir

Las contribuciones son bienvenidas. Al enviar un *pull request*:

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
