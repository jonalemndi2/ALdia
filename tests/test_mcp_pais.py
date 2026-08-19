"""
Que el servidor MCP no tenga reglas fiscales propias.

`docs/AGENTES.md` fija el principio: el MCP no duplica lógica de negocio. Se
cumplía en lo estructural —habla HTTP contra la misma API— y se violaba en un
punto concreto: las seis alícuotas de IVA argentinas estaban escritas a mano en
`server.py` y se validaba contra esa lista ANTES de llamar al servidor.

En una instalación argentina daba el mismo resultado, así que no se notaba. En
una estadounidense, el 7 % de Florida —que el servidor acepta— era rechazado por
el MCP antes de que la petición saliera.
"""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "mcp"))


@pytest.fixture
def srv(monkeypatch):
    """El módulo del servidor MCP, con las reglas del país simuladas.

    Se saltea si el SDK `mcp` no está instalado, y eso es deliberado: el job de
    CI que verifica el lock instala solo lo que instala un comercio, y el SDK no
    es una dependencia del sistema —lo necesita el servidor MCP, que tiene su
    propio `mcp/requirements.txt`. Romper esa verificación por una prueba sería
    confundir dos cosas distintas.

    Los jobs que instalan `requirements-dev.txt` sí lo tienen, así que estas
    pruebas corren igual en cada push. Y `TestNoQuedanReglasFiscalesEscritasAMano`
    no depende del SDK —lee el archivo— así que la guarda contra la regresión
    está activa en todos lados.
    """
    pytest.importorskip(
        "mcp.server",
        reason="el SDK mcp no está instalado (pip install -r backend/requirements-dev.txt)",
    )
    import aldia_mcp.server as s
    s._reglas = None
    yield s
    s._reglas = None


def _fn(herramienta):
    """La función de una tool, sea cual sea la versión del SDK.

    Según la versión, `@servidor.tool(...)` devuelve la función tal cual o un
    objeto que la envuelve en `.fn`. El test no debería depender de eso.
    """
    return getattr(herramienta, "fn", herramienta)


def _reglas(codigo, nombre_impuesto, cerrada, tasas, autoriza):
    return {
        "codigo": codigo,
        "nombre": "Argentina" if codigo == "AR" else "Estados Unidos",
        "identificador": {"nombre": "CUIT" if codigo == "AR" else "EIN",
                          "ejemplo": "20-12345678-9"},
        "impuesto": {"nombre": nombre_impuesto, "lista_cerrada": cerrada,
                     "tasas_sugeridas": tasas},
        "requiere_autorizacion_fiscal": autoriza,
    }


class TestLaTasaLaDecideElServidor:
    def test_en_argentina_la_lista_sigue_siendo_cerrada(self, srv):
        srv._reglas = _reglas("AR", "IVA", True, [0.0, 10.5, 21.0, 27.0], True)
        assert srv._validar_iva(21.0) == 21.0
        with pytest.raises(Exception) as e:
            srv._validar_iva(7.0)          # no es una alícuota legal argentina
        assert "IVA" in str(e.value)

    def test_en_estados_unidos_el_7_por_ciento_pasa(self, srv):
        """El bug: el MCP lo rechazaba antes de que la petición saliera."""
        srv._reglas = _reglas("US", "Sales tax", False, [], False)
        assert srv._validar_iva(7.0) == 7.0
        assert srv._validar_iva(6.25) == 6.25

    def test_pero_una_tasa_absurda_igual_se_ataja(self, srv):
        srv._reglas = _reglas("US", "Sales tax", False, [], False)
        with pytest.raises(Exception):
            srv._validar_iva(45.0)         # es el importe, no la tasa

    def test_si_no_se_pueden_leer_las_reglas_no_se_valida(self, srv):
        """Mejor un viaje de ida y vuelta que rechazar acá algo legítimo."""
        srv._reglas = {}
        assert srv._validar_iva(7.0) == 7.0
        assert srv._validar_iva(21.0) == 21.0


