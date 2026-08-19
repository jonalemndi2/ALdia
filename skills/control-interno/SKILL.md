---
name: control-interno
description: Control interno y auditoría en ALdia - saber quién hizo cada operación, investigar una anulación o un cambio de precio, revisar qué pasó en un turno, detectar intentos rechazados por falta de permisos, y verificar que la contabilidad no se haya desviado. Usar cuando el usuario diga "quién anuló", "quién cambió el precio", "quién tocó la caja", "qué pasó ayer", "revisar el turno de", "auditoría", "no me cierra la cuenta" o sospeche de un error o un manejo indebido.
---

# Control interno (ALdia)

Esta skill se usa cuando algo **no cuadra** o cuando hay que rendir cuentas. Es
un terreno delicado: se está hablando de la conducta de personas concretas que
trabajan en el negocio. Informe **hechos registrados**, nunca conclusiones sobre
intenciones.

## Qué registra el sistema

Toda operación que **modifica** datos queda asentada automáticamente: usuario,
rol, fecha y hora, módulo, qué registro tocó, la dirección de origen y —en los
cambios sensibles— **el valor anterior y el nuevo**. También quedan los intentos
**rechazados**.

Y lo que **no** registra, que hay que decir cuando es relevante:

- **Las consultas no dejan rastro.** No se puede saber quién *miró* la lista de
  deudores; solo quién la modificó.
- Quien tenga acceso al archivo de base de datos puede editarlo por fuera del
  sistema sin dejar rastro. La protección ahí son los permisos del equipo y las
  copias de seguridad.

Dígalo si el usuario va a tomar una decisión seria basándose en el registro.

## Paso 1 — Buscar

```
get_audit_log(fecha_desde="2026-08-17", fecha_hasta="2026-08-17")   # un día
get_audit_log(usuario="caja1")                                      # una persona
get_audit_log(modulo="ventas", accion="anulacion")                  # un tipo de hecho
get_audit_log(resultado="rechazado")                                # intentos fallidos
get_audit_log(texto="factura 32")                                   # un registro puntual
```

Combine los filtros para acotar. Para "¿quién anuló la factura 32?", lo directo
es `texto="factura 32"` y mirar la fila de anulación.

## Paso 2 — Leer bien lo que devuelve

Cada fila trae `valor_anterior` y `valor_nuevo` cuando el cambio los tiene. Ahí
está el hecho concreto:

```
18/08 10:22  admin   administrador  stock    modificación  artículo 901
             [precio: 15.000,00 → 22.500,50]
```

Traduzca a lenguaje llano: *"El 18/08 a las 10:22, admin cambió el precio del
artículo 901 de $15.000,00 a $22.500,50"*. No diga "aumentó el precio un 50 %
sin autorización": eso es una interpretación.

## Paso 3 — Los intentos rechazados son lo más interesante

```
get_audit_log(resultado="rechazado", fecha_desde="...")
```

Un rechazo aislado suele ser un error honesto: alguien entró a la pantalla
equivocada. **Un patrón** —la misma persona intentando repetidamente escribir en
un módulo que no le corresponde— es otra cosa, y merece mencionarse como patrón,
no como acusación.

Los rechazos típicos y su lectura:

| Rechazo | Lectura probable |
|---|---|
| 403 por módulo | La persona necesita ese permiso para su tarea, o se equivocó de pantalla |
| 403 "auditor es de solo consulta" | El rol auditor no puede modificar: es por diseño |
| 401 en login | Contraseña mal tipeada; muchos seguidos, revisar |
| 400 por regla de negocio | Stock insuficiente, CUIT inválido: error de carga |

## Paso 4 — Cuando el problema es que "no cierra la cuenta"

Antes de sospechar de alguien, descarte el error de sistema. Los saldos de
clientes y proveedores son datos derivados y el sistema puede verificarlos
recalculándolos desde los movimientos (**Menú → Chequear Base de Datos**, o el
endpoint de verificación de saldos).

Si hay diferencias, informelas con nombre, CUIT e importe, y aclare que
**corregirlas es una decisión contable** que debe tomar el dueño o el contador,
no el asistente.

## Cómo informar

Sea factual, cronológico y breve. Ejemplo:

```
Factura 32 — historia completa

  18/08 09:22   ventas1 (encargado_ventas)   emitió la factura   $ 18.150,00
  18/08 10:03   admin   (administrador)      la anuló
                        cliente: saldo 34.451,21 → 16.301,21
                        stock artículo 901: 98 → 100

  El sistema no guarda un motivo de anulación. Para saber por qué se anuló,
  hay que preguntarle a admin.
```

Esa última línea importa: **decir qué NO sabe el registro** es parte de informar
bien.

## Reglas de conducta

- No saque conclusiones sobre honestidad ni intenciones. Presente los hechos.
- Si el usuario pide "probar" algo con el registro, aclare los límites: el
  registro prueba qué se hizo desde el sistema, no quién estaba frente a la
  pantalla. Si varias personas comparten el usuario `admin`, no distingue.
- Si detecta que varias personas comparten un mismo usuario, señálelo: es lo
  que más degrada el valor de la auditoría, y se resuelve creando un usuario por
  persona (ver la skill `usuarios-y-permisos`).
- El registro **no se puede borrar ni editar** desde el sistema, tampoco por el
  administrador. Si le piden hacerlo, explique que no existe esa función y que
  esa es justamente la razón por la que sirve.
