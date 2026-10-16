"""
Neto, IVA y total de los comprobantes los calcula el backend, en un solo lugar.

Antes la factura guardaba los totales que mandaba el cliente (el navegador o el
servidor MCP, sumando con float) y el pedido de CAE los recalculaba con otro
criterio: la cuenta corriente y lo declarado ante AFIP podian no cerrar.
"""
import itertools

import pytest

from database import SessionLocal
from dinero import ajustar_por_porcentaje, importes_de_renglones
from models import Factura, StockMercaderia

_codigos = itertools.count(987001)


@pytest.fixture
def cliente(admin, cuit):
    c = cuit("30")
    assert admin.post("/api/clientes/", json={"cuit": c, "nombre": f"Cliente {c[-4:]}"}).status_code == 200
    return c


@pytest.fixture
def articulo(admin):
    def crear(precio=200.0, iva=21, cantidad=1000):
        codigo = next(_codigos)
        r = admin.post("/api/stock/", json={
            "codigo": codigo, "producto": f"Articulo {codigo}", "cantidad": cantidad,
            "unidad": "KG", "preven": precio, "iva": iva, "precom": 1,
        })
        assert r.status_code == 200, r.text
        return codigo
    return crear


def _saldo(admin, cuit):
    return admin.get(f"/api/clientes/{cuit}").json()["saldo"]


def _composicion_afip(numero: int) -> dict:
    from routers.afip import _composicion_iva

    with SessionLocal() as db:
        factura = db.query(Factura).filter(Factura.facturanumero == numero).one()
        return _composicion_iva(db, factura, 1)   # Factura A: discrimina IVA


class TestFactura:
    def test_los_totales_salen_de_los_renglones_y_no_de_lo_declarado(self, admin, cliente, articulo):
        a21 = articulo(precio=9.99, iva=21)
        a105 = articulo(precio=3.33, iva=10.5)
        renglones = [{"codigo": a21, "cantidad": 1.333}, {"codigo": a105, "cantidad": 2.5},
                     {"codigo": a21, "cantidad": 7}]
        esperado = importes_de_renglones([(999, 1.333, 21), (333, 2.5, 10.5), (999, 7, 21)])
        previo = _saldo(admin, cliente)

        r = admin.post("/api/facturas/borradores", json={
            "cliente": cliente, "fecha": "2026-10-16",
            "subtotal": 1, "iva": 0, "total": 1,          # declarado y falso: no cuenta
            "items": renglones,
        })
        assert r.status_code == 200, r.text
        importes = r.json()["importes"]
        assert importes["total"] == esperado.total / 100
        assert [p["alicuota"] for p in importes["por_alicuota"]] == [10.5, 21.0]

        factura = admin.post(f"/api/facturas/borradores/{r.json()['borrador_id']}/confirmar",
                             json={"confirmar": True})
        assert factura.status_code == 200, factura.text
        assert factura.json()["total"] == esperado.total / 100
        assert round(_saldo(admin, cliente) - previo, 2) == esperado.total / 100

    def test_lo_que_se_declara_ante_afip_cierra_al_centavo(self, admin, cliente, articulo):
        renglones = [{"codigo": articulo(precio=p, iva=a), "cantidad": c}
                     for p, a, c in [(0.07, 21, 3.333), (1234.56, 10.5, 0.75),
                                     (19.99, 21, 11.11), (5, 27, 1.005)]]
        r = admin.post("/api/facturas/", json={
            "confirmar": True, "cliente": cliente, "fecha": "2026-10-16", "items": renglones,
        })
        assert r.status_code == 200, r.text
        afip = _composicion_afip(r.json()["facturanumero"])
        assert afip["total"] == r.json()["total"]
        assert afip["neto"] == r.json()["subtotal"]
        assert afip["iva"] == r.json()["iva"]

    def test_el_borrador_congela_el_precio_de_lista(self, admin, cliente, articulo):
        codigo = articulo(precio=100)
        r = admin.post("/api/facturas/borradores", json={
            "cliente": cliente, "fecha": "2026-10-16", "items": [{"codigo": codigo, "cantidad": 2}],
        })
        assert r.status_code == 200, r.text
        assert admin.put(f"/api/stock/{codigo}", json={"preven": 150}).status_code == 200

        f = admin.post(f"/api/facturas/borradores/{r.json()['borrador_id']}/confirmar",
                       json={"confirmar": True})
        assert f.status_code == 200, f.text
        assert f.json()["subtotal"] == 200      # el precio que vio el usuario

    def test_si_cambia_la_alicuota_no_se_confirma_otro_importe(self, admin, cliente, articulo):
        codigo = articulo(precio=100, iva=21)
        previo = _saldo(admin, cliente)
        r = admin.post("/api/facturas/borradores", json={
            "cliente": cliente, "fecha": "2026-10-16", "items": [{"codigo": codigo, "cantidad": 1}],
        })
        assert admin.put(f"/api/stock/{codigo}", json={"iva": 10.5}).status_code == 200

        f = admin.post(f"/api/facturas/borradores/{r.json()['borrador_id']}/confirmar",
                       json={"confirmar": True})
        assert f.status_code == 409, f.text
        assert f.json()["codigo"] == "IMPORTES_CAMBIARON"
        assert _saldo(admin, cliente) == previo
        # El borrador sigue pendiente: no quedo a medio confirmar.
        assert admin.get(f"/api/facturas/borradores/{r.json()['borrador_id']}").json()["estado"] == "pendiente"


