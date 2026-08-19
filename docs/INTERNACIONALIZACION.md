# Internacionalización — lo que la rebanada vertical dejó en claro

Documento escrito **después** de construir una rebanada vertical de Estados
Unidos sobre el motor existente, no antes. Todo lo que dice está verificado
contra el código y cubierto por `tests/test_paises.py`.

La decisión de fondo: **un núcleo comercial común con paquetes de país**, no un
fork "ALdía USA". Argentina y Estados Unidos corren sobre el mismo motor.

---

## Lo que ya funciona

Cambiando **una clave de configuración** (`negocio_pais`), la misma instalación:

| | `AR` | `US` |
|---|---|---|
| Identificador fiscal | CUIT (11 díg., verificador módulo 11) | EIN (9 díg., formato y prefijo) |
| Impuesto sobre la venta | IVA, lista **cerrada** de alícuotas | Sales tax, lista **abierta** |
| Autorización de comprobantes | CAE de ARCA | ninguna |
| Etiqueta de región | Provincia | State |
| Moneda | ARS | USD |

Y el circuito completo anda: alta de cliente con EIN, producto con 7 % de tasa
(que en Argentina se rechaza porque no es una alícuota legal), factura emitida
sin pasar por ningún organismo, y pedir un CAE devuelve
`OPERACION_NO_APLICA_EN_ESTE_PAIS` con acción `abortar` — el agente distingue
"no aplica" de "falló".

**Argentina no cambió en nada.** Es lo primero que verifica la suite.

## La interfaz: tres preguntas, y a propósito

`backend/paises/base.py` define solo lo que el núcleo necesita preguntar:

1. Cómo se llama y cómo se valida el identificador fiscal.
2. Qué impuesto se aplica y qué tasas son legítimas.
3. Si un comprobante necesita autorización de un organismo antes de valer.

Se diseñó al revés de lo natural. La tentación era crear `countries/argentina/`
y `countries/usa/` con un archivo espejo para cada tema —impuestos, facturación,
identificadores, documentos fiscales—. Suena ordenado y sale mal: hoy hay **una
implementación real** (Argentina: WSAA, WSFEv1, CAE, QR, ~1600 líneas) y **una
casi vacía** (EE.UU. no tiene factura electrónica obligatoria). Una abstracción
diseñada desde un caso pesado y uno vacío termina con la forma exacta de
Argentina y un agujero enfrente.

Por eso AFIP **no se movió** de `backend/afip.py`. Lo único que se extrajo es el
interruptor `requiere_autorizacion_fiscal`, y el núcleo nunca aprende qué es un
CAE.

> Regla para lo que venga: una pregunta nueva se agrega a la interfaz cuando
> **dos países** la necesitan de verdad, no cuando uno la podría llegar a usar.

## Lo que el núcleo ni se entera

Auditoría, idempotencia, operaciones pendientes, permisos por rol, secuencias de
comprobantes, dinero en centavos enteros, concurrencia WAL. Nada de eso se tocó
y hay pruebas de que sigue funcionando igual con la instalación en `US`.

Es la mayor parte del sistema, y es la razón por la que esto es un paquete de
país y no un fork.

---

## Lo que la rebanada destapó, y hay que resolver antes de seguir

### 1. El identificador fiscal era la PRIMARY KEY ✅ resuelto

```
clientes.cuit      → PRIMARY KEY
proveedores.cuit   → PRIMARY KEY
```

y **8 tablas** apuntan con `ForeignKey("clientes.cuit", ondelete="RESTRICT")`.
Además es la identidad en la URL (`/api/clientes/{cuit}`) y en las tools del MCP.

Y no era una molestia estética: **un cliente cargado con el identificador mal
tipeado que ya tenía facturas quedaba con ese número para siempre.** No se podía
editar —la identidad de una fila no se edita, y `ClienteUpdate` ni siquiera
aceptaba el campo— ni borrar y volver a cargar, porque la integridad referencial
lo impide en cuanto hay un comprobante emitido. Con razón: una factura no puede
quedar sin titular. El único arreglo era abrir el `.db` a mano.

