---
name: alta-de-cliente-o-proveedor
description: Alta y corrección de fichas de clientes y proveedores en ALdia, con CUIT validado y condición frente al IVA (que decide si se le factura A, B o C). Usar cuando el usuario diga "dame de alta a", "cargá este cliente", "cliente nuevo", "proveedor nuevo", "abrile cuenta corriente a", "anotá los datos de", "es responsable inscripto", "me pasó el CUIT" o dicte los datos de una constancia de inscripción de AFIP.
---

# Alta de clientes y proveedores (ALdia)

Herramientas MCP del servidor **aldia**. Cliente y proveedor son dos fichas casi
idénticas —CUIT, nombre, domicilio, contacto y saldo de cuenta corriente— con
una diferencia que importa mucho:

| | Cliente | Proveedor |
| --- | --- | --- |
| Herramienta | `alta_cliente` | `alta_proveedor` |
| Saldo positivo significa | **el cliente me debe** | **yo le debo al proveedor** |
| Condición frente al IVA | **sí, y decide el comprobante** | no se guarda |

## Paso 0 — Fijarse si ya existe

Antes de dar de alta, **busque**. El alta falla si el CUIT ya está cargado, y un
cliente duplicado parte la cuenta corriente en dos.

```
buscar_cliente(texto="<nombre o CUIT>")
buscar_proveedor(texto="<nombre o CUIT>")
```

Busque por las dos puntas: por nombre ("Distribuidora") y por CUIT. ALdia guarda
algunos CUIT con guiones y otros sin, y la búsqueda contempla las dos formas.

## Paso 1 — Juntar los datos

Obligatorios: **CUIT** y **nombre**. Para un cliente, además, la **condición
frente al IVA**.

Lo demás (domicilio, localidad, provincia, código postal, teléfono, mail) es
opcional, pero pida al menos el **teléfono del cliente**: es con lo que después
se le reclama la deuda (ver la skill de cobranzas), y un deudor sin teléfono es
una cobranza que no se puede hacer.

Si el usuario le está leyendo una constancia de inscripción de AFIP, ahí están
todos: CUIT, razón social, domicilio fiscal e "impuestos" (que dicen si es
responsable inscripto o monotributista).

## Paso 2 — La condición frente al IVA (sólo clientes)

Es un dato **fiscal**, no administrativo. Cruzado con la condición del negocio,
determina qué comprobante hay que emitirle:

| Negocio | Cliente | Comprobante |
| --- | --- | --- |
| Responsable inscripto | Responsable inscripto | **Factura A** (IVA discriminado) |
| Responsable inscripto | Monotributista, exento o consumidor final | **Factura B** (IVA incluido) |
| Monotributista o exento | cualquiera | **Factura C** (sin IVA discriminado) |

Valores válidos: `responsable_inscripto`, `monotributo`, `exento`,
`consumidor_final`, `no_responsable`. Si el usuario dice "RI", "monotributista"
o "consumidor final", la herramienta lo traduce sola.

Para saber cómo está inscripto el negocio:

```
ver_configuracion_negocio()
```

Devuelve la condición del comercio y, en
`comprobante_por_condicion_del_cliente`, qué clase de comprobante sale para cada
tipo de cliente en esta instalación.

**No adivine la condición.** Si el usuario no la sabe, el valor por defecto es
`consumidor_final` — es el más conservador (sale factura B), pero avísele que si
el cliente es responsable inscripto va a querer su factura A con el IVA
discriminado, y que corregirlo después obliga a rehacer comprobantes.

## Paso 3 — Dar el alta

```
alta_cliente(
  cuit="30-71234567-1",
  nombre="Distribuidora del Litoral SRL",
  condicion_iva="responsable_inscripto",
  domicilio="San Martín 1234", localidad="Rosario", provincia="Santa Fe",
  cp="2000", telefono="3411234567", mail="pagos@ejemplo.com"
)
```

```
alta_proveedor(cuit="30-71234567-1", nombre="Frigorífico ...", telefono="...")
```

La respuesta del alta de cliente le dice qué comprobante le corresponde
(`comprobante_que_le_corresponde`). Repítaselo al usuario: es la confirmación de
que la condición quedó bien cargada.

## El CUIT: cómo se valida y qué hacer si falla

ALdia valida el CUIT con el **dígito verificador** (módulo 11), no sólo la
cantidad de dígitos. Un CUIT inventado o con dos cifras cambiadas de lugar se
rechaza con:

```
DATOS INVALIDOS (422) en POST /api/clientes/: cuit: CUIT invalido:
el digito verificador no corresponde (30-71234567-0)
```

Qué hacer:

1. **Pedirle al usuario que lo relea** del comprobante o de la constancia. La
   causa número uno es un dígito tipeado al revés.
2. **Nunca "corregirlo" usted.** Cambiar el último dígito hasta que valide crea
   una ficha con el CUIT de otro contribuyente: los comprobantes salen a nombre
   equivocado y AFIP los rechaza o los imputa mal.
3. Si el cliente no tiene CUIT (consumidor final que sólo tiene DNI), avísele al
   usuario: ALdia exige CUIT de 11 dígitos para abrir ficha. Una venta a
   consumidor final sin identificar no necesita ficha; se cobra de mostrador
   (`registrar_movimiento_caja`) y no va a cuenta corriente.

Otros errores frecuentes:

| Error | Qué pasó | Qué hacer |
| --- | --- | --- |
| `El CUIT debe tener 11 digitos` | faltan o sobran cifras | releer el CUIT completo |
| `El nombre del cliente es obligatorio` | vino vacío | preguntar la razón social |
| `Condicion frente al IVA invalida` | condición mal escrita | usar una de las cinco válidas |
| `PERMISO DENEGADO (403)` | el rol no tiene el módulo `clientes` / `proveedores` | decírselo al usuario y no reintentar |
| El CUIT ya existe | la ficha estaba cargada | buscarla y usarla; no duplicar |

## Corregir una ficha ya cargada

**No hay herramienta MCP de modificación de ficha.** Si hay que cambiar un
teléfono, un domicilio o la condición frente al IVA de alguien ya cargado,
dígale al usuario que lo edite desde el sistema (módulo Clientes o Proveedores,
botón de edición) — y aclare por qué importa: cambiar la condición frente al IVA
no rehace los comprobantes ya emitidos.

El **CUIT no se puede cambiar** en ninguna de las dos: es la clave de la ficha y
de toda su cuenta corriente. Si está mal, hay que dar de alta la ficha correcta
y migrar los movimientos a mano desde el sistema.

## Después del alta

- Cliente nuevo que arranca con deuda anterior: **no la cargue con un
  movimiento de caja**. Emítale la factura que corresponda (skill de
  facturación) o pídale al usuario que aclare de dónde viene ese saldo.
- Proveedor nuevo: ya se le pueden cargar compras y gastos (skill de carga de
  comprobantes).
- Verifique siempre con `buscar_cliente` / `buscar_proveedor` que la ficha quedó
  y muéstresela al usuario con el saldo en 0.
