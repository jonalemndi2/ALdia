"""
Codigos de error de maquina.

Lo que se prueba no es que el texto del mensaje sea lindo, sino el contrato con
el agente: que TODO error traiga `codigo` y `accion`, que el codigo sea el
preciso donde lo hay, y que `accion` diga lo correcto en los tres casos donde
equivocarse cuesta plata (reintentar un CAE ya emitido, no reintentar algo
transitorio, inventar una confirmacion).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from errores import ACCIONES, CATALOGO, ErrorDeNegocio, codigo_y_accion  # noqa: E402


class TestCatalogo:
    """El catalogo es un contrato publicado: tiene que ser coherente solo."""

    def test_toda_accion_es_una_de_las_cuatro(self):
        for codigo, (_estado, accion, _desc) in CATALOGO.items():
            assert accion in ACCIONES, f"{codigo} declara una accion inexistente"

    def test_todo_codigo_explica_para_que_sirve(self):
        # La descripcion se publica en GET /api/errores y es lo que un agente lee
        # para decidir. Una vacia deja al agente sin nada.
        for codigo, (_e, _a, desc) in CATALOGO.items():
            assert desc and len(desc) > 20, f"{codigo} no explica nada"

    def test_los_codigos_son_estables_en_mayusculas(self):
        for codigo in CATALOGO:
            assert codigo.isupper(), f"{codigo} deberia ir en MAYUSCULAS"
            assert " " not in codigo

    def test_un_codigo_inventado_falla_al_programar_no_en_produccion(self):
        # Que reviente aca y no que le llegue al agente un codigo que no existe.
        with pytest.raises(ValueError, match="desconocido"):
            ErrorDeNegocio("NO_EXISTE_ESTE_CODIGO", "lo que sea")

    def test_lo_que_nunca_hay_que_reintentar(self):
        """Reintentar estos duplica plata o declaraciones ante AFIP."""
        for codigo in ("CAE_YA_EMITIDO", "SIN_PERMISO", "SOLO_LECTURA",
                       "NO_PUEDE_ACTUAR_POR", "TIENE_MOVIMIENTOS"):
            assert CATALOGO[codigo][1] == "abortar", codigo

    def test_lo_que_si_conviene_reintentar(self):
        for codigo in ("OPERACION_EN_CURSO", "AFIP_NO_DISPONIBLE", "DEMASIADOS_INTENTOS"):
            assert CATALOGO[codigo][1] == "reintentar", codigo

    def test_lo_que_el_agente_no_puede_decidir_solo(self):
        # Inventar una confirmacion textual seria exactamente el error grave.
        for codigo in ("CONFIRMACION_REQUERIDA", "ACLARACION_REQUERIDA"):
            assert CATALOGO[codigo][1] == "preguntar", codigo


class TestDerivacionAutomatica:
    """Las 86 HTTPException que no declaran codigo igual tienen que traer uno."""

    def test_una_httpexception_comun_recibe_codigo_del_estado(self):
        from fastapi import HTTPException
        assert codigo_y_accion(HTTPException(404, "x")) == ("NO_ENCONTRADO", "corregir")
        assert codigo_y_accion(HTTPException(403, "x")) == ("SIN_PERMISO", "abortar")

    def test_un_estado_no_catalogado_igual_trae_accion(self):
        from fastapi import HTTPException
        codigo, accion = codigo_y_accion(HTTPException(418, "tetera"))
        assert codigo and accion in ACCIONES

    def test_el_error_de_negocio_gana_sobre_el_generico(self):
        exc = ErrorDeNegocio("STOCK_INSUFICIENTE", "faltan 3")
        assert codigo_y_accion(exc) == ("STOCK_INSUFICIENTE", "corregir")
        assert exc.status_code == 400  # el del catalogo


class TestEnLaApi:
    """Contra la aplicacion real, que es donde importa."""

    def test_el_catalogo_se_puede_leer_sin_autenticarse(self, app_cliente):
        # Un agente que recibe 401 tiene que poder averiguar que significa.
        r = app_cliente.get("/api/errores", headers={"Authorization": ""})
        assert r.status_code == 200
        datos = r.json()
        assert len(datos["errores"]) == len(CATALOGO)
        assert set(datos["acciones"]) == set(ACCIONES)

    def test_un_401_trae_codigo_y_accion(self, app_cliente):
        r = app_cliente.get("/api/clientes/", headers={"Authorization": ""})
        assert r.status_code == 401
        cuerpo = r.json()
        assert cuerpo["codigo"] == "NO_AUTENTICADO"
        assert cuerpo["accion"] == "abortar"
        # El mensaje para la persona sigue estando igual que siempre.
        assert cuerpo["detail"]

    def test_un_404_de_una_ruta_sin_migrar_igual_trae_codigo(self, admin):
        r = admin.get("/api/clientes/20999999990")
        assert r.status_code == 404
        assert r.json()["codigo"] == "NO_ENCONTRADO"

    def test_el_422_de_pydantic_trae_codigo(self, admin, cuit):
        # Es el error que mas pega un agente y lo genera el framework, antes de
        # entrar a la ruta: si no se engancha aparte, sale sin codigo.
        r = admin.post("/api/clientes/", json={"cuit": "no-es-un-cuit", "nombre": "X"})
        assert r.status_code == 422
        cuerpo = r.json()
        assert cuerpo["codigo"] == "DATOS_INVALIDOS"
        assert cuerpo["accion"] == "corregir"
        # El detalle estructurado se conserva: el agente necesita saber QUE campo.
        assert isinstance(cuerpo["detail"], list)

    def test_stock_insuficiente_dice_corregir(self, admin, cuit):
        c = cuit()
        admin.post("/api/clientes/", json={"cuit": c, "nombre": "Cliente Test"})
        admin.post("/api/stock/", json={
            "codigo": 90101, "producto": "Producto Test", "cantidad": 2,
            "preven": 100.0, "iva": 21.0, "unidad": "u",
        })
        r = admin.post("/api/facturas/", json={
            "cliente": c, "fecha": "2026-08-19", "tipo": "A",
            "items": [{"codigo": 90101, "cantidad": 50, "precio": 100.0}],
        })
        assert r.status_code == 400
        cuerpo = r.json()
        assert cuerpo["codigo"] == "STOCK_INSUFICIENTE"
        assert cuerpo["accion"] == "corregir"
        # Y el mensaje para la persona sigue diciendo cuanto hay.
        assert "2" in cuerpo["detail"]

    def test_no_se_puede_borrar_un_cliente_con_movimientos(self, admin, cuit):
        c = cuit()
        admin.post("/api/clientes/", json={"cuit": c, "nombre": "Con Movimientos"})
        admin.post("/api/stock/", json={
            "codigo": 90202, "producto": "Otro", "cantidad": 100,
            "preven": 10.0, "iva": 21.0, "unidad": "u",
        })
        admin.post("/api/facturas/", json={
            "cliente": c, "fecha": "2026-08-19", "tipo": "A",
            "items": [{"codigo": 90202, "cantidad": 1, "precio": 10.0}],
        })
        r = admin.delete(f"/api/clientes/{c}")
        assert r.status_code == 409
        cuerpo = r.json()
        assert cuerpo["codigo"] == "TIENE_MOVIMIENTOS"
        # Insistir no lo va a arreglar: es el dato que salva al agente de un bucle.
        assert cuerpo["accion"] == "abortar"

    def test_login_fallido_se_distingue_de_falta_de_token(self, app_cliente):
        """Para un agente no es lo mismo "no mandaste token" que "la clave esta mal".

        Los dos son 401 y los dos terminan en abortar, pero el primero se
        arregla autenticandose y el segundo no se arregla nunca reintentando:
        confundirlos es lo que produce el bucle de login infinito.
        """
        r = app_cliente.post("/api/auth/login",
                             json={"username": "admin", "password": "incorrecta"},
                             headers={"Authorization": ""})
        assert r.status_code == 401
        assert r.json()["codigo"] == "CREDENCIALES_INVALIDAS"

        sin_token = app_cliente.get("/api/clientes/", headers={"Authorization": ""})
        assert sin_token.json()["codigo"] == "NO_AUTENTICADO"

    def test_sin_permiso_dice_abortar(self, admin, app_cliente):
        """Insistir contra un 403 de rol no lo va a arreglar nunca."""
        prov, defi = "clave-provisoria-err", "clave-definitiva-err"
        admin.post("/api/auth/register",
                   json={"username": "deposito_err", "password": prov,
                         "rol": "encargado_deposito"})
        tok = app_cliente.post("/api/auth/login",
                               json={"username": "deposito_err", "password": prov},
                               headers={"Authorization": ""}).json()["access_token"]
        tok = app_cliente.post("/api/auth/cambiar-password",
                               json={"password_actual": prov, "password_nueva": defi},
                               headers={"Authorization": f"Bearer {tok}"}).json()["access_token"]

        r = app_cliente.get("/api/caja/", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 403
        cuerpo = r.json()
        assert cuerpo["codigo"] == "SIN_PERMISO"
        assert cuerpo["accion"] == "abortar"