**Cómo quedó resuelto.** `clientes` y `proveedores` tienen ahora `id` entero
propio como clave primaria; el identificador fiscal pasó a ser un atributo
`UNIQUE NOT NULL`, y se sumó `tax_id_type` (CUIT / EIN), sembrado según el país.
Las 14 claves foráneas se recrearon con `ON UPDATE CASCADE`, así que corregir un
identificador arrastra facturas, remitos, cobros y pagos en una sola transacción.

`POST /api/clientes/{id}/identificacion` (y su par en proveedores) hace la
corrección. Exige repetir el valor nuevo: cambia un dato fiscal que ya figura en
comprobantes emitidos, y para un agente eso tiene que ser una decisión del
usuario — el error es `CONFIRMACION_REQUERIDA`, cuya acción es `preguntar`.

La migración (`aplicar_identidad_subrogada`) reconstruye las 16 tablas con los
mismos candados que ya usaba el proyecto: recuento de filas, `foreign_key_check`
y *rollback* total. Si hay identificadores repetidos o vacíos —lo típico de una
base importada del sistema anterior— **no migra**, lo informa y deja la base como
estaba, en vez de romperle el arranque al comercio.

> **Lo que esto destapó.** La primera versión declaraba la columna con
> `unique=True, index=True`. Con las dos cosas, SQLAlchemy emite la unicidad
> como un `CREATE UNIQUE INDEX` **aparte**, que la reconstrucción de tablas no
> ejecuta: `clientes` quedaba sin índice único y SQLite invalidaba todas las
> claves foráneas que la referencian (`foreign key mismatch`). Lo atajó el
> candado de la migración sobre una base real, no la suite — el test sintético
> no tenía tablas hijas y por eso no lo veía. Ahora sí las tiene.

**Lo que queda,** y es mecánico: la columna todavía se llama `cuit` en la base,
por los 14 destinos de FK, las 48 referencias del MCP y el frontend. La API ya
expone `tax_id` y `tax_id_type` al lado de `cuit`, así que lo nuevo se puede
escribir con nombres neutros y el rename es una limpieza posterior sin apuro.

### 2. El producto estaba solo en castellano ✅ mecanismo resuelto

**Cómo quedó resuelto, y por qué no se tradujeron los 68 mensajes a mano.**

Envolver cada string en una función de traducción funciona y tiene dos problemas
que se ven recién después: cada mensaje nuevo nace sin traducir y nada lo
detecta, y traducir texto libre bien exige entender el contexto de negocio de
cada uno.

Ya existía una costura mejor, construida para otra cosa: **los códigos de
error**. `STOCK_INSUFICIENTE` significa lo mismo en Villa Huidobro y en Miami.
Así que la traducción se cuelga del código, no del texto. Los errores viajan
ahora con `params`:

```json
{
  "detail": "Stock insuficiente de 'Coca 2.25': se piden 12 y hay 5",
  "codigo": "STOCK_INSUFICIENTE",
  "accion": "corregir",
  "params": { "producto": "Coca 2.25", "pedido": 12, "disponible": 5 }
}
```

Con el código y los parámetros, **cualquier cliente arma el mensaje en el idioma
que quiera sin que el servidor traduzca**. El navegador lo hace en
`Web/js/i18n.js`; un agente ni siquiera necesita prosa. Y `detail` sigue
viniendo siempre, en el idioma de la instalación, así que nada de lo que ya
existía se rompe.

El idioma sale de `negocio_locale`, y si está vacío **se hereda del país**: una
instalación estadounidense habla inglés sin configurar nada. Se cambia en
caliente, sin reiniciar.

**Degradación honesta:** un código sin plantilla devuelve el texto original en
castellano, y una plantilla a la que le falta un parámetro también — un mensaje
útil en otro idioma es mejor que `errors.stock.insufficient` en la cara del
cajero. `idiomas.faltantes()` lista lo que falta, y hay una prueba que lo mide:
la deuda de traducción es visible en la suite en vez de descubrirla un usuario.

**Lo que queda sin traducir, y es deliberado:** las 13 skills siguen solo en
castellano —son instrucciones de negocio densas, y traducirlas mal es peor que
no traducirlas— y la mayoría de los rótulos profundos de la UI. El mecanismo
está; poblar los diccionarios es trabajo incremental que ya no requiere decisiones.

