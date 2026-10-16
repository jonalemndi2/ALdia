"""Pruebas de las tools MCP de liquidaciones, perfiles de negocio y adopcion con agentes personales."""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ / "mcp") not in sys.path:
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


class ApiFalsaLiquidaciones:
    def __init__(self):
        self.llamadas = []

    def resolver_cliente(self, texto):
        return {"cuit": "30710011223", "nombre": "Acopio del Litoral S.A.", "saldo": 1450000.0}

    def resolver_proveedor(self, texto):
        return {"cuit": "20281112224", "nombre": "Estancia Don Segundo S.R.L.", "saldo": 820000.0}

    def producto(self, codigo):
        return {
            "codigo": codigo,
            "producto": "Soja Grano Campana 25/26",
            "cantidad": 45000.0,
            "unidad": "KG",
            "preven": 285.0,
            "precom": 260.0,
            "iva": 10.5,
        }

    def get(self, ruta, **params):
        self.llamadas.append(("GET", ruta, params, None, None))
        if ruta == "/api/modulos/perfiles":
            return [
                {"clave": "comercio", "nombre": "Comercio", "modulos_activos": ["stock", "ventas"]},
                {"clave": "agro_mixto", "nombre": "Agro Mixto", "modulos_activos": ["stock", "liquidaciones_granos", "liquidaciones_hacienda"]},
            ]
        if ruta == "/api/liquidaciones/":
            return [
                {
                    "id": 1,
                    "rubro": "granos",
                    "operacion": "compra",
                    "proveedor": "20281112224",
                    "estado": "borrador",
                    "neto_liquidado": 8399320.0,
                }
            ]
        if ruta == "/api/liquidaciones/1":
            return {
                "id": 1,
                "rubro": "granos",
                "operacion": "compra",
                "proveedor": "20281112224",
                "estado": "borrador",
                "neto_liquidado": 8399320.0,
                "items": [{"descripcion": "Soja", "cantidad_neta": 29400.0}],
                "deducciones": [],
                "retenciones": [],
            }
        if ruta == "/api/caja/saldo":
            return {"saldo": 3250000.0}
        if ruta == "/api/clientes/":
            return [
                {"cuit": "30710011223", "nombre": "Acopio del Litoral S.A.", "saldo": 1450000.0},
                {"cuit": "30720033445", "nombre": "Frigorifico Pampa Sur S.R.L.", "saldo": 0.0},
            ]
        if ruta == "/api/proveedores/":
            return [
                {"cuit": "20281112224", "nombre": "Estancia Don Segundo S.R.L.", "saldo": 820000.0},
            ]
        if ruta == "/api/pendientes/":
            return {"pendientes": [{"id": "op-1", "descripcion": "Aclarar cliente"}]}
        return []

    def post(self, ruta, cuerpo=None, operation_id=None, **params):
        self.llamadas.append(("POST", ruta, params, cuerpo, operation_id))
        if ruta.startswith("/api/modulos/perfiles/"):
            clave = ruta.rsplit("/", 1)[-1]
            return {
                "perfil": clave,
                "nombre": "Agropecuario Mixto",
                "modulos_habilitados": ["stock", "liquidaciones_granos", "liquidaciones_hacienda"],
                "modulos_deshabilitados": [],
            }
        if ruta == "/api/liquidaciones/":
            return {
                "id": 12,
                "rubro": cuerpo["rubro"],
                "operacion": cuerpo["operacion"],
                "estado": cuerpo["estado"],
                "subtotal_bruto": 8232000.0,
                "iva_operacion": 864360.0,
                "total_deducciones": 532400.0,
                "total_retenciones": 164640.0,
                "neto_liquidado": 8399320.0,
                "items": cuerpo["items"],
                "deducciones": cuerpo["deducciones"],
                "retenciones": cuerpo["retenciones"],
            }
        if ruta == "/api/liquidaciones/12/confirmar":
            return {"id": 12, "estado": "confirmada", "neto_liquidado": 8399320.0}
        if ruta == "/api/liquidaciones/12/coe":
            return {"id": 12, "estado": "confirmada", "codigo_autorizacion": cuerpo["coe"]}
        return {"ok": True}

    def delete(self, ruta):
        self.llamadas.append(("DELETE", ruta, {}, None, None))
        return {"id": 12, "estado": "anulada"}


def test_perfiles_negocio_listar_y_aplicar(srv, monkeypatch):
    falsa = ApiFalsaLiquidaciones()
    monkeypatch.setattr(srv, "api", lambda: falsa)

    listado = fn(srv.list_business_profiles)()
    assert listado["cantidad"] == 2
    assert listado["perfiles"][1]["clave"] == "agro_mixto"

    with pytest.raises(Exception, match="confirmar=true"):
        fn(srv.apply_business_profile)("agro_mixto", confirmar=False)

    aplicado = fn(srv.apply_business_profile)("agro_mixto", confirmar=True)
    assert aplicado["aplicado"] is True
    assert aplicado["perfil"] == "agro_mixto"
    assert ("POST", "/api/modulos/perfiles/agro_mixto", {}, {}, None) in falsa.llamadas


