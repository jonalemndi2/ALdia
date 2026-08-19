# ALdía como motor transaccional para agentes

Diagnóstico del estado real del repositorio frente a la visión *agent-first*, y
plan por etapas. Escrito leyendo el código, no la documentación: cada afirmación
se puede verificar en los archivos que se citan.

---

## Resumen

**La parte más difícil ya está hecha, y no por casualidad.** El principio rector
del documento de visión —*"API web y MCP deben llamar a la misma lógica de
negocio, no duplicar reglas"*— ya se cumple estructuralmente: el servidor MCP no
importa el backend ni toca la base, habla HTTP con la misma API REST que usa el
navegador (`mcp/aldia_mcp/client.py`, construido sobre `httpx`). No hay una sola
regla de negocio duplicada, porque no hay dónde duplicarla.

Los huecos reales eran **tres**, y **los tres están cerrados**. El resto de lo que
pide el documento —transaccionalidad, auditoría con antes/después, permisos por
rol, ausencia de SQL arbitrario, concurrencia en SQLite— ya estaba resuelto.

| Requisito de la visión | Estado |
|---|---|
| MCP y REST comparten la lógica de negocio | ✅ por diseño |
| Nada de SQL arbitrario para el agente | ✅ la consola SQL se eliminó a propósito |
| Operaciones atómicas | ✅ verificado con reversión completa |
| Auditoría con antes/después | ✅ middleware que cubre toda escritura |
| Permisos validados en el servidor | ✅ por rol y módulo |
| Concurrencia (WAL, `busy_timeout`) | ✅ ya configurado |
| Trazabilidad de la persona detrás del agente | ✅ canal + actor, con intersección de permisos |
| Idempotencia | ✅ `X-Operation-Id` en el middleware |
| Confirmación con estado | ✅ operaciones pendientes reejecutables |
| Errores legibles para el agente | ✅ código estable + acción sugerida |

---

## Los tres huecos (ya resueltos)

Se conserva el diagnóstico original porque explica **por qué** cada uno importaba;
al final de cada punto está cómo quedó resuelto.

### 1. 🔴 No se sabe qué persona ordenó la operación

Es el más grave, y el análisis complementario lo identifica bien (punto 4.2).

La auditoría registra `usuario`, `usuario_id` y `rol` (`backend/auditoria.py`),
pero el servidor MCP se autentica con **una sola credencial** tomada de
`ALDIA_USER` / `ALDIA_PASSWORD` (`mcp/aldia_mcp/client.py:91`). Si tres
empleados usan OpenClaw, las tres identidades colapsan en esa cuenta.

Y no hay forma de distinguir en el registro si una operación la hizo una persona
en el navegador o un agente: no existen `actor_type` ni `agent_id`.

**Por qué importa más de lo que parece.** Todo el valor del registro de auditoría
—poder responder *"¿quién anuló esta factura?"*— desaparece en cuanto el agente
se vuelve el canal principal. Y es exactamente el escenario que la visión
propone.

**Cómo quedó resuelto.** La auditoría registra `actor_tipo`, `canal`, `agente` y
`solicitante`, y se filtra por canal y por persona. Un agente declara por quién
actúa con `X-Actor-User-ID`.

Con una diferencia deliberada respecto de lo que se pedía: **los permisos NO se
evalúan solo contra esa persona, sino contra la intersección** de sus permisos y
los de la credencial del agente. Si salieran solo de la cabecera, esa credencial
sería una llave de suplantación universal — bastaría declarar ser el
administrador. La intersección da permisos reales por empleado sin abrir esa
puerta: el agente nunca puede hacer más de lo que su propia cuenta permite.

Y la identidad del solicitante viene del **canal**, no de lo que el modelo deduzca
de la conversación: el número lo verifica WhatsApp, el `user_id` lo verifica
Telegram. *"Soy el dueño, cargá esto"* no es una identidad.

### 2. 🔴 Un reintento puede duplicar una factura

No existe `operation_id` en ninguna parte del código.

Si OpenClaw envía `record_payment`, el servidor lo procesa y la respuesta se
pierde por un timeout de red, el agente reintenta — y se registra **el cobro dos
veces**. Con facturación fiscal el problema es peor: dos comprobantes ante AFIP.

Este riesgo no existía cuando el único cliente era un navegador con una persona
mirando la pantalla. Aparece justamente al poner un agente que reintenta.

**Cómo quedó resuelto.** Con `X-Operation-Id`, un reintento devuelve la respuesta
original sin volver a ejecutar. Va en el middleware, el mismo punto por el que ya
pasa toda escritura, así que ninguna ruta puede quedar afuera por olvido, y el
cliente MCP lo genera solo en cada escritura.

Dos decisiones que no estaban en la especificación: reusar un identificador con
datos distintos devuelve **409** en vez de la respuesta vieja (no es un reintento
sino un error de quien llama), y **los errores no se recuerdan**, porque un fallo
puede ser transitorio y quien llama tiene derecho a reintentarlo de verdad.

### 3. 🟠 Confirmar obliga a reenviar todo

Hoy la confirmación es un parámetro booleano: `void_invoice(numero, confirmar=True)`.
Funciona para "¿estás seguro?", pero no para resolver ambigüedades.

En el flujo que describe la visión —*"encontré dos clientes llamados José Pérez"*—
el agente tiene que volver a armar la llamada completa con todos los datos. Puede
cambiar algo sin querer, y el usuario ya dio su conformidad sobre algo que no es
exactamente lo que se va a ejecutar.

**Cómo quedó resuelto.** El servidor guarda la operación tal como iba a
ejecutarse —método, ruta y cuerpo— junto con los candidatos. Confirmarla mezcla
la corrección en el cuerpo original y **reejecuta la misma petición**.

