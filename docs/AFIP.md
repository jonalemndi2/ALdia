# Factura Electrónica AFIP — puesta en marcha

Este sistema habla con los web services **reales** de AFIP (WSAA + WSFEv1). No hay
simulación, no hay CAE de ejemplo: si AFIP no autoriza el comprobante, el sistema
lo muestra como no autorizado.

**Estado actual: la integración está implementada y DESHABILITADA.** Falta lo único
que no puede hacer un programador por usted: el **certificado digital** de su CUIT.

---

## 1. Qué hace falta antes de facturar

| Requisito | Dónde se hace |
|---|---|
| Clave fiscal nivel 3 o superior | AFIP, con su CUIT |
| Alta del servicio "Administración de Certificados Digitales" | Portal AFIP |
| Certificado digital (`.crt`) + clave privada (`.key`) | Se genera y se descarga (pasos 3 y 4) |
| Autorizar el certificado a usar el servicio `wsfe` | "Administrador de Relaciones de Clave Fiscal" |
| Punto de venta habilitado para **Factura Electrónica – Web Services** | Portal AFIP → Regímenes de Facturación |

> El punto de venta de web services **no es el mismo** que el del "Comprobantes en
> línea". Hay que dar de alta uno específico para web services, y ese número es el
> que se configura acá.

---

## 2. Generar la clave privada y el pedido de certificado (CSR)

En la PC del comercio, con OpenSSL (viene con Git para Windows, en
`C:\Program Files\Git\usr\bin\openssl.exe`):

```bash
# 1) Clave privada (NO se comparte con nadie, ni con AFIP)
openssl genrsa -out afip.key 2048

# 2) Pedido de certificado. Reemplace el nombre y el CUIT por los suyos.
openssl req -new -key afip.key -subj "/C=AR/O=NOMBRE DEL COMERCIO/CN=aldia/serialNumber=CUIT 20111111112" -out afip.csr
```

- `O=` razón social tal como figura en AFIP.
- `CN=` un alias cualquiera (por ejemplo `aldia`).
- `serialNumber=CUIT 20xxxxxxxxx` — **con la palabra CUIT, un espacio y los 11 dígitos sin guiones**.

## 3. Obtener el certificado en AFIP

**Homologación (pruebas, sin validez fiscal):**

1. Entrar a <https://wsass-homo.afip.gob.ar/> ("WSASS – Autogestión Certificados Homologación").
2. "Nuevo Certificado" → pegar el contenido de `afip.csr` → descargar el `.crt`.
3. En el mismo sitio, "Adherir WS": asociar el certificado (DN) al servicio **wsfe**.

**Producción (facturación real):**

1. AFIP con clave fiscal → **Administración de Certificados Digitales**.
2. "Agregar alias" → subir `afip.csr` → descargar el `.crt`.
3. AFIP → **Administrador de Relaciones de Clave Fiscal** → Nueva Relación →
   Servicio **AFIP → WebServices → Facturación Electrónica** → representante: el
   alias del certificado que creó.

## 4. Instalar los archivos

Copiar los dos archivos a la carpeta `certificados/` del proyecto:

```
ALdia a web/
└── certificados/          <- ignorada por git, NUNCA llega a GitHub
    ├── afip.key           <- su clave privada
    └── afip.crt           <- el certificado que descargó de AFIP
```

Si prefiere otra ubicación, use las variables `AFIP_CERT` y `AFIP_CLAVE`.

## 5. Activar la integración

Dos formas, la variable de entorno tiene prioridad sobre la base de datos.

**a) Variables de entorno** (editar `iniciar_web.bat` y agregar antes de arrancar):

```bat
set AFIP_HABILITADO=si
set AFIP_ENTORNO=homologacion
set AFIP_CUIT=20111111112
set AFIP_PUNTO_VENTA=1
set AFIP_TIPO_COMPROBANTE=1
rem opcional, si los archivos no están en certificados/afip.crt y .key
rem set AFIP_CERT=C:\ruta\a\afip.crt
rem set AFIP_CLAVE=C:\ruta\a\afip.key
```

