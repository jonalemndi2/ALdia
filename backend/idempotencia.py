"""
idempotencia.py - Que un reintento no ejecute la operacion dos veces.

EL PROBLEMA QUE RESUELVE
========================
Un agente reintenta cuando no recibe respuesta. Si la operacion ya se ejecuto y
lo que se perdio fue la respuesta, el reintento la ejecuta de nuevo: dos cobros,
dos facturas. Con facturacion electronica es peor, porque un timeout no
significa que AFIP no haya procesado el pedido.

Este riesgo NO existia cuando el unico cliente era un navegador con una persona
mirando la pantalla: nace con el agente, que reintenta a ciegas.

COMO FUNCIONA: SE RESERVA ANTES DE EJECUTAR
===========================================
Quien llama manda un identificador propio de la operacion en la cabecera
`X-Operation-Id`. Lo primero que hace el sistema es RESERVAR ese identificador:
inserta y confirma una fila en estado "en curso" ANTES de ejecutar la ruta.
Recien despues ejecuta, y al terminar completa esa MISMA fila con el estado HTTP
y el cuerpo de la respuesta.

El orden es el nucleo del archivo. Consultar primero y guardar al final -- que es
como estaba escrito antes -- deja una ventana abierta entre la consulta y el
guardado: dos reintentos que llegan casi juntos (justo lo que pasa cuando a un
agente se le corta la respuesta, o cuando un cliente MCP vence su timeout) miran
los dos, los dos ven que no hay nada, y los dos ejecutan. La segunda solo choca
contra la clave primaria al final, cuando las dos facturas ya se emitieron. La
ventana era chica, pero no era cero.

Reservar primero la cierra, porque el arbitro pasa a ser el INSERT, que SQLite
serializa: de dos reservas simultaneas del mismo identificador entra una sola y
la otra recibe un error de clave duplicada ANTES de haber ejecutado nada.

Que se contesta en cada caso:

  * No hay reserva        -> se reserva y se ejecuta (el camino normal).
  * Reserva completada    -> se devuelve la respuesta guardada, sin ejecutar,
                             con la cabecera `X-Operacion-Repetida: 1`.
  * Reserva EN CURSO      -> 409 con codigo `OPERACION_EN_CURSO`. La respuesta
                             todavia no existe, asi que no se puede repetir, y
                             ejecutar seria duplicar la operacion: lo unico
                             honesto es avisar que la misma operacion se esta
                             ejecutando en este momento y que reintente en unos
                             segundos con el mismo identificador. Quien reintenta
                             despues recibe la respuesta buena.
  * Mismo id, otros datos -> 409 con codigo `OPERACION_CONFLICTIVA`, se controla
                             igual contra una reserva en curso que contra una ya
                             completada.

QUE PASA SI LA OPERACION NO TERMINA BIEN
========================================
Si la ejecucion termina en error (estado >= 400) o revienta, la reserva se
LIBERA: se borra la fila. Es la decision que el sistema ya tenia y se mantiene
tal cual -- un fallo puede ser transitorio (la otra caja tenia el lock de
escritura, AFIP no contesto) y quien llama tiene derecho a que su reintento se
ejecute de verdad, no a recibir el mismo error archivado durante una semana.

Si el proceso muere a mitad -- se cierra la ventana del .bat, se corta la luz --
no queda nadie para liberar nada y esa reserva bloquearia el identificador para
siempre. Por eso una reserva en curso mas vieja que `UMBRAL_ABANDONO` se da por
abandonada y el pedido siguiente la retoma.

La tabla vive en el mismo MetaData que la auditoria, y por el mismo motivo: no
debe desaparecer con un borrado de datos del comercio, porque entonces un
reintento posterior volveria a ejecutar.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, inspect, text
from sqlalchemy.exc import IntegrityError

from auditoria import BaseAuditoria
from database import SessionLocal, engine
from tiempo import ahora_utc

CABECERA_OPERACION = "x-operation-id"

# Cuanto se recuerda una operacion. Un reintento razonable ocurre en segundos o
# minutos; guardar mas tiempo solo hace crecer la tabla sin aportar seguridad.
RETENCION = timedelta(days=7)

# Estados de la reserva.
EN_CURSO = "en_curso"
COMPLETADA = "completada"

# Cuanto puede quedar una reserva "en curso" antes de darla por abandonada.
#
# El numero no es arbitrario: se mide contra la operacion legitima mas lenta del
# sistema, que es una factura electronica -- hasta dos llamadas a AFIP de 30
# segundos cada una (afip.TIMEOUT_SEGUNDOS) mas la espera por el lock de
# escritura de SQLite (database.BUSY_TIMEOUT_MS, 10 segundos): unos 70 segundos
# de techo. El umbral esta algo por encima del doble de ese techo.
#
# Los dos errores posibles no cuestan lo mismo, y por eso se elige asi:
# quedarse corto significa retomar una operacion que en realidad sigue
# corriendo, o sea ejecutarla dos veces -- exactamente lo que este archivo
# existe para impedir. Pasarse significa que un identificador queda bloqueado
# unos minutos de mas despues de una caida del proceso, y quien llama recibe
# mientras tanto un 409 que le dice que espere. Se prefiere siempre el segundo.
UMBRAL_ABANDONO = timedelta(seconds=150)

# Lo que se le sugiere a quien recibe el 409 de operacion en curso. Es del orden
# de lo que tarda una operacion normal, no del umbral de abandono.
ESPERA_SUGERIDA_SEGUNDOS = 3

# Veredictos de reservar().
RESERVA_TOMADA = "tomada"          # es nuestra: se puede ejecutar
RESERVA_COMPLETADA = "completada"  # ya termino: hay que repetir su respuesta
RESERVA_EN_CURSO = "en_curso"      # otra igual esta ejecutandose ahora mismo


class OperacionProcesada(BaseAuditoria):
    __tablename__ = "operaciones_procesadas"

    operacion_id = Column(String(120), primary_key=True)
    metodo = Column(String(10), default="")
    ruta = Column(String(300), default="")
    # Huella de los parametros: detecta que el mismo identificador se reuse con
    # datos distintos, que es un error de quien llama y no un reintento.
    huella = Column(String(64), default="")
    # Lo que distingue "ya se ejecuto y esta es la respuesta" de "se esta
    # ejecutando en este mismo instante". Sin esta columna la fila solo puede
    # escribirse al final, que es lo que dejaba abierta la carrera.
    estado = Column(String(12), nullable=False, default=EN_CURSO)
    # Todavia no hay respuesta cuando se reserva: 0 es "sin contestar".
    estado_http = Column(Integer, default=0)
    respuesta = Column(Text, default="")
    usuario = Column(String(80), default="")
    creada = Column(DateTime, default=ahora_utc)


Index("ix_operaciones_creada", OperacionProcesada.creada)


# Columnas que no existian en la primera version de la tabla. Ver
# `_migrar_columnas_de_reserva`.
#
# El valor por defecto del ALTER es 'completada' y no 'en_curso' a proposito:
# todas las filas que ya estaban guardadas son operaciones TERMINADAS (antes
# solo se escribia al final). Marcarlas "en curso" las convertiria en reservas
# fantasma que bloquearian sus identificadores hasta vencer el umbral.
_COLUMNAS_NUEVAS = (
    ("estado", f"VARCHAR(12) NOT NULL DEFAULT '{COMPLETADA}'"),
)


def _migrar_columnas_de_reserva(motor) -> None:
    """Pone al dia la tabla si venia de una base anterior a la reserva.

    Corre al importar el modulo, que es justo ANTES del create_all de
    `auditoria.instalar_auditoria()` (que importa este archivo por eso mismo):
    sobre una base nueva no hay nada que migrar y la tabla nace completa; sobre
    una base que ya venia funcionando, el ALTER la completa sin perder las
    operaciones recordadas. Mismo criterio que `_migrar_columnas_de_origen` de
    auditoria.py.
    """
    inspector = inspect(motor)
    if OperacionProcesada.__tablename__ not in set(inspector.get_table_names()):
        return
    existentes = {c["name"] for c in inspector.get_columns(OperacionProcesada.__tablename__)}
    faltantes = [(n, t) for n, t in _COLUMNAS_NUEVAS if n not in existentes]
    if not faltantes:
        return
    with motor.begin() as con:
        for nombre, tipo in faltantes:
            con.execute(text(
                f"ALTER TABLE {OperacionProcesada.__tablename__} ADD COLUMN {nombre} {tipo}"
            ))


_migrar_columnas_de_reserva(engine)


class OperacionConflictiva(Exception):
    """Mismo identificador de operacion, pero con otros datos."""


def huella_de(metodo: str, ruta: str, cuerpo: bytes) -> str:
    base = f"{metodo}|{ruta}|".encode() + (cuerpo or b"")
    return hashlib.sha256(base).hexdigest()


def _verificar_huella(previa: OperacionProcesada, operacion_id: str, huella: str) -> None:
    """Lanza OperacionConflictiva si el identificador ya se uso para otra cosa.

    Devolver la respuesta vieja seria mentir, y ejecutar seria arriesgar un
    duplicado. Lo correcto es avisar. Se controla igual contra una reserva en
    curso: que la otra operacion todavia no haya terminado no la vuelve la
    misma operacion.
    """
    if previa.huella and huella and previa.huella != huella:
        raise OperacionConflictiva(
            f"El identificador de operacion '{operacion_id}' ya se uso para otra "
            f"operacion distinta ({previa.metodo} {previa.ruta}). Use uno nuevo."
        )


def reservar(
    operacion_id: str,
    metodo: str,
    ruta: str,
    huella: str,
    usuario: str,
) -> tuple[str, OperacionProcesada | None]:
    """Toma el identificador ANTES de ejecutar. Devuelve (veredicto, fila).

    El INSERT es el arbitro. NO se consulta antes de insertar, y eso es lo
    unico que cierra la carrera: mirar y despues escribir deja el hueco por el
    que se cuelan dos ejecuciones. Si el INSERT entra, esta peticion es la
    duenia de la operacion y puede ejecutar; si choca contra la clave primaria,
    otra igual llego primero y solo queda mirar en que estado quedo.

    Usa su propia sesion, aparte de la de la ruta, a proposito: la reserva tiene
    que sobrevivir a un rollback de la operacion. Si compartiera transaccion, un
    fallo del negocio se llevaria puesta la reserva y volveria a abrir la
    ventana justo cuando mas se reintenta.
    """
    if not operacion_id:
        return RESERVA_TOMADA, None

    operacion_id = operacion_id[:120]
    sesion = SessionLocal()
    try:
        # Dos vueltas: entre el INSERT que choca y la lectura de la fila, la
        # otra peticion puede haber fallado y LIBERADO la reserva. Ahi el
        # identificador vuelve a estar libre y nos toca tomarlo a nosotros.
        for _ in range(2):
            try:
                sesion.add(OperacionProcesada(
                    operacion_id=operacion_id,
                    metodo=metodo[:10],
                    ruta=ruta[:300],
                    huella=huella,
                    estado=EN_CURSO,
                    estado_http=0,
                    respuesta="",
                    usuario=(usuario or "")[:80],
                    creada=ahora_utc(),
                ))
                sesion.commit()
                return RESERVA_TOMADA, None
            except IntegrityError:
                sesion.rollback()

            previa = sesion.get(OperacionProcesada, operacion_id)
            if previa is None:
                continue  # la liberaron entre medio: se vuelve a intentar

            _verificar_huella(previa, operacion_id, huella)

            if previa.estado != EN_CURSO:
                # Ya termino. Ojo: las filas anteriores a la migracion pueden
                # tener el estado en NULL, y tambien son operaciones terminadas.
                sesion.expunge(previa)
                return RESERVA_COMPLETADA, previa

            corte = ahora_utc() - UMBRAL_ABANDONO
            if previa.creada is not None and previa.creada >= corte:
                return RESERVA_EN_CURSO, None

            # Reserva vencida: el proceso que la tomo probablemente murio. Se
            # retoma con un UPDATE condicional -- el WHERE vuelve a exigir el
            # estado y la antiguedad -- para que si dos peticiones la encuentran
            # abandonada al mismo tiempo, la retome una sola. La que pierde
            # cuenta cero filas y se va con un 409, no con una ejecucion.
            retomada = (
                sesion.query(OperacionProcesada)
                .filter(
                    OperacionProcesada.operacion_id == operacion_id,
                    OperacionProcesada.estado == EN_CURSO,
                    OperacionProcesada.creada < corte,
                )
                .update(
                    {
                        OperacionProcesada.metodo: metodo[:10],
                        OperacionProcesada.ruta: ruta[:300],
                        OperacionProcesada.huella: huella,
                        OperacionProcesada.usuario: (usuario or "")[:80],
                        OperacionProcesada.creada: ahora_utc(),
                    },
                    synchronize_session=False,
                )
            )
            sesion.commit()
            return (RESERVA_TOMADA, None) if retomada else (RESERVA_EN_CURSO, None)

        # Dos vueltas y sigue sin poder tomarse: hay otra peticion moviendo esta
        # misma operacion. Ante la duda no se ejecuta.
        return RESERVA_EN_CURSO, None
    finally:
        sesion.close()


def completar(operacion_id: str, estado_http: int, respuesta: bytes) -> None:
    """Cierra la reserva con la respuesta definitiva, para poder repetirla.

    Actualiza la fila que ya reservo esta misma peticion; no inserta nada. Si
    esto no llegara a ejecutarse (por ejemplo, si el proceso muere justo aca),
    la fila queda en curso y el umbral de abandono la destraba: el peor caso es
    que la operacion se pueda reintentar, nunca que se duplique en silencio.
    """
    if not operacion_id:
        return
    sesion = SessionLocal()
    try:
        (
            sesion.query(OperacionProcesada)
            .filter(OperacionProcesada.operacion_id == operacion_id[:120])
            .update(
                {
                    OperacionProcesada.estado: COMPLETADA,
                    OperacionProcesada.estado_http: estado_http,
                    OperacionProcesada.respuesta:
                        (respuesta or b"").decode("utf-8", "replace")[:20000],
                },
                synchronize_session=False,
            )
        )
        sesion.commit()
    except Exception:
        sesion.rollback()
        raise
    finally:
        sesion.close()


def liberar(operacion_id: str) -> None:
    """Suelta la reserva para que el identificador se pueda reintentar de verdad.

    Se llama cuando la ejecucion no llego a buen puerto. Borrar en lugar de
    guardar el error es deliberado y viene de antes: un fallo puede ser
    transitorio y quien llama tiene derecho a que su reintento se EJECUTE, no a
    recibir el mismo error archivado durante una semana.

    Solo borra la fila si sigue en curso: una reserva ya completada es la
    respuesta buena de otra peticion y no se toca.
    """
    if not operacion_id:
        return
    sesion = SessionLocal()
    try:
        (
            sesion.query(OperacionProcesada)
            .filter(
                OperacionProcesada.operacion_id == operacion_id[:120],
                OperacionProcesada.estado == EN_CURSO,
            )
            .delete(synchronize_session=False)
        )
        sesion.commit()
    except Exception:
        sesion.rollback()
        raise
    finally:
        sesion.close()


def purgar() -> int:
    """Borra las operaciones mas viejas que la ventana de retencion."""
    sesion = SessionLocal()
    try:
        corte = ahora_utc() - RETENCION
        borradas = (
            sesion.query(OperacionProcesada)
            .filter(OperacionProcesada.creada < corte)
            .delete(synchronize_session=False)
        )
        sesion.commit()
        return borradas
    finally:
        sesion.close()


def cuerpo_de_conflicto(exc: OperacionConflictiva) -> bytes:
    return json.dumps({"detail": str(exc), "codigo": "OPERACION_CONFLICTIVA"},
                      ensure_ascii=False).encode()


def cuerpo_de_en_curso(operacion_id: str) -> bytes:
    """El 409 de "la misma operacion se esta ejecutando ahora".

    Va con codigo de maquina para que un agente pueda decidir solo: el mensaje
    le dice que espere y reintente CON EL MISMO identificador, que es lo unico
    seguro -- cambiarlo por uno nuevo es pedir el duplicado que se esta
    evitando.
    """
    return json.dumps({
        "detail": (
            f"La operacion '{operacion_id}' se esta ejecutando en este momento. "
            f"Espere unos segundos y reintente con el MISMO identificador: no se "
            f"va a ejecutar dos veces, y el reintento va a devolver el resultado "
            f"de la que ya esta corriendo."
        ),
        "codigo": "OPERACION_EN_CURSO",
        "reintentar_en_segundos": ESPERA_SUGERIDA_SEGUNDOS,
    }, ensure_ascii=False).encode()
