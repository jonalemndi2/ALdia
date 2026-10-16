"""El servidor MCP no hace cuentas con plata: suma centavos exactos y el resto lo calcula el backend."""
import ast
import asyncio
import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ / "mcp") not in sys.path:
    sys.path.insert(0, str(RAIZ / "mcp"))

SERVER = RAIZ / "mcp" / "aldia_mcp" / "server.py"

# Campos que son importes. `iva` no esta: segun el contexto es una alicuota
# (stock, conceptos) o un importe (factura), y las alicuotas si van en float.
CAMPOS_DE_DINERO = re.compile(
    r"saldo|monto|total|neto|importe|precio|preven|precom|debe|haber|base_imponible|base_calculo"
)


@pytest.fixture
def srv():
    pytest.importorskip("mcp.server")
    import aldia_mcp.server as modulo
    modulo._reglas = {}
    yield modulo
    modulo._reglas = None


def fn(tool):
    return getattr(tool, "fn", tool)


class TestNoHayFloatParaPlata:
    """Si alguien vuelve a escribir float(...) sobre un importe, esto falla."""

    def _llamadas(self, nombres):
        fuente = SERVER.read_text(encoding="utf-8")
        for nodo in ast.walk(ast.parse(fuente)):
            if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                    and nodo.func.id in nombres):
                yield nodo.lineno, ast.get_source_segment(fuente, nodo)

    def test_ningun_float_sobre_un_importe(self):
        malos = [f"linea {n}: {texto}" for n, texto in self._llamadas({"float"})
                 if CAMPOS_DE_DINERO.search(texto)]
        assert not malos, "Importes convertidos a float:\n" + "\n".join(malos)

    def test_ningun_round(self):
        """Redondear plata es cosa del backend (redondeo comercial, no bancario)."""
        assert not list(self._llamadas({"round"}))


class TestParidadConElBackend:
    VALORES = [0, 0.01, 0.1, 0.105, 0.115, 1.005, 2.675, 1234.56, -1234.565,
               999999999.99, "10.10", "0.005", 1e-05, 123456789012.34]

    @pytest.mark.parametrize("valor", VALORES)
    def test_centavos_igual_que_el_backend(self, valor):
        from aldia_mcp.dinero import centavos, pesos
        from dinero import a_centavos, a_pesos

        assert centavos(valor) == a_centavos(valor)
        assert pesos(centavos(valor)) == a_pesos(a_centavos(valor))

    def test_la_suma_es_exacta(self):
        from aldia_mcp.dinero import pesos, sumar

        assert 0.1 + 0.2 != 0.3                        # lo que pasa con float
        assert pesos(sumar([0.1] * 10)) == 1.0
        assert sumar([0.07] * 1000) == 7000

    def test_un_importe_invalido_se_rechaza(self):
        from aldia_mcp.client import ALdiaError
        from aldia_mcp.dinero import centavos

        for malo in ("abc", float("nan"), float("inf"), True):
            with pytest.raises(ALdiaError):
                centavos(malo)
        assert centavos(None) == 0 and centavos("") == 0


class ApiFalsa:
    def __init__(self, respuestas=None):
        self.respuestas = respuestas or {}
        self.llamadas = []

    def _responder(self, metodo, ruta, cuerpo):
        self.llamadas.append((metodo, ruta, cuerpo))
        valor = self.respuestas.get((metodo, ruta), {})
        return valor(cuerpo) if callable(valor) else valor

    def get(self, ruta, **params):
        return self._responder("GET", ruta, params)

    def post(self, ruta, cuerpo=None, operation_id=None, **params):
        return self._responder("POST", ruta, cuerpo)

    def put(self, ruta, cuerpo=None):
        return self._responder("PUT", ruta, cuerpo)

    def resolver_cliente(self, texto):
        return {"cuit": "20111111112", "nombre": "Cliente", "saldo": 100.0}

    def resolver_proveedor(self, texto):
        return {"cuit": "30222222223", "nombre": "Proveedor", "saldo": 50.0}

    def producto(self, codigo):
        return {"codigo": codigo, "producto": "Articulo", "cantidad": 100, "preven": 3.33,
                "precom": 1, "iva": 21.0, "unidad": "KG"}

    def enviado(self, metodo, ruta):
        return next(c for m, r, c in self.llamadas if (m, r) == (metodo, ruta))


