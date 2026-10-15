import uuid
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from models import Factura, EmisionFiscalEnCurso
from database import SessionLocal


def cliente(admin, cuit):
    c = cuit()
    assert admin.post('/api/clientes/', json={'cuit': c, 'nombre': 'Cliente piloto ficticio'}).status_code == 200
    return c


def datos(c):
    return {'cliente': c, 'fecha': '2026-09-10', 'subtotal': 100, 'iva': 21, 'total': 121, 'items': []}


def test_borrador_sin_deuda_y_confirmacion_exactamente_una_vez(admin, cuit):
    c = cliente(admin, cuit)
    payload = datos(c)
    b = admin.post('/api/facturas/borradores', json=payload)
    assert b.status_code == 200, b.text
    b = b.json()
    assert b['datos']['total'] == 121
    assert admin.get('/api/facturas/', params={'cliente': c}).json() == []
    assert admin.get(f'/api/clientes/{c}').json()['saldo'] == 0
    ruta = '/api/facturas/borradores/' + b['borrador_id'] + '/confirmar'
    assert admin.post(ruta, json={}).status_code == 409
    r1 = admin.post(ruta, json={'confirmar': True})
    assert r1.status_code == 200, r1.text
    r2 = admin.post(ruta, json={'confirmar': True})
    assert r1.json()['facturanumero'] == r2.json()['facturanumero']
    assert admin.get(f'/api/clientes/{c}').json()['saldo'] == 121
    assert len(admin.get('/api/facturas/', params={'cliente': c}).json()) == 1


def test_legacy_no_muta_sin_confirmacion_y_rechaza_total_inconsistente(admin, cuit):
    c = cliente(admin, cuit)
    assert admin.post('/api/facturas/', json=datos(c)).status_code == 409
    assert admin.post('/api/facturas/', json={**datos(c), 'confirmar': True, 'total': 1}).status_code == 422
    assert admin.get(f'/api/clientes/{c}').json()['saldo'] == 0


def test_no_borra_autorizado_ni_incierto(admin, cuit):
    c = cliente(admin, cuit)
    num = admin.post('/api/facturas/', json={**datos(c), 'confirmar': True}).json()['facturanumero']
    with SessionLocal() as db:
        f = db.query(Factura).filter_by(facturanumero=num).one()
        f.cae = 'CAE-SIMULADO'
        db.commit()
    assert admin.delete(f'/api/facturas/{num}').status_code == 409
    with SessionLocal() as db:
        f = db.query(Factura).filter_by(facturanumero=num).one()
        f.cae = None
        db.add(EmisionFiscalEnCurso(id=1, factura_numero=num, detalle='simulado'))
        db.commit()
    try:
        assert admin.delete(f'/api/facturas/{num}').status_code == 409
    finally:
        with SessionLocal() as db:
            db.query(EmisionFiscalEnCurso).delete()
            db.commit()


def test_fiscal_cerrado_por_defecto(admin, monkeypatch):
    monkeypatch.delenv('ALDIA_EMISION_FISCAL', raising=False)
    r = admin.post('/api/afip/facturas/1/solicitar-cae', json={'confirmar': True})
    assert r.status_code == 409
    assert 'deshabilitada' in r.text


def test_timeout_bloquea_reintento_incluso_con_otro_id(admin, cuit, monkeypatch):
    from routers import afip as router
    c = cliente(admin, cuit)
    num = admin.post('/api/facturas/', json={**datos(c), 'confirmar': True}).json()['facturanumero']
    monkeypatch.setenv('ALDIA_EMISION_FISCAL', 'si')
    monkeypatch.setattr(router, '_config_operativa', lambda db: SimpleNamespace(entorno='homologacion', tipo_comprobante=1, punto_venta=1))
    # Cliente consumidor final: le corresponde Factura B (RG 5616 rechaza A a un CF).
    monkeypatch.setattr(router, '_tipo_sugerido', lambda *a: 6)
    llamadas = []
    def timeout(*args):
        llamadas.append(1)
        raise router.ws.AfipError('Timeout simulado')
    monkeypatch.setattr(router.ws, 'solicitar_cae', timeout)
    try:
        for esperado in (502, 409):
            r = admin.post(f'/api/afip/facturas/{num}/solicitar-cae', json={'confirmar': True},
                           headers={'X-Operation-Id': str(uuid.uuid4())})
            assert r.status_code == esperado, r.text
        assert len(llamadas) == 1
    finally:
        with SessionLocal() as db:
            db.query(EmisionFiscalEnCurso).delete()
            db.commit()


