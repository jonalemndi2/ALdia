"""
test_negocio.py - El circuito comercial completo.

Verifica que las operaciones tengan TODOS sus efectos y que anularlas los
revierta. Es lo que antes hacia el navegador contra una base que no existia, y
por eso se perdia en silencio.
"""
import itertools

import pytest


@pytest.fixture
def cliente_nuevo(admin, cuit):
    c = cuit("30")
    r = admin.post("/api/clientes/", json={"cuit": c, "nombre": f"Cliente {c[-4:]}"})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def proveedor_nuevo(admin, cuit):
    c = cuit("33")
    r = admin.post("/api/proveedores/", json={"cuit": c, "nombre": f"Proveedor {c[-4:]}"})
    assert r.status_code == 200, r.text
    return c


# El codigo de articulo es clave primaria: tiene que ser distinto en CADA
# llamada de CADA prueba, no solo dentro de una. Un contador por fixture se
# reinicia en cada prueba y genera colisiones.
_codigos = itertools.count(800001)


@pytest.fixture
def articulo(admin):
    def _crear(cantidad=100, precio=200.0):
        codigo = next(_codigos)
        r = admin.post("/api/stock/", json={
            "codigo": codigo, "producto": f"Articulo {codigo}",
            "cantidad": cantidad, "unidad": "UN", "preven": precio,
            "iva": 21, "precom": precio / 2,
        })
        assert r.status_code == 200, r.text
        return codigo

    return _crear


def saldo(admin, cuit_cliente):
    return admin.get(f"/api/clientes/{cuit_cliente}").json()["saldo"]


def stock(admin, codigo):
    return admin.get(f"/api/stock/{codigo}").json()["cantidad"]


class TestRemito:
    def test_descuenta_stock(self, admin, cliente_nuevo, articulo):
        codigo = articulo(cantidad=100)
        r = admin.post("/api/remitos/", json={
            "cliente": cliente_nuevo, "fecha": "2026-08-18",
            "total": 700, "iva": 147,
            "items": [{"codigo": codigo, "producto": "X", "cantidad": 7,
                       "precio": 100, "unidad": "UN"}],
        })
        assert r.status_code == 200, r.text
        assert stock(admin, codigo) == 93

    def test_es_atomico(self, admin, cliente_nuevo, articulo):
        """Si un renglon no se puede cumplir, NO debe quedar nada a medias."""
        codigo = articulo(cantidad=5)
        antes = stock(admin, codigo)
        r = admin.post("/api/remitos/", json={
            "cliente": cliente_nuevo, "fecha": "2026-08-18", "total": 100,
            "items": [{"codigo": codigo, "producto": "X", "cantidad": 999,
                       "precio": 100, "unidad": "UN"}],
        })
        if r.status_code != 200:
            assert stock(admin, codigo) == antes


class TestFactura:
    def test_suma_deuda_al_cliente(self, admin, cliente_nuevo):
        inicial = saldo(admin, cliente_nuevo)
        r = admin.post("/api/facturas/", json={
            "cuit": cliente_nuevo, "fecha": "2026-08-18",
            "subtotal": 1000, "ivaTotal": 210, "total": 1210, "items": [],
        })
        assert r.status_code == 200, r.text
        assert saldo(admin, cliente_nuevo) == inicial + 1210

    def test_sin_entrega_descuenta_stock(self, admin, cliente_nuevo, articulo):
        codigo = articulo(cantidad=50)
        r = admin.post("/api/facturas/", json={
            "cuit": cliente_nuevo, "fecha": "2026-08-18",
            "subtotal": 2400, "ivaTotal": 504, "total": 2904,
            "items": [{"codigo": codigo, "producto": "X", "cantidad": 12,
                       "precio": 200, "unidad": "UN"}],
        })
        assert r.status_code == 200, r.text
        assert stock(admin, codigo) == 38

    def test_rechaza_stock_insuficiente(self, admin, cliente_nuevo, articulo):
        codigo = articulo(cantidad=3)
        r = admin.post("/api/facturas/", json={
            "cuit": cliente_nuevo, "fecha": "2026-08-18", "total": 1,
            "items": [{"codigo": codigo, "cantidad": 9999, "precio": 200}],
        })
        assert r.status_code == 400
        assert "insuficiente" in r.text.lower()
        assert stock(admin, codigo) == 3

    def test_anular_revierte_todo(self, admin, cliente_nuevo, articulo):
        codigo = articulo(cantidad=50)
        saldo_previo = saldo(admin, cliente_nuevo)
        r = admin.post("/api/facturas/", json={
            "cuit": cliente_nuevo, "fecha": "2026-08-18",
            "subtotal": 2400, "ivaTotal": 504, "total": 2904,
            "items": [{"codigo": codigo, "producto": "X", "cantidad": 12,
                       "precio": 200, "unidad": "UN"}],
        })
        numero = r.json()["facturanumero"]

        assert admin.delete(f"/api/facturas/{numero}").status_code == 200
        assert saldo(admin, cliente_nuevo) == saldo_previo
        assert stock(admin, codigo) == 50


class TestNumeracion:
    def test_no_reusa_el_numero_de_una_anulada(self, admin, cliente_nuevo):
        """max+1 reusaba el numero: dos comprobantes fiscales iguales."""
        def emitir():
            return admin.post("/api/facturas/", json={
                "cuit": cliente_nuevo, "fecha": "2026-08-18",
                "subtotal": 100, "ivaTotal": 21, "total": 121, "items": [],
            }).json()["facturanumero"]

        primera = emitir()
        admin.delete(f"/api/facturas/{primera}")
        segunda = emitir()
        assert segunda != primera, "Se reuso el numero de una factura anulada"
        assert segunda > primera

    def test_es_correlativa(self, admin, cliente_nuevo):
        numeros = []
        for _ in range(4):
            numeros.append(admin.post("/api/facturas/", json={
                "cuit": cliente_nuevo, "fecha": "2026-08-18",
                "subtotal": 100, "ivaTotal": 21, "total": 121, "items": [],
            }).json()["facturanumero"])
        assert numeros == sorted(numeros)
        assert len(set(numeros)) == 4


