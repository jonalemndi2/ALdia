import itertools
from sqlalchemy import create_engine, text

from database import SessionLocal
from migraciones import aplicar_migraciones
from models import DevolucionCompraItem, ExistenciaDeposito, FacturaProveedor, MovimientoStock, StockMercaderia


_codigos = itertools.count(970001)


def _preparar(admin, cuit, cantidad=10, costo=100):
    proveedor = cuit("33")
    assert admin.post("/api/proveedores/", json={"cuit": proveedor, "nombre": "Proveedor stock"}).status_code == 200
    codigo = next(_codigos)
    assert admin.post("/api/stock/", json={
        "codigo": codigo, "producto": "Producto stockeable", "cantidad": cantidad,
        "unidad": "UN", "preven": 300, "iva": 21, "precom": costo,
    }).status_code == 200
    return proveedor, codigo


def _compra(admin, proveedor, codigo, numero="A-1", estado="confirmada", headers=None):
    return admin.post("/api/compras/", headers=headers or {}, json={
        "proveedor_cuit": proveedor, "fecha": "2026-09-01", "num_factura": numero,
        "estado": estado,
        "items": [{"codigo": codigo, "producto": "Producto stockeable", "cantidad": 5, "precio": 200}],
    })


def test_compra_confirmada_mueve_stock_deuda_y_libro(admin, cuit):
    proveedor, codigo = _preparar(admin, cuit)
    r = _compra(admin, proveedor, codigo)
    assert r.status_code == 200, r.text
    assert admin.get(f"/api/stock/{codigo}").json()["cantidad"] == 15
    assert admin.get(f"/api/proveedores/{proveedor}").json()["saldo"] == 1210
    with SessionLocal() as db:
        factura = db.query(FacturaProveedor).filter_by(id=r.json()["id"]).one()
        mov = db.query(MovimientoStock).filter_by(origen_tipo="factura_compra", origen_id=factura.id).one()
        existencia = db.query(ExistenciaDeposito).filter_by(codigo=codigo).one()
        assert factura.num_factura == "A-1" and factura.estado == "confirmada"
        assert mov.cantidad == 5 and mov.costo_unitario == 20000
        assert existencia.cantidad == 15
        assert existencia.costo_promedio == 13333  # (10*100 + 5*200) / 15 pesos


def test_borrador_no_impacta_hasta_confirmar_y_reintento_es_idempotente(admin, cuit):
    proveedor, codigo = _preparar(admin, cuit)
    op = {"X-Operation-Id": "compra-stock-idempotente-1"}
    r = _compra(admin, proveedor, codigo, "B-1", "borrador", op)
    assert r.status_code == 200 and r.json()["estado"] == "borrador"
    assert admin.get(f"/api/stock/{codigo}").json()["cantidad"] == 10
    repetida = _compra(admin, proveedor, codigo, "B-1", "borrador", op)
    assert repetida.status_code == 200 and repetida.json()["id"] == r.json()["id"]
    assert admin.post(f"/api/compras/{r.json()['id']}/confirmar").status_code == 200
    assert admin.get(f"/api/stock/{codigo}").json()["cantidad"] == 15


def test_listado_y_detalle_publicos_de_compras(admin, cuit):
    proveedor, codigo = _preparar(admin, cuit)
    creada = _compra(admin, proveedor, codigo, "LIST-1", "borrador").json()
    listado = admin.get("/api/compras/", params={"proveedor": proveedor, "limite": 5})
    assert listado.status_code == 200
    assert any(x["id"] == creada["id"] and x["estado"] == "borrador" for x in listado.json())
    detalle = admin.get(f"/api/compras/{creada['id']}")
    assert detalle.status_code == 200
    assert detalle.json()["num_factura"] == "LIST-1"
    assert detalle.json()["renglones"][0]["codigo"] == codigo


