"""Contratos de las tools MCP contra las rutas REST vigentes."""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "mcp"))


@pytest.fixture
def srv(monkeypatch):
    pytest.importorskip("mcp.server")
    import aldia_mcp.server as modulo
    modulo._reglas = {}
    yield modulo
    modulo._reglas = None


def fn(tool):
    return getattr(tool, "fn", tool)


class ApiFalsa:
    def __init__(self):
        self.llamadas = []

    def resolver_cliente(self, texto):
        return {"cuit": "201", "nombre": "Cliente", "saldo": 100}

    def resolver_proveedor(self, texto):
        return {"cuit": "302", "nombre": "Proveedor", "saldo": 200}

    def producto(self, codigo):
        return {"codigo": codigo, "producto": "Artículo", "cantidad": 10, "precom": 3}

    def get(self, ruta, **params):
        self.llamadas.append(("GET", ruta, params, None, None))
        if ruta == "/api/tesoreria/cuentas":
            return [{"id": 5, "nombre": "Caja", "clase": "caja_chica", "activa": True}]
        if ruta.startswith("/api/compras/") and ruta != "/api/compras/":
            return {
                "id": 8, "proveedor": "302", "total": 12, "estado": "borrador",
                "renglones": [{
                    "compra_id": 91, "codigo": 1, "cantidad": 2,
                    "cantidad_disponible_devolver": 2, "precio": 3,
                }],
            }
        if ruta.endswith("cuenta-corriente"):
            return {"moneda": "ARS", "movimientos": [{"tipo": "Compra"}]}
        return []

    def post(self, ruta, cuerpo=None, operation_id=None, **params):
        self.llamadas.append(("POST", ruta, params, cuerpo, operation_id))
        if ruta == "/api/cobros/":
            return {"ordcobro": 1, "monto": 5, "tipo": "efectivo", "fecha": "2026-09-02"}
        if ruta == "/api/pagos/":
            return {"ordpago": 2, "monto": 6, "tipo": "transferencia", "fecha": "2026-09-02"}
        if ruta == "/api/compras/":
            return {"id": 8, "estado": cuerpo["estado"], "fecha": cuerpo["fecha"]}
        return {"ok": True, "estado": "confirmada"}


def test_cobro_y_pago_envian_cuenta_y_operation_id(srv, monkeypatch):
    falsa = ApiFalsa(); monkeypatch.setattr(srv, "api", lambda: falsa)
    fn(srv.record_payment)("Cliente", 5, cuenta_tesoreria_id=3, confirmar=True,
                           operation_id="cobro-1")
    fn(srv.record_vendor_payment)("Proveedor", 6, tipo="transferencia", referencia="op",
                                  cuenta_tesoreria_id=4, confirmar=True,
                                  operation_id="pago-1")
    cobro, pago = [x for x in falsa.llamadas if x[0] == "POST"]
    assert (cobro[1], cobro[3]["cuenta_tesoreria_id"], cobro[4]) == ("/api/cobros/", 3, "cobro-1")
    assert (pago[1], pago[3]["cuenta_tesoreria_id"], pago[4]) == ("/api/pagos/", 4, "pago-1")


def test_operacion_financiera_sin_confirmacion_no_escribe(srv, monkeypatch):
    falsa = ApiFalsa(); monkeypatch.setattr(srv, "api", lambda: falsa)
    with pytest.raises(Exception, match="confirmar=true"):
        fn(srv.record_vendor_payment)("Proveedor", 10)
    assert not [x for x in falsa.llamadas if x[0] == "POST"]


def test_compra_borrador_no_afirma_movimientos(srv, monkeypatch):
    falsa = ApiFalsa(); monkeypatch.setattr(srv, "api", lambda: falsa)
    salida = fn(srv.record_purchase)("Proveedor", [{"codigo": 1, "cantidad": 2, "precio": 3}])
    llamada = next(x for x in falsa.llamadas if x[0] == "POST")
    assert llamada[1] == "/api/compras/"
    assert llamada[3]["estado"] == "borrador"
    assert "todavía no modifica" in salida["nota"]


