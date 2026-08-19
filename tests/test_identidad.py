"""
Identidad subrogada de clientes y proveedores.

Lo que se prueba es un BUG CONCRETO que el comercio se comía, no una abstracción:
un cliente cargado con el identificador mal tipeado que ya tenía facturas
quedaba con ese número para siempre. No se podía editar (era la clave primaria)
ni borrar (tenía movimientos). El único arreglo era abrir el .db a mano.

La segunda mitad prueba la migración sobre una base con el esquema VIEJO, que es
donde esto se puede romper de verdad: las instalaciones que ya existen.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def _cliente_con_factura(admin, cuit_mal, codigo=88001):
    """Deja un cliente con una factura emitida: el estado que trababa todo."""
    admin.post("/api/clientes/", json={"cuit": cuit_mal, "nombre": "Ferretería Central"})
    admin.post("/api/stock/", json={
        "codigo": codigo, "producto": "Tornillos", "cantidad": 100,
        "preven": 50.0, "iva": 21.0, "unidad": "u"})
    # Los importes los manda quien factura: el total no se deduce de los items.
    r = admin.post("/api/facturas/", json={
        "cliente": cuit_mal, "fecha": "2026-08-19", "tipo": "A",
        "subtotal": 100.0, "iva": 21.0, "total": 121.0,
        "items": [{"codigo": codigo, "cantidad": 2, "precio": 50.0}]})
    assert r.status_code in (200, 201), r.text
    return r.json()


class TestLaFichaTieneIdentidadPropia:
    def test_el_cliente_trae_id_y_tipo_de_identificador(self, admin, cuit):
        c = cuit()
        r = admin.post("/api/clientes/", json={"cuit": c, "nombre": "Con identidad"})
        datos = r.json()
        assert isinstance(datos["id"], int) and datos["id"] > 0
        # El mismo valor con los dos nombres: `cuit` para lo que ya existe,
        # `tax_id` para lo que se escriba de ahora en mas.
        assert datos["cuit"] == c
        assert datos["tax_id"] == c
        assert datos["tax_id_type"] == "CUIT"

    def test_el_id_no_cambia_aunque_cambie_el_identificador(self, admin, cuit):
        viejo, nuevo = cuit(), cuit()
        creado = admin.post("/api/clientes/",
                            json={"cuit": viejo, "nombre": "Estable"}).json()
        r = admin.post(f"/api/clientes/{viejo}/identificacion",
                       json={"tax_id": nuevo, "confirmar": nuevo})
        assert r.status_code == 200, r.text
        # Es la MISMA ficha: eso es lo que significa tener identidad propia.
        assert r.json()["id"] == creado["id"]


class TestElBugQueSeArregla:
    def test_se_corrige_un_identificador_con_facturas_emitidas(self, admin, cuit):
        """El caso real: se cargó mal, ya se facturó, y hay que corregirlo."""
        mal, bien = cuit(), cuit()
        factura = _cliente_con_factura(admin, mal)
        num = factura["facturanumero"]

        r = admin.post(f"/api/clientes/{mal}/identificacion",
                       json={"tax_id": bien, "confirmar": bien,
                             "motivo": "se cargó con un dígito de más"})
        assert r.status_code == 200, r.text
        assert r.json()["cuit"] == bien

        # Y la factura ya emitida sigue apuntando al cliente: el ON UPDATE
        # CASCADE la arrastró en la misma transacción. Sin esto quedaría
        # huérfana, que es peor que no poder corregir.
        emitida = admin.get(f"/api/facturas/{num}").json()
        assert emitida["cliente"] == bien, "La factura quedó apuntando al viejo"

        # El cliente no perdió sus movimientos: sigue sin poder borrarse.
        assert admin.delete(f"/api/clientes/{bien}").status_code == 409

    def test_el_saldo_no_se_pierde_en_la_correccion(self, admin, cuit):
        mal, bien = cuit(), cuit()
        _cliente_con_factura(admin, mal, codigo=88002)
        saldo_antes = admin.get(f"/api/clientes/{mal}").json()["saldo"]
        assert saldo_antes > 0

        admin.post(f"/api/clientes/{mal}/identificacion",
                   json={"tax_id": bien, "confirmar": bien})

        assert admin.get(f"/api/clientes/{bien}").json()["saldo"] == saldo_antes

    def test_el_viejo_ya_no_existe(self, admin, cuit):
        mal, bien = cuit(), cuit()
        admin.post("/api/clientes/", json={"cuit": mal, "nombre": "Se muda"})
        admin.post(f"/api/clientes/{mal}/identificacion",
                   json={"tax_id": bien, "confirmar": bien})
        assert admin.get(f"/api/clientes/{mal}").status_code == 404


class TestGuardas:
    def test_sin_confirmar_no_se_toca_nada(self, admin, cuit):
        """Cambia un dato fiscal de comprobantes emitidos: no puede ser un
        efecto colateral de mandar un PUT."""
        mal, bien = cuit(), cuit()
        _cliente_con_factura(admin, mal, codigo=88003)

        r = admin.post(f"/api/clientes/{mal}/identificacion", json={"tax_id": bien})
        assert r.status_code == 400
        cuerpo = r.json()
        assert cuerpo["codigo"] == "CONFIRMACION_REQUERIDA"
        # Para un agente: esto se pregunta, no se deduce.
        assert cuerpo["accion"] == "preguntar"
        # Y el mensaje dice QUE se va a arrastrar, antes de arrastrarlo.
        assert "factura" in cuerpo["detail"].lower()
        assert admin.get(f"/api/clientes/{mal}").status_code == 200

    def test_no_se_puede_pisar_a_otro_cliente(self, admin, cuit):
        uno, otro = cuit(), cuit()
        admin.post("/api/clientes/", json={"cuit": uno, "nombre": "Uno"})
        admin.post("/api/clientes/", json={"cuit": otro, "nombre": "Otro"})
        r = admin.post(f"/api/clientes/{uno}/identificacion",
                       json={"tax_id": otro, "confirmar": otro})
        assert r.status_code == 400
        assert r.json()["codigo"] == "YA_EXISTE"

    def test_el_identificador_nuevo_se_valida(self, admin, cuit):
        uno = cuit()
        admin.post("/api/clientes/", json={"cuit": uno, "nombre": "Uno"})
        # Verificador que no cierra: se rechaza igual que en un alta.
        r = admin.post(f"/api/clientes/{uno}/identificacion",
                       json={"tax_id": "20123456781", "confirmar": "20123456781"})
        assert r.status_code == 422

    def test_corregir_por_el_mismo_valor_no_es_una_correccion(self, admin, cuit):
        uno = cuit()
        admin.post("/api/clientes/", json={"cuit": uno, "nombre": "Uno"})
        r = admin.post(f"/api/clientes/{uno}/identificacion",
                       json={"tax_id": uno, "confirmar": uno})
        assert r.status_code == 422


class TestMigracionDesdeElEsquemaViejo:
    """Donde esto se puede romper de verdad: las instalaciones que ya existen."""

    @staticmethod
    def _base_vieja(ruta: Path) -> None:
        """Reproduce el esquema anterior: el CUIT como clave primaria."""
        con = sqlite3.connect(ruta)
        con.executescript("""
            CREATE TABLE clientes (
                cuit TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                domicilio TEXT DEFAULT '', localidad TEXT DEFAULT '',
                provincia TEXT DEFAULT '', cp TEXT DEFAULT '',
                telefono TEXT DEFAULT '', mail TEXT DEFAULT '',
                saldo INTEGER DEFAULT 0,
                condicion_iva TEXT DEFAULT 'consumidor_final'
            );
            CREATE TABLE proveedores (
                cuit TEXT PRIMARY KEY, nombre TEXT NOT NULL,
                domicilio TEXT DEFAULT '', localidad TEXT DEFAULT '',
                provincia TEXT DEFAULT '', cp TEXT DEFAULT '',
                telefono TEXT DEFAULT '', mail TEXT DEFAULT '',
                saldo INTEGER DEFAULT 0
            );
            -- Una tabla HIJA con clave foránea real. Sin esto la prueba no vale
            -- nada: la primera versión de la migración dejaba a `clientes` sin
            -- índice único y SQLite rechazaba toda FK que la referenciara con
            -- "foreign key mismatch". Con solo las tablas padre no se nota.
            CREATE TABLE stockmercaderia (
                codigo INTEGER PRIMARY KEY, producto TEXT NOT NULL,
                cantidad REAL DEFAULT 0, unidad TEXT DEFAULT 'UN'
            );
            CREATE TABLE ventas (
                nmov INTEGER PRIMARY KEY,
                cliente TEXT REFERENCES clientes(cuit),
                codigo INTEGER REFERENCES stockmercaderia(codigo),
                cantidad REAL DEFAULT 0
            );
        """)
        con.execute("INSERT INTO clientes (cuit, nombre, saldo) VALUES (?,?,?)",
                    ("20123456789", "Cliente Viejo", 150000))
        con.execute("INSERT INTO proveedores (cuit, nombre, saldo) VALUES (?,?,?)",
                    ("30712345678", "Proveedor Viejo", 90000))
        con.execute("INSERT INTO stockmercaderia (codigo, producto) VALUES (?,?)",
                    (500, "Producto Viejo"))
        con.execute("INSERT INTO ventas (nmov, cliente, codigo, cantidad) VALUES (?,?,?,?)",
                    (1, "20123456789", 500, 3))
        con.commit()
        con.close()

    def test_migra_sin_perder_datos(self, tmp_path):
        ruta = tmp_path / "vieja.db"
        self._base_vieja(ruta)

        from sqlalchemy import create_engine
        import migraciones
        motor = create_engine(f"sqlite:///{ruta}")
        resumen = migraciones.aplicar_identidad_subrogada(motor)
        assert resumen["aplicada"], resumen["motivo"]

        con = sqlite3.connect(ruta)
        cols = {c[1] for c in con.execute("PRAGMA table_info(clientes)")}
        assert "id" in cols and "tax_id_type" in cols

        fila = con.execute(
            "SELECT id, cuit, nombre, saldo, tax_id_type FROM clientes").fetchone()
        assert fila[1] == "20123456789"
        assert fila[2] == "Cliente Viejo"
        assert fila[3] == 150000, "Se perdió el saldo en la migración"
        assert fila[4] == "CUIT"
        assert isinstance(fila[0], int)

        # Y el proveedor también.
        assert con.execute("SELECT nombre FROM proveedores").fetchone()[0] == "Proveedor Viejo"

        # La tabla hija sobrevivió y sigue apuntando bien. Es lo que destapó que
        # la unicidad tiene que ir DENTRO del CREATE TABLE y no como índice
        # aparte: si no, SQLite invalida la clave foránea entera.
        assert con.execute("SELECT cliente FROM ventas").fetchone()[0] == "20123456789"
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        con.close()

    def test_es_idempotente(self, tmp_path):
        """Reiniciar el servidor no puede volver a migrar."""
        ruta = tmp_path / "vieja.db"
        self._base_vieja(ruta)
        from sqlalchemy import create_engine
        import migraciones
        motor = create_engine(f"sqlite:///{ruta}")

        assert migraciones.aplicar_identidad_subrogada(motor)["aplicada"] is True
        segunda = migraciones.aplicar_identidad_subrogada(motor)
        assert segunda["aplicada"] is False
        assert segunda["motivo"] == "ya estaba"

    def test_con_identificadores_repetidos_no_migra_y_avisa(self, tmp_path):
        """Un UNIQUE no se puede imponer sobre datos que ya lo violan.

        Antes que romper el arranque del comercio a la mañana, se deja la base
        como estaba y se dice qué corregir.
        """
        ruta = tmp_path / "sucia.db"
        self._base_vieja(ruta)
        con = sqlite3.connect(ruta)
        # Se fuerza el duplicado por fuera de la PK vieja, como quedaría una base
        # importada del sistema anterior.
        con.executescript("""
            CREATE TABLE clientes_tmp AS SELECT * FROM clientes;
            DROP TABLE clientes;
            ALTER TABLE clientes_tmp RENAME TO clientes;
        """)
        con.execute("INSERT INTO clientes (cuit, nombre, saldo) VALUES (?,?,?)",
                    ("20123456789", "Duplicado", 0))
        con.commit(); con.close()

        from sqlalchemy import create_engine
        import migraciones
        resumen = migraciones.aplicar_identidad_subrogada(
            create_engine(f"sqlite:///{ruta}"))

        assert resumen["aplicada"] is False
        assert "repetido" in resumen["motivo"]
        # La base quedó intacta: las dos filas siguen ahí.
        con = sqlite3.connect(ruta)
        assert con.execute("SELECT COUNT(*) FROM clientes").fetchone()[0] == 2
        con.close()

class TestProveedores:
    """El mismo problema y la misma solución del otro lado del mostrador."""

    def test_se_corrige_con_compras_registradas(self, admin, cuit):
        mal, bien = cuit("30"), cuit("30")
        admin.post("/api/proveedores/", json={"cuit": mal, "nombre": "Distribuidora Sur"})
        assert admin.get(f"/api/proveedores/{mal}").json()["tax_id_type"] == "CUIT"

        r = admin.post(f"/api/proveedores/{mal}/identificacion",
                       json={"tax_id": bien, "confirmar": bien,
                             "motivo": "lo pasaron mal por teléfono"})
        assert r.status_code == 200, r.text
        assert r.json()["cuit"] == bien
        assert admin.get(f"/api/proveedores/{mal}").status_code == 404

    def test_tambien_exige_confirmacion(self, admin, cuit):
        mal, bien = cuit("30"), cuit("30")
        admin.post("/api/proveedores/", json={"cuit": mal, "nombre": "Otra"})
        r = admin.post(f"/api/proveedores/{mal}/identificacion", json={"tax_id": bien})
        assert r.status_code == 400
        assert r.json()["codigo"] == "CONFIRMACION_REQUERIDA"