def test_crear_y_confirmar_borrador_liquidacion(srv, monkeypatch):
    falsa = ApiFalsaLiquidaciones()
    monkeypatch.setattr(srv, "api", lambda: falsa)

    borrador = fn(srv.create_settlement_draft)(
        tercero="Estancia Don Segundo",
        rubro="granos",
        operacion="compra",
        items=[
            {
                "codigo": 101,
                "descripcion": "Soja Campana 25/26",
                "cantidad_bruta": 30000,
                "merma_pct": 2.0,
                "precio_unitario": 280.0,
                "iva_alicuota": 10.5,
            }
        ],
        deducciones=[
            {"concepto": "flete", "descripcion": "Flete corto", "base_imponible": 350000.0, "iva_alicuota": 21.0}
        ],
        retenciones=[
            {"tipo": "sisa", "descripcion": "Retencion SISA", "alicuota": 2.0, "importe": 164640.0}
        ],
        datos_dominio={"campana": "25/26", "carta_porte": "0001-99887766"},
        operation_id="liq-draft-1",
    )

    assert borrador["id"] == 12
    assert borrador["estado"] == "borrador"
    assert "confirm_settlement_draft" in borrador["_nota"]
    post_crear = next(x for x in falsa.llamadas if x[0] == "POST" and x[1] == "/api/liquidaciones/")
    assert post_crear[3]["estado"] == "borrador"
    assert post_crear[3]["proveedor"] == "20281112224"
    assert post_crear[4] == "liq-draft-1"

    # Confirmar exige confirmar=True
    with pytest.raises(Exception, match="confirmar=true"):
        fn(srv.confirm_settlement_draft)(12, confirmar=False)

    confirmada = fn(srv.confirm_settlement_draft)(12, confirmar=True, operation_id="liq-conf-1")
    assert confirmada["confirmada"] is True
    assert confirmada["estado"] == "confirmada"
    post_conf = [x for x in falsa.llamadas if x[0] == "POST" and x[1] == "/api/liquidaciones/12/confirmar"][0]
    assert post_conf[4] == "liq-conf-1"


def test_registrar_coe_y_anular_liquidacion(srv, monkeypatch):
    falsa = ApiFalsaLiquidaciones()
    monkeypatch.setattr(srv, "api", lambda: falsa)

    with pytest.raises(Exception, match="confirmar=true"):
        fn(srv.register_settlement_coe)(12, "123456789012", confirmar=False)

    con_coe = fn(srv.register_settlement_coe)(12, "123456789012", observaciones="COE ARCA", confirmar=True)
    assert con_coe["codigo_autorizacion"] == "123456789012"

    with pytest.raises(Exception, match="confirmar=true"):
        fn(srv.void_settlement)(12, confirmar=False)

    anulada = fn(srv.void_settlement)(12, confirmar=True)
    assert anulada["anulada"] is True
    assert anulada["estado"] == "anulada"
    assert any(x[0] == "DELETE" and x[1] == "/api/liquidaciones/12" for x in falsa.llamadas)


def test_daily_briefing_estructura_y_sin_rutas_admin(srv, monkeypatch):
    falsa = ApiFalsaLiquidaciones()
    monkeypatch.setattr(srv, "api", lambda: falsa)

    resumen = fn(srv.get_daily_briefing)()
    assert resumen["caja"]["saldo_disponible"] == 3250000.0
    assert resumen["cuentas_por_cobrar"]["cantidad_deudores"] == 1
    assert resumen["cuentas_por_cobrar"]["total_a_cobrar"] == 1450000.0
    assert resumen["cuentas_por_pagar"]["cantidad_acreedores"] == 1
    assert resumen["cuentas_por_pagar"]["total_a_pagar"] == 820000.0
    assert resumen["liquidaciones_en_borrador"]["cantidad"] == 1
    assert resumen["operaciones_pendientes_aclaracion"]["cantidad"] == 1

    rutas = [x[1] for x in falsa.llamadas]
    assert not any("/api/admin/" in r for r in rutas)


def test_descubrimiento_y_lectura_de_skills_operativas(srv):
    listado = fn(srv.list_operational_skills)()
    assert listado["cantidad"] >= 10
    assert listado["guia_maestra_disponible"] is True
    nombres = {s["name"] for s in listado["skills"]}
    assert "liquidacion-cereales-y-hacienda" in nombres

    skill = fn(srv.get_operational_skill)("liquidacion-cereales-y-hacienda")
    assert skill["name"] == "liquidacion-cereales-y-hacienda"
    assert "create_settlement_draft" in skill["content"]
    assert "confirm_settlement_draft" in skill["content"]

    maestro = fn(srv.get_operational_skill)("README")
    assert "liquidacion-cereales-y-hacienda" in maestro["content"]


def test_script_crear_demo_genera_base_aislada(tmp_path):
    from scripts.crear_demo import crear_base_demo

    with pytest.raises(ValueError, match="aldia.db"):
        crear_base_demo(tmp_path / "aldia.db")

    ruta_demo = tmp_path / "aldia_demo.db"
    info = crear_base_demo(ruta_demo)
    assert ruta_demo.is_file()
    assert info["liquidacion_borrador_id"] == 1
