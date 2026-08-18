---
name: factura-electronica-afip
description: Factura electrónica de ALdia - pedirle el CAE a AFIP para una factura ya emitida, elegir el tipo de comprobante (A, B, C, notas de crédito y débito), y entender qué hacer cuando AFIP rechaza. Usar cuando el usuario diga "pedir el CAE", "autorizar la factura", "AFIP me la rechazó", "no me sale el CAE", "factura electrónica", "está habilitada la facturación electrónica", "qué comprobante le tengo que hacer", "factura A o B" o "el comprobante no tiene validez".
---

# Factura electrónica AFIP (ALdia)

Herramientas MCP del servidor **aldia**. En ALdia la factura se emite **primero**
en el sistema y **después** se le pide la autorización a AFIP:

```
emitir_factura(...)  →  solicitar_cae(numero=...)  →  CAE + vencimiento
```

El **CAE** (Código de Autorización Electrónico) es el número que le da validez
fiscal al comprobante. Sin CAE, la factura existe en ALdia y le genera deuda al
cliente, pero **no es un comprobante fiscal válido**.

## Regla que no se negocia

**El CAE lo otorga AFIP. Usted nunca lo inventa, nunca lo supone y nunca da por
autorizada una factura que no lo esté.** Si `solicitar_cae` devuelve un error, la
factura NO quedó autorizada: dígaselo al usuario con el mensaje real del sistema.
Un CAE inventado en un comprobante impreso es un problema fiscal serio para el
comercio.

## Paso 1 — ¿Este ALdia puede facturar electrónicamente?

```
ver_estado_afip()
```

Mire `puede_pedir_cae`:

- **false, con `problemas`** — típicamente faltan el certificado y la clave
  privada de AFIP, o el CUIT del emisor. El sistema **factura en modo local, sin
  CAE**. No hay nada que el asistente pueda resolver: hay que cargar el
  certificado, y eso lo hace el administrador. Dígaselo así, sin prometer nada.
- **true, entorno `homologacion`** — está en el **entorno de pruebas** de AFIP.
  Los CAE que devuelve son reales pero **no tienen validez fiscal**. Avísele al
  usuario cada vez: es exactamente el caso en el que alguien podría creer que ya
  está facturando de verdad.
- **true, entorno `produccion`** — comprobantes fiscales reales.

## Paso 2 — Qué comprobante corresponde

Lo determinan las condiciones frente al IVA del **negocio** y del **cliente**:

| Negocio | Cliente | Comprobante | Código AFIP |
| --- | --- | --- | --- |
| Responsable inscripto | Responsable inscripto | Factura A | 1 |
| Responsable inscripto | Monotributo / exento / consumidor final | Factura B | 6 |
| Monotributista o exento | cualquiera | Factura C | 11 |

Notas asociadas: **crédito** 3 (A), 8 (B), 13 (C); **débito** 2 (A), 7 (B),
12 (C).

Para verlo aplicado a un comprobante concreto:

```
ver_factura(numero=<n>)      # trae clase_que_corresponde y tipo_sugerido_para_cae
ver_configuracion_negocio()  # condición del negocio y el mapa completo
```

Si no se pasa `tipo_comprobante`, el sistema lo deduce solo, y para facturas eso
es lo correcto. **Hay una excepción importante**: una **nota de débito** tiene
importe positivo, así que el sistema la tomaría por una factura. En ese caso
indique el tipo a mano (2, 7 o 12). Las notas de crédito se detectan solas
porque su importe es negativo.

## Paso 3 — Pedir el CAE

```
solicitar_cae(numero=<n>)
```

Parámetros opcionales: `tipo_comprobante`, `punto_venta`, `concepto`
(1 = productos, 2 = servicios, 3 = ambos), `doc_tipo` / `doc_nro` del receptor
(por defecto 80 = CUIT y el CUIT del cliente de la factura; 99 para consumidor
final sin identificar).

Respuesta exitosa: `cae`, `cae_vencimiento`, `punto_venta`, `numero_afip` y
`tiene_validez_fiscal`. Informe al usuario:

```
Factura 12 AUTORIZADA por AFIP
  Comprobante : Factura A 0001-00000034
  CAE         : 76123456789012   (vence 28/08/2026)
  Entorno     : producción
```