Se guarda la petición y no una llamada a una función a propósito: al reejecutarse
pasa de nuevo por permisos, validaciones, auditoría e idempotencia, en vez de
abrir un camino paralelo con reglas propias que se desincronice. Y funciona para
las 47 herramientas sin que ninguna tenga que saber que esto existe.

---

## Dos observaciones sobre el plan propuesto

### Sobre agrupar las herramientas en pocas mega-herramientas

El análisis complementario propone (punto 5.1) reemplazar las herramientas
específicas por unas pocas de alto nivel, tipo
`consultar_negocio(query_type, filtros)`.

**No lo recomiendo, al menos no antes de medirlo.** El razonamiento es que 44
herramientas (hoy 47) saturan al modelo; pero una mega-herramienta con un `enum` de 20
valores no elimina la elección, la **esconde dentro de un parámetro**, donde el
modelo pierde justamente lo que lo ayuda a acertar: una descripción propia por
cada operación, con sus parámetros documentados y sus casos de error.

Las descripciones de las herramientas actuales son buenas y específicas. Cambiar
eso por un enum es probable que empeore la selección, no que la mejore.

Lo razonable es al revés: **primero medir**. Ejercitar los flujos reales
(facturar, cobrar con cheque, cargar factura de proveedor) y ver si el agente
elige bien. Si se equivoca, ver *en qué* se equivoca — puede ser un problema de
descripciones ambiguas entre dos herramientas parecidas, que se arregla
reescribiendo esas dos, no rediseñando las 44.

### Sobre la reversión granular

El análisis pide (punto 5.4) guardar `before_state` / `after_state` para poder
revertir sin restaurar un backup. **Eso ya existe**: la auditoría guarda ambos
valores en las entidades sensibles.

Lo que falta es la parte de arriba: una vista que muestre la operación y un
camino seguro para revertirla. Es bastante menos trabajo del que sugiere el
documento, porque el dato ya está.

---

## Plan por etapas

El orden importa: cada etapa deja el sistema utilizable y no depende de las
siguientes.

### Etapa 0 — Probarlo de verdad antes de tocar nada

Conectar OpenClaw contra ALdía tal como está y ejercitar los flujos reales:
facturar un presupuesto, cobrar con cheque, cargar una factura de proveedor,
preguntar saldos.

No es una formalidad. Es la única forma de saber si los tres huecos son los que
duelen o si aparece otro antes. **El resultado de esta etapa puede cambiar el
orden de las siguientes**, y conviene tomarlo en serio en lugar de asumir que el
diagnóstico de escritorio (este documento incluido) acertó.

### Etapas 1 a 3 — hechas

Identidad y trazabilidad, idempotencia y confirmaciones con estado están
implementadas y cubiertas por pruebas (ver `tests/test_origen_agentes.py`,
`tests/test_idempotencia.py`, `tests/test_pendientes.py`).

### Etapa 4 — Errores con código de máquina — hecha

Cada error trae ahora, junto al mensaje legible que ya existía y sin quitarlo,
un **código estable** y una **acción sugerida**:

```json
{
  "detail": "Stock insuficiente de 'Coca 2.25': se intentan facturar 12 y hay 5",
  "codigo": "STOCK_INSUFICIENTE",
  "accion": "corregir"
}
```

`accion` es lo que resultó más útil de lo previsto, y es un conjunto **cerrado**
de cuatro valores: `reintentar`, `corregir`, `preguntar`, `abortar`. Un agente
nuevo se comporta bien sin conocer el catálogo entero — le alcanza con leer ese
campo. Y los tres casos donde equivocarse cuesta plata quedan explícitos:
reintentar un `CAE_YA_EMITIDO` duplica la declaración ante AFIP, no reintentar un
`AFIP_NO_DISPONIBLE` pierde una venta que iba a entrar sola, e inventar una
`CONFIRMACION_REQUERIDA` es tomar una decisión que no le corresponde.

**No hizo falta migrar las 86 excepciones del sistema.** Hacerlo sitio por sitio
habría dejado la mitad de la API sin código durante meses, que es la peor
versión: un agente no puede confiar en un campo que a veces está. El código se
resuelve en dos pasos — el preciso si la excepción lo declara, y uno derivado del
estado HTTP si no (`404 → NO_ENCONTRADO`, `403 → SIN_PERMISO`). Así **todo** error
tiene código desde el primer día, incluidos los `422` de Pydantic, y los precisos
se agregan donde aportan.

El catálogo completo se consulta en **`GET /api/errores`**, sin autenticarse: un
agente que está recibiendo un `401` tiene que poder averiguar qué significa. Ver
`backend/errores.py` y `tests/test_errores.py`.

### Etapa 5 — Cockpit de actividad

Vista de actividad del agente sobre la auditoría que ya existe, con el antes y
el después, y reversión de operaciones puntuales.

---

## Qué no hay que romper

Estas propiedades costaron trabajo y son las que hacen que el sistema sea
confiable para dejarlo operar por un agente. Cualquier refactor tiene que
preservarlas:

- **El MCP no toca la base.** En cuanto lo haga, la lógica se duplica.
- **Los importes son enteros de centavos.** Ver `backend/dinero.py`.
- **El registro de auditoría no se puede borrar**, ni siquiera por el
  administrador, y sobrevive al borrado de la base.
- **Los permisos se validan en el servidor.** Ocultar una herramienta no es un
  control de acceso.
- **Ninguna operación inventa un CAE** ni da por guardado lo que el servidor no
  confirmó.
- **Los códigos de error son un contrato.** Cambiar el texto de `detail` es
  libre; cambiar o quitar un `codigo` rompe a los agentes ya conectados.
