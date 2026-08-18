"""
test_seguridad.py - Autenticacion, autorizacion por rol y validacion fiscal.

Estas pruebas cubren los agujeros que tuvo el sistema y que no deben volver:
endpoints sin autenticacion, roles que solo se ocultaban en el menu, y datos
fiscales invalidos que se guardaban igual.
"""
import pytest

RUTAS_DE_DATOS = [
    "/api/clientes/", "/api/proveedores/", "/api/stock/", "/api/remitos/",
    "/api/facturas/", "/api/cobros/", "/api/pagos/", "/api/caja/", "/api/gastos/",
]


class TestAutenticacion:
    @pytest.mark.parametrize("ruta", RUTAS_DE_DATOS)
    def test_sin_token_no_se_lee(self, app_cliente, ruta):
        r = app_cliente.get(ruta, headers={"Authorization": ""})
        assert r.status_code == 401, f"{ruta} respondio {r.status_code} sin token"

    def test_sin_token_no_se_escribe(self, app_cliente):
        r = app_cliente.post("/api/clientes/",
                             json={"cuit": "20123456786", "nombre": "Anonimo"},
                             headers={"Authorization": ""})
        assert r.status_code == 401

    def test_sin_token_no_se_borra(self, app_cliente):
        r = app_cliente.delete("/api/caja/1", headers={"Authorization": ""})
        assert r.status_code == 401

    def test_reset_db_exige_administrador(self, app_cliente):
        """Esta ruta llego a borrar toda la base sin pedir nada."""
        r = app_cliente.post("/api/admin/reset-db", headers={"Authorization": ""})
        assert r.status_code == 401

    def test_token_forjado_se_rechaza(self, app_cliente):
        """Con la clave vieja hardcodeada cualquiera se hacia administrador."""
        import jwt
        from datetime import datetime, timedelta
        forjado = jwt.encode(
            {"sub": "admin", "exp": datetime.utcnow() + timedelta(hours=1)},
            "aldia-secret-key-2024-cambiar-en-produccion", algorithm="HS256")
        r = app_cliente.get("/api/auth/usuarios",
                            headers={"Authorization": f"Bearer {forjado}"})
        assert r.status_code == 401

    def test_login_incorrecto(self, app_cliente):
        r = app_cliente.post("/api/auth/login",
                             json={"username": "admin", "password": "no-es"})
        assert r.status_code == 401


class TestAutorizacionPorRol:
    @pytest.fixture(scope="class")
    def token_caja(self, admin):
        admin.post("/api/auth/register",
                   json={"username": "caja_test", "password": "clave-de-prueba-1",
                         "rol": "caja"})
        r = admin.post("/api/auth/login",
                       json={"username": "caja_test", "password": "clave-de-prueba-1"})
        assert r.status_code == 200
        return r.json()["access_token"]

    @pytest.fixture(scope="class")
    def token_auditor(self, admin):
        admin.post("/api/auth/register",
                   json={"username": "auditor_test", "password": "clave-de-prueba-2",
                         "rol": "auditor"})
        r = admin.post("/api/auth/login",
                       json={"username": "auditor_test", "password": "clave-de-prueba-2"})
        assert r.status_code == 200
        return r.json()["access_token"]

    def test_caja_no_escribe_en_stock(self, app_cliente, token_caja):
        r = app_cliente.post("/api/stock/",
                             json={"codigo": 999001, "producto": "Intruso"},
                             headers={"Authorization": f"Bearer {token_caja}"})
        assert r.status_code == 403

    def test_caja_no_emite_facturas(self, app_cliente, token_caja, cuit):
        r = app_cliente.post("/api/facturas/",
                             json={"cuit": cuit(), "fecha": "2026-08-18", "total": 100},
                             headers={"Authorization": f"Bearer {token_caja}"})
        assert r.status_code == 403

    def test_caja_si_accede_a_lo_suyo(self, app_cliente, token_caja):
        cabeceras = {"Authorization": f"Bearer {token_caja}"}
        assert app_cliente.get("/api/caja/", headers=cabeceras).status_code == 200
        assert app_cliente.get("/api/clientes/", headers=cabeceras).status_code == 200

    def test_auditor_lee_todo(self, app_cliente, token_auditor):
        cabeceras = {"Authorization": f"Bearer {token_auditor}"}
        assert app_cliente.get("/api/stock/", headers=cabeceras).status_code == 200
        assert app_cliente.get("/api/facturas/", headers=cabeceras).status_code == 200

    def test_auditor_no_modifica_nada(self, app_cliente, token_auditor):
        r = app_cliente.post("/api/stock/",
                             json={"codigo": 999002, "producto": "X"},
                             headers={"Authorization": f"Bearer {token_auditor}"})
        assert r.status_code == 403

    def test_caja_no_administra_usuarios(self, app_cliente, token_caja):
        r = app_cliente.get("/api/auth/usuarios",
                            headers={"Authorization": f"Bearer {token_caja}"})
        assert r.status_code == 403


class TestValidacionFiscal:
    @pytest.mark.parametrize("cuit_malo,motivo", [
        ("", "vacio"),
        ("XX", "no numerico"),
        ("2012345678", "10 digitos"),
        ("20-12345678-0", "digito verificador incorrecto"),
    ])
    def test_cuit_invalido_se_rechaza(self, admin, cuit_malo, motivo):
        r = admin.post("/api/clientes/", json={"cuit": cuit_malo, "nombre": "X"})
        assert r.status_code == 422, f"Acepto un CUIT {motivo}: {cuit_malo}"

    def test_cuit_valido_se_acepta(self, admin, cuit):
        r = admin.post("/api/clientes/", json={"cuit": cuit(), "nombre": "Cliente Real"})
        assert r.status_code == 200

    def test_nombre_vacio_se_rechaza(self, admin, cuit):
        r = admin.post("/api/clientes/", json={"cuit": cuit(), "nombre": ""})
        assert r.status_code == 422

    def test_precio_negativo_se_rechaza(self, admin):
        r = admin.post("/api/stock/",
                       json={"codigo": 999010, "producto": "X", "preven": -5})
        assert r.status_code == 422

    @pytest.mark.parametrize("alicuota", [999, 15, 7.5, -21])
    def test_alicuota_invalida_se_rechaza(self, admin, alicuota):
        r = admin.post("/api/stock/",
                       json={"codigo": 999011, "producto": "X", "iva": alicuota})
        assert r.status_code == 422

    @pytest.mark.parametrize("alicuota", [0, 2.5, 5, 10.5, 21, 27])
    def test_alicuotas_vigentes_se_aceptan(self, admin, alicuota):
        codigo = 990000 + int(alicuota * 10)
        r = admin.post("/api/stock/",
                       json={"codigo": codigo, "producto": f"Art {alicuota}",
                             "iva": alicuota})
        assert r.status_code == 200

    def test_caja_en_negativo_se_rechaza(self, admin):
        r = admin.post("/api/caja/",
                       json={"fecha": "2026-08-18", "debe": -999999})
        assert r.status_code == 422

    def test_movimiento_de_caja_sin_importe_se_rechaza(self, admin):
        r = admin.post("/api/caja/", json={"fecha": "2026-08-18"})
        assert r.status_code == 422
