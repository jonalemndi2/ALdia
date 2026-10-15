"""
RG 5616 (ARCA): condicion frente al IVA del receptor en cada comprobante.

Desde el 01/12/2026 ARCA rechaza el pedido de CAE que no informa
CondicionIVAReceptorId, o que informa uno que no corresponde a la clase del
comprobante. Sin red: la llamada a ARCA se intercepta.
"""
import uuid
from types import SimpleNamespace

import pytest

import afip as ws
from conftest import cuit_valido


CFG = SimpleNamespace(entorno="homologacion", cuit=20123456786)


def _comprobante(tipo, condicion, moneda="PES"):
    return ws.ComprobanteAFIP(
        punto_venta=1, tipo_comprobante=tipo, doc_tipo=80, doc_nro=20123456786,
        fecha="20261015", imp_neto=100.0, imp_iva=21.0, imp_total=121.0,
        alicuotas=[{"Id": 5, "BaseImp": 100.0, "Importe": 21.0}],
        condicion_iva_receptor=condicion, moneda=moneda,
    )


@pytest.fixture
def arca_capturada(monkeypatch):
    """Intercepta FECAESolicitar y guarda lo que se le habria enviado a ARCA."""
    enviados = []
    monkeypatch.setattr(ws, "exigir_operativa", lambda cfg: None)
    monkeypatch.setattr(ws, "fe_comp_ultimo_autorizado", lambda *a: 0)
    monkeypatch.setattr(ws, "_auth", lambda cfg: {})

    def llamar(cfg, metodo, **kw):
        enviados.append(kw["FeCAEReq"]["FeDetReq"]["FECAEDetRequest"][0])
        det = SimpleNamespace(CAE="70000000000001", CAEFchVto="20261025", Resultado="A",
                              Observaciones=None, CbteDesde=1)
        return SimpleNamespace(Errors=None, Events=None,
                               FeCabResp=SimpleNamespace(Resultado="A", PtoVta=1, CbteTipo=1),
                               FeDetResp=SimpleNamespace(FECAEDetResponse=[det]))
    monkeypatch.setattr(ws, "_llamar", llamar)
    return enviados


class TestLoQueViajaAArca:
    def test_se_informa_la_condicion_del_receptor(self, arca_capturada):
        ws.solicitar_cae(CFG, _comprobante(1, 1))
        assert arca_capturada[0]["CondicionIVAReceptorId"] == 1

    def test_en_pesos_no_se_manda_cancelacion_en_moneda_extranjera(self, arca_capturada):
        ws.solicitar_cae(CFG, _comprobante(6, 5))
        assert "CanMisMonExt" not in arca_capturada[0]

    def test_en_moneda_extranjera_se_informa_la_cancelacion(self, arca_capturada):
        ws.solicitar_cae(CFG, _comprobante(6, 5, moneda="DOL"))
        assert arca_capturada[0]["CanMisMonExt"] in ("S", "N")

    def test_sin_condicion_no_se_llama_a_arca(self, arca_capturada):
        with pytest.raises(ws.AfipError, match="RG 5616"):
            ws.solicitar_cae(CFG, _comprobante(1, None))
        assert arca_capturada == []


class TestCondicionPorClase:
    @pytest.mark.parametrize("tipo,condicion", [
        (1, 1), (1, 6), (3, 6),          # A: responsable inscripto, monotributo
        (6, 5), (6, 4), (8, 15),         # B: consumidor final, exento, no alcanzado
        (11, 1), (11, 5),                # C: cualquiera
    ])
    def test_combinaciones_validas(self, tipo, condicion):
        ws.validar_condicion_receptor(tipo, condicion)

    @pytest.mark.parametrize("tipo,condicion", [(1, 5), (1, 4), (6, 1), (6, 6)])
    def test_combinaciones_que_arca_rechaza(self, tipo, condicion):
        with pytest.raises(ws.AfipError, match="no es valida"):
            ws.validar_condicion_receptor(tipo, condicion)


class TestClaseSugerida:
    def test_ri_a_monotributista_es_clase_a(self):
        assert ws.clase_comprobante("responsable_inscripto", "monotributo") == "A"
        assert ws.tipo_comprobante_sugerido("responsable_inscripto", "monotributo") == 1

    def test_ri_a_consumidor_final_y_exento_es_clase_b(self):
        assert ws.clase_comprobante("responsable_inscripto", "consumidor_final") == "B"
        assert ws.clase_comprobante("responsable_inscripto", "exento") == "B"

    def test_monotributista_emite_c(self):
        assert ws.clase_comprobante("monotributo", "responsable_inscripto") == "C"

    def test_cada_condicion_de_alta_tiene_codigo_valido_para_su_clase(self):
        """Lo que sugiere el sistema nunca puede ser algo que ARCA rechace."""
        from schemas import CONDICIONES_IVA
        for emisor in ("responsable_inscripto", "monotributo"):
            for clave, datos in CONDICIONES_IVA.items():
                tipo = ws.tipo_comprobante_sugerido(emisor, clave)
                ws.validar_condicion_receptor(tipo, datos["afip_id"])


class TestEndpoint:
    def test_tipo_forzado_incompatible_se_corta_antes_de_arca(self, admin, monkeypatch):
        from routers import afip as router
        monkeypatch.setenv("ALDIA_EMISION_FISCAL", "si")
        monkeypatch.setattr(router, "_config_operativa",
                            lambda db: SimpleNamespace(entorno="homologacion", tipo_comprobante=1, punto_venta=1))
        llamadas = []
        monkeypatch.setattr(router.ws, "solicitar_cae", lambda *a: llamadas.append(a))

        c = cuit_valido("20", uuid.uuid4().int % 10**8)
        assert admin.post("/api/clientes/", json={"cuit": c, "nombre": "Consumidor ficticio",
                                                   "condicion_iva": "consumidor_final"}).status_code == 200
        num = admin.post("/api/facturas/", json={"cliente": c, "fecha": "2026-10-15", "subtotal": 100,
                                                  "iva": 21, "total": 121, "items": [],
                                                  "confirmar": True}).json()["facturanumero"]
        r = admin.post(f"/api/afip/facturas/{num}/solicitar-cae",
                       json={"confirmar": True, "tipo_comprobante": 1},
                       headers={"X-Operation-Id": str(uuid.uuid4())})
        assert r.status_code == 400 and "RG 5616" in r.text
        assert llamadas == []
        # No queda bloqueada la emision: no fue un resultado incierto.
        from database import SessionLocal
        from models import EmisionFiscalEnCurso
        with SessionLocal() as db:
            assert db.query(EmisionFiscalEnCurso).count() == 0