def test_anulacion_administrativa_no_elude_cae(admin, cuit):
    c = cliente(admin, cuit)
    num = admin.post('/api/facturas/', json={**datos(c), 'confirmar': True}).json()['facturanumero']
    with SessionLocal() as db:
        f = db.query(Factura).filter_by(facturanumero=num).one()
        f.cae = 'SIMULADO'
        db.commit()
    assert admin.delete(f'/api/admin/movimientos/factura/{num}').status_code == 409
    assert admin.get(f'/api/clientes/{c}').json()['saldo'] == 121


def test_borrador_stock_insuficiente_no_deja_efectos(admin, cuit):
    c = cliente(admin, cuit)
    codigo = uuid.uuid4().int % 100000000
    r = admin.post("/api/stock/", json={"codigo": codigo, "producto": "Artículo ficticio", "cantidad": 1, "preven": 50, "iva": 21})
    assert r.status_code == 200, r.text
    b = admin.post('/api/facturas/borradores', json={**datos(c),
        'items': [{'codigo': codigo, 'cantidad': 2, 'precio': 50}]}).json()
    ruta = '/api/facturas/borradores/' + b['borrador_id']
    assert admin.post(ruta+'/confirmar', json={'confirmar': True}).status_code == 400
    assert admin.get(ruta).json()['estado'] == 'pendiente'
    assert admin.get(f'/api/clientes/{c}').json()['saldo'] == 0


def test_borrador_anulado_no_revive(admin, cuit):
    c = cliente(admin, cuit)
    b = admin.post('/api/facturas/borradores', json=datos(c)).json()['borrador_id']
    ruta = f'/api/facturas/borradores/{b}/confirmar'
    num = admin.post(ruta, json={'confirmar': True}).json()['facturanumero']
    assert admin.delete(f'/api/facturas/{num}').status_code == 200
    assert admin.post(ruta, json={'confirmar': True}).status_code == 409
    assert admin.get(f'/api/clientes/{c}').json()['saldo'] == 0


def test_restauracion_aislada_no_modifica_fuente(tmp_path):
    import importlib.util
    from pathlib import Path
    import sqlite3
    import hashlib
    spec = importlib.util.spec_from_file_location('verificar_respaldo', Path(__file__).parents[1]/'scripts/verificar_respaldo.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    origen = tmp_path/'copia.db'
    with sqlite3.connect(origen) as db:
        for tabla in ('clientes', 'facturas', 'usuarios'):
            db.execute(f'CREATE TABLE {tabla}(id INTEGER PRIMARY KEY)')
        db.execute('INSERT INTO facturas VALUES(1)')
    antes = hashlib.sha256(origen.read_bytes()).digest()
    assert mod.verificar(origen) == 3
    assert hashlib.sha256(origen.read_bytes()).digest() == antes


def test_confirmaciones_concurrentes_no_duplican(admin, cuit):
    from concurrent.futures import ThreadPoolExecutor
    c = cliente(admin, cuit)
    b = admin.post('/api/facturas/borradores', json=datos(c)).json()['borrador_id']
    def confirmar():
        return admin.post(f'/api/facturas/borradores/{b}/confirmar', json={'confirmar': True})
    with ThreadPoolExecutor(max_workers=2) as pool:
        respuestas = list(pool.map(lambda _: confirmar(), range(2)))
    assert all(r.status_code == 200 for r in respuestas)
    assert len({r.json()['facturanumero'] for r in respuestas}) == 1
    assert admin.get(f'/api/clientes/{c}').json()['saldo'] == 121
