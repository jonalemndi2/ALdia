---
name: usuarios-y-permisos
description: Administración de usuarios, roles y módulos de ALdia - dar de alta al empleado nuevo con el rol que corresponde, darlo de baja cuando se va, y habilitar o restringir módulos del sistema. Usar cuando el usuario diga "dame de alta un usuario", "crear un usuario para", "entró un empleado nuevo", "qué rol le pongo", "no le aparece la pantalla de", "no puede entrar a", "sacale el acceso a", "se fue del negocio", "no uso el módulo de" o "quién tiene acceso a".
---

# Usuarios, roles y módulos (ALdia)

Herramientas MCP del servidor **aldia**. Todo lo de esta skill **requiere rol
administrador**. Si el usuario con el que opera no lo es, las herramientas
devuelven `PERMISO DENEGADO (403)`: dígaselo y no insista.

```
check_connection()   # con qué usuario y rol está operando
```

## Los roles de ALdia

En ALdia el permiso no se da pantalla por pantalla: se da un **rol**, y cada
**módulo** dice qué roles lo ven.

| Rol | Para quién | Qué puede hacer |
| --- | --- | --- |
| `administrador` | el dueño, el encargado general | todo: comprobantes, anulaciones, usuarios, módulos |
| `encargado_ventas` | mostrador, vendedores | stock, clientes, remitos y facturas |
| `encargado_compras` | quien recibe mercadería y trata con proveedores | proveedores, compras, pagos, gastos |
| `encargado_deposito` | depósito | stock: recepción de mercadería e inventario |
| `caja` | cajeros | clientes, cuentas corrientes, caja: cobros y movimientos |
| `finanzas` | administración | caja, cuentas corrientes, gastos, IVA |
| `auditor` | contador, control | **consulta todo y no puede escribir nada** (lo bloquea el backend) |

Criterio para elegir: **el rol más chico con el que la persona pueda hacer su
trabajo**. Un cajero no necesita facturar ni anular; un repositor no necesita
ver la caja. Si el usuario duda, pregúntele qué tareas concretas hace esa
persona y proponga el rol, explicando qué queda afuera.

**No hay rol "sólo lectura de un módulo"**: o el rol ve el módulo entero, o no
lo ve. `auditor` es el único que lee todo sin poder tocar nada.

## Alta de usuario

### Paso 1 — Preguntar antes de crear

1. **Nombre de usuario**: sin espacios, el que va a tipear al entrar
   (`jperez`, `caja2`, `deposito`).
2. **Rol**: de la tabla de arriba.
3. **Contraseña**: **no la invente usted**. Pídasela al usuario (o que la elija
   la persona). Mínimo 8 caracteres. Nunca la repita en la conversación, no la
   escriba en un resumen y no la guarde en ningún archivo: ALdia la almacena
   hasheada con bcrypt y no se puede volver a leer.

### Paso 2 — Crear

```
create_user(usuario="jperez", password="<la que dio el usuario>", rol="caja")
```

La respuesta trae `modulos_que_ve`: **léasela al usuario**. Es la verificación de
que el rol es el correcto, antes de que la persona se encuentre con que no puede
trabajar.

### Paso 3 — Verificar

```
list_users()
```

Confirme que aparece con el rol esperado. Si `rol_reconocido` viene en `false`,
ese usuario tiene un rol que ningún módulo contempla: puede iniciar sesión pero
no ve nada. Corríjalo dando de baja y creando de nuevo con un rol válido.

### Errores frecuentes

| Error | Qué hacer |
| --- | --- |
| `El nombre de usuario ya existe` | buscar el existente con `list_users`; ¿es la misma persona? |
| `Rol invalido: '...'` | usar uno de los siete roles; preguntar qué tiene que poder hacer |
| `La contrasena tiene que tener al menos 8 caracteres` | pedirle otra al usuario |
| `El nombre de usuario no puede tener espacios` | proponer la versión con punto (`juan.perez`) |
| `PERMISO DENEGADO (403)` | hace falta un administrador |

## Baja de usuario

Cuando alguien deja el comercio, **darlo de baja el mismo día**. Un usuario
activo de alguien que ya no trabaja es la forma más común de que se toque la
caja sin que nadie se entere.

```
list_users()                              # ubicar el id
delete_user(user_id=<id>)                  # sin confirmar: devuelve el aviso
delete_user(user_id=<id>, confirmar=true)  # sólo tras la autorización del usuario
```

Es **destructiva**: informe nombre y rol de quien va a borrar, espere la
autorización explícita y recién entonces pase `confirmar=true`.

Lo que la persona hizo **no se borra**: queda en el registro de auditoría con su
nombre (skill de auditoría). Y no se puede eliminar el usuario con el que se está
operando.

**Cambiar la contraseña o el rol de alguien no se puede desde el asistente**: no
hay endpoint de modificación de usuario. Si hay que cambiar un rol, la vía es dar
de baja y volver a crear (avise que se pierde nada más que la ficha, no el
historial); si es una contraseña olvidada, lo resuelve el administrador desde el
sistema.

## Módulos: qué ve cada rol

```
list_modules()
```

Devuelve los nueve módulos (`stock`, `clientes`, `ventas`, `proveedores`,
`gastos`, `cuentas_corrientes`, `caja`, `iva`, `administracion`) con si están
habilitados y qué roles acceden a cada uno.

**"A Fulano no le aparece tal pantalla"** se diagnostica acá, en este orden:

1. `check_connection()` o `list_users()` → ¿qué rol tiene Fulano?
2. `list_modules()` → ¿el módulo está `habilitado`? Si no, está apagado para todo
   el comercio.
3. ¿El rol de Fulano figura en `roles_con_acceso` de ese módulo? Si no, es eso.

### Cambiar la configuración de un módulo

```
configure_module(clave="iva", habilitado=false)
configure_module(clave="caja", roles="administrador,caja,finanzas,encargado_ventas")
```

- `habilitado=false` **apaga el módulo para toda la instalación**: desaparece
  para todos y sus operaciones devuelven error. Se usa cuando el comercio no usa
  esa parte del sistema (un kiosco que no lleva libro IVA).
- `roles` **reemplaza** la lista completa, no agrega. Consulte primero con
  `list_modules()` y mande la lista entera; si no, le saca el acceso a alguien sin
  querer. El rol `administrador` se conserva siempre.

Antes de ejecutar, dígale al usuario **qué cambia y a quiénes afecta**, y espere
la confirmación. Sacar un módulo puede dejar a un empleado sin poder trabajar en
plena jornada.

## Después de cualquier cambio

Todo esto queda auditado. Para mostrarle al usuario qué se hizo:

```
get_audit_log(modulo="administracion", limite=20)
get_audit_log(accion="alta de usuario")
```

Y si alguien reporta que "no lo deja hacer algo", los intentos rechazados por
permisos también quedan registrados:

```
get_audit_log(resultado="rechazado", usuario="jperez")
```

Es la forma más rápida de ver si el problema es de permisos o de otra cosa.
