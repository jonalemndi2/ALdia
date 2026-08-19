"""
test_origen_agentes.py - Trazabilidad multicanal.

ALdia se opera por varios caminos: el navegador, un asistente propio, un canal
de consulta por WhatsApp o Telegram. Sin registrar el origen, todo lo que entra
por un agente queda como la cuenta con la que ese agente se autentica, y el
registro de auditoria pierde su valor justo cuando el agente pasa a ser el canal
principal.

La propiedad de seguridad que se verifica aca: las cabeceras de origen sirven
para ATRIBUIR, nunca para AUTORIZAR.
"""
import pytest


def _ultima_fila(admin):
    r = admin.get("/api/auditoria/?por_pagina=1")
    assert r.status_code == 200
    filas = r.json()["filas"]
    assert filas, "El registro de auditoria quedo vacio"
    return filas[0]


class TestOrigen:
    def test_la_web_queda_como_persona(self, admin):
        admin.post("/api/caja/", json={"fecha": "2026-08-18", "debe": 100,
                                       "descripcion": "desde la web"})
        fila = _ultima_fila(admin)
        assert fila["actor_tipo"] == "persona"
        assert fila["canal"] == "web"
        assert fila["solicitante"] == ""

    def test_un_agente_queda_identificado(self, admin):
        """Misma cuenta, distinto canal: el registro los distingue."""
        admin.post("/api/caja/",
                   json={"fecha": "2026-08-18", "debe": 200, "descripcion": "por whatsapp"},
                   headers={"X-ALdia-Canal": "whatsapp",
                            "X-ALdia-Agente": "bot-consulta",
                            "X-ALdia-Solicitante": "+5493411234567"})
        fila = _ultima_fila(admin)
        assert fila["actor_tipo"] == "agente"
        assert fila["canal"] == "whatsapp"
        assert fila["agente"] == "bot-consulta"
        assert fila["solicitante"] == "+5493411234567"

    def test_se_puede_filtrar_por_canal(self, admin):
        admin.post("/api/caja/",
                   json={"fecha": "2026-08-18", "debe": 300, "descripcion": "por telegram"},
                   headers={"X-ALdia-Canal": "telegram", "X-ALdia-Solicitante": "99887766"})
        r = admin.get("/api/auditoria/?canal=telegram")
        assert r.status_code == 200
        filas = r.json()["filas"]
        assert filas and all(f["canal"] == "telegram" for f in filas)

    def test_se_puede_filtrar_por_solicitante(self, admin):
        """Responder '¿qué pidió este número?' es el objetivo de todo esto."""
        numero = "+5493419998887"
        admin.post("/api/caja/",
                   json={"fecha": "2026-08-18", "debe": 400, "descripcion": "de ese numero"},
                   headers={"X-ALdia-Canal": "whatsapp", "X-ALdia-Solicitante": numero})
        # El '+' hay que codificarlo: en una query string significa espacio.
        r = admin.get("/api/auditoria/", params={"solicitante": numero})
        assert r.status_code == 200
        filas = r.json()["filas"]
        assert filas and all(f["solicitante"] == numero for f in filas)


class TestLasCabecerasNoAutorizan:
    """Lo esencial: declarar un origen no cambia lo que se puede hacer."""

    # Scope de clase: el usuario se crea UNA vez. Con scope de funcion, la
    # segunda prueba intenta registrar el mismo nombre y falla por duplicado.
    @pytest.fixture(scope="class")
    def token_consulta(self, admin, app_cliente):
        """Un canal de consulta: rol auditor, lee todo y no escribe nada."""
        provisoria, definitiva = "clave-provisoria-bot", "clave-definitiva-bot"
        admin.post("/api/auth/register",
                   json={"username": "bot_consulta", "password": provisoria,
                         "rol": "auditor"})
        r = app_cliente.post("/api/auth/login",
                             json={"username": "bot_consulta", "password": provisoria},
                             headers={"Authorization": ""})
        token = r.json()["access_token"]
        app_cliente.post("/api/auth/cambiar-password",
                         json={"password_actual": provisoria, "password_nueva": definitiva},
                         headers={"Authorization": f"Bearer {token}"})
        return token

    def test_el_canal_de_consulta_lee(self, app_cliente, token_consulta):
        r = app_cliente.get("/api/caja/",
                            headers={"Authorization": f"Bearer {token_consulta}",
                                     "X-ALdia-Canal": "whatsapp"})
        assert r.status_code == 200

    def test_el_canal_de_consulta_no_escribe(self, app_cliente, token_consulta):
        r = app_cliente.post("/api/caja/", json={"fecha": "2026-08-18", "debe": 500},
                             headers={"Authorization": f"Bearer {token_consulta}",
                                      "X-ALdia-Canal": "whatsapp"})
        assert r.status_code == 403

    def test_falsear_el_origen_no_da_permisos(self, app_cliente, token_consulta):
        """Decir que la pide el dueño no convierte al bot en el dueño."""
        r = app_cliente.post("/api/caja/", json={"fecha": "2026-08-18", "debe": 500},
                             headers={"Authorization": f"Bearer {token_consulta}",
                                      "X-ALdia-Canal": "web",
                                      "X-ALdia-Solicitante": "admin",
                                      "X-ALdia-Agente": ""})
        assert r.status_code == 403, (
            "Una cabecera de atribución otorgó permisos: la identidad tiene que "
            "salir del token, no de lo que declare quien llama."
        )

    def test_el_intento_rechazado_tambien_queda_registrado(self, app_cliente, token_consulta, admin):
        app_cliente.post("/api/caja/", json={"fecha": "2026-08-18", "debe": 600},
                         headers={"Authorization": f"Bearer {token_consulta}",
                                  "X-ALdia-Canal": "whatsapp",
                                  "X-ALdia-Solicitante": "+5490000000"})
        r = admin.get("/api/auditoria/?resultado=rechazado&canal=whatsapp")
        assert r.status_code == 200
        filas = r.json()["filas"]
        assert filas, "No quedó registrado el intento rechazado del canal de consulta"
        assert filas[0]["solicitante"] == "+5490000000"
