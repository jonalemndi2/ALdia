"""
Emision fiscal pedida por un agente (codigo de un solo uso), rol agente y
versionado del sistema. Todo con datos ficticios y sin red: ARCA y Telegram se
simulan.
"""
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import cuit_valido

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

PASSWORD_AGENTE = "clave-del-agente-de-pruebas"


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def token_agente(admin):
    usuario = f"agente-{uuid.uuid4().hex[:6]}"
    r = admin.post("/api/auth/register",
                   json={"username": usuario, "password": "inicial-del-agente-1", "rol": "agente"})
    assert r.status_code == 200, r.text
    from fastapi.testclient import TestClient
    import main
    anon = TestClient(main.app)
    r = anon.post("/api/auth/login", json={"username": usuario, "password": "inicial-del-agente-1"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    r = anon.post("/api/auth/cambiar-password",
                  json={"password_actual": "inicial-del-agente-1", "password_nueva": PASSWORD_AGENTE},
                  headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def como_agente(token_agente):
    def _h():
        return {"Authorization": f"Bearer {token_agente}", "X-Operation-Id": str(uuid.uuid4())}
    return _h


def _post_agente(admin, ruta, cuerpo, headers):
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app).post(ruta, json=cuerpo, headers=headers)


def _get_agente(admin, ruta, headers):
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app).get(ruta, headers=headers)


def _factura(admin):
    c = cuit_valido("30", uuid.uuid4().int % 10**8)
    assert admin.post("/api/clientes/", json={"cuit": c, "nombre": "Cliente ficticio de emision",
                                              "condicion_iva": "responsable_inscripto"}).status_code == 200
    r = admin.post("/api/facturas/", json={"cliente": c, "fecha": "2026-10-14", "subtotal": 100,
                                           "iva": 21, "total": 121, "items": [], "confirmar": True})
    assert r.status_code == 200, r.text
    return r.json()["facturanumero"]


@pytest.fixture
def agente_en_ventas(admin):
    """Pedir un CAE es escribir en ventas: el administrador tiene que habilitarlo."""
    roles = next(m for m in admin.get("/api/modulos/").json() if m["clave"] == "ventas")["roles"]
    assert admin.put("/api/modulos/ventas", json={"roles": roles + ",agente"}).status_code == 200
    yield
    admin.put("/api/modulos/ventas", json={"roles": roles})


@pytest.fixture
def arca_simulada(monkeypatch, agente_en_ventas):
    """ARCA que autoriza siempre y Telegram que guarda el mensaje en vez de enviarlo."""
    from routers import afip as router
    import autorizacion_fiscal as af

    monkeypatch.setenv("ALDIA_EMISION_FISCAL", "si")
    monkeypatch.setenv("ALDIA_EMISION_FISCAL_AGENTE", "si")
    monkeypatch.setenv("ALDIA_TELEGRAM_BOT_TOKEN", "token-ficticio")
    monkeypatch.setenv("ALDIA_TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr(router, "_config_operativa",
                        lambda db: SimpleNamespace(entorno="homologacion", tipo_comprobante=1, punto_venta=1))
    monkeypatch.setattr(router, "_tipo_sugerido", lambda *a: 1)

    enviados, llamadas = [], []
    monkeypatch.setattr(af, "_enviar_telegram", lambda texto: enviados.append(texto))

    def cae(cfg, comprobante):
        llamadas.append(comprobante)
        return {"cae": "70000000000001", "cae_vencimiento": "20261024", "punto_venta": 1,
                "tipo_comprobante": 1, "resultado": "A", "numero_comprobante": len(llamadas),
                "observaciones": ""}
    monkeypatch.setattr(router.ws, "solicitar_cae", cae)
    return SimpleNamespace(enviados=enviados, llamadas=llamadas)


def _codigo(texto):
    for linea in texto.splitlines():
        if linea.startswith("Codigo:"):
            return linea.split(":", 1)[1].strip()
    raise AssertionError(f"El mensaje no trae codigo: {texto}")


# ─────────────────────────────────────────────────────────────
# Rol agente
# ─────────────────────────────────────────────────────────────

class TestRolAgente:
    def test_lee_lo_que_lee_el_auditor(self, admin, como_agente):
        r = _get_agente(admin, "/api/clientes/", como_agente())
        assert r.status_code == 200, r.text

    def test_no_escribe_donde_no_lo_habilitaron(self, admin, como_agente):
        c = cuit_valido("20", uuid.uuid4().int % 10**8)
        r = _post_agente(admin, "/api/clientes/", {"cuit": c, "nombre": "No deberia crearse"}, como_agente())
        assert r.status_code == 403, r.text

    def test_escribe_donde_el_administrador_lo_habilita(self, admin, como_agente):
        roles = next(m for m in admin.get("/api/modulos/").json() if m["clave"] == "clientes")["roles"]
        try:
            assert admin.put("/api/modulos/clientes", json={"roles": roles + ",agente"}).status_code == 200
            c = cuit_valido("20", uuid.uuid4().int % 10**8)
            r = _post_agente(admin, "/api/clientes/", {"cuit": c, "nombre": "Alta por agente"}, como_agente())
            assert r.status_code == 200, r.text
        finally:
            admin.put("/api/modulos/clientes", json={"roles": roles})

    def test_no_entra_a_administracion(self, admin, como_agente):
        r = _get_agente(admin, "/api/modulos/", como_agente())
        assert r.status_code == 403


# ─────────────────────────────────────────────────────────────
# Emision fiscal con codigo
# ─────────────────────────────────────────────────────────────

class TestEmisionDelAgente:
    def test_sin_permiso_de_ventas_no_llega_al_cae(self, admin, como_agente, monkeypatch):
        monkeypatch.setenv("ALDIA_EMISION_FISCAL", "si")
        monkeypatch.setenv("ALDIA_EMISION_FISCAL_AGENTE", "si")
        num = _factura(admin)
        r = _post_agente(admin, f"/api/afip/facturas/{num}/solicitar-cae", {"confirmar": True}, como_agente())
        assert r.status_code == 403 and "SIN_PERMISO" in r.text

    def test_apagada_por_defecto(self, admin, como_agente, agente_en_ventas, monkeypatch):
        monkeypatch.setenv("ALDIA_EMISION_FISCAL", "si")
        monkeypatch.delenv("ALDIA_EMISION_FISCAL_AGENTE", raising=False)
        num = _factura(admin)
        r = _post_agente(admin, f"/api/afip/facturas/{num}/solicitar-cae", {"confirmar": True}, como_agente())
        assert r.status_code == 403
        assert "EMISION_FISCAL_DEL_AGENTE_DESHABILITADA" in r.text

    def test_sin_canal_no_hay_codigo_ni_emision(self, admin, como_agente, arca_simulada, monkeypatch):
        monkeypatch.delenv("ALDIA_TELEGRAM_BOT_TOKEN")
        num = _factura(admin)
        r = _post_agente(admin, f"/api/afip/facturas/{num}/solicitar-cae", {"confirmar": True}, como_agente())
        assert r.status_code == 403
        assert arca_simulada.llamadas == [] and arca_simulada.enviados == []

    def test_circuito_completo(self, admin, como_agente, arca_simulada):
        num = _factura(admin)
        ruta = f"/api/afip/facturas/{num}/solicitar-cae"

        # 1. Sin codigo: no emite, envia el codigo a la persona.
        r = _post_agente(admin, ruta, {"confirmar": True}, como_agente())
        assert r.status_code == 409, r.text
        assert "CODIGO_DE_AUTORIZACION_REQUERIDO" in r.text
        assert arca_simulada.llamadas == []
        assert len(arca_simulada.enviados) == 1
        mensaje = arca_simulada.enviados[0]
        assert "Cliente ficticio de emision" in mensaje
        codigo = _codigo(mensaje)
        assert codigo not in r.text, "el codigo nunca puede volver al agente"

        # 2. Codigo equivocado: rechaza y no emite.
        malo = "000000" if codigo != "000000" else "111111"
        r = _post_agente(admin, ruta, {"confirmar": True, "codigo": malo}, como_agente())
        assert r.status_code == 403 and "CODIGO_DE_AUTORIZACION_INVALIDO" in r.text
        assert arca_simulada.llamadas == []

        # 3. Codigo correcto: emite una vez.
        r = _post_agente(admin, ruta, {"confirmar": True, "codigo": codigo}, como_agente())
        assert r.status_code == 200, r.text
        assert r.json()["cae"] == "70000000000001"
        assert len(arca_simulada.llamadas) == 1

    def test_el_codigo_no_sirve_para_otra_factura_ni_dos_veces(self, admin, como_agente, arca_simulada):
        a, b = _factura(admin), _factura(admin)
        _post_agente(admin, f"/api/afip/facturas/{a}/solicitar-cae", {"confirmar": True}, como_agente())
        codigo = _codigo(arca_simulada.enviados[-1])

        r = _post_agente(admin, f"/api/afip/facturas/{b}/solicitar-cae",
                         {"confirmar": True, "codigo": codigo}, como_agente())
        assert r.status_code == 403 and arca_simulada.llamadas == []

        assert _post_agente(admin, f"/api/afip/facturas/{a}/solicitar-cae",
                            {"confirmar": True, "codigo": codigo}, como_agente()).status_code == 200
        # Ya tiene CAE: ni con el mismo codigo se pide otro.
        r = _post_agente(admin, f"/api/afip/facturas/{a}/solicitar-cae",
                         {"confirmar": True, "codigo": codigo}, como_agente())
        assert r.status_code == 409 and "CAE_YA_EMITIDO" in r.text
        assert len(arca_simulada.llamadas) == 1

    def test_si_la_factura_cambia_el_codigo_deja_de_valer(self, admin, como_agente, arca_simulada):
        from database import SessionLocal
        from models import Factura
        num = _factura(admin)
        ruta = f"/api/afip/facturas/{num}/solicitar-cae"
        _post_agente(admin, ruta, {"confirmar": True}, como_agente())
        codigo = _codigo(arca_simulada.enviados[-1])
        with SessionLocal() as db:
            f = db.query(Factura).filter(Factura.facturanumero == num).first()
            f.fecha = "2026-10-13"
            db.commit()
        r = _post_agente(admin, ruta, {"confirmar": True, "codigo": codigo}, como_agente())
        assert r.status_code == 403 and "cambio" in r.text
        assert arca_simulada.llamadas == []

    def test_demasiados_intentos_invalidan_el_codigo(self, admin, como_agente, arca_simulada):
        import autorizacion_fiscal as af
        num = _factura(admin)
        ruta = f"/api/afip/facturas/{num}/solicitar-cae"
        _post_agente(admin, ruta, {"confirmar": True}, como_agente())
        codigo = _codigo(arca_simulada.enviados[-1])
        malo = "000000" if codigo != "000000" else "111111"
        for _ in range(af.CODIGO_MAX_INTENTOS):
            _post_agente(admin, ruta, {"confirmar": True, "codigo": malo}, como_agente())
        r = _post_agente(admin, ruta, {"confirmar": True, "codigo": codigo}, como_agente())
        assert r.status_code == 403
        assert arca_simulada.llamadas == []

    def test_el_administrador_no_necesita_codigo(self, admin, arca_simulada):
        num = _factura(admin)
        r = admin.post(f"/api/afip/facturas/{num}/solicitar-cae", json={"confirmar": True},
                       headers={"X-Operation-Id": str(uuid.uuid4())})
        assert r.status_code == 200, r.text
        assert arca_simulada.enviados == []


# ─────────────────────────────────────────────────────────────
# Versionado
# ─────────────────────────────────────────────────────────────

class TestVersion:
    def test_la_version_sale_del_archivo(self, admin):
        import version as v
        r = admin.get("/api/sistema/version")
        assert r.status_code == 200, r.text
        assert r.json()["version"] == v.version_instalada()
        assert r.json()["actualizacion"]["consultada"] is False   # las pruebas no usan la red

    def test_el_agente_puede_consultarla_pero_no_actualizar(self, admin, como_agente):
        assert _get_agente(admin, "/api/sistema/version", como_agente()).status_code == 200
        assert _post_agente(admin, "/api/sistema/actualizar", {}, como_agente()).status_code == 403

    def test_comparar(self):
        import version as v
        assert v.comparar("2.1.0", "2.0.9") == 1
        assert v.comparar("2.1.0", "2.1.0") == 0
        assert v.comparar("2.1.0", "2.10.0") == -1

    def test_novedades_entre_versiones(self):
        import version as v
        texto = ("# Novedades\n\n## 2.2.0 — 2026-11-01\n- nueva\n\n"
                 "## 2.1.0 — 2026-10-14\n- media\n\n## 2.0.0\nbase\n")
        novedades = v.novedades_entre(texto, "2.0.0", "2.2.0")
        assert [n["version"] for n in novedades] == ["2.2.0", "2.1.0"]
        assert novedades[0]["texto"] == "- nueva"

    def test_el_changelog_tiene_la_version_actual(self):
        import version as v
        versiones = [s["version"] for s in v.secciones_changelog(v.changelog_local())]
        assert v.version_instalada() in versiones, "falta la seccion de la version en CHANGELOG.md"


# ─────────────────────────────────────────────────────────────
# Aviso al agente (servidor MCP)
# ─────────────────────────────────────────────────────────────

class TestAvisoDeVersionAlAgente:
    @pytest.fixture
    def srv(self, monkeypatch, tmp_path):
        pytest.importorskip("mcp.server", reason="el SDK mcp no está instalado")
        import aldia_mcp.server as s
        monkeypatch.setenv("ALDIA_MCP_ESTADO", str(tmp_path / "vista.json"))
        estado = {"version": "2.1.0", "actualizacion": {"disponible": False}}

        class ApiFalsa:
            def get(self, ruta, **_):
                assert ruta == "/api/sistema/version"
                return estado
        monkeypatch.setattr(s, "api", lambda: ApiFalsa())

        def nuevo_proceso():
            s._aviso_revisado = False
            s._aviso_pendiente = None
        nuevo_proceso()
        yield SimpleNamespace(s=s, estado=estado, nuevo_proceso=nuevo_proceso)
        nuevo_proceso()

    def test_primera_vez_no_avisa(self, srv):
        assert "_aviso_aldia" not in srv.s._adjuntar_aviso({"ok": 1})

    def test_avisa_una_sola_vez_despues_de_actualizar(self, srv):
        srv.s._adjuntar_aviso({"ok": 1})
        srv.nuevo_proceso()
        srv.estado["version"] = "2.2.0"
        r = srv.s._adjuntar_aviso({"ok": 1})
        assert r["_aviso_aldia"]["actualizado"] == {**r["_aviso_aldia"]["actualizado"], "de": "2.1.0", "a": "2.2.0"}
        assert "_aviso_aldia" not in srv.s._adjuntar_aviso({"ok": 2})
        srv.nuevo_proceso()
        assert "_aviso_aldia" not in srv.s._adjuntar_aviso({"ok": 3})

    def test_avisa_version_disponible(self, srv):
        srv.s._adjuntar_aviso({"ok": 1})
        srv.nuevo_proceso()
        srv.estado["actualizacion"] = {"disponible": True, "ultima": "2.3.0", "novedades": [{"version": "2.3.0"}]}
        r = srv.s._adjuntar_aviso({"ok": 1})
        assert r["_aviso_aldia"]["disponible"]["version"] == "2.3.0"

    def test_una_lista_no_consume_el_aviso(self, srv):
        srv.s._adjuntar_aviso({"ok": 1})
        srv.nuevo_proceso()
        srv.estado["version"] = "2.2.0"
        assert srv.s._adjuntar_aviso([1, 2]) == [1, 2]
        assert "_aviso_aldia" in srv.s._adjuntar_aviso({"ok": 1})

    def test_las_herramientas_registradas_llevan_el_aviso(self, srv):
        import asyncio
        srv.s._adjuntar_aviso({"ok": 1})
        srv.nuevo_proceso()
        srv.estado["version"] = "2.2.0"
        resultado = asyncio.run(srv.s.servidor.call_tool("get_system_version", {}))
        assert "_aviso_aldia" in str(resultado)
