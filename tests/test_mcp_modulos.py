"""El servidor MCP muestra solo las herramientas y skills de los módulos activos."""
import asyncio
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ / "mcp") not in sys.path:
    sys.path.insert(0, str(RAIZ / "mcp"))

from routers.modulos import MODULOS_DEFAULT  # noqa: E402

CLAVES_BACKEND = {m["clave"] for m in MODULOS_DEFAULT}
ADMIN_POR_CHAT = {"create_user", "delete_user", "configure_module",
                  "apply_business_profile", "delete_cash_movement"}
LIQUIDACIONES = {"list_settlements", "get_settlement", "create_settlement_draft",
                 "confirm_settlement_draft", "register_settlement_coe", "void_settlement"}


@pytest.fixture
def srv():
    pytest.importorskip("mcp.server")
    import aldia_mcp.server as modulo
    modulo._reglas = {}
    yield modulo
    modulo._reglas = None


def fn(tool):
    return getattr(tool, "fn", tool)


def _permisos(lectura=(), escritura=(), apagados=(), auditoria=False, fijados=False):
    """Respuesta de GET /api/modulos/permisos con los modulos indicados."""
    return {
        "modulos": [
            {
                "clave": clave,
                "habilitado": clave not in apagados,
                "lectura": clave not in apagados and clave in lectura,
                "escritura": clave not in apagados and clave in escritura,
            }
            for clave in CLAVES_BACKEND
        ],
        "auditoria": auditoria,
        "fijados_por_entorno": fijados,
    }


COMERCIO = ("stock", "clientes", "ventas", "proveedores", "gastos",
            "cuentas_corrientes", "caja", "iva", "administracion")


class ApiFalsa:
    def __init__(self, permisos=None, rutas=None):
        self.permisos = permisos
        self.rutas = rutas or {}
        self.llamadas = []
        self.usuario_actual = {"username": "agente", "rol": "agente"}
        self.base_url = "http://aldia.test"

    def get(self, ruta, **params):
        self.llamadas.append(ruta)
        if ruta == "/api/modulos/permisos":
            if self.permisos is None:
                raise ConnectionError("ALdia no responde")
            return self.permisos
        if ruta in self.rutas:
            valor = self.rutas[ruta]
            if isinstance(valor, Exception):
                raise valor
            return valor
        return []


def _visibles(srv, monkeypatch, api):
    monkeypatch.setattr(srv, "api", lambda: api)
    srv._olvidar_permisos()
    return {h.name for h in asyncio.run(srv.servidor.list_tools())}


class TestCatalogo:
    def test_toda_herramienta_registrada_declara_su_modulo(self, srv):
        registradas = {t.name for t in srv.servidor._tool_manager.list_tools()}
        assert registradas == set(srv._HERRAMIENTAS)

    def test_los_modulos_declarados_existen_en_el_backend(self, srv):
        validos = CLAVES_BACKEND | {srv.NUCLEO, srv.AUDITORIA}
        for nombre, (modulos, _) in srv._HERRAMIENTAS.items():
            assert set(modulos) <= validos, f"{nombre} declara {modulos}"

    def test_escritura_sale_de_las_anotaciones(self, srv):
        for t in srv.servidor._tool_manager.list_tools():
            _, escritura = srv._HERRAMIENTAS[t.name]
            assert escritura is (not t.annotations.read_only_hint), t.name

    def test_una_herramienta_sin_modulo_no_se_puede_registrar(self, srv):
        with pytest.raises(TypeError, match="modulo"):
            srv.servidor.tool(title="Sin modulo", annotations=srv.SOLO_LECTURA)

    def test_la_administracion_por_chat_es_la_que_dice_el_plan(self, srv):
        en_el_modulo = {n for n, (m, _) in srv._HERRAMIENTAS.items() if srv.ADMIN_POR_CHAT in m}
        assert en_el_modulo == ADMIN_POR_CHAT


