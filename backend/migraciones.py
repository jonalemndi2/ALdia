"""
migraciones.py - Migraciones de esquema para bases ya existentes.

`Base.metadata.create_all()` crea las tablas que faltan, pero NO agrega columnas
nuevas a una tabla que ya existe. Como el sistema ya esta instalado con datos
reales del comercio, las columnas nuevas se agregan aca con
`ALTER TABLE ... ADD COLUMN`, que en SQLite es una operacion segura: no reescribe
la tabla, no toca los datos y las filas viejas quedan con NULL en la columna nueva.

Se ejecuta en cada arranque y es idempotente: si la columna ya esta, no hace nada.

Este archivo tiene DOS migraciones de naturaleza distinta:

  * `aplicar_migraciones()`  -> columnas nuevas y conversion de dinero a
    centavos. Barato y seguro.
  * `aplicar_claves_foraneas()` -> pone las claves foraneas REALES en tablas
    que ya existen. SQLite NO permite agregar una FK con ALTER TABLE, asi que
    hay que RECREAR la tabla. Es la operacion mas delicada del arranque y esta
    documentada en detalle mas abajo, junto con la verificacion previa de
    huerfanos que decide si se aplica o no.
"""
from sqlalchemy.schema import CreateTable
from sqlalchemy import inspect, text


