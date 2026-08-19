"""
test_idempotencia.py - Que un reintento no ejecute la operacion dos veces.

Un agente reintenta cuando no recibe respuesta. Si lo que se perdio fue la
respuesta y no la ejecucion, el reintento duplica el cobro o la factura. Con
facturacion electronica es peor: un timeout no significa que AFIP no haya
procesado el pedido.
"""
import itertools
import threading
from datetime import datetime, timedelta, timezone

import pytest

_ops = itertools.count(1)


def _op_id(nombre="op"):
    return f"prueba_{nombre}_{next(_ops)}"


@pytest.fixture
def cliente_con_saldo(admin, cuit):
    c = cuit("30")
    admin.post("/api/clientes/", json={"cuit": c, "nombre": f"Cliente {c[-4:]}"})
    admin.post("/api/facturas/", json={"cuit": c, "fecha": "2026-08-18",
                                       "subtotal": 1000, "ivaTotal": 210,
                                       "total": 1210, "items": []})
    return c


def _saldo(admin, c):
    return admin.get(f"/api/clientes/{c}").json()["saldo"]


class TestReintentos:
    def test_el_mismo_id_no_cobra_dos_veces(self, admin, cliente_con_saldo):
        """El caso que motiva todo esto."""
        op = _op_id("cobro")
        cuerpo = {"cliente": cliente_con_saldo, "monto": 500,
                  "fecha": "2026-08-18", "tipo": "efectivo"}

        antes = _saldo(admin, cliente_con_saldo)
        r1 = admin.post("/api/cobros/", json=cuerpo, headers={"X-Operation-Id": op})
        assert r1.status_code == 200
        despues_del_primero = _saldo(admin, cliente_con_saldo)
        assert despues_del_primero == antes - 500

        # El agente no recibió la respuesta y reintenta.
        r2 = admin.post("/api/cobros/", json=cuerpo, headers={"X-Operation-Id": op})
        assert r2.status_code == 200
        assert r2.json() == r1.json(), "La respuesta repetida debe ser idéntica"
        assert r2.headers.get("x-operacion-repetida") == "1"

        assert _saldo(admin, cliente_con_saldo) == despues_del_primero, (
            "El reintento volvió a cobrar: el saldo se movió dos veces"
        )

    def test_diez_reintentos_siguen_siendo_un_cobro(self, admin, cliente_con_saldo):
        op = _op_id("insistente")
        cuerpo = {"cliente": cliente_con_saldo, "monto": 100,
                  "fecha": "2026-08-18", "tipo": "efectivo"}
        antes = _saldo(admin, cliente_con_saldo)
        for _ in range(10):
            assert admin.post("/api/cobros/", json=cuerpo,
                              headers={"X-Operation-Id": op}).status_code == 200
        assert _saldo(admin, cliente_con_saldo) == antes - 100

    def test_sin_id_no_hay_proteccion(self, admin, cliente_con_saldo):
        """Sin identificador el sistema no puede saber que es un reintento.

        Se documenta para que quede explícito: la protección la habilita quien
        llama, mandando el identificador.
        """
        cuerpo = {"cliente": cliente_con_saldo, "monto": 50,
                  "fecha": "2026-08-18", "tipo": "efectivo"}
        antes = _saldo(admin, cliente_con_saldo)
        admin.post("/api/cobros/", json=cuerpo)
        admin.post("/api/cobros/", json=cuerpo)
        assert _saldo(admin, cliente_con_saldo) == antes - 100  # se cobró dos veces

    def test_ids_distintos_son_operaciones_distintas(self, admin, cliente_con_saldo):
        cuerpo = {"cliente": cliente_con_saldo, "monto": 25,
                  "fecha": "2026-08-18", "tipo": "efectivo"}
        antes = _saldo(admin, cliente_con_saldo)
        admin.post("/api/cobros/", json=cuerpo, headers={"X-Operation-Id": _op_id()})
        admin.post("/api/cobros/", json=cuerpo, headers={"X-Operation-Id": _op_id()})
        assert _saldo(admin, cliente_con_saldo) == antes - 50


class TestConflictos:
    def test_reusar_un_id_con_otros_datos_se_rechaza(self, admin, cliente_con_saldo):
        """No es un reintento: es un error de quien llama, y hay que avisarlo.

        Devolver la respuesta vieja sería mentir; ejecutar sería arriesgar un
        duplicado silencioso.
        """
        op = _op_id("conflicto")
        admin.post("/api/cobros/",
                   json={"cliente": cliente_con_saldo, "monto": 10,
                         "fecha": "2026-08-18", "tipo": "efectivo"},
                   headers={"X-Operation-Id": op})

        r = admin.post("/api/cobros/",
                       json={"cliente": cliente_con_saldo, "monto": 99999,
                             "fecha": "2026-08-18", "tipo": "efectivo"},
                       headers={"X-Operation-Id": op})
        assert r.status_code == 409
        assert r.json().get("codigo") == "OPERACION_CONFLICTIVA"


