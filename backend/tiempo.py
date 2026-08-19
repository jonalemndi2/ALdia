"""
tiempo.py - El instante actual, en un solo formato y en un solo lugar.

POR QUE ESTE ARCHIVO EXISTE
===========================
`datetime.utcnow()` quedo deprecada en Python 3.12 y se va a eliminar. El
reemplazo obvio, `datetime.now(timezone.utc)`, devuelve un datetime CON zona, y
cambiarlo asi nomas rompe el sistema en silencio por dos motivos distintos:

  1. LAS COLUMNAS DateTime DE SQLITE NO GUARDAN LA ZONA.
     Si se le pasa un datetime con tzinfo, SQLite lo escribe igual y al releerlo
     vuelve SIN zona. Entonces `guardado < datetime.now(timezone.utc)` lanza
     "can't compare offset-naive and offset-aware datetimes" — y no en el
     momento de escribir, que seria facil de encontrar, sino despues, al comparar.

  2. LAS COMPARACIONES DE TEXTO.
     Varias fechas del sistema se ordenan y filtran como texto. Una misma
     columna con valores mezclados ('2026-08-19 14:03:00' junto a
     '2026-08-19 14:03:00+00:00') se ordena mal sin dar ningun error: la purga
     de operaciones viejas y la deteccion de reservas abandonadas
     (ver idempotencia.py) dejarian de encontrar filas y nadie se enteraria.

Por eso el sistema sigue guardando UTC INGENUO — el mismo formato que venia
usando `utcnow()` — pero obtenido de la forma que no esta deprecada. La
normalizacion vive aca, una sola vez, para que no haya dos criterios conviviendo
en la base.

QUE USAR
========
  * `ahora_utc()`  -> para lo que se guarda o se compara contra la base.
  * `datetime.now()` (hora local) -> para lo que LEE una persona. El registro de
    auditoria usa la hora local del servidor a proposito: al duenio del comercio
    le sirve "18/08 10:22", no un UTC que tiene que traducir mentalmente.
"""
from datetime import datetime, timezone

__all__ = ["ahora_utc"]


def ahora_utc() -> datetime:
    """Instante actual en UTC y SIN tzinfo. Ver el encabezado del archivo."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
