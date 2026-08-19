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

Los huecos reales son **tres**, y son concretos. El resto de lo que pide el
documento —transaccionalidad, auditoría con antes/después, permisos por rol,
ausencia de SQL arbitrario, concurrencia en SQLite— ya está resuelto.

| Requisito de la visión | Estado |
|---|---|
| MCP y REST comparten la lógica de negocio | ✅ por diseño |
| Nada de SQL arbitrario para el agente | ✅ la consola SQL se eliminó a propósito |
| Operaciones atómicas | ✅ verificado con reversión completa |
| Auditoría con antes/después | ✅ middleware que cubre toda escritura |
| Permisos validados en el servidor | ✅ por rol y módulo |
| Concurrencia (WAL, `busy_timeout`) | ✅ ya configurado |
| Confirmación en operaciones destructivas | ✅ `confirmar=true` en 24 herramientas |
| Errores legibles para el agente | ⚠️ legibles, pero sin código de máquina |
| **Trazabilidad de la persona detrás del agente** | ❌ **falta** |
| **Idempotencia (`operation_id`)** | ❌ **falta** |
| **Estado de confirmación (drafts)** | ❌ **falta** |

---

## Los tres huecos

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

**Qué hace falta:** que el MCP reciba la identidad del humano en cada llamada
(no como parámetro de la herramienta, que el modelo podría inventar, sino desde
el contexto de la sesión), y que la auditoría guarde `actor_type`, `agent_id` y
el `usuario_id` real. Los permisos deben evaluarse contra esa persona, no contra
la cuenta del agente.

### 2. 🔴 Un reintento puede duplicar una factura

No existe `operation_id` en ninguna parte del código.

Si OpenClaw envía `registrar_cobro`, el servidor lo procesa y la respuesta se
pierde por un timeout de red, el agente reintenta — y se registra **el cobro dos
veces**. Con facturación fiscal el problema es peor: dos comprobantes ante AFIP.

Este riesgo no existía cuando el único cliente era un navegador con una persona
mirando la pantalla. Aparece justamente al poner un agente que reintenta.

**Qué hace falta:** que las operaciones de escritura acepten un identificador de
solicitud, que se registre al procesarlas, y que un segundo intento con el mismo
identificador devuelva el resultado original en vez de ejecutar de nuevo.

### 3. 🟠 Confirmar obliga a reenviar todo

Hoy la confirmación es un parámetro booleano: `anular_factura(numero, confirmar=True)`.
Funciona para "¿estás seguro?", pero no para resolver ambigüedades.

En el flujo que describe la visión —*"encontré dos clientes llamados José Pérez"*—
el agente tiene que volver a armar la llamada completa con todos los datos. Puede
cambiar algo sin querer, y el usuario ya dio su conformidad sobre algo que no es
exactamente lo que se va a ejecutar.

**Qué hace falta:** que el servidor guarde la operación pendiente y devuelva un
identificador, para que confirmarla sea decir *"ejecutá lo que ya te describí,
con esta aclaración"* en lugar de repetir todo.

---

## Dos observaciones sobre el plan propuesto

### Sobre agrupar las 44 herramientas en pocas mega-herramientas

El análisis complementario propone (punto 5.1) reemplazar las herramientas
específicas por unas pocas de alto nivel, tipo
`consultar_negocio(query_type, filtros)`.

**No lo recomiendo, al menos no antes de medirlo.** El razonamiento es que 44
herramientas saturan al modelo; pero una mega-herramienta con un `enum` de 20
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

### Etapa 1 — Identidad y trazabilidad

Que cada operación sepa qué persona la ordenó y por qué canal.

- Identidad del usuario final en cada llamada MCP, tomada del contexto.
- `actor_type` (persona / agente), `agent_id` y `usuario_id` real en la auditoría.
- Permisos evaluados contra la persona, no contra la cuenta del agente.
- La pantalla de auditoría filtra por canal y por persona.

Va primero porque **sin esto, todo lo que haga el agente es anónimo**, y ninguna
de las etapas siguientes arregla eso.

### Etapa 2 — Idempotencia

Identificador de solicitud en las operaciones de escritura, registro de las ya
procesadas, y respuesta repetida en vez de ejecución duplicada.

Va segunda porque el daño que evita —una factura fiscal duplicada— es difícil de
deshacer, y aparece solo cuando el agente ya está operando.

### Etapa 3 — Confirmaciones con estado

Operaciones pendientes guardadas con su identificador, y confirmación por
referencia. Habilita el flujo conversacional de resolución de ambigüedades que
describe la visión.

### Etapa 4 — Errores con código de máquina

Agregar un código estable (`CLIENTE_AMBIGUO`, `STOCK_INSUFICIENTE`,
`CONFIRMACION_REQUERIDA`…) junto al mensaje legible que ya existe, sin quitarlo.
El mensaje sirve para que el modelo entienda; el código, para que el orquestador
decida sin interpretar texto.

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
