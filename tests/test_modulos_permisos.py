"""
Módulos activables por instalación: permisos por módulo para el servidor MCP,
módulos que nacen apagados y ALDIA_MODULOS como única fuente cuando está definida.
"""
from datetime import timedelta

import pytest

from database import SessionLocal
from models import Modulo, Usuario
from routers.auth import create_access_token, hash_password
from routers.modulos import (
    MODULO_ADMIN_POR_CHAT,
    MODULOS_DEFAULT,
    aplicar_modulos_del_entorno,
)


def _token(rol: str, username: str) -> dict:
    with SessionLocal() as db:
        u = db.query(Usuario).filter(Usuario.username == username).first()
        if not u:
            u = Usuario(
                username=username,
                password_hash=hash_password("ClaveSegura123!"),
                rol=rol,
                debe_cambiar_password=False,
            )
            db.add(u)
            db.commit()
        token = create_access_token({"sub": username, "rol": rol}, timedelta(minutes=60))
    return {"Authorization": f"Bearer {token}"}


def _estado_modulos() -> dict[str, bool]:
    with SessionLocal() as db:
        return {m.clave: bool(m.habilitado) for m in db.query(Modulo).all()}


def _restaurar(estado: dict[str, bool]) -> None:
    with SessionLocal() as db:
        for m in db.query(Modulo).all():
            if m.clave in estado:
                m.habilitado = estado[m.clave]
        db.commit()


def _por_clave(respuesta) -> dict[str, dict]:
    return {m["clave"]: m for m in respuesta.json()["modulos"]}


class TestCatalogoPorDefecto:
    def test_los_verticales_y_la_administracion_por_chat_nacen_apagados(self):
        por_defecto = {m["clave"]: m["habilitado"] for m in MODULOS_DEFAULT}
        assert por_defecto["liquidaciones_granos"] is False
        assert por_defecto["liquidaciones_hacienda"] is False
        assert por_defecto[MODULO_ADMIN_POR_CHAT] is False
        assert por_defecto["ventas"] is True


class TestPermisosParaElMcp:
    def test_admin_lee_y_escribe_solo_en_los_modulos_prendidos(self, admin):
        estado = _estado_modulos()
        try:
            _restaurar({**estado, "iva": False})
            r = admin.get("/api/modulos/permisos")
            assert r.status_code == 200, r.text
            permisos = _por_clave(r)
            assert permisos["ventas"] == {**permisos["ventas"], "habilitado": True,
                                          "lectura": True, "escritura": True}
            assert permisos["iva"]["lectura"] is False
            assert permisos["iva"]["escritura"] is False
            assert r.json()["auditoria"] is True
        finally:
            _restaurar(estado)

    def test_el_agente_lee_como_auditor_y_escribe_solo_donde_lo_nombran(self, admin):
        agente = _token("agente", "agente_permisos_test")
        with SessionLocal() as db:
            ventas = db.query(Modulo).filter(Modulo.clave == "ventas").one()
            roles_antes = ventas.roles
        try:
            permisos = _por_clave(admin.get("/api/modulos/permisos", headers=agente))
            assert permisos["ventas"]["lectura"] is True
            assert permisos["ventas"]["escritura"] is False
            # Administración solo la ve el rol administrador.
            assert permisos["administracion"]["lectura"] is False

            r = admin.put("/api/modulos/ventas", json={"roles": roles_antes + ",agente"})
            assert r.status_code == 200, r.text
            permisos = _por_clave(admin.get("/api/modulos/permisos", headers=agente))
            assert permisos["ventas"]["escritura"] is True
            assert admin.get("/api/modulos/permisos", headers=agente).json()["auditoria"] is False
        finally:
            admin.put("/api/modulos/ventas", json={"roles": roles_antes})

    def test_responde_lo_mismo_que_el_control_real(self, admin):
        """Si /permisos dice que no, la ruta tiene que rechazar, y al reves."""
        agente = _token("agente", "agente_contrato_test")
        permisos = _por_clave(admin.get("/api/modulos/permisos", headers=agente))
        lectura = admin.get("/api/clientes/", headers=agente)
        assert (lectura.status_code == 200) is permisos["clientes"]["lectura"]
        escritura = admin.post("/api/clientes/", headers=agente,
                               json={"cuit": "20111111112", "nombre": "No deberia"})
        assert (escritura.status_code != 403) is permisos["clientes"]["escritura"]