class TestLasToolsNoCalculan:
    def test_la_factura_no_manda_totales_y_muestra_los_del_backend(self, srv, monkeypatch):
        api = ApiFalsa({("POST", "/api/facturas/borradores"): {
            "borrador_id": "b1",
            "importes": {"neto": 8.33, "iva": 1.75, "total": 10.08, "renglones": [8.33],
                         "por_alicuota": [{"alicuota": 21.0, "base": 8.33, "iva": 1.75}]},
        }})
        monkeypatch.setattr(srv, "api", lambda: api)
        r = fn(srv.create_invoice)("Cliente", items=[{"codigo": 1, "cantidad": 2.5}])
        enviado = api.enviado("POST", "/api/facturas/borradores")
        assert not {"subtotal", "iva", "total"} & set(enviado)
        assert (r["subtotal"], r["iva"], r["total"]) == (8.33, 1.75, 10.08)
        assert r["detalle"][0]["neto"] == 8.33

    def test_el_gasto_no_manda_totales(self, srv, monkeypatch):
        api = ApiFalsa({("POST", "/api/gastos/"): {"id": 7, "subtotal": 0.1, "iva": 0.02, "total": 0.12}})
        monkeypatch.setattr(srv, "api", lambda: api)
        r = fn(srv.record_expense)("Proveedor", [{"descripcion": "a", "monto": 0.05},
                                                 {"descripcion": "b", "monto": 0.05}],
                                   confirmar=True)
        assert not {"subtotal", "iva", "total"} & set(api.enviado("POST", "/api/gastos/"))
        assert r["total"] == 0.12

    def test_la_nota_de_credito_pide_la_cotizacion_al_backend(self, srv, monkeypatch):
        api = ApiFalsa({
            ("POST", "/api/facturas/cotizar"): {
                "neto": 8.33, "iva": 1.75, "total": 10.08, "renglones": [8.33],
                "por_alicuota": [{"alicuota": 21.0, "base": 8.33, "iva": 1.75}]},
            ("POST", "/api/facturas/"): {"facturanumero": 9, "subtotal": -8.33, "iva": -1.75,
                                         "total": -10.08},
        })
        monkeypatch.setattr(srv, "api", lambda: api)
        monkeypatch.setattr(srv, "_condicion_del_negocio", lambda: "responsable_inscripto")
        r = fn(srv.create_credit_note)("Cliente", items=[{"codigo": 1, "cantidad": 2.5}],
                                       confirmar=True)
        nota = api.enviado("POST", "/api/facturas/")
        assert nota["subtotal"] == -8.33 and nota["alicuota_iva"] == 21.0
        assert "iva" not in nota and "total" not in nota
        assert r["total_acreditado"] == 10.08

    def test_dos_alicuotas_en_una_nota_de_credito_se_rechazan(self, srv, monkeypatch):
        api = ApiFalsa({("POST", "/api/facturas/cotizar"): {
            "neto": 2, "renglones": [1, 1],
            "por_alicuota": [{"alicuota": 10.5}, {"alicuota": 21.0}]}})
        monkeypatch.setattr(srv, "api", lambda: api)
        with pytest.raises(srv.ALdiaError, match="alicuotas distintas"):
            fn(srv.create_credit_note)("Cliente", items=[{"codigo": 1, "cantidad": 1},
                                                         {"codigo": 2, "cantidad": 1}],
                                       confirmar=True)
        assert not [c for m, r, c in api.llamadas if r == "/api/facturas/"]

    def test_la_nota_de_debito_manda_la_alicuota(self, srv, monkeypatch):
        api = ApiFalsa({("POST", "/api/facturas/"): {"facturanumero": 3, "subtotal": 1000.05,
                                                      "iva": 210.01, "total": 1210.06}})
        monkeypatch.setattr(srv, "api", lambda: api)
        monkeypatch.setattr(srv, "_condicion_del_negocio", lambda: "responsable_inscripto")
        r = fn(srv.create_debit_note)("Cliente", "Intereses", 1000.05, confirmar=True)
        nota = api.enviado("POST", "/api/facturas/")
        assert (nota["subtotal"], nota["alicuota_iva"]) == (1000.05, 21.0)
        assert r["total_debitado"] == 1210.06

    def test_el_aumento_porcentual_lo_calcula_el_backend(self, srv, monkeypatch):
        api = ApiFalsa({("PUT", "/api/stock/5"): {"codigo": 5, "preven": 9.05}})
        monkeypatch.setattr(srv, "api", lambda: api)
        fn(srv.update_product)(5, aumento_pct=-10)
        assert api.enviado("PUT", "/api/stock/5") == {"aumento_pct": -10.0}