Si el entorno es homologación, agregue en el mismo mensaje: **"CAE de prueba,
sin validez fiscal"**.

El CAE tiene **vencimiento**: es la fecha límite para entregarle el comprobante
al cliente. Menciónela.

## Paso 4 — Cuando AFIP rechaza

Cada error significa algo distinto y se resuelve distinto:

| Error | Qué pasó | Qué hacer |
| --- | --- | --- |
| **400 — AFIP no configurado** | falta certificado, clave o CUIT emisor | no se puede autorizar; es tarea del administrador. La factura queda válida como comprobante interno, sin valor fiscal |
| **422 — rechazo de AFIP** | AFIP **miró** el comprobante y lo rechazó | leer el motivo, corregir la causa y volver a pedirlo. El rechazo queda guardado en la factura (`resultado = R`) |
| **409 — ya tiene CAE** | el comprobante ya estaba autorizado | no volver a pedirlo: duplicaría la declaración. Mostrar el CAE existente |
| **502 — AFIP no responde** | red, certificado o WSAA caídos | AFIP **no llegó a evaluar** el comprobante: no cambió nada, se reintenta más tarde |
| **403 — permiso denegado** | el rol no tiene el módulo `ventas` | decírselo al usuario; pedir un CAE es emitir un comprobante fiscal |

Causas típicas de un **rechazo 422**, en orden de frecuencia:

1. **Tipo de comprobante equivocado** — factura A a un cliente que no es
   responsable inscripto, o nota de débito pedida como factura. Revise la
   condición frente al IVA del cliente y vuelva a pedirlo con el tipo correcto.
2. **CUIT del receptor inválido o inexistente para AFIP** — el CUIT valida el
   dígito verificador pero no está inscripto. Hay que confirmarlo con el
   cliente.
3. **Importes que no cierran** — la suma de los renglones no da el total
   declarado, o hay una alícuota de IVA que AFIP no acepta (válidas: 0, 2.5, 5,
   10.5, 21 y 27). ALdia corta antes de mandarlo, con el detalle de la
   diferencia.
4. **Numeración fuera de secuencia** — se facturó por otro sistema en el mismo
   punto de venta.
5. **Fecha fuera de rango** — AFIP acepta una ventana de días alrededor de hoy;
   una factura con fecha muy vieja se rechaza.

Después de corregir, **vuelva a pedir el CAE de la misma factura**: mientras el
resultado sea rechazo no hay CAE, así que no se duplica nada.

Si lo que está mal es el comprobante en sí (cliente equivocado, artículos
equivocados) y **todavía no tiene CAE**, lo correcto es anular la factura y
rehacerla (skill de facturación). Si **ya tiene CAE**, no se anula: se corrige
con una nota de crédito (skill de notas de crédito y débito).

## Notas de crédito y débito ante AFIP

Se autorizan igual que una factura, pero indicando el tipo:

```
emitir_nota_credito(cliente="...", items=[...], motivo="Devolución")
solicitar_cae(numero=<n>, tipo_comprobante=3)    # 3 = NC A, 8 = NC B, 13 = NC C

emitir_nota_debito(cliente="...", concepto="Intereses", importe_neto=5000)
solicitar_cae(numero=<n>, tipo_comprobante=7)    # 2 = ND A, 7 = ND B, 12 = ND C
```

La respuesta de cada nota trae `tipo_comprobante_para_cae` ya calculado: úselo.

## El QR fiscal

Desde 2021 todo comprobante electrónico impreso debe llevar el **código QR**
(RG 4892/2020). ALdia lo genera, pero **no hay herramienta MCP que lo devuelva**:
se imprime desde el sistema, y sólo existe si la factura tiene CAE. Si el usuario
pregunta por el QR, indíquele que imprima el comprobante desde ALdia.

## Limitaciones a tener presentes

- El CAE se pide **de a un comprobante**: no hay autorización por lote.
- No hay herramienta para consultar en AFIP el último comprobante autorizado ni
  las tablas oficiales de tipos; el backend las expone pero el asistente no las
  usa para decidir.
- ALdia **no guarda el vínculo** entre una nota de crédito o débito y la factura
  original: hay que anotarlo en el comprobante impreso.
- Configurar AFIP (certificado, punto de venta, CUIT, condición del negocio) se
  hace desde el sistema, no desde el asistente.