class TestAlcance:
    def test_una_factura_tampoco_se_duplica(self, admin, cuit):
        """El caso más caro: dos comprobantes fiscales por el mismo hecho."""
        c = cuit("30")
        admin.post("/api/clientes/", json={"cuit": c, "nombre": "Cliente factura"})
        op = _op_id("factura")
        cuerpo = {"cuit": c, "fecha": "2026-08-18", "subtotal": 100,
                  "ivaTotal": 21, "total": 121, "items": []}

        r1 = admin.post("/api/facturas/", json=cuerpo, headers={"X-Operation-Id": op})
        r2 = admin.post("/api/facturas/", json=cuerpo, headers={"X-Operation-Id": op})
        assert r1.json()["facturanumero"] == r2.json()["facturanumero"], (
            "Se emitieron dos comprobantes fiscales para la misma operación"
        )

    def test_un_error_no_se_recuerda(self, admin):
        """Un fallo puede ser transitorio: quien llama tiene derecho a reintentar."""
        op = _op_id("fallido")
        malo = {"cliente": "20123456786", "monto": 10,
                "fecha": "2026-08-18", "tipo": "efectivo"}   # cliente inexistente
        assert admin.post("/api/cobros/", json=malo,
                          headers={"X-Operation-Id": op}).status_code == 404
        # El mismo id vuelve a intentarse de verdad, no devuelve el error cacheado.
        r = admin.post("/api/cobros/", json=malo, headers={"X-Operation-Id": op})
        assert r.status_code == 404
        assert r.headers.get("x-operacion-repetida") != "1"


