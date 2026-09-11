# ALdía: oferta comercial y condiciones del piloto

## Qué se puede ofrecer hoy

Instalación asistida de gestión comercial local, configuración, capacitación,
soporte y actualizaciones administradas. El alcance se acuerda por escrito para
cada comercio. No ofrecer todavía emisión fiscal autónoma ni contabilidad
certificada. Validar con el contador del cliente las operaciones a utilizar.

La licencia Apache-2.0 permite comercializar el software y los servicios respetando
sus avisos y condiciones. El código público puede obtenerse sin contratar soporte.
No introducir bloqueos en una instalación local al cancelar el abono.

## Paquetes propuestos (sin precios prometidos)

- **Puesta en marcha, pago único:** una instalación y empresa, usuarios/roles,
  importación de un archivo acordado, capacitación y prueba de respaldo.
- **Soporte, mensual opcional:** actualizaciones programadas, revisión de copias,
  asistencia remota con cupo de horas y plazo de respuesta pactados.
- **Administrado:** lo anterior más servidor, almacenamiento y monitoreo. Ofrecer
  sólo tras validar aislamiento, seguridad y recuperación del despliegue concreto.

Cotizar instalación = horas estimadas × tarifa + costos de terceros + contingencia.
Cotizar abono = horas reservadas × tarifa + infraestructura + margen. Definir qué
consume el cupo y cotizar migraciones, visitas y desarrollos aparte. No prometer
24/7 ni recuperación inmediata sin recursos que lo respalden. Los importes y el
tratamiento de IVA deben acordarse antes de entregar una oferta al cliente.

## Condiciones mínimas para la propuesta

Identificar partes, versión y alcance; modalidad local/alojada; precio e impuestos;
horarios y canal de atención; tiempo de primera respuesta (no confundir con tiempo
de resolución); cupo y excedentes; ventanas de actualización; responsabilidad de
copias externas; destino y retención de datos; acceso remoto autorizado; exportación
y entrega de datos al finalizar. Revisión contractual local antes de usarla como contrato.

## Cambio de contrato técnico

- `create_invoice` ahora prepara un borrador; devuelve `borrador_id`, sin stock ni deuda.
- `confirm_invoice_draft(id, confirmar=true)` confirma los efectos comerciales una
  sola vez por borrador. Confirmar no implica CAE.
- REST: POST `/api/facturas/borradores`, GET de listado/detalle y POST
  `/api/facturas/borradores/{id}/confirmar`. El contenido preparado es inmutable.
- POST `/api/facturas/` conserva compatibilidad para integradores, pero exige
  `confirmar=true`. Para reintentos usar un mismo `X-Operation-Id`; preferir borradores.
- Un booleano NO prueba consentimiento humano: la integración debe mostrar el
  detalle y obtener aprobación real. Nunca dar cuentas administrativas a agentes.
- La herramienta MCP fiscal no emite. La API fiscal exige administrador,
  confirmación y `ALDIA_EMISION_FISCAL=si`, además de configuración ARCA válida.
  Esta variable está apagada por defecto. No habilitar producción durante el piloto.
- Existe una reserva fiscal durable antes de llamar a ARCA. Si hay timeout o caída,
  bloquea nuevas emisiones. No borrar la reserva ni repetir a ciegas: un operador
  debe conciliar comprobante, numeración y CAE contra ARCA. Aún no hay interfaz de
  conciliación; requiere intervención técnica documentada. No es un circuito fiscal
  listo para ofrecer sin acompañamiento.
- No se elimina una factura con CAE o resultado autorizado. Una venta comercial
  anulada no puede volver a confirmarse reutilizando su borrador.
- Sin Internet puede prepararse y confirmarse una operación interna; eso no crea
  una factura fiscal ni una cola de emisión automática.

## Aceptación antes del primer cliente

1. Instalación limpia y usuarios individuales con mínimo permiso.
2. Ensayo del circuito completo con datos ficticios: venta, devolución, cobro,
   pago y cierre; revisión del contador de los saldos y ajustes.
3. Ensayo de doble clic, reintento, caída y stock insuficiente.
4. Copia en dispositivo externo y ensayo aislado de restauración.
5. Acuerdo escrito de alcance y soporte; persona responsable en el comercio.
6. Piloto limitado con acompañamiento. Medir incidencias y tiempo ahorrado antes
   de ofrecer a más clientes. Las pruebas automatizadas no sustituyen este paso.

## Respaldos y actualizaciones

Antes de actualizar, cerrar puestos y crear una copia coherente mediante la API
SQLite. No copiar únicamente el `.db` activo ni borrar su WAL. Conservar una copia
fuera del equipo. Ensayar, sin reemplazar la base operativa:

```text
.venv/bin/python scripts/verificar_respaldo.py /ruta/a/copia.db
```

Windows: usar `.venv\Scripts\python.exe`. El ensayo verifica integridad,
referencias y reapertura de una copia aislada; no certifica corrección contable.
Para restaurar de verdad: detener TODOS los procesos, conservar base y archivos
laterales actuales en respaldo aparte, validar la copia elegida y seguir un
procedimiento de recuperación supervisado. Nunca mezclar WAL antiguo con otra base.

La actualización agrega tablas, no convierte ni elimina registros existentes.
No desplegar sobre la base real sin respaldo previo. Volver a una versión anterior
puede quitar estos controles; un rollback debe evaluarse, no aplicarse a ciegas.

## Limitaciones aún abiertas

El cierre de total contra subtotal más IVA no sustituye la conciliación de todos
los renglones y sus impuestos históricos. Las notas de ajuste y anulaciones
comerciales requieren validación contable de extremo a extremo. No se declara
resuelto el circuito fiscal de notas ni la recuperación automática ante timeout.
El reset destructivo remoto fue deshabilitado; una instalación nueva usa otra base.