def test_operation_id_rechaza_payload_distinto(admin, cuit):
    proveedor, codigo = _preparar(admin, cuit)
    op = {"X-Operation-Id": "compra-stock-fingerprint-1"}
    original = _compra(admin, proveedor, codigo, "FP-1", headers=op)
    assert original.status_code == 200
    igual = _compra(admin, proveedor, codigo, "FP-1", headers=op)
    assert igual.status_code == 200 and igual.json()["id"] == original.json()["id"]
    distinto = admin.post("/api/compras/", headers=op, json={
        "proveedor_cuit": proveedor, "fecha": "2026-09-01", "num_factura": "FP-1",
        "items": [{"codigo": codigo, "producto": "X", "cantidad": 6, "precio": 200}],
    })
    assert distinto.status_code == 409


def test_anulacion_crea_reversa_sin_borrar(admin, cuit):
    proveedor, codigo = _preparar(admin, cuit)
    factura_id = _compra(admin, proveedor, codigo, "C-1").json()["id"]
    r = admin.post(f"/api/compras/{factura_id}/anular")
    assert r.status_code == 200, r.text
    assert admin.get(f"/api/stock/{codigo}").json()["cantidad"] == 10
    assert admin.get(f"/api/proveedores/{proveedor}").json()["saldo"] == 0
    with SessionLocal() as db:
        assert db.query(FacturaProveedor).filter_by(id=factura_id).one().estado == "anulada"
        assert db.query(MovimientoStock).filter_by(origen_tipo="factura_compra", origen_id=factura_id).count() == 1
        assert db.query(MovimientoStock).filter_by(origen_tipo="anulacion_factura_compra", origen_id=factura_id).count() == 1
    # La identidad fiscal no se libera al anular.
    assert _compra(admin, proveedor, codigo, "C-1").status_code == 409


def test_anulacion_mismo_sku_revierte_costos_en_orden_inverso(admin, cuit):
    proveedor, codigo = _preparar(admin, cuit, cantidad=10, costo=100)
    r = admin.post("/api/compras/", json={
        "proveedor_cuit": proveedor, "fecha": "2026-09-01", "num_factura": "MULTI-1",
        "items": [
            {"codigo": codigo, "producto": "X", "cantidad": 2, "precio": 200},
            {"codigo": codigo, "producto": "X", "cantidad": 3, "precio": 300},
        ],
    })
    assert r.status_code == 200, r.text
    assert admin.post(f"/api/compras/{r.json()['id']}/anular").status_code == 200
    with SessionLocal() as db:
        existencia = db.query(ExistenciaDeposito).filter_by(codigo=codigo).one()
        producto = db.query(StockMercaderia).filter_by(codigo=codigo).one()
        assert existencia.cantidad == 10
        assert existencia.costo_promedio == 10000
        assert producto.precom == 10000


def test_devolucion_fisica_exige_origen_y_no_supera_compra(admin, cuit):
    proveedor, codigo = _preparar(admin, cuit)
    factura_id = _compra(admin, proveedor, codigo, "D-1").json()["id"]
    compra_id = admin.get(f"/api/compras/{factura_id}/renglones").json()[0]["compra_id"]
    base = {"proveedor_cuit": proveedor, "fecha": "2026-09-02",
            "items": [{"compra_id": compra_id, "codigo": codigo, "producto": "Producto stockeable", "cantidad": 6, "precio": 200}]}
    assert admin.post("/api/devoluciones/", json=base).status_code == 422
    base["factura_id"] = factura_id
    assert admin.post("/api/devoluciones/", json=base).status_code == 409
    base["items"][0]["cantidad"] = 2
    assert admin.post("/api/devoluciones/", json=base).status_code == 200
    assert admin.get(f"/api/stock/{codigo}").json()["cantidad"] == 13


def test_devolucion_identifica_renglon_exacto_con_sku_repetido(admin, cuit):
    proveedor, codigo = _preparar(admin, cuit)
    r = admin.post("/api/compras/", json={
        "proveedor_cuit": proveedor, "fecha": "2026-09-01", "num_factura": "DEV-LINEA",
        "items": [
            {"codigo": codigo, "producto": "X lote 1", "cantidad": 2, "precio": 100},
            {"codigo": codigo, "producto": "X lote 2", "cantidad": 4, "precio": 200},
        ],
    })
    lineas = admin.get(f"/api/compras/{r.json()['id']}/renglones").json()
    segunda = lineas[1]
    payload = {"proveedor_cuit": proveedor, "fecha": "2026-09-02", "factura_id": r.json()["id"],
               "items": [{"compra_id": segunda["compra_id"], "codigo": codigo,
                          "producto": "X lote 2", "cantidad": 4, "precio": 200}]}
    assert admin.post("/api/devoluciones/", json=payload).status_code == 200
    assert admin.post("/api/devoluciones/", json=payload).status_code == 409
    with SessionLocal() as db:
        assert db.query(DevolucionCompraItem).filter_by(compra_id=lineas[0]["compra_id"]).count() == 0
        assert db.query(DevolucionCompraItem).filter_by(compra_id=segunda["compra_id"]).count() == 1


