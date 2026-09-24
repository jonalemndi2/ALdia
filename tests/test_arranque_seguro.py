"""
test_arranque_seguro.py - Lo que una instalacion nueva expone antes de configurarse.

Tres agujeros de la auditoria de septiembre de 2026:

1. La clave inicial de admin era fija y publica ("admin123"). El cambio
   obligatorio no protegia nada: el primero que entraba la cambiaba y se quedaba
   con la cuenta.
2. GET /api/config/ respondia sin sesion con CUIT, domicilio y la ruta del
   certificado de AFIP.
3. Un login con la clave nueva en el mismo segundo del cambio recibia un token
   que nacia invalido.
"""
import os
import stat

import pytest


class TestClaveInicial:
    def test_sin_variable_es_aleatoria(self, app_cliente, monkeypatch):
        import main
        monkeypatch.delenv("ALDIA_ADMIN_PASSWORD", raising=False)
        claves = {main.clave_inicial_del_admin() for _ in range(5)}
        assert len(claves) == 5, "La clave inicial tiene que cambiar en cada instalación"
        assert "admin123" not in claves
        assert all(len(c) >= 12 for c in claves)

    def test_la_variable_de_entorno_manda(self, app_cliente, monkeypatch):
        import main
        monkeypatch.setenv("ALDIA_ADMIN_PASSWORD", "  elegida-por-el-instalador ")
        assert main.clave_inicial_del_admin() == "elegida-por-el-instalador"

    def test_queda_anotada_solo_para_el_dueno(self, app_cliente, monkeypatch, tmp_path, capsys):
        import main
        archivo = tmp_path / ".aldia_clave_inicial"
        monkeypatch.setattr(main, "ARCHIVO_CLAVE_INICIAL", str(archivo))
        monkeypatch.delenv("ALDIA_ADMIN_PASSWORD", raising=False)

        main.avisar_clave_inicial("clave-de-muestra")

        assert archivo.read_text(encoding="utf-8").strip() == "clave-de-muestra"
        assert "clave-de-muestra" in capsys.readouterr().err
        if os.name != "nt":
            assert stat.S_IMODE(archivo.stat().st_mode) == 0o600

    def test_con_variable_no_se_escribe_nada(self, app_cliente, monkeypatch, tmp_path):
        import main
        archivo = tmp_path / ".aldia_clave_inicial"
        monkeypatch.setattr(main, "ARCHIVO_CLAVE_INICIAL", str(archivo))
        monkeypatch.setenv("ALDIA_ADMIN_PASSWORD", "ya-la-conoce")

        main.avisar_clave_inicial("ya-la-conoce")

        assert not archivo.exists()

    def test_vive_al_lado_de_la_base_y_no_del_codigo(self, app_cliente):
        # Si viviera en backend/, cambiar la clave de admin en las pruebas
        # borraria el archivo de la instalacion real de quien las corre.
        from conftest import RUTA_DB
        from security import ARCHIVO_CLAVE_INICIAL
        assert os.path.dirname(ARCHIVO_CLAVE_INICIAL) == os.path.dirname(os.path.abspath(RUTA_DB))


class TestConfigExigeSesion:
    def test_anonimo_no_lee_la_configuracion(self, app_cliente, admin):
        r = app_cliente.get("/api/config/", headers={"Authorization": ""})
        assert r.status_code == 401, r.text

    def test_logueado_si(self, admin):
        r = admin.get("/api/config/")
        assert r.status_code == 200
        assert "negocio_nombre" in r.json()

    def test_pais_sigue_publico_para_la_pantalla_de_login(self, app_cliente):
        r = app_cliente.get("/api/config/pais", headers={"Authorization": ""})
        assert r.status_code == 200
        assert "codigo" in r.json()


_n = iter(range(1, 1000))


@pytest.fixture
def usuario_con_clave_cambiada(admin, app_cliente):
    nombre = f"reingreso{next(_n)}"
    provisoria, nueva = "provisoria-123", "definitiva-456"
    assert admin.post("/api/auth/register", json={
        "username": nombre, "password": provisoria, "rol": "auditor",
    }).status_code == 200
    token = app_cliente.post("/api/auth/login", json={
        "username": nombre, "password": provisoria,
    }, headers={"Authorization": ""}).json()["access_token"]
    cambio = app_cliente.post("/api/auth/cambiar-password", json={
        "password_actual": provisoria, "password_nueva": nueva,
    }, headers={"Authorization": f"Bearer {token}"})
    assert cambio.status_code == 200, cambio.text
    return nombre, nueva


class TestLoginInmediatoTrasElCambio:
    def test_el_token_del_login_sirve_en_el_acto(self, app_cliente, usuario_con_clave_cambiada):
        nombre, clave = usuario_con_clave_cambiada
        login = app_cliente.post("/api/auth/login", json={
            "username": nombre, "password": clave,
        }, headers={"Authorization": ""})
        assert login.status_code == 200
        me = app_cliente.get("/api/auth/me", headers={
            "Authorization": f"Bearer {login.json()['access_token']}",
        })
        assert me.status_code == 200, (
            "Un login con la clave nueva no puede devolver un token que ya nace "
            f"vencido: {me.text}"
        )