# ─────────────────────────────────────────────────────────────────────────────
# La carrera: dos reintentos que llegan JUNTOS.
#
# Es el caso que motiva el diseño de reserva-antes-de-ejecutar. Un agente al que
# se le corta la respuesta, o un cliente MCP que vence su timeout, no reintenta
# "un rato después": reintenta encima del pedido anterior. Si el sistema mira la
# tabla primero y la escribe al final, los dos pedidos miran, los dos no
# encuentran nada y los dos ejecutan.
#
# Lo que se verifica NO es el código de respuesta -- eso puede mentir -- sino
# cuántas filas quedaron en la tabla real de cobros.
# ─────────────────────────────────────────────────────────────────────────────
class TestCarrera:
    @staticmethod
    def _en_paralelo(disparar, cantidad=2):
        """Lanza `cantidad` peticiones lo más juntas que se pueda."""
        barrera = threading.Barrier(cantidad)
        respuestas = []
        candado = threading.Lock()

        def correr():
            barrera.wait()          # todos salen en el mismo instante
            r = disparar()
            with candado:
                respuestas.append(r)

        hilos = [threading.Thread(target=correr) for _ in range(cantidad)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=30)
        assert not any(h.is_alive() for h in hilos), "Alguna petición quedó colgada"
        return respuestas

    def test_dos_cobros_simultaneos_con_el_mismo_id_cobran_una_sola_vez(
            self, admin, cliente_con_saldo):
        """El defecto real: la ventana entre consultar y guardar.

        Con el flujo anterior (consultar, ejecutar, guardar al final) esta
        prueba encuentra DOS cobros en la tabla: los dos pedidos pasaron la
        consulta antes de que ninguno hubiera guardado nada. Con la reserva
        tomada antes de ejecutar, el segundo choca contra la clave primaria
        cuando todavía no ejecutó nada.
        """
        op = _op_id("carrera")
        monto = 303
        cuerpo = {"cliente": cliente_con_saldo, "monto": monto,
                  "fecha": "2026-08-18", "tipo": "efectivo"}
        antes = _saldo(admin, cliente_con_saldo)

        respuestas = self._en_paralelo(
            lambda: admin.post("/api/cobros/", json=cuerpo,
                               headers={"X-Operation-Id": op})
        )

        # La prueba de verdad: filas en la tabla de cobros, no códigos HTTP.
        cobros = [c for c in admin.get(f"/api/cobros/?cliente={cliente_con_saldo}").json()
                  if c["monto"] == monto]
        assert len(cobros) == 1, (
            f"La operación se ejecutó {len(cobros)} veces: dos reintentos "
            f"simultáneos con el mismo X-Operation-Id entraron los dos"
        )
        assert _saldo(admin, cliente_con_saldo) == antes - monto

        # Y la respuesta que recibe cada uno tiene que ser una de las dos
        # definidas, nunca un 500 ni un error de clave duplicada.
        assert len(respuestas) == 2
        for r in respuestas:
            assert r.status_code in (200, 409), r.text
            if r.status_code == 409:
                assert r.json().get("codigo") == "OPERACION_EN_CURSO"
                assert r.headers.get("retry-after")

    def test_cinco_reintentos_simultaneos_emiten_una_sola_factura(self, admin, cuit):
        """El caso más caro: cinco pedidos encimados, un solo comprobante fiscal."""
        c = cuit("30")
        admin.post("/api/clientes/", json={"cuit": c, "nombre": "Cliente carrera"})
        op = _op_id("carrera_factura")
        cuerpo = {"cuit": c, "fecha": "2026-08-18", "subtotal": 100,
                  "ivaTotal": 21, "total": 121, "items": []}

        self._en_paralelo(
            lambda: admin.post("/api/facturas/", json=cuerpo,
                               headers={"X-Operation-Id": op}),
            cantidad=5,
        )

        facturas = admin.get(f"/api/facturas/?cliente={c}").json()
        assert len(facturas) == 1, (
            f"Se emitieron {len(facturas)} comprobantes fiscales para la misma "
            f"operación"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Los bordes de la reserva: qué pasa cuando la fila queda tomada y la primera
# petición no terminó (o no va a terminar nunca).
# ─────────────────────────────────────────────────────────────────────────────
def _reservar_a_mano(op, huella="", antiguedad_segundos=0):
    """Deja una reserva "en curso" como la que dejaría otra petición en vuelo.

    `antiguedad_segundos` permite envejecerla para simular el proceso que se
    murió a mitad y nunca cerró su reserva.
    """
    import idempotencia
    from database import SessionLocal

    sesion = SessionLocal()
    try:
        sesion.add(idempotencia.OperacionProcesada(
            operacion_id=op, metodo="POST", ruta="/api/cobros/", huella=huella,
            estado=idempotencia.EN_CURSO, estado_http=0, respuesta="",
            usuario="admin",
            creada=datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(seconds=antiguedad_segundos),
        ))
        sesion.commit()
    finally:
        sesion.close()


def _fila(op):
    import idempotencia
    from database import SessionLocal

    sesion = SessionLocal()
    try:
        fila = sesion.get(idempotencia.OperacionProcesada, op)
        if fila is not None:
            sesion.expunge(fila)
        return fila
    finally:
        sesion.close()


class TestReservaEnCurso:
    def test_mientras_la_primera_corre_la_segunda_recibe_409_y_no_ejecuta(
            self, admin, cliente_con_saldo):
        """No se puede devolver una respuesta que todavía no existe.

        Las dos alternativas son peores: ejecutar duplica la operación, y
        esperar a que la otra termine deja la petición colgada del tiempo de un
        tercero. Se contesta con un código de máquina y `Retry-After`.
        """
        op = _op_id("en_curso")
        _reservar_a_mano(op)

        antes = _saldo(admin, cliente_con_saldo)
        r = admin.post("/api/cobros/",
                       json={"cliente": cliente_con_saldo, "monto": 40,
                             "fecha": "2026-08-18", "tipo": "efectivo"},
                       headers={"X-Operation-Id": op})

        assert r.status_code == 409
        assert r.json().get("codigo") == "OPERACION_EN_CURSO"
        assert r.headers.get("retry-after")
        assert r.headers.get("x-operacion-repetida") == "0"
        assert _saldo(admin, cliente_con_saldo) == antes, "Se ejecutó igual"

    def test_el_mismo_id_con_otros_datos_es_conflicto_aunque_esté_en_curso(
            self, admin, cliente_con_saldo):
        """La verificación de huella no se relaja contra una reserva en vuelo.

        Que la otra operación no haya terminado no la convierte en la misma
        operación: sigue siendo un identificador reusado con otros datos.
        """
        op = _op_id("en_curso_conflicto")
        _reservar_a_mano(op, huella="0" * 64)

        r = admin.post("/api/cobros/",
                       json={"cliente": cliente_con_saldo, "monto": 40,
                             "fecha": "2026-08-18", "tipo": "efectivo"},
                       headers={"X-Operation-Id": op})
        assert r.status_code == 409
        assert r.json().get("codigo") == "OPERACION_CONFLICTIVA"

    def test_una_reserva_abandonada_se_retoma(self, admin, cliente_con_saldo):
        """El proceso que la tomó murió: nadie va a cerrar esa reserva.

        Sin salida, ese identificador quedaría bloqueado para siempre. Pasado
        el umbral, el pedido siguiente la retoma y ejecuta de verdad.
        """
        import idempotencia

        op = _op_id("abandonada")
        _reservar_a_mano(
            op, antiguedad_segundos=idempotencia.UMBRAL_ABANDONO.total_seconds() + 60
        )

        antes = _saldo(admin, cliente_con_saldo)
        r = admin.post("/api/cobros/",
                       json={"cliente": cliente_con_saldo, "monto": 60,
                             "fecha": "2026-08-18", "tipo": "efectivo"},
                       headers={"X-Operation-Id": op})

        assert r.status_code == 200, r.text
        assert _saldo(admin, cliente_con_saldo) == antes - 60
        assert _fila(op).estado == idempotencia.COMPLETADA

    def test_una_reserva_reciente_no_se_retoma(self, admin, cliente_con_saldo):
        """El umbral se mide de verdad: una reserva de hace un instante manda."""
        import idempotencia

        op = _op_id("reciente")
        _reservar_a_mano(
            op, antiguedad_segundos=idempotencia.UMBRAL_ABANDONO.total_seconds() - 30
        )
        r = admin.post("/api/cobros/",
                       json={"cliente": cliente_con_saldo, "monto": 40,
                             "fecha": "2026-08-18", "tipo": "efectivo"},
                       headers={"X-Operation-Id": op})
        assert r.status_code == 409
        assert r.json().get("codigo") == "OPERACION_EN_CURSO"


class TestCierreDeLaReserva:
    def test_un_fallo_borra_la_reserva(self, admin):
        """Si quedara tomada, el reintento legítimo chocaría contra ella."""
        op = _op_id("libera")
        malo = {"cliente": "20123456786", "monto": 10,
                "fecha": "2026-08-18", "tipo": "efectivo"}
        assert admin.post("/api/cobros/", json=malo,
                          headers={"X-Operation-Id": op}).status_code == 404
        assert _fila(op) is None, "La reserva quedó colgada después de un error"

    def test_un_exito_deja_la_reserva_completada_con_su_respuesta(
            self, admin, cliente_con_saldo):
        import idempotencia

        op = _op_id("completa")
        r = admin.post("/api/cobros/",
                       json={"cliente": cliente_con_saldo, "monto": 15,
                             "fecha": "2026-08-18", "tipo": "efectivo"},
                       headers={"X-Operation-Id": op})
        assert r.status_code == 200
        fila = _fila(op)
        assert fila.estado == idempotencia.COMPLETADA
        assert fila.estado_http == 200
        assert fila.respuesta == r.text

class TestElReintentoNoPeleaPorElLock:
    """Un reintento que llega mientras la primera petición ejecuta.

    Esto viene de un CI en rojo, intermitente y solo en el runner: la reserva
    moría con `database is locked` y algún hilo quedaba colgado. La causa no era
    el test sino el diseño: para contestar "ya se está ejecutando" había que
    pedir el mismo lock de escritura que la petición en curso estaba reteniendo,
    así que la respuesta que debería ser instantánea era la más lenta de todas.

    En una máquina rápida no se nota nunca. Con varias terminales y un disco
    lento, el reintento termina en un error en vez de en un 409.
    """

    def test_contesta_en_curso_con_el_lock_de_escritura_tomado(self, admin):
        import sqlite3
        import idempotencia
        from database import DB_PATH, SessionLocal
        from idempotencia import EN_CURSO, OperacionProcesada, reservar
        from tiempo import ahora_utc

        op = _op_id("bajo_lock")
        sesion = SessionLocal()
        sesion.add(OperacionProcesada(
            operacion_id=op, metodo="POST", ruta="/api/cobros/", huella="h",
            estado=EN_CURSO, estado_http=0, respuesta="", usuario="x",
            creada=ahora_utc()))
        sesion.commit()
        sesion.close()

        # Otra conexión retiene el lock, como haría la petición que está
        # ejecutando la operación original.
        bloqueante = sqlite3.connect(DB_PATH, timeout=30)
        bloqueante.execute("PRAGMA journal_mode=WAL")
        bloqueante.execute("BEGIN IMMEDIATE")
        bloqueante.execute(
            "INSERT INTO operaciones_procesadas (operacion_id, estado) "
            "VALUES ('otra-cualquiera', 'en_curso')")
        try:
            veredicto, _ = reservar(op, "POST", "/api/cobros/", "h", "x")
        finally:
            bloqueante.rollback()
            bloqueante.close()

        # Sin el camino de solo lectura, esto levanta OperationalError
        # ("database is locked") al agotar el busy_timeout.
        assert veredicto == idempotencia.RESERVA_EN_CURSO