class TestElCAENoSePideDondeNoExiste:
    def test_en_estados_unidos_se_corta_antes_de_llamar(self, srv, monkeypatch):
        srv._reglas = _reglas("US", "Sales tax", False, [], False)

        def no_deberia_llamarse():
            raise AssertionError("Se llamó a la API para pedir un CAE en EE.UU.")

        monkeypatch.setattr(srv, "api", no_deberia_llamarse)
        with pytest.raises(Exception) as e:
            _fn(srv.solicitar_cae)(numero=1)
        mensaje = str(e.value).lower()
        assert "no requieren autorizacion" in mensaje or "autorizacion previa" in mensaje


class TestNoQuedanReglasFiscalesEscritasAMano:
    def test_la_lista_de_alicuotas_ya_no_se_usa_para_validar(self):
        """La constante puede quedar como respaldo, pero no como fuente de verdad."""
        fuente = (RAIZ / "mcp" / "aldia_mcp" / "server.py").read_text(encoding="utf-8")
        cuerpo = fuente.split("def _validar_iva", 1)[1].split("def ", 1)[0]
        assert "ALICUOTAS_IVA" not in cuerpo, (
            "_validar_iva volvió a validar contra la lista argentina escrita a mano"
        )
        assert "_reglas_del_pais" in cuerpo


class TestIdentificadorNeutro:
    def test_alta_cliente_acepta_tax_id(self, srv, monkeypatch):
        enviado = {}

        class ApiFalsa:
            def post(self, ruta, cuerpo):
                enviado.update(cuerpo)
                return {"cuit": cuerpo["cuit"], "nombre": cuerpo["nombre"], "saldo": 0}

            def get(self, ruta, **kw):
                return {}

        srv._reglas = _reglas("US", "Sales tax", False, [], False)
        monkeypatch.setattr(srv, "api", lambda: ApiFalsa())
        _fn(srv.alta_cliente)(tax_id="12-3456789", nombre="Acme Plumbing LLC",
                            city="Miami", region="FL", postal_code="33101")
        assert enviado["cuit"] == "12-3456789"
        assert enviado["city"] == "Miami"
        assert enviado["region"] == "FL"

    def test_sin_identificador_el_error_nombra_el_del_pais(self, srv, monkeypatch):
        srv._reglas = _reglas("US", "Sales tax", False, [], False)
        monkeypatch.setattr(srv, "api", lambda: None)
        with pytest.raises(Exception) as e:
            _fn(srv.alta_cliente)(nombre="Sin identificador")
        assert "EIN" in str(e.value)

class TestNoDaConsejoArgentinoEnEEUU:
    def test_el_alta_no_habla_de_factura_A_B_o_C(self, srv, monkeypatch):
        """La clase de comprobante solo existe donde un organismo los autoriza.

        En una instalación estadounidense esto le contestaba "Factura B" al
        agente: una respuesta argentina a una pregunta que ahí no se hace.
        """
        class ApiFalsa:
            def post(self, ruta, cuerpo):
                return {"cuit": cuerpo["cuit"], "nombre": cuerpo["nombre"], "saldo": 0}

            def get(self, ruta, **kw):
                return {}

        srv._reglas = _reglas("US", "Sales tax", False, [], False)
        monkeypatch.setattr(srv, "api", lambda: ApiFalsa())
        salida = _fn(srv.alta_cliente)(tax_id="12-3456789", nombre="Acme Plumbing LLC")

        assert "comprobante_que_le_corresponde" not in salida
        assert "nota" not in salida
        assert salida["creado"] is True

    def test_pero_en_argentina_sigue_estando(self, srv, monkeypatch):
        class ApiFalsa:
            def post(self, ruta, cuerpo):
                return {"cuit": cuerpo["cuit"], "nombre": cuerpo["nombre"], "saldo": 0}

            def get(self, ruta, **kw):
                return {"negocio_iva": "Responsable Inscripto"}

        srv._reglas = _reglas("AR", "IVA", True, [21.0], True)
        monkeypatch.setattr(srv, "api", lambda: ApiFalsa())
        salida = _fn(srv.alta_cliente)(cuit="20123456789", nombre="Cliente AR")

        assert "Factura" in salida["comprobante_que_le_corresponde"]