class TestPerfiles:
    def test_aplicar_un_perfil_no_toca_la_administracion_por_chat(self, admin):
        estado = _estado_modulos()
        try:
            _restaurar({**estado, MODULO_ADMIN_POR_CHAT: True})
            r = admin.post("/api/modulos/perfiles/comercio")
            assert r.status_code == 200, r.text
            assert MODULO_ADMIN_POR_CHAT not in r.json()["modulos_deshabilitados"]
            assert _estado_modulos()[MODULO_ADMIN_POR_CHAT] is True
        finally:
            _restaurar(estado)


class TestAldiaModulos:
    def test_la_variable_fija_los_modulos_en_el_arranque(self, monkeypatch):
        estado = _estado_modulos()
        monkeypatch.setenv("ALDIA_MODULOS", "servicios, liquidaciones_granos, inventado")
        try:
            with SessionLocal() as db:
                aplicar_modulos_del_entorno(db)
            ahora = _estado_modulos()
            assert ahora["liquidaciones_granos"] is True
            assert ahora["ventas"] is True
            assert ahora["administracion"] is True
            assert ahora["stock"] is False            # servicios no lleva stock
            assert ahora["liquidaciones_hacienda"] is False
            assert ahora[MODULO_ADMIN_POR_CHAT] is False
        finally:
            _restaurar(estado)

    def test_avisa_las_claves_que_no_reconoce(self, monkeypatch, capsys):
        estado = _estado_modulos()
        monkeypatch.setenv("ALDIA_MODULOS", "comercio,inventado")
        try:
            with SessionLocal() as db:
                aplicar_modulos_del_entorno(db)
            assert "inventado" in capsys.readouterr().err
        finally:
            _restaurar(estado)

    def test_sin_la_variable_no_toca_nada(self, monkeypatch):
        estado = _estado_modulos()
        monkeypatch.delenv("ALDIA_MODULOS", raising=False)
        with SessionLocal() as db:
            aplicar_modulos_del_entorno(db)
        assert _estado_modulos() == estado

    @pytest.mark.parametrize("pedido", ["prender_modulo", "aplicar_perfil"])
    def test_con_la_variable_el_panel_no_puede_cambiarlos(self, admin, monkeypatch, pedido):
        monkeypatch.setenv("ALDIA_MODULOS", "comercio")
        estado = _estado_modulos()
        try:
            if pedido == "prender_modulo":
                r = admin.put("/api/modulos/iva", json={"habilitado": not estado["iva"]})
            else:
                r = admin.post("/api/modulos/perfiles/servicios")
            assert r.status_code == 409, r.text
            assert r.json()["codigo"] == "MODULOS_FIJADOS_POR_ENTORNO"
            assert _estado_modulos() == estado
            assert admin.get("/api/modulos/permisos").json()["fijados_por_entorno"] is True
        finally:
            _restaurar(estado)

    def test_con_la_variable_los_roles_se_siguen_editando(self, admin, monkeypatch):
        monkeypatch.setenv("ALDIA_MODULOS", "comercio")
        with SessionLocal() as db:
            iva = db.query(Modulo).filter(Modulo.clave == "iva").one()
            habilitado, roles = bool(iva.habilitado), iva.roles
        try:
            # El panel manda `habilitado` siempre, aunque no cambie.
            r = admin.put("/api/modulos/iva", json={"habilitado": habilitado,
                                                     "roles": roles + ",caja"})
            assert r.status_code == 200, r.text
            assert "caja" in r.json()["roles"]
        finally:
            admin.put("/api/modulos/iva", json={"roles": roles})
