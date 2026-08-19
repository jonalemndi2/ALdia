---
name: puesta-en-marcha
description: Configuración inicial de ALdia en un negocio nuevo - cargar los datos fiscales del comercio, crear los usuarios del personal con su rol, habilitar solo los módulos que se usan, y cargar el stock, los clientes y los proveedores iniciales. Usar cuando el usuario diga "recién instalé", "empezar a usarlo", "configurar el sistema", "poner los datos de mi negocio", "cargar todo por primera vez", "dar de alta a mis empleados" o pregunte por dónde empezar.
---

# Puesta en marcha (ALdia)

ALdia arranca con la base **vacía**: sin clientes, sin artículos, sin
comprobantes, y con un único usuario `admin`. Esta skill acompaña el primer día.

El orden importa: lo que se configura primero condiciona lo que se carga después.

## Paso 1 — Datos fiscales del comercio (antes que nada)

```
get_business_config()
```

Se cargan desde **Menú → Configuración del Negocio**. Guíe al usuario para
completar:

- **Nombre del comercio** — aparece en la barra superior y en los comprobantes.
- **CUIT** del negocio.
- **Condición frente al IVA** — la más importante: **decide si emite facturas
  A/B o C**. Un monotributista emite siempre C; un responsable inscripto emite A
  a otros responsables inscriptos y B al resto.
- **Punto de venta** — el habilitado en AFIP. Si va a usar factura electrónica,
  tiene que ser un punto de venta **de tipo Web Services**, no el de
  Comprobantes en Línea.
- Dirección y teléfono, que salen impresos.

**Hágalo antes de facturar.** Si la condición frente al IVA está mal, todos los
comprobantes salen con el tipo equivocado y AFIP los rechaza.

## Paso 2 — Cambiar la contraseña de admin

La contraseña inicial (`admin123`) es pública: está en la documentación del
proyecto. Insista en cambiarla antes de cargar nada real.

## Paso 3 — Un usuario por persona

Este es el paso que más se saltea y el que más caro sale después.

```
list_users()
create_user(username="maria", password="...", rol="caja")
```

Roles disponibles y para quién:

| Rol | Para quién |
|---|---|
| `administrador` | El dueño. Acceso total. |
| `caja` | Cajeros: cobros, caja, clientes. |
| `encargado_ventas` | Mostrador y facturación: ventas, remitos, stock. |
| `encargado_compras` | Compras: proveedores, gastos, stock. |
| `encargado_deposito` | Depósito: solo stock. |
| `finanzas` | Administración: caja, cuentas corrientes, IVA, gastos. |
| `auditor` | Contador o control: **ve todo, no modifica nada**. |

**Por qué importa:** el sistema registra quién hizo cada operación. Si tres
personas comparten `admin`, ese registro no sirve para nada. Dígaselo al usuario
con esas palabras — es la diferencia entre poder investigar una diferencia de
caja y no poder.

Los permisos se validan en el servidor, así que un rol no puede hacer lo que no
le corresponde ni aunque conozca el atajo.

## Paso 4 — Habilitar solo lo que se usa

```
list_modules()
configure_module(clave="iva", habilitado=false)     # ejemplo: no lo usa
```

Un kiosco quizá no necesite Remitos ni Cuentas Corrientes. Menos módulos =
menos pantallas para el personal = menos errores. Se puede volver a habilitar en
cualquier momento.

## Paso 5 — Cargar los datos iniciales

En este orden, porque cada uno depende del anterior:

1. **Proveedores** — `create_vendor(...)`. Se necesitan para cargar compras.
2. **Artículos** — `create_product(...)` con código, descripción, unidad, precio
   de venta y alícuota de IVA. Si va a cargar el stock con una compra real,
   puede dar de alta el artículo en cero y que la compra lo llene.
3. **Clientes** — `create_customer(...)`. Solo hacen falta los de **cuenta
   corriente**; las ventas de mostrador no necesitan ficha. Cargue la
   **condición frente al IVA** de cada uno: define si se le factura A, B o C.

Para cargas grandes, proponga hacerlo por tandas y confirmar cada tanda, en vez
de aceptar una lista larga sin verificar.

## Paso 6 — Factura electrónica (opcional, después)

Viene **deshabilitada** y requiere un certificado digital de AFIP a nombre del
comercio. No es parte del primer día: el sistema factura internamente sin ella.
Cuando el usuario quiera activarla, remítalo a `docs/AFIP.md`, que tiene el
trámite paso a paso.

Mientras no esté configurada, los comprobantes salen marcados como **documento
no fiscal**, que es lo correcto: no tienen CAE.

## Paso 7 — Copias de seguridad

Antes de que el sistema tenga datos que duelan, deje resuelto el respaldo. Toda
la información vive en un solo archivo (`backend/aldia.db`): alcanza con
copiarlo periódicamente a otro disco o a la nube, preferentemente con el
servidor detenido.

Es la conversación menos interesante del primer día y la más importante del día
que falle el disco.

## Cierre

Termine con un checklist de lo que quedó hecho y lo que falta:

```
Puesta en marcha
  ✓ Datos del comercio (CUIT, condición IVA, punto de venta)
  ✓ Contraseña de admin cambiada
  ✓ 3 usuarios creados (maría/caja, juan/ventas, contador/auditor)
  ✓ Módulos: deshabilitado Remitos (no se usa)
  ✓ 45 artículos, 12 proveedores, 8 clientes de cuenta corriente
  · Pendiente: certificado de AFIP para factura electrónica
  · Pendiente: definir dónde se guarda la copia de seguridad
```