**b) Tabla `configuracion`** (Administración → Configuración, o `PUT /api/config/`):

| Clave | Ejemplo |
|---|---|
| `afip_habilitado` | `si` |
| `afip_entorno` | `homologacion` o `produccion` |
| `afip_cuit` | `20111111112` (si falta, usa `negocio_cuit`) |
| `afip_punto_venta` | `1` (si falta, usa `negocio_punto_venta`) |
| `afip_tipo_comprobante` | `1` = Factura A, `6` = B, `11` = C |
| `afip_cert` / `afip_clave` | rutas alternativas a los archivos |

## 6. Probar (siempre primero en homologación)

1. Entrar a **Facturas → Remitir Factura**. Arriba se ve el estado real de AFIP.
   - "AFIP no configurado…" → falta algo, el texto dice qué.
   - "AFIP operativo en HOMOLOGACION…" → el certificado ya autentica.
2. Emitir una factura de prueba y presionar **Solicitar CAE a AFIP**.
3. Si AFIP la autoriza, el CAE y su vencimiento quedan guardados y se imprimen
   en el comprobante.

Cuando todo funcione en homologación, cambiar `AFIP_ENTORNO` a `produccion`
(certificado de producción, que es **otro archivo**) y repetir la prueba con un
comprobante real.

---

## 7. Qué hace el sistema por dentro

| Paso | Detalle |
|---|---|
| Ticket de acceso | Arma `loginTicketRequest`, lo firma en CMS/PKCS#7 (SHA-256) con su certificado y lo manda al WSAA. El ticket dura 12 h y se **cachea** en `backend/.afip_ta_*.json` porque AFIP rechaza pedir otro mientras haya uno vigente. |
| Numeración | Antes de cada pedido consulta `FECompUltimoAutorizado` y usa el número siguiente. La numeración de AFIP es independiente del número interno de factura del sistema. |
| Importes | Arma neto, IVA por alícuota y total a partir de los renglones de la factura. Si la suma de los renglones no coincide con el total de la factura, **no pide el CAE**: avisa para que se corrija. |
| Rechazos | Los `Errors` y `Observaciones` de AFIP se traducen al castellano, se guardan en la factura (`resultado = 'R'`) y se devuelven como error. Nunca como éxito. |
| Fallas de red o certificado | No modifican el estado fiscal de la factura: se puede reintentar. |

Endpoints (todos requieren sesión y permiso del módulo *ventas*):

```
GET  /api/afip/estado                          estado + FEDummy de AFIP
GET  /api/afip/tipos-comprobante               FEParamGetTiposCbte
GET  /api/afip/tipos-iva                       FEParamGetTiposIva
GET  /api/afip/ultimo-autorizado               FECompUltimoAutorizado
POST /api/afip/facturas/{n}/solicitar-cae      FECAESolicitar
```

---

## 8. Advertencias

- **La clave privada y el certificado nunca deben subirse a GitHub.** La carpeta
  `certificados/` y los patrones `*.key`, `*.crt`, `*.pem` están en `.gitignore`.
  Si alguna vez los sube por error, hay que revocar el certificado en AFIP.
- Los CAE obtenidos en **homologación no tienen validez fiscal**. El sistema lo
  avisa en pantalla y en la respuesta del pedido.
- **Falta el código QR obligatorio** (RG 4892) en el comprobante impreso. El CAE
  se imprime; el QR todavía no. Antes de usar esto para facturar de verdad hay
  que agregarlo, o imprimir los comprobantes con otra herramienta.
- Este sistema no consulta la condición de IVA del receptor: el tipo de
  comprobante (A/B/C) se elige a mano al pedir el CAE, o sale de la
  configuración. Elegir mal el tipo hace que AFIP rechace el comprobante.
