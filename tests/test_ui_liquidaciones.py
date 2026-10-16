"""Contratos estáticos del frontend SPA para Liquidaciones Agropecuarias y Perfiles de Negocio."""
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_api_js_expone_liquidaciones_y_perfiles_modulos():
    fuente = (ROOT / "Web/js/api.js").read_text(encoding="utf-8")
    assert "getPerfiles" in fuente
    assert "/modulos/perfiles" in fuente
    assert "aplicarPerfil" in fuente
    assert "liquidaciones:" in fuente
    for metodo in ("getAll", "getOne", "create", "confirmar", "registrarCoe", "anular"):
        assert metodo in fuente, f"Falta método {metodo} en API.liquidaciones"


def test_modulo_liquidaciones_cumple_csp_y_acciones_declarativas():
    fuente = (ROOT / "Web/js/modules/liquidaciones.js").read_text(encoding="utf-8")
    assert "const Liquidaciones =" in fuente
    assert "window.Liquidaciones = Liquidaciones" in fuente

    for metodo in (
        "showGranos",
        "showHacienda",
        "crearNueva",
        "guardar",
        "verDetalle",
        "confirmarBorrador",
        "anular",
        "agregarDeduccion",
        "agregarRetencion",
    ):
        assert f"{metodo}(" in fuente, f"Falta método {metodo} en Liquidaciones"

    for accion in (
        'data-action="Liquidaciones.crearNueva"',
        'data-action="Liquidaciones.guardar"',
        'data-action="Liquidaciones.verDetalle"',
        'data-action="Liquidaciones.confirmarBorrador"',
        'data-action="Liquidaciones.anular"',
        'data-action="Liquidaciones.agregarDeduccion"',
        'data-action="Liquidaciones.agregarRetencion"',
    ):
        assert accion in fuente, f"Falta acción declarativa {accion}"

    assert "Utils.escapeHtml(" in fuente
    assert "<script" not in fuente.lower()
    assert "onclick=" not in fuente.lower()
    assert "onchange=" not in fuente.lower()


def test_admin_incluye_perfiles_rapidos_de_negocio():
    fuente = (ROOT / "Web/js/modules/admin.js").read_text(encoding="utf-8")
    assert "Perfiles Rápidos de Negocio" in fuente
    assert 'data-action="Admin.aplicarPerfil"' in fuente
    assert "Auth.applyModulos()" in fuente
    for perfil in ("comercio", "agro_granos", "agro_hacienda", "agro_mixto", "servicios"):
        assert perfil in fuente, f"Falta perfil {perfil} en admin.js"


def test_index_auth_y_placeholders_integran_liquidaciones():
    index_html = (ROOT / "Web/index.html").read_text(encoding="utf-8")
    assert 'data-modulo="liquidaciones_granos,liquidaciones_hacienda"' in index_html
    assert 'data-action="Liquidaciones.showGranos"' in index_html
    assert 'data-action="Liquidaciones.showHacienda"' in index_html
    pos_liq = index_html.index('<script src="js/modules/liquidaciones.js"></script>')
    pos_app = index_html.index('<script src="js/app.js"></script>')
    assert pos_liq < pos_app

    auth_js = (ROOT / "Web/js/modules/auth.js").read_text(encoding="utf-8")
    assert "'Liquidaciones': 'liquidaciones_granos'" in auth_js

    placeholders_js = (ROOT / "Web/js/placeholders.js").read_text(encoding="utf-8")
    assert "'Liquidaciones'" in placeholders_js
