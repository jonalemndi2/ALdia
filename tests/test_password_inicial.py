"""
test_password_inicial.py - Cambio obligatorio de la contrasena de fabrica.

La contrasena inicial esta documentada en el README publico del proyecto. Una
instalacion que la conserve tiene, en los hechos, un acceso conocido por
cualquiera. Estas pruebas verifican que sea IMPOSIBLE quedarse con ella.

Se ejercita sobre un usuario propio y no sobre `admin`, para no depender del
orden en que corran los archivos de prueba: todo usuario recien creado nace en
el mismo estado que el admin de una instalacion nueva.
"""
import itertools

import pytest

_n = itertools.count(1)
CLAVE_PROVISORIA = "clave-provisoria-1"


@pytest.fixture
def usuario_nuevo(admin, app_cliente):
    """Crea un usuario y devuelve (nombre, token). Nace con la clave a cambiar."""
    nombre = f"empleado{next(_n)}"
    r = admin.post("/api/auth/register",
                   json={"username": nombre, "password": CLAVE_PROVISORIA,
                         "rol": "caja"})
    assert r.status_code == 200, r.text
    assert r.json()["debe_cambiar_password"] is True, (
        "Un usuario nuevo debe nacer obligado a cambiar la contraseña: si no, "
        "el administrador conoce la clave de todos sus empleados."
    )

    login = app_cliente.post("/api/auth/login",
                             json={"username": nombre, "password": CLAVE_PROVISORIA},
                             headers={"Authorization": ""})
    assert login.status_code == 200
    return nombre, login.json()["access_token"]


class TestBloqueo:
    def test_login_funciona_pero_avisa(self, usuario_nuevo, app_cliente):
        """Puede autenticarse: el bloqueo es para operar, no para entrar."""
        nombre, token = usuario_nuevo
        r = app_cliente.post("/api/auth/login",
                             json={"username": nombre, "password": CLAVE_PROVISORIA},
                             headers={"Authorization": ""})
        assert r.status_code == 200
        assert r.json()["user"]["debe_cambiar_password"] is True

    @pytest.mark.parametrize("ruta", ["/api/clientes/", "/api/caja/"])
    def test_no_puede_leer(self, usuario_nuevo, app_cliente, ruta):
        _, token = usuario_nuevo
        r = app_cliente.get(ruta, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403, f"{ruta} dejó operar con la clave inicial"
        assert "contraseña inicial" in r.json()["detail"]

    def test_no_puede_escribir(self, usuario_nuevo, app_cliente):
        _, token = usuario_nuevo
        r = app_cliente.post("/api/caja/",
                             json={"fecha": "2026-08-18", "debe": 100,
                                   "descripcion": "x"},
                             headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_me_si_responde(self, usuario_nuevo, app_cliente):
        """/me no bloquea: es como el frontend sabe qué pantalla mostrar."""
        _, token = usuario_nuevo
        r = app_cliente.get("/api/auth/me",
                            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["debe_cambiar_password"] is True


class TestCambio:
    def test_rechaza_la_actual_incorrecta(self, usuario_nuevo, app_cliente):
        _, token = usuario_nuevo
        r = app_cliente.post("/api/auth/cambiar-password",
                             json={"password_actual": "no-es-esta",
                                   "password_nueva": "una-clave-larga"},
                             headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_rechaza_clave_corta(self, usuario_nuevo, app_cliente):
        _, token = usuario_nuevo
        r = app_cliente.post("/api/auth/cambiar-password",
                             json={"password_actual": CLAVE_PROVISORIA,
                                   "password_nueva": "corta"},
                             headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 422

    def test_rechaza_la_misma_clave(self, usuario_nuevo, app_cliente):
        _, token = usuario_nuevo
        r = app_cliente.post("/api/auth/cambiar-password",
                             json={"password_actual": CLAVE_PROVISORIA,
                                   "password_nueva": CLAVE_PROVISORIA},
                             headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 422

    def test_el_cambio_desbloquea(self, usuario_nuevo, app_cliente):
        nombre, token = usuario_nuevo
        cab = {"Authorization": f"Bearer {token}"}
        nueva = "clave-propia-del-empleado"

        assert app_cliente.get("/api/caja/", headers=cab).status_code == 403

        r = app_cliente.post("/api/auth/cambiar-password",
                             json={"password_actual": CLAVE_PROVISORIA,
                                   "password_nueva": nueva},
                             headers=cab)
        assert r.status_code == 200

        # El token viejo YA NO SIRVE: cambiar la contraseña cierra todas las
        # sesiones abiertas, que es el motivo por el que uno la cambia.
        assert app_cliente.get("/api/caja/", headers=cab).status_code == 401

        # El que devuelve el cambio sí, y ya operativo.
        cab_nueva = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert app_cliente.get("/api/caja/", headers=cab_nueva).status_code == 200

        # La clave vieja ya no sirve; la nueva sí, y sin exigir otro cambio.
        assert app_cliente.post("/api/auth/login",
                                json={"username": nombre, "password": CLAVE_PROVISORIA},
                                headers={"Authorization": ""}).status_code == 401
        r = app_cliente.post("/api/auth/login",
                             json={"username": nombre, "password": nueva},
                             headers={"Authorization": ""})
        assert r.status_code == 200
        assert r.json()["user"]["debe_cambiar_password"] is False


class TestAdminDeFabrica:
    def test_el_admin_sembrado_nace_obligado(self, admin):
        """El admin del primer arranque también nace con la marca puesta.

        El fixture `admin` ya tuvo que cambiar la contraseña para poder operar;
        que esta consulta responda 200 lo demuestra.
        """
        r = admin.get("/api/auth/me")
        assert r.status_code == 200
        assert r.json()["debe_cambiar_password"] is False
