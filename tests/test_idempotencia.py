"""
test_idempotencia.py - Que un reintento no ejecute la operacion dos veces.

Un agente reintenta cuando no recibe respuesta. Si lo que se perdio fue la
respuesta y no la ejecucion, el reintento duplica el cobro o la factura. Con
facturacion electronica es peor: un timeout no significa que AFIP no haya
procesado el pedido.
"""
import itertools

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