class TestFiltro:
    def test_comercio_con_admin_no_ve_agro_ni_administracion_por_chat(self, srv, monkeypatch):
        api = ApiFalsa(_permisos(lectura=COMERCIO, escritura=COMERCIO,
                                 apagados=("liquidaciones_granos", "liquidaciones_hacienda",
                                           "administracion_por_chat"),
                                 auditoria=True))
        visibles = _visibles(srv, monkeypatch, api)
        assert not visibles & LIQUIDACIONES
        assert not visibles & ADMIN_POR_CHAT
        assert {"create_invoice", "record_payment", "get_audit_log", "check_connection"} <= visibles

    def test_el_agente_de_fabrica_solo_lee(self, srv, monkeypatch):
        """El rol agente lee como el auditor y no escribe en ningun modulo."""
        api = ApiFalsa(_permisos(lectura=COMERCIO, apagados=("administracion_por_chat",)))
        visibles = _visibles(srv, monkeypatch, api)
        escritura_visible = {n for n in visibles if srv._HERRAMIENTAS[n][1]}
        nucleo = {n for n, (m, _) in srv._HERRAMIENTAS.items() if srv.NUCLEO in m}
        assert escritura_visible <= nucleo
        assert "find_customer" in visibles
        assert "get_audit_log" not in visibles

    def test_escribir_en_ventas_no_abre_los_demas_modulos(self, srv, monkeypatch):
        api = ApiFalsa(_permisos(lectura=COMERCIO, escritura=("ventas",)))
        visibles = _visibles(srv, monkeypatch, api)
        assert "create_invoice" in visibles
        assert "record_vendor_payment" not in visibles

    def test_un_solo_rubro_de_liquidaciones_alcanza(self, srv, monkeypatch):
        api = ApiFalsa(_permisos(lectura=("liquidaciones_hacienda",),
                                 escritura=("liquidaciones_hacienda",),
                                 apagados=("liquidaciones_granos",)))
        assert LIQUIDACIONES <= _visibles(srv, monkeypatch, api)

    def test_sin_respuesta_del_backend_se_ve_todo_menos_la_administracion_por_chat(
            self, srv, monkeypatch):
        visibles = _visibles(srv, monkeypatch, ApiFalsa(permisos=None))
        assert visibles == set(srv._HERRAMIENTAS) - ADMIN_POR_CHAT

    def test_prendida_a_conciencia_la_administracion_por_chat_aparece(self, srv, monkeypatch):
        api = ApiFalsa(_permisos(lectura=CLAVES_BACKEND, escritura=CLAVES_BACKEND))
        assert ADMIN_POR_CHAT <= _visibles(srv, monkeypatch, api)


class TestLlamadas:
    def test_llamar_una_herramienta_oculta_explica_como_prenderla(self, srv, monkeypatch):
        from mcp.server.mcpserver.exceptions import ToolError

        api = ApiFalsa(_permisos(lectura=COMERCIO, escritura=COMERCIO,
                                 apagados=("liquidaciones_granos", "liquidaciones_hacienda",
                                           "administracion_por_chat")))
        monkeypatch.setattr(srv, "api", lambda: api)
        with pytest.raises(ToolError, match="Administracion por chat"):
            asyncio.run(srv.servidor.call_tool("delete_user", {"usuario": "x"}))
        with pytest.raises(ToolError, match="apagado"):
            asyncio.run(srv.servidor.call_tool("list_settlements", {}))
        assert api.llamadas == ["/api/modulos/permisos"]   # nunca llego a ejecutarse

    def test_sin_permiso_de_escritura_lo_dice(self, srv, monkeypatch):
        from mcp.server.mcpserver.exceptions import ToolError

        monkeypatch.setattr(srv, "api", lambda: ApiFalsa(_permisos(lectura=COMERCIO)))
        with pytest.raises(ToolError, match="permiso de escritura"):
            asyncio.run(srv.servidor.call_tool("create_customer", {"cuit": "1", "nombre": "x"}))

    def test_los_permisos_se_cachean(self, srv, monkeypatch):
        api = ApiFalsa(_permisos(lectura=COMERCIO))
        monkeypatch.setattr(srv, "api", lambda: api)
        srv._permisos_vigentes()
        srv._permisos_vigentes()
        assert api.llamadas.count("/api/modulos/permisos") == 1


class TestCheckConnection:
    def test_dice_que_esta_apagado_y_cuantas_herramientas_ve(self, srv, monkeypatch):
        api = ApiFalsa(_permisos(lectura=COMERCIO, escritura=("ventas",),
                                 apagados=("liquidaciones_granos", "liquidaciones_hacienda",
                                           "administracion_por_chat")))
        monkeypatch.setattr(srv, "api", lambda: api)
        r = fn(srv.check_connection)()
        assert "liquidaciones_granos" in r["modulos_apagados"]
        assert r["modulos_con_escritura"] == ["ventas"]
        assert r["herramientas_visibles"] + r["herramientas_ocultas"] == len(srv._HERRAMIENTAS)
        assert r["herramientas_ocultas"] > 0
        assert "Administracion > Modulos" in r["como_habilitar"]


class TestSkills:
    def test_toda_skill_tiene_modulo_y_los_modulos_existen(self, srv):
        carpetas = {p.name for p in (RAIZ / "skills").iterdir()
                    if p.is_dir() and (p / "SKILL.md").is_file()}
        assert carpetas == set(srv._MODULOS_DE_SKILL)
        validos = CLAVES_BACKEND | {srv.NUCLEO, srv.AUDITORIA}
        for nombre, modulos in srv._MODULOS_DE_SKILL.items():
            assert set(modulos) <= validos, nombre
        assert set(srv._PAIS_DE_SKILL) <= carpetas

    def test_se_listan_solo_las_del_pais_y_los_modulos_activos(self, srv, monkeypatch):
        api = ApiFalsa(_permisos(lectura=COMERCIO,
                                 apagados=("liquidaciones_granos", "liquidaciones_hacienda")))
        monkeypatch.setattr(srv, "api", lambda: api)
        srv._reglas = {"codigo": "AR"}
        nombres = {s["name"] for s in fn(srv.list_operational_skills)()["skills"]}
        assert "facturacion" in nombres
        assert "factura-electronica-afip" in nombres
        assert "liquidacion-cereales-y-hacienda" not in nombres
        assert not {n for n in nombres if n.startswith("us-")}

        with pytest.raises(srv.ALdiaError, match="No aplica"):
            fn(srv.get_operational_skill)("liquidacion-cereales-y-hacienda")
        assert "ALdia" in fn(srv.get_operational_skill)("README")["content"]

    def test_en_estados_unidos_no_aparecen_las_argentinas(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "api", lambda: ApiFalsa(_permisos(lectura=CLAVES_BACKEND)))
        srv._reglas = {"codigo": "US"}
        nombres = {s["name"] for s in fn(srv.list_operational_skills)()["skills"]}
        assert {"us-setup", "us-customers-and-vendors", "control-de-stock"} <= nombres
        assert "factura-electronica-afip" not in nombres


