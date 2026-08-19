"""
test_pendientes.py - Operaciones que esperan una aclaracion.

El flujo que habilita: el agente arma un cobro, el sistema encuentra dos
clientes con el mismo nombre y deja la operacion pendiente con los candidatos.
El usuario elige, el agente confirma, y se ejecuta la MISMA operacion — sin que
el agente tenga que reconstruirla y sin riesgo de que cambie algo por el camino.
"""
import itertools

import pytest

_n = itertools.count(1)


@pytest.fixture
def cliente(admin, cuit):
    c = cuit("30")
    admin.post("/api/clientes/", json={"cuit": c, "nombre": f"Cliente {next(_n)}"})
    return c


def _saldo(admin, c):
    return admin.get(f"/api/clientes/{c}").json()["saldo"]


def _crear_pendiente(admin, cuerpo, **extra):
    datos = {
        "metodo": "POST",
        "ruta": "/api/caja/",
        "cuerpo": cuerpo,
        "motivo": "AMBIGUEDAD",
        "descripcion": "Hay dos clientes que coinciden",
        "candidatos": [{"cuit": "1", "nombre": "Uno"}, {"cuit": "2", "nombre": "Dos"}],
        "campo": "cliente",
    }
    datos.update(extra)
    return admin.post("/api/pendientes/", json=datos)


class TestFlujoCompleto:
    def test_se_guarda_y_se_confirma(self, admin, cliente):
        """El caso que motiva todo: elegir un dato y ejecutar lo ya descripto."""
        # El agente deja la operación trabada, SIN el cliente resuelto.
        r = _crear_pendiente(
            admin,
            cuerpo={"cliente": "", "monto": 500, "fecha": "2026-08-19", "tipo": "efectivo"},
            ruta="/api/cobros/",
        )
        assert r.status_code == 200, r.text
        pendiente = r.json()
        assert pendiente["estado"] == "pendiente"
        assert pendiente["campo_a_corregir"] == "cliente"
        assert len(pendiente["candidatos"]) == 2

        antes = _saldo(admin, cliente)

        # El usuario eligió: se confirma indicando SOLO el dato que faltaba.
        r = admin.post(f"/api/pendientes/{pendiente['id']}/confirmar",
                       json={"correcciones": {"cliente": cliente}})
        assert r.status_code == 200, r.text
        assert r.json()["estado"] == "confirmada"

        # Y la operación ocurrió de verdad.
        assert _saldo(admin, cliente) == antes - 500

    def test_las_correcciones_no_pisan_el_resto(self, admin, cliente):
        """Corregir un campo no debe alterar los demás: ese es el punto."""
        r = _crear_pendiente(
            admin,
            cuerpo={"cliente": "", "monto": 1234.56, "fecha": "2026-08-19",
                    "tipo": "efectivo", "referencia": "REC-001"},
            ruta="/api/cobros/",
        )
        pid = r.json()["id"]
        admin.post(f"/api/pendientes/{pid}/confirmar",
                   json={"correcciones": {"cliente": cliente}})

        cobros = admin.get("/api/cobros/", params={"cliente": cliente}).json()
        assert cobros[0]["monto"] == 1234.56
        assert cobros[0]["referencia"] == "REC-001"

    def test_se_puede_cancelar(self, admin, cliente):
        r = _crear_pendiente(admin, cuerpo={"fecha": "2026-08-19", "debe": 100})
        pid = r.json()["id"]
        assert admin.post(f"/api/pendientes/{pid}/cancelar").json()["estado"] == "cancelada"
        # Y ya no se puede ejecutar.
        assert admin.post(f"/api/pendientes/{pid}/confirmar",
                          json={"correcciones": {}}).status_code == 409


class TestNoSeEjecutaDosVeces:
    def test_confirmar_dos_veces_se_rechaza(self, admin, cliente):
        r = _crear_pendiente(
            admin,
            cuerpo={"cliente": cliente, "monto": 100, "fecha": "2026-08-19",
                    "tipo": "efectivo"},
            ruta="/api/cobros/",
        )
        pid = r.json()["id"]
        antes = _saldo(admin, cliente)

        assert admin.post(f"/api/pendientes/{pid}/confirmar",
                          json={"correcciones": {}}).status_code == 200
        assert admin.post(f"/api/pendientes/{pid}/confirmar",
                          json={"correcciones": {}}).status_code == 409

        assert _saldo(admin, cliente) == antes - 100, "Se ejecutó dos veces"


