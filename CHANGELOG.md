# Novedades de ALdía

Cada versión publicada tiene su sección. El número sigue
[versionado semántico](https://semver.org/lang/es/): `MAYOR.MENOR.PARCHE`.

- **MAYOR**: cambia algo que obliga a revisar la instalación o la forma de trabajar.
- **MENOR**: funciones nuevas, compatibles con lo anterior.
- **PARCHE**: correcciones.

El sistema lee este archivo para mostrar las novedades en la pantalla
"Actualizar sistema" y para avisarle al asistente de IA que hay una versión
nueva. Mantener el formato de los títulos: `## X.Y.Z — AAAA-MM-DD`.

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
