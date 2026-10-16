---
name: liquidacion-cereales-y-hacienda
description: Liquidaciones de cereales (LPG: peso bruto, humedad, merma, flete, secado, zarandeo, comisión, retenciones SISA/Ganancias, COE) y de hacienda (LSP: cabezas, kg brutos, desbaste, DTE, RENSPA, tropa, gastos de feria y SENASA) en ALdia. Usar cuando el usuario envíe o pida cargar una liquidación primaria o secundaria de granos, una cuenta de venta y líquido producto de hacienda, registrar un COE de 12 dígitos o consultar liquidaciones agropecuarias.
---

# Liquidación de cereales y hacienda (ALdia)

Esta skill guía la carga, verificación, confirmación y registro fiscal de
**Liquidaciones Primarias/Secundarias de Granos (LPG)** y **Liquidaciones
Pecuarias / de Hacienda (LSP)** usando las herramientas MCP del servidor
**aldia**.

## Por qué una liquidación no es una factura común

Una liquidación agropecuaria o de consignación integra **tres bloques** en un
mismo documento:

1. **Operación bruta**: cantidad física neta (después de aplicar la **merma** en
   granos o el **desbaste** en hacienda) multiplicada por el precio unitario,
   más el IVA de la operación (habitualmente **10,5 %** en granos y hacienda
   bovina en Argentina).
2. **Deducciones comerciales**: gastos descontados en la misma liquidación
   (flete corto/largo, secado, zarandeo, paritaria, comisión de acopio o feria,
   derecho de mercado, guías, arancel SENASA), cada uno con su base imponible y
   su propia alícuota de IVA (generalmente **21 %** o **10,5 %**).
3. **Retenciones y percepciones impositivas**: importes retenidos sobre la
   operación (Retención de IVA / SISA, Retención de Ganancias RG 830, Ingresos
   Brutos, sellados o tasas provinciales).

El monto que realmente mueve la cuenta corriente del productor, acopio o
frigorífico es el **Neto Liquidado**:

```
Neto Liquidado = (Subtotal Bruto + IVA Operación)
               − (Subtotal Deducciones + IVA Deducciones)
               − Total Retenciones
```

Toda esa aritmética se ejecuta **en el servidor en centavos enteros**. El
asistente nunca debe redondear ni calcular el neto a mano: envía los datos
físicos y las bases al borrador y lee el cálculo exacto que devuelve ALdia.

---

## Flujo obligatorio: De PDF/Foto a Borrador → Confirmación del usuario

Cuando el usuario envía una foto, un PDF o dicta los datos de una liquidación:

### Paso 1 — Verificar el tercero y el artículo (si mueve stock)

1. Busque al productor, acopio, consignatario o frigorífico con `find_vendor`
   (si `operacion="compra"`) o `find_customer` (si `operacion="venta"`).
   - **Venta (`operacion="venta"`)**: el negocio entrega/vende el cereal o la
     hacienda a un comprador (acopio, corredor, frigorífico, feria) que nos
     liquida y nos debe el neto.
   - **Compra (`operacion="compra"`)**: el negocio recibe/compra de un productor
     o proveedor y le debemos el neto liquidado.
2. Si quiere que la liquidación descuente o ingrese stock físico en el depósito
   (ej. kilos de Soja, Maíz, Trigo o cabezas/kilos de Novillo), busque el
   código del artículo con `find_product`. Si solo lleva control contable sin
   artículo de inventario vinculado, puede omitir `codigo` en el renglón.

### Paso 2 — Crear siempre primero el borrador (`create_settlement_draft`)

Nunca impacte stock ni cuenta corriente sin mostrar antes la liquidación
calculada. Llame a:

```
create_settlement_draft(
    tercero="CUIT o nombre",
    rubro="granos" | "hacienda" | "general",
    operacion="compra" | "venta",
    fecha="YYYY-MM-DD",
    num_comprobante="LPG-0001-00045120",
    datos_dominio={...},
    items=[...],
    deducciones=[...],
    retenciones=[...],
)
```

El borrador queda guardado con `estado="borrador"` y **no mueve stock ni
saldos**.

### Paso 3 — Presentar el desglose y pedir confirmación explícita

Muestre al usuario en prosa clara:

- **Tercero** (nombre y CUIT) y tipo (`compra` o `venta`).
- **Kilos brutos, merma/desbaste y kilos netos** (y cantidad de **cabezas** en
  hacienda).
- **Bruto de la operación** (subtotal + IVA).
- **Total de deducciones** (flete, secado, zarandeo, comisión, SENASA + IVA).
- **Total de retenciones** (SISA, Ganancias, IIBB).
- **Neto liquidado final** y compárelo contra el total impreso en el PDF/foto
  del usuario.

