# Emisión fiscal pedida por un asistente de IA

Por defecto, un asistente conectado por MCP **no puede** pedir un CAE: la
emisión fiscal la hace un administrador desde la WebUI. Esta guía explica cómo
habilitarlo de forma controlada.

## Cómo funciona

```
asistente: request_fiscal_authorization(numero=12, confirmar=true)
ALdía:     no emite. Manda por Telegram a la persona responsable:
             "pide el CAE de la factura 12 — Cliente X — $121,00 — Código: 482913"
           y le responde al asistente CODIGO_DE_AUTORIZACION_REQUERIDO
asistente: "¿Me pasás el código que te llegó?"
persona:   "482913"
asistente: request_fiscal_authorization(numero=12, confirmar=true, codigo="482913")
ALdía:     verifica el código y recién entonces le pide el CAE a ARCA
```

La confirmación `confirmar=true` la escribe el modelo, así que por sí sola no
prueba que una persona haya aprobado nada. El código sí: lo genera ALdía, viaja
por un canal que el asistente no lee y ALdía guarda solamente su hash.

El código:

- sirve para **una** factura y **un** uso;
- vence a los **10 minutos**;
- deja de valer si la factura cambia (cliente, total o fecha) después de pedirlo;
- admite 5 intentos fallidos; después hay que pedir otro.

## Requisitos

1. **Emisión fiscal habilitada** y ARCA configurado (ver [AFIP.md](AFIP.md)):
   `ALDIA_EMISION_FISCAL=si`.
2. **Usuario del asistente con rol `agente`.** Este rol consulta lo mismo que el
   `auditor` y escribe solamente en los módulos que el administrador le habilite.
   Para pedir un CAE necesita escritura en **Ventas**: en *Administración →
   Módulos del Sistema* agregue `agente` a los roles de Ventas.
3. **Habilitar la emisión del agente:** `ALDIA_EMISION_FISCAL_AGENTE=si`.
4. **Canal para el código** (Telegram):
   - `ALDIA_TELEGRAM_BOT_TOKEN`: token de un bot de Telegram.
   - `ALDIA_TELEGRAM_CHAT_ID`: chat de la persona que autoriza.

   Si el asistente también conversa por Telegram, puede usarse el mismo bot: los
   mensajes que envía un bot no le llegan como mensajes entrantes, así que el
   asistente no ve el código.

Las claves van en un archivo de entorno con permisos `600` (por ejemplo, un
`EnvironmentFile=` de systemd), nunca en el código ni en un archivo versionado.

## Límite conocido

El código protege contra errores del modelo y contra instrucciones inyectadas
que llegan por la conversación. **No** protege contra un asistente que corre con
el mismo usuario del sistema operativo que ALdía y tiene acceso a una terminal:
ese puede leer la base, las claves y el certificado directamente. Si el
asistente tiene terminal, córralo con otro usuario del sistema.