class TestResumenesPorModulo:
    def test_el_briefing_omite_los_modulos_apagados(self, srv, monkeypatch):
        api = ApiFalsa(
            _permisos(lectura=("clientes", "proveedores"),
                      apagados=("caja", "liquidaciones_granos", "liquidaciones_hacienda")),
            rutas={"/api/clientes/": [{"cuit": "1", "nombre": "A", "saldo": 10}]},
        )
        monkeypatch.setattr(srv, "api", lambda: api)
        r = fn(srv.get_daily_briefing)()
        assert "caja" not in r and "liquidaciones_en_borrador" not in r
        assert set(r["no_incluido"]) == {"caja", "liquidaciones_en_borrador"}
        assert r["cuentas_por_cobrar"]["cantidad_deudores"] == 1
        assert "/api/caja/saldo" not in api.llamadas

    def test_una_falla_en_una_seccion_no_tumba_el_briefing(self, srv, monkeypatch):
        api = ApiFalsa(
            _permisos(lectura=COMERCIO),
            rutas={"/api/caja/saldo": srv.ALdiaError("HTTP 500")},
        )
        monkeypatch.setattr(srv, "api", lambda: api)
        r = fn(srv.get_daily_briefing)()
        assert r["caja"]["cantidad"] is None and "500" in r["caja"]["error"]
        assert "cuentas_por_cobrar" in r

    def test_los_movimientos_del_dia_omiten_los_modulos_apagados(self, srv, monkeypatch):
        api = ApiFalsa(_permisos(lectura=("caja", "ventas"),
                                 apagados=("gastos", "proveedores", "cuentas_corrientes")),
                       rutas={"/api/caja/saldo": {"saldo": 5}})
        monkeypatch.setattr(srv, "api", lambda: api)
        r = fn(srv.get_daily_cash_movements)("2026-10-16")
        assert set(r["no_incluido"]) == {"cobros", "pagos", "gastos"}
        assert "/api/gastos/" not in api.llamadas
        assert "/api/facturas/" in api.llamadas


class TestDePuntaAPunta:
    """El servidor MCP de verdad contra el backend de verdad, sin respuestas armadas.

    Es la prueba de que /api/modulos/permisos y lo que el MCP espera leer de ahí
    son el mismo contrato.
    """

    def test_el_agente_ve_lo_que_el_backend_le_permite(self, srv, admin, monkeypatch):
        from fastapi.testclient import TestClient

        import main
        from aldia_mcp.client import ALdiaClient
        from database import SessionLocal
        from models import Modulo, Usuario
        from routers.auth import hash_password

        with SessionLocal() as db:
            if not db.query(Usuario).filter(Usuario.username == "agente_e2e").first():
                db.add(Usuario(username="agente_e2e", rol="agente",
                               password_hash=hash_password("ClaveDelAgente123!"),
                               debe_cambiar_password=False))
                db.commit()
            ventas = db.query(Modulo).filter(Modulo.clave == "ventas").one()
            roles_ventas = ventas.roles
            estado = {m.clave: bool(m.habilitado) for m in db.query(Modulo).all()}

        cliente = ALdiaClient(base_url="http://testserver", usuario="agente_e2e",
                              password="ClaveDelAgente123!")
        cliente._http = TestClient(main.app)       # sin `with`: el backend ya arrancó
        monkeypatch.setattr(srv, "api", lambda: cliente)

        def visibles():
            srv._olvidar_permisos()
            return {h.name for h in asyncio.run(srv.servidor.list_tools())}

        try:
            admin.post("/api/modulos/perfiles/comercio")
            antes = visibles()
            assert "find_customer" in antes
            assert "create_invoice" not in antes        # el agente nace sin escritura
            assert not antes & LIQUIDACIONES
            assert not antes & ADMIN_POR_CHAT

            r = admin.put("/api/modulos/ventas", json={"roles": roles_ventas + ",agente"})
            assert r.status_code == 200, r.text
            assert "create_invoice" in visibles()
        finally:
            admin.put("/api/modulos/ventas", json={"roles": roles_ventas})
            with SessionLocal() as db:
                for m in db.query(Modulo).all():
                    m.habilitado = estado.get(m.clave, m.habilitado)
                db.commit()
