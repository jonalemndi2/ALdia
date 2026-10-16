# Novedades de ALdía

Cada versión publicada tiene su sección. El número sigue
[versionado semántico](https://semver.org/lang/es/): `MAYOR.MENOR.PARCHE`.

- **MAYOR**: cambia algo que obliga a revisar la instalación o la forma de trabajar.
- **MENOR**: funciones nuevas, compatibles con lo anterior.
- **PARCHE**: correcciones.

El sistema lee este archivo para mostrar las novedades en la pantalla
"Actualizar sistema" y para avisarle al asistente de IA que hay una versión
nueva. Mantener el formato de los títulos: `## X.Y.Z — AAAA-MM-DD`.

## 2.5.0 — 2026-10-16

- **Los importes de factura, remito, notas y gastos los calcula el backend.**
  Antes la factura guardaba el neto, el IVA y el total que mandaba quien la
  cargaba (el panel o el asistente, sumando con decimales binarios), y el pedido
  de CAE los recalculaba con otro criterio: la cuenta corriente del cliente y lo
  declarado ante AFIP podían diferir en centavos, y con más de 5 centavos AFIP no
  autorizaba. Ahora hay un solo cálculo (`backend/importes.py`): cada renglón se
  redondea una vez y el IVA una vez por alícuota, con la alícuota del artículo en
  el stock. Lo usan la factura, el remito, el pedido de CAE y un endpoint nuevo,
  `POST /api/facturas/cotizar`, para mostrar el importe antes de emitir.
- **Un borrador no se confirma por otro importe.** El borrador congela el precio
  de lista de cada renglón. Si al confirmar el importe ya no es el que vio el
  usuario (por ejemplo, cambió la alícuota del artículo), se rechaza con
  `IMPORTES_CAMBIARON` en vez de impactar un importe que nadie aprobó. Un
  borrador preparado con una versión anterior puede pedir que se lo prepare de
  nuevo.
- **Notas por importe con alícuota.** Con `alicuota_iva`, el backend calcula el IVA
  y el total de una nota de crédito o débito por importe. El panel y el asistente
  ya lo usan, y la confirmación del panel muestra el total que calculó el backend.
- **El servidor MCP no hace cuentas con plata.** No multiplica, no aplica
  alícuotas ni redondea: manda los datos y muestra lo que calculó el backend.
  Para los resúmenes (resumen del día, movimientos de caja, deudores, chequera,
  liquidaciones) suma centavos enteros exactos (`aldia_mcp/dinero.py`), y un test
  impide volver a convertir importes a `float`. La remarcación por porcentaje la
  calcula el backend (`aumento_pct`) con redondeo comercial: antes, una rebaja
  del 10 % sobre $10,05 daba $9,04 en lugar de $9,05.
- **Arreglado: cargar un gasto con conceptos fallaba siempre**
  ("FOREIGN KEY constraint failed"), desde el panel y desde el asistente. Además,
  si no se declaran los totales del comprobante, se calculan a partir de los
  conceptos; si se declaran, se respetan, porque el crédito fiscal es el del
  comprobante del proveedor.
- **Remitos sin facturar.** Cada renglón trae su `importe` calculado por el
  backend, y la herramienta del asistente informa `total_neto_sin_facturar`
  (antes `total_sin_facturar`).

## 2.4.0 — 2026-10-16

- **El asistente ve solo las herramientas de los módulos activos.** Cada
  herramienta MCP declara su módulo, y el servidor MCP filtra la lista con
  `GET /api/modulos/permisos`, un endpoint nuevo que dice en qué módulos puede
  leer y en cuáles escribir el usuario conectado, con el mismo control que
  aplica cada operación. Con el perfil Comercio, el administrador pasa de 72 a
  61 herramientas y una cuenta `agente` recién creada a 30 (solo consultas). Las
  skills se filtran igual, y además por país. Si el backend no responde, se
  muestran todas menos la administración por chat.
- **Administración por chat, apagada por defecto.** Crear y borrar usuarios,
  prender o apagar módulos y borrar movimientos de caja pasan al módulo
  `administracion_por_chat`. Eso se hace desde el panel salvo que alguien lo
  prenda. Si usabas el asistente para crear usuarios, prendelo en
  *Administración → Módulos*.
- **`ALDIA_MODULOS`.** Variable del backend que fija los módulos activos en cada
  arranque, con perfiles o claves: `ALDIA_MODULOS=comercio,liquidaciones_granos`.
  Mientras está definida, el panel no los puede prender ni apagar.
- **Los módulos agropecuarios nacen apagados** en las instalaciones nuevas, como
  ya anunciaba la 2.3.0 (en realidad nacían prendidos). Las instalaciones
  existentes no cambian: si los tenés prendidos y no los usás, apagalos.
- **El panel reconoce el rol `agente`.** No aparecía en la pantalla de Módulos, y
  guardar un módulo le sacaba al asistente el permiso de escritura sin avisar.
  Ahora además se puede crear la cuenta del asistente desde *Usuarios*.
- **Resumen del día y movimientos de caja por módulo.** `get_daily_briefing` y
  `get_daily_cash_movements` traen solo las secciones de los módulos activos y
  dicen en `no_incluido` cuáles quedaron afuera, en vez de fallar enteros.
  `check_connection` informa qué módulos están apagados y cómo se prenden.

## 2.3.1 — 2026-10-16

- **El resumen matutino ya no oculta fallas.** Si `get_daily_briefing` no
  puede consultar las liquidaciones en borrador o las operaciones pendientes,
  lo informa como error en vez de devolver una lista vacía. Antes el asistente
  podía decir "no tenés nada pendiente" sin haberlo podido consultar.
- **La fecha de hoy se calcula en la zona del negocio.** El servidor MCP usa
  `America/Argentina/Cordoba` (configurable con `ALDIA_ZONA_HORARIA`) en vez
  de la hora del servidor. Con el servidor en UTC, después de las 21 hs el
  resumen salía con la fecha del día siguiente.

## 2.3.0 — 2026-10-16

- **Perfiles de negocio y módulos verticales instalables.** Nuevos módulos
  `liquidaciones_granos` y `liquidaciones_hacienda` (apagados por defecto en
  comercios comunes) y selector de perfiles rápidos (`comercio`, `agro_granos`,
  `agro_hacienda`, `agro_mixto`, `servicios`) en *Administración → Módulos* y
  en `GET / POST /api/modulos/perfiles`.
- **Motor multipaís de liquidaciones (Cereales, Hacienda y Consignación).**
  Comprobantes con cálculo exacto en centavos enteros para peso bruto, porcentaje
  de merma/humedad o desbaste, cabezas, deducciones gravadas (flete, secado,
  zarandeo, comisión, gastos de feria/SENASA) y retenciones impositivas. Impacta
  automáticamente el stock neto en el submayor (`MovimientoStock`), las cuentas
  corrientes (`saldos.verificar()`) y el Libro IVA (`/api/iva/consulta`). En
  Argentina permite registrar el **COE** (Código de Operación Electrónica); en
  Estados Unidos opera como *Settlement Sheet* en USD con EIN.
- **Bandeja de borradores e interfaz Web de Liquidaciones.** Pantallas de
  *Liquidaciones → Cereales y Granos* y *Hacienda*, con bandeja de borradores
  preparados por el asistente de IA para confirmar con un clic.
- **Adopción con agentes de IA personales (MCP, skills embebidas y demo).**
  Nuevas herramientas MCP (`create_settlement_draft`, `confirm_settlement_draft`,
  `list_settlements`, `get_settlement`, `register_settlement_coe`,
  `void_settlement`, `list_business_profiles`, `apply_business_profile`),
  resumen matutino `get_daily_briefing`, manuales operativos consultables por
  MCP (`list_operational_skills` y `get_operational_skill`), nueva skill
  `liquidacion-cereales-y-hacienda`, paquete instalable `mcp/pyproject.toml` y
  generador de base de demostración `scripts/crear_demo.py`.

## 2.2.0 — 2026-10-15

- **Todas las condiciones frente al IVA de ARCA (RG 5616).** Se suman
  *Monotributista Social* (13), *Monotributo Trabajador Independiente Promovido*
  (16), *Sujeto No Categorizado* (7) e *IVA Liberado – Ley N° 19.640* (10). Se
  eligen en la ficha del cliente y viajan en cada pedido de CAE.
- **Clase de comprobante.** Un responsable inscripto emite clase A a cualquier
  monotributista (común, social o promovido) y B al resto. Un negocio
  monotributista social o promovido emite clase C, igual que el monotributo común.
- **API.** `GET /api/afip/condiciones-iva` informa, para cada condición, el código
  de ARCA, la clase que emite un responsable inscripto
  (`clase_si_el_negocio_es_ri`) y las clases en que ARCA la acepta
  (`clases_validas_rg5616`).
- **Asistente (MCP y skills).** Reconoce las condiciones nuevas y sus sinónimos
  ("monotributista social", "promovido", "ley 19.640"...), y las skills traen la
  tabla completa de ARCA. Una prueba verifica que el MCP y el backend apliquen
  exactamente la misma regla.

## 2.1.1 — 2026-10-15

- **RG 5616 (ARCA).** Cada pedido de CAE informa la condición frente al IVA del
  receptor (`CondicionIVAReceptorId`), tomada de la ficha del cliente. Desde el
  01/12/2026 ARCA rechaza los comprobantes que no la traen. En moneda extranjera
  se informa además si se cancela en esa moneda (`CanMisMonExt`).
- **Control previo.** Si la condición del cliente no corresponde a la clase del
  comprobante (por ejemplo, Factura A a un consumidor final), ALdía lo corta antes
  de llamar a ARCA, sin bloquear las emisiones siguientes.
- **Monotributista: Factura A.** Un responsable inscripto le emite clase A a un
  monotributista (antes ALdía sugería B, que ARCA rechaza por la RG 5616).

## 2.1.0 — 2026-10-14

- **Versionado y actualización del sistema.** Archivo `VERSION`, la versión
  visible al pie de la WebUI y la pantalla *Administración → Actualizar
  sistema*, que muestra las novedades e instala la versión nueva (con copia de
  seguridad previa).
- **El asistente se entera de las versiones nuevas.** La herramienta MCP
  `get_system_version` informa la versión y si hay una nueva. Además, la
  primera respuesta después de una actualización trae un aviso con las
  novedades para que el asistente se lo cuente al usuario.
- **Emisión fiscal por chat con código de un solo uso.** Un asistente (rol
  `agente`) puede pedir el CAE si la instalación lo habilita
  (`ALDIA_EMISION_FISCAL_AGENTE=si`): ALdía envía un código por Telegram a la
  persona responsable y la emisión solo sigue con ese código. Vence a los 10
  minutos, sirve para una sola factura y se invalida si la factura cambia.
- **Rol `agente`.** Rol para la cuenta de servicio de un asistente de IA:
  consulta lo mismo que el auditor y escribe solo en los módulos que el
  administrador le habilite.
- **ARCA: conexión con OpenSSL 3.** Se corrige el error `dh key too small` al
  conectar con los web services de ARCA, sin bajar la seguridad del resto del
  sistema.

## 2.0.0

Versión base del piloto comercial.
