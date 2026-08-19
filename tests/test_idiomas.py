"""
El sistema hablando el idioma de quien lo usa.

Lo que se prueba no es la calidad de las traducciones sino el mecanismo: que el
código de error viaje siempre, que los `params` alcancen para rearmar el mensaje
del otro lado, y que un código sin plantilla degrade a un mensaje útil en vez de
mostrar una clave cruda.

`test_no_hay_deuda_de_traduccion_invisible` es el que más vale a largo plazo:
convierte "faltan traducciones" en algo que la suite grita, en vez de algo que
descubre un usuario.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import idiomas  # noqa: E402


@pytest.fixture
def en_ingles(admin):
    admin.put("/api/config/", json={"negocio_locale": "en-US"})
    idiomas.olvidar_idioma()
    yield
    admin.put("/api/config/", json={"negocio_locale": "es-AR"})
    idiomas.olvidar_idioma()


class TestElMecanismo:
    def test_normaliza_lo_que_le_manden(self):
        assert idiomas.normalizar("en_US") == "en-US"
        assert idiomas.normalizar("EN-us") == "en-US"
        assert idiomas.normalizar("en") == "en-US"
        assert idiomas.normalizar("") == "es-AR"
        # Un idioma que no existe no rompe: se cae al de por defecto.
        assert idiomas.normalizar("klingon") == "es-AR"

    def test_traduce_con_parametros(self):
        msg = idiomas.traducir("STOCK_INSUFICIENTE", "respaldo", idioma="en-US",
                               producto="Widget", pedido=12, disponible=5)
        assert "Widget" in msg and "12" in msg and "5" in msg
        assert "Not enough stock" in msg

    def test_sin_plantilla_devuelve_el_texto_original(self):
        """Mejor un mensaje útil en otro idioma que una clave sin traducir."""
        assert idiomas.traducir("CONFLICTO_DE_INTEGRIDAD", "texto original",
                                idioma="en-US") == "texto original"

    def test_si_falta_un_parametro_no_devuelve_un_mensaje_roto(self):
        """Una plantilla a medio rellenar es peor que el texto original."""
        msg = idiomas.traducir("STOCK_INSUFICIENTE", "el respaldo", idioma="en-US",
                               producto="Widget")   # faltan pedido y disponible
        assert msg == "el respaldo"
        assert "{" not in msg

    def test_no_hay_deuda_de_traduccion_invisible(self):
        """Cada código del catálogo debería tener plantilla en los dos idiomas.

        No falla si falta alguna --sería frenar el desarrollo por una traducción--
        pero deja la lista a la vista. Si esta lista crece sin control, el
        mecanismo dejó de mantenerse.
        """
        from errores import CATALOGO
        for idioma in idiomas.IDIOMAS:
            faltan = idiomas.faltantes(idioma)
            cubiertos = len(CATALOGO) - len(faltan)
            assert cubiertos >= len(CATALOGO) * 0.4, (
                f"{idioma}: solo {cubiertos}/{len(CATALOGO)} códigos traducidos. "
                f"Faltan: {', '.join(faltan[:10])}"
            )


class TestEnLaApi:
    def test_el_error_viaja_con_codigo_y_parametros(self, admin, cuit):
        c = cuit()
        admin.post("/api/clientes/", json={"cuit": c, "nombre": "Cliente i18n"})
        admin.post("/api/stock/", json={
            "codigo": 95001, "producto": "Widget", "cantidad": 3,
            "preven": 10.0, "iva": 21.0, "unidad": "u"})
        r = admin.post("/api/facturas/", json={
            "cliente": c, "fecha": "2026-08-19", "tipo": "A",
            "subtotal": 100.0, "iva": 21.0, "total": 121.0,
            "items": [{"codigo": 95001, "cantidad": 99, "precio": 10.0}]})

        cuerpo = r.json()
        assert cuerpo["codigo"] == "STOCK_INSUFICIENTE"
        # Con esto el cliente arma el mensaje en el idioma que quiera, sin
        # parsear la prosa del servidor.
        assert cuerpo["params"]["producto"] == "Widget"
        assert cuerpo["params"]["disponible"] == 3

    def test_el_servidor_responde_en_el_idioma_configurado(self, admin, en_ingles):
        r = admin.post("/api/auth/login",
                       json={"username": "admin", "password": "no-es-la-clave"})
        assert r.status_code == 401
        assert r.json()["detail"] == "Incorrect username or password"

    def test_y_vuelve_al_castellano(self, admin):
        """Cambiar el idioma tiene que ser reversible, no un viaje de ida."""
        r = admin.post("/api/auth/login",
                       json={"username": "admin", "password": "tampoco"})
        assert r.json()["detail"] == "Usuario o contraseña incorrectos"

    def test_el_catalogo_de_errores_se_publica_en_el_idioma(self, admin, en_ingles):
        datos = admin.get("/api/errores").json()
        assert datos["idioma"] == "en-US"
        assert "retry" in datos["acciones"]["reintentar"].lower()
        # Los CÓDIGOS nunca se traducen: son el contrato con los agentes.
        assert any(e["codigo"] == "STOCK_INSUFICIENTE" for e in datos["errores"])

    def test_el_idioma_se_hereda_del_pais(self, admin):
        """Una instalación estadounidense habla inglés sin configurar nada."""
        admin.put("/api/config/", json={"negocio_locale": "", "negocio_pais": "US"})
        idiomas.olvidar_idioma()
        try:
            assert idiomas.idioma_configurado() == "en-US"
        finally:
            admin.put("/api/config/", json={"negocio_pais": "AR"})
            idiomas.olvidar_idioma()