def test_nota_credito_financiera_no_mueve_stock(admin, cuit):
    proveedor, codigo = _preparar(admin, cuit)
    _compra(admin, proveedor, codigo, "NC-BASE")
    r = admin.post("/api/compras/notas-credito-financieras", json={
        "proveedor": proveedor, "fecha": "2026-09-02", "monto": 210,
        "referencia": "NC A-2", "descripcion": "Bonificación financiera",
    })
    assert r.status_code == 200, r.text
    assert r.json()["mueve_stock"] is False
    assert admin.get(f"/api/stock/{codigo}").json()["cantidad"] == 15
    assert admin.get(f"/api/proveedores/{proveedor}").json()["saldo"] == 1000


def test_migracion_normaliza_duplicados_historicos_y_reinicia(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE factprov (id INTEGER PRIMARY KEY, proveedor VARCHAR(20), fecha VARCHAR(10), subtotal INTEGER, iva INTEGER, total INTEGER)"))
        c.execute(text("INSERT INTO factprov VALUES (1,'P1','2026-01-01',1,0,1),(2,'P1','2026-01-02',1,0,1)"))
    aplicar_migraciones(engine)
    # Simular que ambos comprobantes históricos recibieron el mismo número al
    # importar datos antiguos, antes de volver a arrancar con el índice nuevo.
    with engine.begin() as c:
        c.execute(text("DROP INDEX IF EXISTS ux_factprov_proveedor_numero"))
        c.execute(text("UPDATE factprov SET num_factura='A-1'"))
    aplicar_migraciones(engine)
    aplicar_migraciones(engine)
    with engine.begin() as c:
        numeros = [r[0] for r in c.execute(text("SELECT num_factura FROM factprov ORDER BY id"))]
        conflictos = c.execute(text("SELECT COUNT(*) FROM conflictos_factprov_legacy")).scalar_one()
        assert numeros == ["A-1", "A-1 [DUPLICADO LEGACY #2]"]
        assert conflictos == 1


def test_migracion_duplicado_legacy_busca_sufijo_libre(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy_colision.db'}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE factprov (id INTEGER PRIMARY KEY, proveedor VARCHAR(20), fecha VARCHAR(10), subtotal INTEGER, iva INTEGER, total INTEGER, num_factura VARCHAR(80), estado VARCHAR(20) DEFAULT 'confirmada', operation_id VARCHAR(100), payload_fingerprint VARCHAR(64), anulada_en TIMESTAMP)"))
        c.execute(text(
            "INSERT INTO factprov(id,proveedor,fecha,subtotal,iva,total,num_factura) VALUES "
            "(1,'P1','2026-01-01',1,0,1,'A-1'),"
            "(2,'P1','2026-01-02',1,0,1,'A-1'),"
            "(3,'P1','2026-01-03',1,0,1,'A-1 [DUPLICADO LEGACY #2]')"
        ))
    aplicar_migraciones(engine)
    aplicar_migraciones(engine)
    with engine.begin() as c:
        numeros = [r[0] for r in c.execute(text("SELECT num_factura FROM factprov ORDER BY id"))]
        evidencia = c.execute(text(
            "SELECT num_factura_original,num_factura_normalizado FROM conflictos_factprov_legacy WHERE factprov_id=2"
        )).one()
        assert numeros == ["A-1", "A-1 [DUPLICADO LEGACY #2-2]", "A-1 [DUPLICADO LEGACY #2]"]
        assert evidencia == ("A-1", "A-1 [DUPLICADO LEGACY #2-2]")