class TestValidaciones:
    def test_una_operacion_rechazada_lo_informa(self, admin):
        """Confirmar no saltea las validaciones: se reejecuta la operación real."""
        r = _crear_pendiente(
            admin,
            cuerpo={"cliente": "20123456786", "monto": 100, "fecha": "2026-08-19",
                    "tipo": "efectivo"},   # cliente inexistente
            ruta="/api/cobros/",
        )
        pid = r.json()["id"]
        resp = admin.post(f"/api/pendientes/{pid}/confirmar", json={"correcciones": {}})
        assert resp.status_code == 404

    def test_no_puede_apuntar_a_si_mismo(self, admin):
        """Sin esto, confirmar dispararía una cadena de confirmaciones."""
        r = _crear_pendiente(admin, cuerpo={}, ruta="/api/pendientes/")
        assert r.status_code == 400

    def test_ruta_fuera_de_la_api_se_rechaza(self, admin):
        assert _crear_pendiente(admin, cuerpo={}, ruta="/etc/passwd").status_code == 400

    def test_metodo_de_lectura_no_tiene_sentido(self, admin):
        assert _crear_pendiente(admin, cuerpo={}, metodo="GET").status_code == 400

    def test_una_pendiente_ajena_no_se_puede_confirmar(self, admin, app_cliente):
        """Lleva la conformidad de una persona concreta sobre algo concreto."""
        prov, defi = "clave-provisoria-pend", "clave-definitiva-pend"
        admin.post("/api/auth/register",
                   json={"username": "otro_usuario", "password": prov, "rol": "caja"})
        tok = app_cliente.post("/api/auth/login",
                               json={"username": "otro_usuario", "password": prov},
                               headers={"Authorization": ""}).json()["access_token"]
        # Cambiar la contrasena invalida los tokens anteriores: se usa el nuevo.
        tok = app_cliente.post("/api/auth/cambiar-password",
                               json={"password_actual": prov, "password_nueva": defi},
                               headers={"Authorization": f"Bearer {tok}"}).json()["access_token"]

        # La crea "otro_usuario"...
        r = app_cliente.post("/api/pendientes/",
                             json={"metodo": "POST", "ruta": "/api/caja/",
                                   "cuerpo": {"fecha": "2026-08-19", "debe": 50}},
                             headers={"Authorization": f"Bearer {tok}"})
        pid = r.json()["id"]

        # ...y otro usuario de rol caja no debería poder confirmarla.
        # (admin sí puede, por eso se prueba con un tercero)
        admin.post("/api/auth/register",
                   json={"username": "tercero", "password": prov, "rol": "caja"})
        tok3 = app_cliente.post("/api/auth/login",
                                json={"username": "tercero", "password": prov},
                                headers={"Authorization": ""}).json()["access_token"]
        tok3 = app_cliente.post("/api/auth/cambiar-password",
                                json={"password_actual": prov, "password_nueva": defi},
                                headers={"Authorization": f"Bearer {tok3}"}).json()["access_token"]
        resp = app_cliente.post(f"/api/pendientes/{pid}/confirmar",
                                json={"correcciones": {}},
                                headers={"Authorization": f"Bearer {tok3}"})
        assert resp.status_code == 403


class TestMezclaDeCorrecciones:
    def test_mezcla_profunda(self):
        from pendientes import aplicar_correcciones
        original = {"cliente": "", "items": [1], "extra": {"a": 1, "b": 2}}
        resultado = aplicar_correcciones(original, {"cliente": "X", "extra": {"b": 9}})
        assert resultado["cliente"] == "X"
        assert resultado["items"] == [1]          # no se tocó
        assert resultado["extra"] == {"a": 1, "b": 9}   # 'a' sobrevivió
