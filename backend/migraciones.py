"""
migraciones.py - Migraciones de esquema para bases ya existentes.

`Base.metadata.create_all()` crea las tablas que faltan, pero NO agrega columnas
nuevas a una tabla que ya existe. Como el sistema ya esta instalado con datos
reales del comercio, las columnas nuevas se agregan aca con
`ALTER TABLE ... ADD COLUMN`, que en SQLite es una operacion segura: no reescribe
la tabla, no toca los datos y las filas viejas quedan con NULL en la columna nueva.

Se ejecuta en cada arranque y es idempotente: si la columna ya esta, no hace nada.
"""
from sqlalchemy import inspect, text


# tabla -> [(columna, tipo SQL, comentario)]
COLUMNAS_NUEVAS = {
    "clientes": [
        # Condicion frente al IVA: define si corresponde factura A, B o C.
        # Las fichas ya cargadas quedan como consumidor final, que es el caso
        # mas comun y el mas seguro (factura B en vez de A).
        ("condicion_iva", "VARCHAR(30) DEFAULT 'consumidor_final'"),
    ],
    "facturas": [
        # Datos fiscales que devuelve AFIP al autorizar el comprobante (WSFEv1).
        ("cae", "VARCHAR(20)"),                 # Código de Autorización Electrónico
        ("cae_vencimiento", "VARCHAR(10)"),     # vencimiento del CAE (YYYY-MM-DD)
        ("punto_venta", "INTEGER"),             # punto de venta habilitado en AFIP
        ("tipo_comprobante", "INTEGER"),        # 1 = Factura A, 6 = B, 11 = C...
        ("resultado", "VARCHAR(1)"),            # A aprobado / R rechazado / P parcial
        ("nro_comprobante_afip", "INTEGER"),    # numeración de AFIP (distinta de facturanumero)
        ("afip_observaciones", "TEXT"),         # motivo textual informado por AFIP
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Conversion de DINERO a enteros de centavos.
#
# Los importes pasaron de Float (pesos con decimales) a Integer (centavos). Una
# base recien creada ya nace en centavos porque `create_all()` usa models.py; lo
# que hay que convertir es el CONTENIDO de una base ya instalada, multiplicando
# cada importe por 100 y redondeando al centavo mas cercano.
#
# La conversion NO es idempotente por si misma (aplicarla dos veces multiplica
# los importes por 10.000), asi que se protege con una marca persistida en la
# tabla `migraciones_aplicadas`: se ejecuta una unica vez por base, dentro de una
# sola transaccion, y si algo falla no queda a medias.
#
# tabla -> columnas de dinero. Se omiten a proposito las cantidades (kilos) y
# las alicuotas (stockmercaderia.iva, compragastos.iva), que NO son dinero.
# ─────────────────────────────────────────────────────────────────────────────
MARCA_CENTAVOS = "dinero_en_centavos_v1"

COLUMNAS_DINERO = {
    "clientes": ["saldo"],
    "proveedores": ["saldo"],
    "stockmercaderia": ["preven", "precom"],
    "cdc": ["total"],
    "remito": ["total", "iva"],
    "ventas": ["precio"],
    "facturas": ["subtotal", "iva", "total"],
    "factprov": ["subtotal", "iva", "total"],
    "compras": ["precio"],
    "gastosfacturas": ["subtotal", "iva", "total"],
    "compragastos": ["monto"],
    "movimientos_sin_impuestos": ["precio"],
    "nfan": ["monto"],
    "ndprov": ["monto"],
    "cobros": ["monto"],
    "pagos": ["monto"],
    "caja": ["debe", "haber"],
    "chequera": ["monto"],
    "conscom": ["precio"],
}


def _asegurar_tabla_marcas(conexion) -> None:
    conexion.execute(text(
        "CREATE TABLE IF NOT EXISTS migraciones_aplicadas ("
        " clave VARCHAR(80) PRIMARY KEY,"
        " aplicada_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    ))


def _ya_aplicada(conexion, clave: str) -> bool:
    fila = conexion.execute(
        text("SELECT 1 FROM migraciones_aplicadas WHERE clave = :c"), {"c": clave}
    ).first()
    return fila is not None


def convertir_dinero_a_centavos(engine) -> list:
    """Convierte los importes de una base preexistente de pesos a centavos.

    Segura e idempotente: se marca en `migraciones_aplicadas` y no se vuelve a
    correr. Si la base esta vacia igual queda marcada, para que un import de
    datos viejos posterior no la dispare por error sobre datos ya en centavos.

    SQLite es de tipado dinamico: el ALTER de tipo no existe ni hace falta. Se
    convierte el VALOR (x100, redondeado) y los enteros conviven sin problema en
    una columna declarada REAL. Nota honesta: en una base vieja la columna
    conserva la afinidad REAL, asi que SQLite devolvera 123456.0 en vez de
    123456; los centavos son enteros y hasta 2^53 la representacion es exacta,
    y `dinero.pesos_decimal()` acepta ambos. Una base nueva nace ya con INTEGER.
    """
    with engine.begin() as conexion:
        _asegurar_tabla_marcas(conexion)
        if _ya_aplicada(conexion, MARCA_CENTAVOS):
            return []

        inspector = inspect(engine)
        tablas = set(inspector.get_table_names())
        convertidas = []
        for tabla, columnas in COLUMNAS_DINERO.items():
            if tabla not in tablas:
                continue
            existentes = {col["name"] for col in inspector.get_columns(tabla)}
            presentes = [c for c in columnas if c in existentes]
            if not presentes:
                continue
            # ROUND() de SQLite redondea half-away-from-zero, que es el mismo
            # criterio comercial (HALF_UP) que usa backend/dinero.py.
            sets = ", ".join(
                f"{c} = CAST(ROUND(COALESCE({c}, 0) * 100) AS INTEGER)" for c in presentes
            )
            conexion.execute(text(f"UPDATE {tabla} SET {sets}"))
            convertidas.extend(f"{tabla}.{c}" for c in presentes)

        conexion.execute(
            text("INSERT INTO migraciones_aplicadas (clave) VALUES (:c)"),
            {"c": MARCA_CENTAVOS},
        )

    if convertidas:
        print(f"[migraciones] Importes convertidos a centavos: {len(convertidas)} columnas")
    return convertidas


def aplicar_migraciones(engine) -> list:
    """Agrega las columnas faltantes. Devuelve la lista de cambios aplicados."""
    aplicadas = []
    inspector = inspect(engine)
    tablas = set(inspector.get_table_names())

    for tabla, columnas in COLUMNAS_NUEVAS.items():
        if tabla not in tablas:
            # La tabla todavía no existe: create_all() ya la crea con todo.
            continue
        existentes = {col["name"] for col in inspector.get_columns(tabla)}
        for nombre, tipo in columnas:
            if nombre in existentes:
                continue
            with engine.begin() as conexion:
                conexion.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}"))
            aplicadas.append(f"{tabla}.{nombre}")

    if aplicadas:
        print(f"[migraciones] Columnas agregadas: {', '.join(aplicadas)}")

    # Los importes pasan de pesos (Float) a centavos (Integer). Se hace una sola
    # vez por base y queda registrado.
    aplicadas.extend(convertir_dinero_a_centavos(engine))
    return aplicadas
