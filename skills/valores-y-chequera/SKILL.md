---
name: valores-y-chequera
description: Manejo de cheques en ALdia - qué cheques hay en cartera, cuáles vencen y cuándo depositarlos, cheques propios emitidos que van a debitar de la cuenta, y endoso de un cheque de tercero para pagarle a un proveedor. Usar cuando el usuario diga "qué cheques tengo", "cheques a depositar", "cuándo vence el cheque", "me pagaron con cheque", "pagué con cheque", "endosar", "cartera de cheques", "chequera" o pregunte por valores a cobrar.
---

# Valores y chequera (ALdia)

Un cheque **no es plata todavía**. Esta es la idea que ordena todo lo demás: si
el asistente trata los cheques como efectivo, el saldo de caja va a dar mal y el
comerciante va a creer que tiene dinero que no tiene.

## Cómo lo entiende ALdia

| | Qué es | Efecto en caja |
|---|---|---|
| Cheque **recibido** de un cliente | Un valor a cobrar. Entra a la chequera. | **Ninguno** hasta que se deposita y acredita |
| Cheque **propio emitido** a un proveedor | Una obligación futura. | **Ninguno** hasta que el banco lo debita |
| Cheque de tercero **endosado** | Un valor que se usa para pagar. | **Ninguno**: no sale plata de la caja |
| Cobro o pago en **efectivo/transferencia** | Dinero real. | Genera el asiento de caja |

Por eso, cuando alguien pregunta "¿cuánto tengo?", hay **dos respuestas** y
conviene dar las dos: el efectivo (`get_cash_balance`) y los valores en cartera
(`list_checks`).

## Paso 1 — Ver la cartera

```
list_checks(solo_pendientes=true)    # solo los que siguen sin usarse/cobrarse
list_checks()                        # todos, incluidos los ya aplicados
```

Distinga siempre los dos grupos que devuelve:

- **Cheques recibidos de clientes** — valores a cobrar. Son un activo.
- **Cheques propios emitidos** — obligaciones. Van a salir de la cuenta.

Al informar, ordene por **vencimiento** y marque los que vencen dentro de los
próximos días. Un cheque vencido sin depositar es plata parada.

## Paso 2 — Registrar un cobro con cheque

Cuando un cliente paga con cheque, no es un movimiento de caja: es un cobro con
`tipo="cheque"`.

```
record_payment(
  cliente="30712345671",
  monto=45000,
  tipo="cheque",
  referencia="CH-00123456",     # número del cheque
  banco="Banco Nación",
  vencimiento="2026-10-15"      # fecha de cobro del cheque
)
```

**Pida siempre el número, el banco y el vencimiento.** Sin el vencimiento el
sistema asume la fecha del cobro, y después nadie sabe cuándo depositarlo.

Efecto: baja la deuda del cliente y el cheque queda en la chequera. **No entra a
caja**, y eso es correcto — si el usuario dice "pero cobré", explique que el
dinero aparece cuando el cheque se acredita.

## Paso 3 — Pagar con cheque

Hay dos casos distintos y conviene preguntar cuál es:

**a) Cheque propio** (el comerciante libra un cheque de su chequera):

```
record_vendor_payment(proveedor="30500010912", monto=45000, tipo="cheque",
               referencia="CH-99887", banco="Banco Nación",
               vencimiento="2026-11-30")
```

**b) Endoso de un cheque de tercero** (le pasa al proveedor un cheque que le
dieron a él). Primero identifique el cheque en la cartera y pase su `cheque_id`:

```
list_checks(solo_pendientes=true)          # elegir el cheque
record_vendor_payment(proveedor="30500010912", monto=45000,
               tipo="cheque tercero", cheque_id=4)
```

El sistema **marca ese cheque como usado**, así que no se puede endosar dos
veces. Si intenta usar uno ya endosado, la respuesta lo dice con el número y el
pago donde se usó: no insista, avísele al usuario y pídale otro cheque.

## Paso 4 — Cuando el cheque se acredita

ALdia registra el cheque en la chequera, pero el **ingreso efectivo del dinero**
al depositarlo se carga como movimiento de caja o de banco:

```
record_cash_movement(concepto="Acreditación cheque CH-00123456", ingreso=45000)
```

Hágalo solo cuando el usuario confirme que el banco lo acreditó. Un cheque
rechazado no se acredita: en ese caso hay que volver a generar la deuda del
cliente, y conviene avisarle al usuario que eso requiere una decisión suya
(anular el cobro con `void_payment(..., confirmar=true)` y volver a gestionarlo).

## Cómo informar

En prosa y en pesos, separando lo que es dinero de lo que todavía no:

```
Cartera al 18/08
  Efectivo en caja            $ 125.400,00
  Cheques a cobrar (4)        $ 310.000,00
     CH-00123456  Banco Nación   vence 15/10   $ 45.000,00
     ...
  Cheques propios emitidos (2) $ 88.000,00
     CH-99887     vence 30/11   $ 45.000,00

  Atención: 1 cheque vence esta semana.
```

## Errores frecuentes

- **Tratar un cheque como efectivo.** No entra a caja. Si el usuario pregunta
  cuánta plata tiene, aclare las dos cifras.
- Registrar un cobro con cheque *y además* un movimiento de caja por el mismo
  importe: lo estaría contando dos veces.
- Olvidar el vencimiento. Sin él, la cartera no sirve para planificar.
- Endosar sin `cheque_id`: se registraría como cheque propio y el cheque del
  tercero quedaría disponible para usarse otra vez.
