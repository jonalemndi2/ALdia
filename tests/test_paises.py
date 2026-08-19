"""
Rebanada vertical: la misma instalación, configurada como Estados Unidos.

Esto es una PRUEBA DE ARQUITECTURA además de una prueba funcional. Lo que
demuestra es que el país es una propiedad de la configuración y no una rama del
código: el mismo motor factura en Argentina y en Estados Unidos sin que el
núcleo —auditoría, idempotencia, permisos, secuencias, dinero— se entere.

Lo primero que se prueba, y lo más importante, es que **Argentina no cambió**.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import paises  # noqa: E402


@pytest.fixture
def como_eeuu(admin):
    """Reconfigura la instalación como Estados Unidos y la deja como estaba."""
    admin.put("/api/config/", json={"negocio_pais": "US"})
    yield
    admin.put("/api/config/", json={"negocio_pais": "AR"})
    paises.olvidar_pais()


class TestArgentinaNoCambio:
    """La red de seguridad: la instalación por defecto sigue siendo argentina."""

    def test_el_pais_por_defecto_es_argentina(self, admin):
        r = admin.get("/api/config/pais")
        assert r.status_code == 200
        datos = r.json()
        assert datos["codigo"] == "AR"
        assert datos["identificador"]["nombre"] == "CUIT"
        assert datos["impuesto"]["nombre"] == "IVA"
        assert datos["requiere_autorizacion_fiscal"] is True

    def test_el_cuit_sigue_validando_el_digito_verificador(self, admin):
        # Once dígitos, pero el verificador no cierra: tiene que rechazarse.
        r = admin.post("/api/clientes/", json={"cuit": "20123456781", "nombre": "X"})
        assert r.status_code == 422

    def test_las_alicuotas_de_iva_siguen_siendo_una_lista_cerrada(self, admin):
        r = admin.post("/api/stock/", json={
            "codigo": 77001, "producto": "Con IVA raro", "cantidad": 1,
            "preven": 100.0, "iva": 7.0, "unidad": "u",   # 7% no existe en AR
        })
        assert r.status_code == 422


class TestEstadosUnidos:
    def test_cambiar_el_pais_cambia_las_reglas(self, admin, como_eeuu):
        datos = admin.get("/api/config/pais").json()
        assert datos["codigo"] == "US"
        assert datos["moneda"] == "USD"
        assert datos["identificador"]["nombre"] == "EIN"
        assert datos["impuesto"]["nombre"] == "Sales tax"
        assert datos["etiquetas"]["region"] == "State"
        # No hay organismo que autorice comprobantes.
        assert datos["requiere_autorizacion_fiscal"] is False

    def test_los_limites_conocidos_se_publican(self, admin, como_eeuu):
        """Que la tasa se carga a mano tiene que estar dicho, no escondido."""
        advertencias = admin.get("/api/config/pais").json()["advertencias"]
        assert advertencias, "El paquete de EE.UU. debe declarar sus limitaciones"
        assert any("nexus" in a for a in advertencias)

    def test_se_da_de_alta_un_cliente_con_EIN(self, admin, como_eeuu):
        r = admin.post("/api/clientes/", json={
            "cuit": "12-3456789", "nombre": "Acme Plumbing LLC",
        })
        assert r.status_code in (200, 201), r.text
        # Se normaliza a los 9 dígitos, igual que el CUIT a 11.
        assert r.json()["cuit"] == "123456789"

    def test_un_EIN_con_prefijo_inexistente_se_rechaza(self, admin, como_eeuu):
        r = admin.post("/api/clientes/", json={"cuit": "07-1234567", "nombre": "X"})
        assert r.status_code == 422

    def test_un_CUIT_argentino_ya_no_entra(self, admin, como_eeuu):
        """11 dígitos no es un EIN: la instalación cambió de reglas de verdad."""
        r = admin.post("/api/clientes/", json={"cuit": "20123456789", "nombre": "X"})
        assert r.status_code == 422

    def test_una_tasa_de_sales_tax_cualquiera_es_valida(self, admin, como_eeuu):
        """7% no existe en Argentina y es perfectamente normal en Florida."""
        r = admin.post("/api/stock/", json={
            "codigo": 77002, "producto": "Widget", "cantidad": 10,
            "preven": 100.0, "iva": 7.0, "unidad": "u",
        })
        assert r.status_code in (200, 201), r.text

    def test_una_tasa_absurda_igual_se_ataja(self, admin, como_eeuu):
        """Lista abierta no es lista sin control: 45% es cargar el importe en
        el campo de la tasa, que es el error de carga tipico."""
        r = admin.post("/api/stock/", json={
            "codigo": 77003, "producto": "Widget", "cantidad": 10,
            "preven": 100.0, "iva": 45.0, "unidad": "u",
        })
        assert r.status_code == 422

    def test_se_factura_sin_pasar_por_ningun_organismo(self, admin, como_eeuu):
        """La rebanada completa: cliente, producto y factura, sin AFIP."""
        admin.post("/api/clientes/", json={
            "cuit": "12-3456789", "nombre": "Acme Plumbing LLC"})
        admin.post("/api/stock/", json={
            "codigo": 77010, "producto": "Installation", "cantidad": 100,
            "preven": 250.0, "iva": 7.0, "unidad": "u"})

        r = admin.post("/api/facturas/", json={
            "cliente": "123456789", "fecha": "2026-08-19", "tipo": "A",
            "items": [{"codigo": 77010, "cantidad": 4, "precio": 250.0}],
        })
        assert r.status_code in (200, 201), r.text
        factura = r.json()
        # Emitida y válida por sí misma: sin CAE y sin haber hablado con nadie.
        assert not factura.get("cae")

    def test_pedir_un_CAE_no_aplica_y_lo_dice_con_codigo(self, admin, como_eeuu):
        """El agente tiene que poder distinguir "no aplica" de "fallo"."""
        admin.post("/api/clientes/", json={
            "cuit": "12-3456789", "nombre": "Acme Plumbing LLC"})
        admin.post("/api/stock/", json={
            "codigo": 77020, "producto": "Service", "cantidad": 10,
            "preven": 100.0, "iva": 7.0, "unidad": "u"})
        num = admin.post("/api/facturas/", json={
            "cliente": "123456789", "fecha": "2026-08-19", "tipo": "A",
            "items": [{"codigo": 77020, "cantidad": 1, "precio": 100.0}],
        }).json().get("facturanumero")

        r = admin.post(f"/api/afip/facturas/{num}/solicitar-cae", json={})
        assert r.status_code == 409
        cuerpo = r.json()
        assert cuerpo["codigo"] == "OPERACION_NO_APLICA_EN_ESTE_PAIS"
        # No es a corregir ni a reintentar: no existe el circuito.
        assert cuerpo["accion"] == "abortar"


class TestConfiguracion:
    def test_un_pais_sin_paquete_se_rechaza(self, admin):
        """Guardarlo dejaria el sistema validando con las reglas de otro lado."""
        r = admin.put("/api/config/", json={"negocio_pais": "XX"})
        assert r.status_code == 400
        assert r.json()["codigo"] == "PAIS_NO_SOPORTADO"
        # Y la instalación sigue siendo la que era.
        assert admin.get("/api/config/pais").json()["codigo"] == "AR"


class TestElNucleoNoSeEntera:
    """Lo que NO cambia entre países, que es la mayor parte del sistema."""

    def test_la_auditoria_registra_igual(self, admin, como_eeuu):
        admin.post("/api/clientes/", json={
            "cuit": "12-3456789", "nombre": "Auditado LLC"})
        registros = admin.get("/api/auditoria/").json()["filas"]
        # El alta quedo auditada igual que en Argentina: el middleware no sabe
        # ni tiene por que saber con que reglas fiscales se valido el alta.
        assert any(f.get("modulo") == "clientes" and f.get("resultado") == "exito"
                   for f in registros), "El alta con EIN no quedo auditada"

    def test_la_idempotencia_funciona_igual(self, admin, como_eeuu):
        admin.post("/api/clientes/", json={
            "cuit": "12-3456789", "nombre": "Idempotente LLC"})
        admin.post("/api/stock/", json={
            "codigo": 77030, "producto": "Cosa", "cantidad": 50,
            "preven": 10.0, "iva": 7.0, "unidad": "u"})
        cuerpo = {"cliente": "123456789", "fecha": "2026-08-19", "tipo": "A",
                  "items": [{"codigo": 77030, "cantidad": 1, "precio": 10.0}]}
        cab = {"X-Operation-Id": "us-idem-001"}

        primera = admin.post("/api/facturas/", json=cuerpo, headers=cab)
        segunda = admin.post("/api/facturas/", json=cuerpo, headers=cab)

        assert primera.status_code in (200, 201)
        # El reintento devuelve la respuesta guardada, no una factura nueva.
        assert segunda.headers.get("x-operacion-repetida") == "1"
