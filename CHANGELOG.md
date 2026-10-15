# Novedades de ALdía

Cada versión publicada tiene su sección. El número sigue
[versionado semántico](https://semver.org/lang/es/): `MAYOR.MENOR.PARCHE`.

- **MAYOR**: cambia algo que obliga a revisar la instalación o la forma de trabajar.
- **MENOR**: funciones nuevas, compatibles con lo anterior.
- **PARCHE**: correcciones.

El sistema lee este archivo para mostrar las novedades en la pantalla
"Actualizar sistema" y para avisarle al asistente de IA que hay una versión
nueva. Mantener el formato de los títulos: `## X.Y.Z — AAAA-MM-DD`.

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