### 3. El sales tax de esta rebanada NO sirve para cumplir 🟠

Está dicho en `backend/paises/estados_unidos.py` y se publica en
`GET /api/config/pais` — a propósito: un límite conocido que no se declara es
peor que no tener la función.

Lo que hace: aplica **una tasa cargada a mano**, igual para todo. Correcto solo
para un comercio con una ubicación, venta presencial y obligación en una sola
jurisdicción.

Lo que no hace, y hace falta para cumplir de verdad: determinar la jurisdicción
(estado + condado + ciudad + distritos especiales, del orden de 13.000
combinaciones), criterio de origen o destino según el estado, nexus económico,
categorías exentas (alimentos, ropa, medicamentos) y certificados de exención de
mayoristas.

Nada de eso se codea adentro de ALdía y se mantiene actualizado. Para eso está
la interfaz: se enchufa un proveedor especializado sin tocar el núcleo.

> **Tensión a decidir antes de enchufarlo.** ALdía es AGPL, corre en la PC del
> comercio y funciona sin internet — tanto que en este mismo repo se le sacó la
> dependencia del CDN para lograrlo. Un proveedor de cálculo fiscal es un
> servicio pago y en línea. La salida sana es que sea **opcional**, con la tasa
> manual como respaldo, y que el sistema nunca deje de facturar porque se cayó
> la conexión.

### 4. No hay entidad "Empresa", y eso abarata todo 🟢

ALdía es **monoinquilino**: un archivo SQLite por comercio, y `configuracion` es
clave/valor. Así que país, moneda, locale y zona horaria son **claves nuevas en
una tabla que ya existe**. Casi gratis.

No construir una entidad `Empresa` salvo que se quiera SaaS multiinquilino de
verdad — lo cual pelea de frente con AGPL + un archivo por comercio, que hoy es
buena parte del atractivo del proyecto.

---

## Orden sugerido

Difiere del orden intuitivo, y por dos motivos concretos: lo de mayor radio va
primero, y lo que determina si el país es viable se prototipa temprano.

1. ~~**Identidad**: PK subrogada + `tax_id`/`tax_id_type`~~ ✅ **hecho**.
2. ~~**i18n**: catálogo de mensajes, aprovechando los códigos de error~~ ✅
   **mecanismo hecho**; falta poblar diccionarios y traducir las skills.
3. **Dirección internacional**: `address_line_1/2`, `city`, `region`,
   `postal_code`, `country_code`. Barato y no depende de nada.
4. **Moneda explícita** en los importes que salen de la API. El núcleo de
   centavos enteros ya sirve tal cual para ARS y USD.
5. **Medios de pago**: generalizar a `PaymentMethod` y sumar ACH. El módulo de
   cheques **no se tira** — en EE.UU. los cheques comerciales siguen existiendo;
   lo que se internacionaliza son campos y estados.
6. **Sales tax enchufable** con proveedor externo opcional (punto 3).
7. **Datos de proveedores EE.UU.**: `legal_name`, `DBA`, `TIN`, estado del W-9,
   elegibilidad 1099. Preparar el modelo; **no** generar 1099 todavía.

## Lo que sigue igual, y no hay que romper

- **El MCP no conoce países.** Las tools expresan intenciones comerciales
  (`crear_factura`, `registrar_cobro`), nunca `crear_factura_afip`. Hoy ya es
  cierto estructuralmente: el MCP habla HTTP contra la misma API que el
  navegador. El mismo mensaje —*"John me pagó la factura con este cheque"*—
  funciona en los dos países sin que el agente sepa de impuestos.
- **Un país nuevo no debería tocar el núcleo.** Si para agregar uno hay que
  editar algo fuera de `backend/paises/`, la interfaz quedó corta y hay que
  arreglarla ahí, no parchear el core.
- **Los límites conocidos se publican.** `GET /api/config/pais` devuelve
  `advertencias`. Un paquete de país que no declara lo que no hace es una
  trampa para quien lo instale.