# tabla -> [(columna, tipo SQL, comentario)]
COLUMNAS_NUEVAS = {
    "usuarios": [
        # Una instalacion que ya venia funcionando puede tener el admin con la
        # contrasena de fabrica, que esta publicada en el README. Se marca en 1
        # para todos los usuarios existentes: la proxima vez que entren van a
        # tener que definir una propia.
        ("debe_cambiar_password", "BOOLEAN NOT NULL DEFAULT 1"),
        # Instante del ultimo cambio de contrasena. Es la linea de corte que
        # invalida los tokens emitidos antes. Queda en NULL para los usuarios ya
        # cargados, y NULL significa "no hay nada que invalidar": sus sesiones
        # abiertas siguen valiendo, que es lo correcto -- no cambiaron la clave,
        # asi que no hay ninguna que proteger.
        ("password_cambiada_en", "TIMESTAMP"),
        # Permiso para declarar `X-Actor-User-ID` y operar a nombre de otro.
        # Se agrega en 0 para TODOS los usuarios existentes: es el punto del
        # arreglo. Quien lo necesite (la cuenta de servicio del agente) lo
        # recibe del administrador de forma explicita, uno por uno.
        ("puede_actuar_por", "BOOLEAN NOT NULL DEFAULT 0"),
    ],
    "caja": [
        # En que cuenta cae el asiento: efectivo (el cajon) o banco. Las filas
        # ya existentes quedan en "efectivo" a proposito -- es como se venian
        # tratando, y reinterpretar asientos viejos cambiaria cierres de caja
        # que el comercio ya dio por buenos.
        ("cuenta", "VARCHAR(20) NOT NULL DEFAULT 'efectivo'"),
    ],
    "ncp": [
        # Importe de la nota de credito (devolucion a proveedor), en centavos.
        # Antes la devolucion RESTABA del saldo del proveedor pero solo dejaba
        # un texto: el importe no quedaba registrado y el saldo no se podia
        # recalcular desde los movimientos. Ver backend/saldos.py.
        ("monto", "INTEGER DEFAULT 0"),
    ],
    "proveedores": [
        # Direccion internacional. El modelo viejo asume Argentina: "provincia"
        # no existe en Estados Unidos y "codigo postal" no es un ZIP code. Las
        # columnas viejas se conservan --las usa el frontend, el MCP y los
        # comprobantes ya impresos-- y se pueblan las dos en paralelo.
        ("address_line_1", "VARCHAR(300) DEFAULT ''"),
        ("address_line_2", "VARCHAR(300) DEFAULT ''"),
        ("city", "VARCHAR(120) DEFAULT ''"),
        ("region", "VARCHAR(80) DEFAULT ''"),
        ("postal_code", "VARCHAR(20) DEFAULT ''"),
        ("country_code", "VARCHAR(2) DEFAULT ''"),
        # Datos que el IRS pide de un proveedor estadounidense. El modelo queda
        # PREPARADO; no se genera ningun 1099 (ver la nota en models.py).
        ("legal_name", "VARCHAR(200) DEFAULT ''"),
        ("dba", "VARCHAR(200) DEFAULT ''"),
        ("w9_recibido", "BOOLEAN DEFAULT 0"),
        ("w9_fecha", "VARCHAR(10) DEFAULT ''"),
        ("elegible_1099", "BOOLEAN DEFAULT 0"),
    ],
    "clientes": [
        # Direccion internacional. El modelo viejo asume Argentina: "provincia"
        # no existe en Estados Unidos y "codigo postal" no es un ZIP code. Las
        # columnas viejas se conservan --las usa el frontend, el MCP y los
        # comprobantes ya impresos-- y se pueblan las dos en paralelo.
        ("address_line_1", "VARCHAR(300) DEFAULT ''"),
        ("address_line_2", "VARCHAR(300) DEFAULT ''"),
        ("city", "VARCHAR(120) DEFAULT ''"),
        ("region", "VARCHAR(80) DEFAULT ''"),
        ("postal_code", "VARCHAR(20) DEFAULT ''"),
        ("country_code", "VARCHAR(2) DEFAULT ''"),
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


# ═════════════════════════════════════════════════════════════════════════════
# CLAVES FORANEAS REALES SOBRE UNA BASE QUE YA EXISTE
#
# EL PROBLEMA
# -----------
# SQLite no tiene `ALTER TABLE ... ADD CONSTRAINT`. La unica forma de agregarle
# una clave foranea a una tabla que ya existe es RECREARLA: crear una tabla nueva
# con el esquema correcto, copiar los datos, borrar la vieja y renombrar. Es el
# procedimiento que documenta el propio SQLite ("Making Other Kinds Of Table
# Schema Changes"), y es el que se implementa aca.
#
# LA DECISION: se aplica, pero solo cuando es seguro
# --------------------------------------------------
# La alternativa era dejar las FK solo para bases nuevas y no tocar las
# instaladas. Se descarto porque justamente las bases instaladas -- las que
# vienen arrastrando datos migrados de Access -- son las que mas necesitan la
# verificacion. Pero la recreacion se hace con tres candados:
#
#   1. VERIFICACION PREVIA. Antes de tocar nada se buscan los huerfanos (filas
#      que apuntan a un padre que no existe). Si una tabla tiene huerfanos NO se
#      recrea: se deja exactamente como estaba y se informa con nombre de tabla,
#      columna, cantidad y ejemplos concretos. El arranque NUNCA se aborta -- el
#      sistema se abre con doble clic y el usuario no tiene consola donde leer un
#      stacktrace -- y el detalle queda disponible en
#      GET /api/admin/verificar-integridad.
#
#   2. TODO EN UNA TRANSACCION. Si algo falla en el medio, ROLLBACK: la base
#      queda como estaba. No existe un estado intermedio con la tabla a medio
#      copiar.
#
#   3. CONTROL DE FILAS Y DE COLUMNAS. Se compara la cantidad de filas antes y
#      despues de copiar, y se aborta si no coincide. Y si la tabla real tiene
#      columnas que el modelo no conoce (restos de una version vieja), la tabla
#      se saltea: recrearla borraria esos datos en silencio.
#
# El plan de FK no esta escrito a mano aca: sale de `Base.metadata`, o sea de lo
# declarado en models.py. Una FK nueva en el modelo se migra sola.
# ═════════════════════════════════════════════════════════════════════════════

SUFIJO_TEMPORAL = "__migrando_fk"


def _plan_de_claves_foraneas(metadata) -> dict:
    """tabla -> [(columna, tabla_padre, columna_padre, ondelete)] segun models.py."""
    plan = {}
    for tabla in metadata.sorted_tables:
        for columna in tabla.columns:
            for fk in columna.foreign_keys:
                plan.setdefault(tabla.name, []).append((
                    columna.name,
                    fk.column.table.name,
                    fk.column.name,
                    (fk.ondelete or "NO ACTION").upper(),
                ))
    return plan


def verificar_huerfanos(engine, metadata=None) -> list:
    """Filas que apuntan a un padre inexistente. NO modifica nada.

    Es la verificacion que corre ANTES de activar las FK y la que alimenta a
    GET /api/admin/verificar-integridad. Devuelve una lista de diccionarios, uno
    por columna con problemas, con ejemplos concretos para que el usuario pueda
    ir a buscar los registros: "remito.cliente: 3 filas apuntan a un cliente que
    no existe (ejemplos: 20-11111111-2, ...)".

    Los NULL no son huerfanos: una FK no controla las columnas vacias, y en este
    esquema "sin cliente" es un estado valido para datos historicos.
    """
    if metadata is None:
        from database import Base
        metadata = Base.metadata

    inspector = inspect(engine)
    tablas_reales = set(inspector.get_table_names())
    problemas = []

    with engine.connect() as conexion:
        for tabla, claves in _plan_de_claves_foraneas(metadata).items():
            if tabla not in tablas_reales:
                continue
            columnas_reales = {c["name"] for c in inspector.get_columns(tabla)}
            for columna, padre, columna_padre, _ondelete in claves:
                if padre not in tablas_reales or columna not in columnas_reales:
                    continue
                consulta = text(
                    f'SELECT h."{columna}" AS valor, COUNT(*) AS cuantas '
                    f'FROM "{tabla}" h '
                    f'WHERE h."{columna}" IS NOT NULL AND NOT EXISTS ('
                    f'  SELECT 1 FROM "{padre}" p WHERE p."{columna_padre}" = h."{columna}") '
                    f'GROUP BY h."{columna}" ORDER BY cuantas DESC'
                )
                filas = conexion.execute(consulta).fetchall()
                if not filas:
                    continue
                problemas.append({
                    "tabla": tabla,
                    "columna": columna,
                    "referencia": f"{padre}.{columna_padre}",
                    "filas_huerfanas": sum(int(f.cuantas) for f in filas),
                    "valores_distintos": len(filas),
                    "ejemplos": [str(f.valor) for f in filas[:5]],
                    "detalle": (
                        f"{tabla}.{columna}: {sum(int(f.cuantas) for f in filas)} fila(s) "
                        f"apuntan a un registro de {padre} que no existe"
                    ),
                })
    return problemas


def _fk_ya_declaradas(conexion, tabla: str) -> int:
    """Cuantas claves foraneas tiene HOY la tabla en la base real."""
    return len(conexion.exec_driver_sql(f'PRAGMA foreign_key_list("{tabla}")').fetchall())


def _ddl_con_otro_nombre(tabla, dialecto, nombre_nuevo: str) -> str:
    """CREATE TABLE de `tabla` (con sus FK) pero con otro nombre.

    Se compila el DDL real desde el modelo -- asi las FK, los tipos y la PK
    salen exactamente como los declara models.py -- y se reemplaza UNICAMENTE el
    nombre que va inmediatamente despues de 'CREATE TABLE'. No se toca ningun
    otro texto del DDL, en particular las clausulas REFERENCES, que tienen que
    seguir apuntando a las tablas definitivas.
    """
    ddl = str(CreateTable(tabla).compile(dialect=dialecto))
    marca = f"CREATE TABLE {tabla.name} ("
    if marca not in ddl:
        raise RuntimeError(f"No se pudo reescribir el DDL de {tabla.name}: {ddl[:120]!r}")
    return ddl.replace(marca, f'CREATE TABLE "{nombre_nuevo}" (', 1)


def aplicar_claves_foraneas(engine, metadata=None) -> dict:
    """Recrea las tablas que necesitan claves foraneas. Nunca aborta el arranque.

    Devuelve un resumen con lo aplicado, lo salteado y por que.
    """
    if metadata is None:
        from database import Base
        metadata = Base.metadata

    plan = _plan_de_claves_foraneas(metadata)
    inspector = inspect(engine)
    tablas_reales = set(inspector.get_table_names())

    resumen = {"recreadas": [], "ya_estaban": [], "salteadas": [], "huerfanos": []}

    # ── Candado 1: huerfanos ────────────────────────────────────────────────
    huerfanos = verificar_huerfanos(engine, metadata)
    resumen["huerfanos"] = huerfanos
    tablas_sucias = {h["tabla"] for h in huerfanos}

    candidatas = []
    for nombre in [t.name for t in metadata.sorted_tables]:
        if nombre not in plan or nombre not in tablas_reales:
            continue

        with engine.connect() as conexion:
            ya = _fk_ya_declaradas(conexion, nombre)
        if ya >= len(plan[nombre]):
            resumen["ya_estaban"].append(nombre)
            continue

        if nombre in tablas_sucias:
            motivo = "; ".join(h["detalle"] for h in huerfanos if h["tabla"] == nombre)
            resumen["salteadas"].append({"tabla": nombre, "motivo": motivo})
            continue

        # ── Candado 3a: columnas desconocidas ───────────────────────────────
        columnas_modelo = {c.name for c in metadata.tables[nombre].columns}
        columnas_reales = {c["name"] for c in inspector.get_columns(nombre)}
        sobrantes = columnas_reales - columnas_modelo
        if sobrantes:
            resumen["salteadas"].append({
                "tabla": nombre,
                "motivo": (
                    f"la tabla real tiene columnas que el modelo no conoce "
                    f"({', '.join(sorted(sobrantes))}); recrearla las borraria"
                ),
            })
            continue

        candidatas.append(nombre)

    if not candidatas:
        if resumen["salteadas"]:
            _informar_salteadas(resumen["salteadas"])
        return resumen

    # ── La recreacion propiamente dicha ─────────────────────────────────────
    #
    # Va sobre una conexion cruda porque hay que manejar a mano el PRAGMA y la
    # transaccion: `PRAGMA foreign_keys` es un no-op dentro de una transaccion,
    # asi que se apaga ANTES del BEGIN y se vuelve a prender DESPUES del COMMIT.
    # Se apaga porque durante la copia las tablas hijas apuntan un rato a tablas
    # que se estan por recrear; al final se valida todo junto con
    # `PRAGMA foreign_key_check`.
    bruta = engine.raw_connection()
    try:
        cursor = bruta.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN")
        try:
            for nombre in candidatas:
                tabla = metadata.tables[nombre]
                temporal = f"{nombre}{SUFIJO_TEMPORAL}"
                columnas_modelo = [c.name for c in tabla.columns]
                columnas_reales = {c["name"] for c in inspector.get_columns(nombre)}
                # Se copian solo las columnas que existen en las dos puntas: una
                # columna nueva del modelo que todavia no esta en la base queda
                # con su valor por defecto, igual que con ADD COLUMN.
                comunes = [c for c in columnas_modelo if c in columnas_reales]
                lista = ", ".join(f'"{c}"' for c in comunes)

                antes = cursor.execute(f'SELECT COUNT(*) FROM "{nombre}"').fetchone()[0]

                cursor.execute(f'DROP TABLE IF EXISTS "{temporal}"')
                cursor.execute(_ddl_con_otro_nombre(tabla, engine.dialect, temporal))
                cursor.execute(
                    f'INSERT INTO "{temporal}" ({lista}) SELECT {lista} FROM "{nombre}"'
                )

                # ── Candado 3b: no se puede perder una fila ─────────────────
                despues = cursor.execute(f'SELECT COUNT(*) FROM "{temporal}"').fetchone()[0]
                if antes != despues:
                    raise RuntimeError(
                        f"Copiando {nombre}: habia {antes} filas y se copiaron {despues}"
                    )

                cursor.execute(f'DROP TABLE "{nombre}"')
                cursor.execute(f'ALTER TABLE "{temporal}" RENAME TO "{nombre}"')
                resumen["recreadas"].append(nombre)

            # ── Candado 1 bis: red de seguridad ─────────────────────────────
            # Ultima verificacion con el esquema YA nuevo, por si la de arriba
            # se quedo corta. Si aparece cualquier violacion, se deshace todo.
            violaciones = cursor.execute("PRAGMA foreign_key_check").fetchall()
            if violaciones:
                raise RuntimeError(
                    f"El esquema nuevo dejaria {len(violaciones)} violacion(es) de "
                    f"integridad; se deshace la migracion. Ejemplos: {violaciones[:5]}"
                )

            cursor.execute("COMMIT")
        except Exception as exc:
            cursor.execute("ROLLBACK")
            resumen["recreadas"] = []
            resumen["salteadas"].append({"tabla": "(todas)", "motivo": str(exc)})
            print(
                "[migraciones] NO se pudieron activar las claves foraneas; la base "
                f"quedo intacta. Motivo: {exc}"
            )
        finally:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    finally:
        bruta.close()

    if resumen["recreadas"]:
        print(
            f"[migraciones] Claves foraneas activadas en {len(resumen['recreadas'])} "
            f"tabla(s): {', '.join(resumen['recreadas'])}"
        )
    _informar_salteadas(resumen["salteadas"])
    return resumen


def _informar_salteadas(salteadas: list) -> None:
    """Informe legible por consola de lo que NO se pudo migrar."""
    if not salteadas:
        return
    print("[migraciones] ATENCION: quedaron tablas SIN clave foranea.")
    print("[migraciones] El sistema funciona igual, pero esas tablas no tienen")
    print("[migraciones] verificacion de integridad en la base. Detalle:")
    for s in salteadas:
        print(f"[migraciones]   - {s['tabla']}: {s['motivo']}")
    print("[migraciones] Vea GET /api/admin/verificar-integridad o la pantalla")
    print("[migraciones] Administracion > Estado de la Base de Datos.")


def dependientes(db, tabla: str, valor, metadata=None) -> list:
    """Que registros impiden borrar una ficha maestra, y cuantos son.

    Recorre el MISMO plan de claves foraneas que se uso para migrar (o sea, lo
    declarado en models.py) y busca quien apunta a `valor`. Al salir de la
    metadata y no de una lista escrita a mano, una relacion nueva queda cubierta
    sola, sin que nadie tenga que acordarse de actualizar este control.

    Sirve para contestar "no se puede borrar este cliente PORQUE tiene 3 facturas
    y 2 remitos" en vez de dejar que el motor tire un error 500 ilegible.
    Solo mira las relaciones RESTRICT: las CASCADE se borran solas y no son un
    impedimento.
    """
    if metadata is None:
        from database import Base
        metadata = Base.metadata

    encontrados = []
    for hija, claves in _plan_de_claves_foraneas(metadata).items():
        for columna, padre, _columna_padre, ondelete in claves:
            if padre != tabla or ondelete == "CASCADE":
                continue
            cuantas = db.execute(
                text(f'SELECT COUNT(*) FROM "{hija}" WHERE "{columna}" = :v'), {"v": valor}
            ).scalar() or 0
            if cuantas:
                encontrados.append({"tabla": hija, "columna": columna, "cantidad": int(cuantas)})
    return encontrados


def estado_claves_foraneas(engine, metadata=None) -> dict:
    """Que tablas tienen HOY sus claves foraneas activas. Solo lectura."""
    if metadata is None:
        from database import Base
        metadata = Base.metadata

    plan = _plan_de_claves_foraneas(metadata)
    tablas_reales = set(inspect(engine).get_table_names())

    con_fk, sin_fk = [], []
    with engine.connect() as conexion:
        verificacion_activa = bool(
            conexion.exec_driver_sql("PRAGMA foreign_keys").scalar()
        )
        for tabla, claves in sorted(plan.items()):
            if tabla not in tablas_reales:
                continue
            (con_fk if _fk_ya_declaradas(conexion, tabla) >= len(claves) else sin_fk).append(tabla)

    return {
        "verificacion_activa": verificacion_activa,
        "tablas_con_fk": con_fk,
        "tablas_sin_fk": sin_fk,
        "claves_declaradas": sum(len(v) for v in plan.values()),
    }


# ═════════════════════════════════════════════════════════════════════════════
# Identidad subrogada de clientes y proveedores
#
# EL PROBLEMA QUE RESUELVE
# ------------------------
# Hasta esta migracion la clave primaria de `clientes` y `proveedores` era el
# CUIT. Suena razonable --es unico por definicion-- y tiene una consecuencia que
# el comercio se come de verdad: un cliente cargado con el numero MAL TIPEADO
# que ya tiene facturas emitidas queda con ese numero para siempre. No se puede
# editar, porque la identidad de una fila no se edita y el endpoint de
# actualizacion ni siquiera acepta el campo. Y no se puede borrar y volver a
# cargar, porque tiene movimientos y la integridad referencial lo impide --con
# razon: los comprobantes emitidos no pueden quedar sin titular.
#
# El unico arreglo era editar el archivo .db a mano.
#
# QUE HACE
# --------
#   1. Le da a las dos tablas un `id` entero propio como clave primaria.
#   2. El identificador fiscal pasa a ser un atributo UNIQUE y obligatorio.
#   3. Agrega `tax_id_type` (CUIT / EIN), sembrado segun el pais configurado:
#      sin eso, una base no puede decir si "123456789" es un EIN o un CUIT a
#      medio cargar.
#   4. Recrea las 14 tablas hijas con ON UPDATE CASCADE, para que corregir un
#      identificador se propague a facturas, remitos, cobros y pagos en vez de
#      dejar filas huerfanas.
#
# POR QUE ESTA APARTE DE aplicar_claves_foraneas
# ----------------------------------------------
# Aquella decide que recrear contando cuantas FK declara la tabla real. Aca las
# FK ya estan declaradas: lo que cambia es su clausula ON UPDATE, que ese conteo
# no ve. Comparte los candados --recuento de filas, foreign_key_check y rollback
# total-- pero el disparador es otro.
# ═════════════════════════════════════════════════════════════════════════════

MARCA_IDENTIDAD = "identidad_subrogada_v1"

# Las dos tablas que cambian de clave primaria, y las hijas que las referencian.
_TABLAS_DE_IDENTIDAD = ("clientes", "proveedores")


def _hijas_de(metadata, padres: tuple) -> list:
    """Tablas con una FK hacia alguno de los padres, en orden de creacion."""
    salida = []
    for tabla in metadata.sorted_tables:
        for fk in tabla.foreign_keys:
            if fk.column.table.name in padres:
                salida.append(tabla.name)
                break
    return salida


def aplicar_identidad_subrogada(engine, metadata=None) -> dict:
    """Migra clientes/proveedores a clave primaria propia. Nunca aborta el arranque."""
    if metadata is None:
        from database import Base
        metadata = Base.metadata

    resumen = {"aplicada": False, "recreadas": [], "motivo": ""}

    inspector = inspect(engine)
    tablas_reales = set(inspector.get_table_names())
    if not set(_TABLAS_DE_IDENTIDAD) <= tablas_reales:
        resumen["motivo"] = "base nueva: las tablas se crean ya con el esquema actual"
        return resumen

    # Ya migrada: `clientes` tiene la columna id.
    columnas_clientes = {c["name"] for c in inspector.get_columns("clientes")}
    if "id" in columnas_clientes:
        resumen["motivo"] = "ya estaba"
        return resumen

    # Candado: un identificador duplicado o vacio impide poner el UNIQUE NOT
    # NULL. Se avisa y se deja la base como estaba, en vez de romper el arranque
    # del comercio a la manana.
    with engine.connect() as conexion:
        for tabla in _TABLAS_DE_IDENTIDAD:
            malos = conexion.execute(text(
                f'SELECT COUNT(*) FROM "{tabla}" WHERE cuit IS NULL OR TRIM(cuit) = ""'
            )).scalar()
            repetidos = conexion.execute(text(
                f'SELECT COUNT(*) FROM (SELECT cuit FROM "{tabla}" '
                f'GROUP BY cuit HAVING COUNT(*) > 1)'
            )).scalar()
            if malos or repetidos:
                resumen["motivo"] = (
                    f"{tabla}: {malos} fila(s) sin identificador y {repetidos} "
                    f"identificador(es) repetido(s). Corrijalos y reinicie."
                )
                print(f"[migraciones] identidad subrogada NO aplicada — {resumen['motivo']}")
                return resumen

    # El tipo de identificador que corresponde a esta instalacion.
    try:
        from paises import pais_configurado
        tipo = pais_configurado().identificador.nombre
    except Exception:
        tipo = "CUIT"

    candidatas = list(_TABLAS_DE_IDENTIDAD) + [
        t for t in _hijas_de(metadata, _TABLAS_DE_IDENTIDAD)
        if t in tablas_reales and t not in _TABLAS_DE_IDENTIDAD
    ]

    bruta = engine.raw_connection()
    try:
        cursor = bruta.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN")
        try:
            for nombre in candidatas:
                tabla = metadata.tables[nombre]
                temporal = f"{nombre}{SUFIJO_TEMPORAL}"
                columnas_modelo = [c.name for c in tabla.columns]
                columnas_reales = {c["name"] for c in inspector.get_columns(nombre)}
                comunes = [c for c in columnas_modelo if c in columnas_reales]
                origen = [f'"{c}"' for c in comunes]
                destino = list(origen)

                # `tax_id_type` es NOT NULL y NO existe en la tabla vieja, asi que
                # no entra en las columnas comunes. Hay que darle valor en el
                # mismo INSERT: sembrarlo despues con un UPDATE no sirve, porque
                # la restriccion se evalua al insertar. Este fue el primer
                # intento y fallaba con "NOT NULL constraint failed".
                parametros = ()
                if nombre in _TABLAS_DE_IDENTIDAD and "tax_id_type" not in columnas_reales:
                    destino.append('"tax_id_type"')
                    origen.append("?")
                    parametros = (tipo,)

                antes = cursor.execute(f'SELECT COUNT(*) FROM "{nombre}"').fetchone()[0]

                cursor.execute(f'DROP TABLE IF EXISTS "{temporal}"')
                cursor.execute(_ddl_con_otro_nombre(tabla, engine.dialect, temporal))
                cursor.execute(
                    f'INSERT INTO "{temporal}" ({", ".join(destino)}) '
                    f'SELECT {", ".join(origen)} FROM "{nombre}"',
                    parametros,
                )

                despues = cursor.execute(f'SELECT COUNT(*) FROM "{temporal}"').fetchone()[0]
                if antes != despues:
                    raise RuntimeError(
                        f"Copiando {nombre}: habia {antes} filas y se copiaron {despues}"
                    )

                cursor.execute(f'DROP TABLE "{nombre}"')
                cursor.execute(f'ALTER TABLE "{temporal}" RENAME TO "{nombre}"')
                resumen["recreadas"].append(nombre)

            violaciones = cursor.execute("PRAGMA foreign_key_check").fetchall()
            if violaciones:
                raise RuntimeError(
                    f"El esquema nuevo dejaria {len(violaciones)} violacion(es) de "
                    f"integridad; se deshace la migracion. Ejemplos: {violaciones[:5]}"
                )

            cursor.execute("COMMIT")
            resumen["aplicada"] = True
        except Exception as exc:
            cursor.execute("ROLLBACK")
            resumen["recreadas"] = []
            resumen["motivo"] = str(exc)
            print(
                "[migraciones] NO se pudo aplicar la identidad subrogada; la base "
                f"quedo intacta. Motivo: {exc}"
            )
        finally:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    finally:
        bruta.close()

    if resumen["aplicada"]:
        print(
            f"[migraciones] Identidad subrogada aplicada ({tipo}) en "
            f"{len(resumen['recreadas'])} tabla(s)."
        )
    return resumen