def test_devolucion_envia_factura_y_renglon(srv, monkeypatch):
    falsa = ApiFalsa(); monkeypatch.setattr(srv, "api", lambda: falsa)
    fn(srv.record_vendor_return)(
        "Proveedor", [{"compra_id": 91, "codigo": 1, "cantidad": 1, "precio": 3}],
        factura_id=8, motivo="fallado", confirmar=True, operation_id="dev-1",
    )
    llamada = next(x for x in falsa.llamadas if x[0] == "POST")
    assert llamada[1] == "/api/devoluciones/"
    assert llamada[3]["factura_id"] == 8
    assert llamada[3]["items"][0]["compra_id"] == 91
    assert llamada[3]["items"][0]["precio"] == 3
    assert llamada[3]["motivo"] == "fallado"


def test_compras_y_cuenta_corriente_no_usen_admin(srv, monkeypatch):
    falsa = ApiFalsa(); monkeypatch.setattr(srv, "api", lambda: falsa)
    fn(srv.list_purchases)(); fn(srv.get_vendor_balance)("Proveedor")
    rutas = [x[1] for x in falsa.llamadas]
    assert "/api/compras/" in rutas
    assert "/api/proveedores/302/cuenta-corriente" in rutas
    assert not any("/api/admin/" in ruta for ruta in rutas)


def test_tesoreria_usa_endpoints_vigentes_y_confirma_cheques(srv, monkeypatch):
    falsa = ApiFalsa(); monkeypatch.setattr(srv, "api", lambda: falsa)
    fn(srv.list_treasury_accounts)(); fn(srv.get_treasury_balances)()
    fn(srv.list_treasury_movements)(7); fn(srv.list_received_checks)()
    fn(srv.deposit_received_check)(4, 7, confirmar=True, operation_id="dep-1")
    rutas = [x[1] for x in falsa.llamadas]
    assert rutas == ["/api/tesoreria/cuentas", "/api/tesoreria/saldos",
                     "/api/tesoreria/movimientos", "/api/tesoreria/cheques",
                     "/api/tesoreria/cheques/4/depositar"]
    assert falsa.llamadas[-1][4] == "dep-1"


def test_confirmar_anular_y_nc_financiera_rutas_vigentes(srv, monkeypatch):
    falsa = ApiFalsa(); monkeypatch.setattr(srv, "api", lambda: falsa)
    fn(srv.confirm_purchase)(8, confirmar=True)
    fn(srv.void_purchase)(8, confirmar=True)
    fn(srv.record_vendor_credit_note)("Proveedor", 9, confirmar=True)
    rutas_post = [x[1] for x in falsa.llamadas if x[0] == "POST"]
    assert rutas_post == ["/api/compras/8/confirmar", "/api/compras/8/anular",
                          "/api/compras/notas-credito-financieras"]


def test_gasto_describe_devengamiento_sin_egreso(srv, monkeypatch):
    falsa = ApiFalsa(); monkeypatch.setattr(srv, "api", lambda: falsa)
    salida = fn(srv.record_expense)("Proveedor", [{"descripcion": "Luz", "monto": 10}],
                                    confirmar=True)
    assert "No salio dinero" in salida["nota"]


def test_movimiento_manual_envia_caja_concreta(srv, monkeypatch):
    falsa = ApiFalsa(); monkeypatch.setattr(srv, "api", lambda: falsa)
    salida = fn(srv.record_cash_movement)("Fondo fijo", ingreso=10, confirmar=True)
    llamada = next(x for x in falsa.llamadas if x[0] == "POST")
    assert llamada[1] == "/api/caja/"
    assert llamada[3]["cuenta_tesoreria_id"] == 5
    assert salida["cuenta_tesoreria_id"] == 5