### Paso 4 — Confirmar el borrador (`confirm_settlement_draft`)

Recién cuando el usuario confirme que el neto y los conceptos coinciden con su
comprobante, ejecute:

```
confirm_settlement_draft(liquidacion_id=ID, confirmar=true)
```

Al confirmar:
- Se actualiza el stock físico por la **`cantidad_neta`** (no por los kilos
  brutos).
- Se impacta la cuenta corriente del cliente o proveedor por el
  **`neto_liquidado`**.

---

## Campos específicos por rubro

### 1. Cereales y Oleaginosas (`rubro="granos"` — LPG)

- **Renglón (`items`)**:
  - `descripcion`: especie y campaña (ej. `"Soja Campaña 25/26"`, `"Maíz"`).
  - `cantidad_bruta`: peso bruto de balanza (normalmente en `"KG"` o `"TN"`).
  - `merma_pct` o `merma_cantidad`: merma por humedad, zarandeo y volátil. Si
    informa `cantidad_bruta` y `merma_pct`, ALdia calcula `merma_cantidad` y
    `cantidad_neta` automáticamente.
  - `precio_unitario`: precio por unidad neta (por kg o por tonelada, en la
    misma unidad que `cantidad_neta`).
  - `iva_alicuota`: `10.5` (granos en Argentina) o la tasa vigente del país.
- **Metadatos (`datos_dominio`)**:
  - `campana`: ej. `"25/26"`
  - `especie`: ej. `"Soja"`, `"Maíz"`, `"Trigo"`, `"Girasol"`
  - `grado`: `"G2"`, `"G1"`
  - `factor`: ej. `98.5`
  - `humedad_pct`: ej. `15.2`
  - `carta_porte`: número de Carta de Porte Electrónica (CPE)
  - `procedencia` y `puerto`: localidad de origen y puerto de destino
- **Deducciones habituales (`deducciones`)**:
  - `concepto`: `"flete"`, `"secado"`, `"zarandeo"`, `"comision"`, `"almacenaje"`, `"paritaria"`
  - `base_imponible`: importe neto del gasto sin IVA
  - `iva_alicuota`: `21.0` o `10.5` según corresponda en la liquidación
- **Retenciones habituales (`retenciones`)**:
  - `tipo`: `"sisa"`, `"iva"`, `"ganancias"`, `"iibb"`, `"sellos"`
  - `base_calculo`, `alicuota`, `importe` y `certificado`

### 2. Hacienda y Ganadería (`rubro="hacienda"` — LSP)

- **Renglón (`items`)**:
  - `descripcion`: categoría (ej. `"Novillos Mestizos"`, `"Vaquillonas"`, `"Terneros"`).
  - `cabezas`: cantidad de animales (entero).
  - `cantidad_bruta`: kilos vivos en balanza de origen/feria.
  - `merma_pct` o `merma_cantidad`: **desbaste** (porcentaje o kilos descontados
    por desbaste).
  - `cantidad_neta`: kilos netos a liquidar.
  - `precio_unitario`: precio por kilo vivo neto (o al gancho).
  - `iva_alicuota`: `10.5` en hacienda bovina/ovina/porcina en Argentina.
- **Metadatos (`datos_dominio`)**:
  - `dte`: número de Documento de Tránsito Electrónico (SENASA)
  - `renspa`: número de RENSPA del establecimiento
  - `tropa`: número de tropa
  - `consignatario`: nombre de la casa consignataria o feria
  - `destino`: `"Faena"` o `"Invernada / Cría"`
- **Deducciones habituales (`deducciones`)**:
  - `concepto`: `"comision"`, `"flete"`, `"senasa"`, `"guia"`, `"piso_feria"`, `"ipcva"`

---

## Registro de COE y anulaciones

- **Registrar COE (`register_settlement_coe`)**:
  En instalaciones argentinas, las liquidaciones primarias y secundarias llevan
  un **Código de Operación Electrónica (COE)** de **12 dígitos numéricos**
  otorgado por ARCA/AFIP. Para asentarlo sobre una liquidación existente:
  ```
  register_settlement_coe(liquidacion_id=ID, coe="123456789012", confirmar=true)
  ```
  Nunca invente un COE. En países sin autorización fiscal previa (como EE.UU.),
  esta herramienta no aplica.
- **Anular una liquidación (`void_settlement`)**:
  Si una liquidación se cargó con error, `void_settlement(liquidacion_id=ID, confirmar=true)`
  la marca como `anulada` y, si ya estaba confirmada, revierte automáticamente
  tanto el movimiento de stock neto como el saldo en cuenta corriente. Pida
  siempre autorización explícita del usuario antes de pasar `confirmar=true`.