class TestNotasPorImporte:
    def test_con_alicuota_el_iva_lo_calcula_el_servidor(self, admin, cliente):
        r = admin.post("/api/facturas/", json={
            "confirmar": True, "cliente": cliente, "fecha": "2026-10-16",
            "subtotal": -1000.05, "alicuota_iva": 21, "items": [],
        })
        assert r.status_code == 200, r.text
        assert (r.json()["subtotal"], r.json()["iva"], r.json()["total"]) == (-1000.05, -210.01, -1210.06)

    def test_sin_alicuota_se_respeta_lo_declarado_si_cierra(self, admin, cliente):
        ok = admin.post("/api/facturas/", json={
            "confirmar": True, "cliente": cliente, "fecha": "2026-10-16",
            "subtotal": 100, "ivaTotal": 21, "total": 121, "items": [],
        })
        assert ok.status_code == 200, ok.text
        mal = admin.post("/api/facturas/", json={
            "confirmar": True, "cliente": cliente, "fecha": "2026-10-16",
            "subtotal": 100, "ivaTotal": 21, "total": 125, "items": [],
        })
        assert mal.status_code == 422

    def test_la_alicuota_tiene_que_ser_valida(self, admin, cliente):
        r = admin.post("/api/facturas/", json={
            "confirmar": True, "cliente": cliente, "fecha": "2026-10-16",
            "subtotal": 100, "alicuota_iva": 19, "items": [],
        })
        assert r.status_code == 422


class TestCotizar:
    def test_cotiza_renglones_sin_guardar_nada(self, admin, articulo):
        codigo = articulo(precio=3.33, iva=21, cantidad=10)
        r = admin.post("/api/facturas/cotizar", json={"items": [{"codigo": codigo, "cantidad": 2.5}]})
        assert r.status_code == 200, r.text
        assert r.json()["renglones"] == [8.33]          # 3,33 x 2,5 = 8,325 -> 8,33
        assert r.json()["total"] == 10.08               # + IVA 1,75
        assert admin.get(f"/api/stock/{codigo}").json()["cantidad"] == 10

    def test_cotiza_un_importe_con_su_alicuota(self, admin):
        r = admin.post("/api/facturas/cotizar", json={"subtotal": 1000.05, "alicuota_iva": 21})
        assert r.status_code == 200, r.text
        assert (r.json()["iva"], r.json()["total"]) == (210.01, 1210.06)


class TestRemitoYGasto:
    def test_el_remito_calcula_neto_e_iva(self, admin, cliente, articulo):
        codigo = articulo(precio=3.33, iva=21)
        r = admin.post("/api/remitos/", json={
            "cliente": cliente, "fecha": "2026-10-16", "total": 999, "iva": 999,
            "items": [{"codigo": codigo, "producto": "X", "cantidad": 2.5, "precio": 3.33}],
        })
        assert r.status_code == 200, r.text
        assert (r.json()["total"], r.json()["iva"]) == (8.33, 1.75)

    def test_el_gasto_sin_totales_los_calcula_con_iva_por_alicuota(self, admin, cuit):
        prov = cuit("33")
        assert admin.post("/api/proveedores/", json={"cuit": prov, "nombre": "Prov gasto"}).status_code == 200
        r = admin.post("/api/gastos/", json={
            "proveedor": prov, "fecha": "2026-10-16",
            "items": [{"descripcion": "a", "monto": 0.05, "iva": 21},
                      {"descripcion": "b", "monto": 0.05, "iva": 21}],
        })
        assert r.status_code == 200, r.text
        # IVA una vez sobre 0,10 = 0,021 -> 0,02 (por renglon daria 0,01 + 0,01).
        assert (r.json()["subtotal"], r.json()["iva"], r.json()["total"]) == (0.1, 0.02, 0.12)

    def test_el_gasto_con_totales_declarados_los_respeta(self, admin, cuit):
        prov = cuit("33")
        assert admin.post("/api/proveedores/", json={"cuit": prov, "nombre": "Prov doc"}).status_code == 200
        r = admin.post("/api/gastos/", json={
            "proveedor": prov, "fecha": "2026-10-16",
            "subtotal": 100, "iva": 21.01, "total": 121.01,
            "items": [{"descripcion": "a", "monto": 100, "iva": 21}],
        })
        assert r.status_code == 200, r.text
        assert r.json()["iva"] == 21.01


class TestRemarcacion:
    def test_el_precio_nuevo_lo_calcula_el_servidor_con_redondeo_comercial(self, admin, articulo):
        codigo = articulo(precio=10.05)
        r = admin.put(f"/api/stock/{codigo}", json={"aumento_pct": -10})
        assert r.status_code == 200, r.text
        # 10,05 - 10 % = 9,045 -> 9,05. Con float daba 9,04.
        assert r.json()["preven"] == 9.05
        assert ajustar_por_porcentaje(1005, -10) == 905

    def test_precio_y_aumento_juntos_no(self, admin, articulo):
        codigo = articulo(precio=10)
        r = admin.put(f"/api/stock/{codigo}", json={"aumento_pct": 10, "preven": 12})
        assert r.status_code == 422

    def test_sin_precio_no_hay_aumento(self, admin, articulo):
        codigo = articulo(precio=0)
        r = admin.put(f"/api/stock/{codigo}", json={"aumento_pct": 10})
        assert r.status_code == 422
        with SessionLocal() as db:
            assert db.query(StockMercaderia).filter_by(codigo=codigo).one().preven == 0