class TestSumasExactas:
    def test_movimientos_del_dia(self, srv, monkeypatch):
        api = ApiFalsa({
            ("GET", "/api/caja/"): [{"debe": 0.1, "haber": 0}] * 10,
            ("GET", "/api/cobros/"): [{"monto": 0.07, "tipo": "efectivo"}] * 3,
            ("GET", "/api/caja/saldo"): {"saldo": 1},
        })
        monkeypatch.setattr(srv, "api", lambda: api)
        r = fn(srv.get_daily_cash_movements)("2026-10-16")
        assert r["totales"]["ingresos_caja"] == 1.0
        assert r["totales"]["cobros_total"] == 0.21

    def test_remitos_sin_facturar_suman_el_importe_del_backend(self, srv, monkeypatch):
        api = ApiFalsa({("GET", "/api/remitos/nofacturados"): [
            {"id": 1, "cantidad": 2.5, "precio": 3.33, "importe": 8.33},
            {"id": 2, "cantidad": 1, "precio": 0.1, "importe": 0.1},
        ]})
        monkeypatch.setattr(srv, "api", lambda: api)
        assert fn(srv.list_uninvoiced_delivery_notes)()["total_neto_sin_facturar"] == 8.43


def test_factura_del_mcp_cierra_con_afip(srv, admin, cuit, monkeypatch):
    """Factura armada por el MCP de verdad contra el backend de verdad."""
    from fastapi.testclient import TestClient

    import main
    from aldia_mcp.client import ALdiaClient
    from conftest import PASSWORD_ADMIN
    from database import SessionLocal
    from models import Factura
    from routers.afip import _composicion_iva

    cliente = cuit("30")
    assert admin.post("/api/clientes/", json={"cuit": cliente, "nombre": "Cliente MCP"}).status_code == 200
    codigos = []
    for i, (precio, iva) in enumerate([(9.99, 21), (3.33, 10.5), (0.07, 27)]):
        codigo = 989001 + i
        r = admin.post("/api/stock/", json={"codigo": codigo, "producto": f"Art {i}",
                                            "cantidad": 100, "unidad": "KG", "preven": precio,
                                            "iva": iva, "precom": 1})
        assert r.status_code == 200, r.text
        codigos.append(codigo)

    cli = ALdiaClient(base_url="http://testserver", usuario="admin", password=PASSWORD_ADMIN)
    cli._http = TestClient(main.app)
    monkeypatch.setattr(srv, "api", lambda: cli)

    borrador = fn(srv.create_invoice)(cliente, items=[
        {"codigo": codigos[0], "cantidad": 1.333},
        {"codigo": codigos[1], "cantidad": 2.5},
        {"codigo": codigos[2], "cantidad": 3.333},
    ])
    factura = fn(srv.confirm_invoice_draft)(borrador["borrador_id"], confirmar=True)
    assert factura["total"] == borrador["total"]

    with SessionLocal() as db:
        guardada = db.query(Factura).filter(Factura.facturanumero == factura["facturanumero"]).one()
        afip = _composicion_iva(db, guardada, 1)
    assert (afip["neto"], afip["iva"], afip["total"]) == (
        borrador["subtotal"], borrador["iva"], borrador["total"])
    assert Decimal(str(borrador["total"])) == Decimal(str(borrador["subtotal"])) + Decimal(str(borrador["iva"]))