class TestCobros:
    def test_efectivo_baja_saldo_y_entra_a_caja(self, admin, cliente_nuevo):
        admin.post("/api/facturas/", json={
            "cuit": cliente_nuevo, "fecha": "2026-08-18",
            "subtotal": 1000, "ivaTotal": 210, "total": 1210, "items": [],
        })
        previo = saldo(admin, cliente_nuevo)

        r = admin.post("/api/cobros/", json={
            "cliente": cliente_nuevo, "monto": 500, "fecha": "2026-08-18",
            "tipo": "efectivo",
        })
        assert r.status_code == 200, r.text
        orden = r.json()["ordcobro"]

        assert saldo(admin, cliente_nuevo) == previo - 500
        movimientos = admin.get("/api/caja/").json()
        assert any(m["referencia"] == f"COBRO {orden}" for m in movimientos)

    def test_con_cheque_no_entra_a_caja(self, admin, cliente_nuevo):
        """Un cheque no es efectivo: va a la chequera."""
        cajas_antes = len(admin.get("/api/caja/").json())
        r = admin.post("/api/cobros/", json={
            "cliente": cliente_nuevo, "monto": 900, "fecha": "2026-08-18",
            "tipo": "cheque", "referencia": "CH-7788", "banco": "Banco Test",
            "vencimiento": "2026-12-31",
        })
        assert r.status_code == 200, r.text
        assert len(admin.get("/api/caja/").json()) == cajas_antes

        chequera = admin.get("/api/caja/chequera").json()
        assert any(c["numcheque"] == "CH-7788" for c in chequera)

    def test_anular_revierte_saldo_y_caja(self, admin, cliente_nuevo):
        previo = saldo(admin, cliente_nuevo)
        orden = admin.post("/api/cobros/", json={
            "cliente": cliente_nuevo, "monto": 250, "fecha": "2026-08-18",
            "tipo": "efectivo",
        }).json()["ordcobro"]

        assert admin.delete(f"/api/cobros/{orden}").status_code == 200
        assert saldo(admin, cliente_nuevo) == previo
        movimientos = admin.get("/api/caja/").json()
        assert not any(m["referencia"] == f"COBRO {orden}" for m in movimientos)

    def test_cliente_inexistente_se_rechaza(self, admin):
        r = admin.post("/api/cobros/", json={
            "cliente": "20123456786", "monto": 100, "fecha": "2026-08-18",
            "tipo": "efectivo",
        })
        assert r.status_code == 404


class TestPagos:
    def test_baja_saldo_del_proveedor(self, admin, proveedor_nuevo):
        r = admin.post("/api/pagos/", json={
            "proveedor": proveedor_nuevo, "monto": 1500, "fecha": "2026-08-18",
            "tipo": "efectivo",
        })
        assert r.status_code == 200, r.text
        p = admin.get(f"/api/proveedores/{proveedor_nuevo}").json()
        assert p["saldo"] == -1500

    def test_proveedor_inexistente_se_rechaza(self, admin):
        r = admin.post("/api/pagos/", json={
            "proveedor": "20123456786", "monto": 100, "fecha": "2026-08-18",
            "tipo": "efectivo",
        })
        assert r.status_code == 404


class TestExactitudDelCircuito:
    def test_diez_cobros_de_diez_centavos(self, admin, cliente_nuevo):
        """Con float el saldo quedaba en -0.9999999999999999."""
        previo = saldo(admin, cliente_nuevo)
        for _ in range(10):
            admin.post("/api/cobros/", json={
                "cliente": cliente_nuevo, "monto": 0.10, "fecha": "2026-08-18",
                "tipo": "efectivo",
            })
        assert saldo(admin, cliente_nuevo) == previo - 1.00

    def test_facturar_y_cobrar_cierra_en_cero(self, admin, cliente_nuevo):
        previo = saldo(admin, cliente_nuevo)
        admin.post("/api/facturas/", json={
            "cuit": cliente_nuevo, "fecha": "2026-08-18",
            "subtotal": 233.31, "ivaTotal": 49.00, "total": 282.31, "items": [],
        })
        admin.post("/api/cobros/", json={
            "cliente": cliente_nuevo, "monto": 282.31, "fecha": "2026-08-18",
            "tipo": "efectivo",
        })
        assert saldo(admin, cliente_nuevo) == previo


class TestConsistencia:
    def test_los_saldos_cierran_contra_los_movimientos(self, admin):
        """Despues de todo el circuito, el saldo guardado debe coincidir."""
        r = admin.get("/api/admin/verificar-saldos")
        assert r.status_code == 200
        informe = r.json()
        assert informe["consistente"], (
            f"{informe['cantidad_diferencias']} saldo(s) desviado(s): "
            f"{informe['diferencias']}"
        )

    def test_no_hay_filas_huerfanas(self, admin):
        r = admin.get("/api/admin/verificar-integridad")
        assert r.status_code == 200
        d = r.json()
        assert d["verificacion_fk_activa"], "La verificacion de claves foraneas esta apagada"
        assert d["filas_huerfanas"] == 0, d["huerfanos"]
