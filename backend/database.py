"""
database.py - Configuración de SQLAlchemy y conexión a SQLite real

POR QUE ESTE ARCHIVO TIENE MAS DE CUATRO LINEAS
===============================================
SQLite viene configurado, por compatibilidad historica, de una forma que NO
sirve para un sistema con varias terminales escribiendo a la vez. Dos ajustes
son imprescindibles y los dos se hacen aca, en un solo lugar, para que ninguna
parte del codigo tenga que acordarse de nada:

  1. `PRAGMA foreign_keys=ON`
     SQLite trae la verificacion de claves foraneas APAGADA por defecto: acepta
     las clausulas REFERENCES en el CREATE TABLE y despues no las controla. Hay
     que encenderla en CADA conexion (no es una propiedad del archivo, es de la
     conexion), y por eso va enganchada al evento `connect` del pool: cualquier
     conexion nueva -- incluidas las que abre el pool despues de un reciclado --
     nace con la verificacion activa. Sin esto, las ForeignKey de models.py
     serian decoracion.

  2. `BEGIN IMMEDIATE` en las transacciones de ESCRITURA (+ WAL)
     Este es el arreglo de fondo de la numeracion de comprobantes. El driver de
     SQLite abre las transacciones en modo DIFERIDO: la transaccion arranca
     leyendo y recien pide el lock de escritura cuando llega el primer INSERT.
     Con dos cajas facturando al mismo tiempo eso significa que las dos LEEN el
     mismo estado y despues las dos intentan escribir; la segunda choca contra
     la PRIMARY KEY (o contra el lock) y la venta se pierde con un error 500.
     Medido en este sistema antes del arreglo: de 12 facturas emitidas
     simultaneamente entraban 3 y se perdian 9.

     `BEGIN IMMEDIATE` toma el lock de escritura al PRINCIPIO. Las escrituras
     hacen fila de a una (SQLite ya las serializa igual) en vez de pisarse, y lo
     que cada una lee ya es definitivo. Combinado con `busy_timeout`, la segunda
     caja espera unos milisegundos en lugar de fallar.

     COSTO: una escritura larga bloquea a las demas ESCRITURAS mientras dura.
     Para acotarlo, el modo IMMEDIATE se aplica SOLO a las peticiones HTTP de
     escritura (POST/PUT/PATCH/DELETE); los GET siguen usando transacciones
     diferidas. Y con WAL activado, esos GET ni siquiera se bloquean contra la
     escritura en curso: en WAL los lectores no esperan al escritor. En el modo
     `delete` anterior, un lector si bloqueaba el COMMIT del escritor.

NOTA SOBRE EL RESPALDO
======================
WAL agrega dos archivos al lado de la base: `aldia.db-wal` y `aldia.db-shm`.
Con el servidor DETENIDO, SQLite hace checkpoint y todo queda dentro de
`aldia.db`, asi que el respaldo sigue siendo "copiar el archivo". Si se copia con
el servidor ANDANDO, hay que copiar los tres archivos o usar `.backup` de la
herramienta sqlite3; copiar solo `aldia.db` en caliente puede dejar afuera las
ultimas operaciones.
"""
import os
from contextvars import ContextVar

from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Ruta de la base de datos SQLite en disco.
# Por defecto, `backend/aldia.db` (el comportamiento de siempre). Se puede
# apuntar a otro archivo con ALDIA_DB, que es lo que se usa para levantar una
# instancia de pruebas sin tocar la base real del comercio.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("ALDIA_DB") or os.path.join(BASE_DIR, "aldia.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Cuanto espera una escritura a que se libere el lock antes de darse por vencida.
# 10 segundos es holgadisimo para el tipo de operacion de este sistema (emitir un
# comprobante son milisegundos) y evita que una caja vea un error porque otra
# estaba grabando en ese instante.
BUSY_TIMEOUT_MS = int(os.getenv("ALDIA_BUSY_TIMEOUT_MS", "10000"))

# Crear motor con check_same_thread=False para SQLite
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False  # Poner True para ver los queries SQL en consola
)


# ─────────────────────────────────────────────────────────────────────────────
# Marca de "esta peticion escribe".
#
# La setea `TransaccionDeEscrituraMiddleware` (ver main.py) leyendo el metodo
# HTTP, y la lee el evento `begin` de mas abajo para decidir si la transaccion
# arranca en modo IMMEDIATE. Es un ContextVar y no un threading.local porque
# FastAPI ejecuta las rutas sincronicas en un pool de hilos: el contexto se
# copia al hilo trabajador, un thread-local no viajaria.
#
# El valor por defecto es False a proposito: cualquier codigo que no pase por el
# middleware (migraciones del arranque, scripts, el propio create_all) usa
# transacciones normales, que es lo correcto porque ahi no hay concurrencia.
# ─────────────────────────────────────────────────────────────────────────────
transaccion_de_escritura: ContextVar[bool] = ContextVar(
    "aldia_transaccion_de_escritura", default=False
)


@event.listens_for(engine, "connect")
def _configurar_conexion(dbapi_connection, connection_record):  # noqa: ARG001
    """Se ejecuta UNA VEZ POR CONEXION, apenas se abre.

    Es el unico lugar donde se puede activar la verificacion de claves foraneas:
    `PRAGMA foreign_keys` es por conexion, no por archivo. Si esto no corre, las
    FK declaradas en models.py no se controlan y la base vuelve a aceptar un
    remito de un cliente que no existe.
    """
    # El driver deja de manejar las transacciones por su cuenta para que las
    # abra SQLAlchemy en el evento `begin` (unica forma de elegir IMMEDIATE).
    dbapi_connection.isolation_level = None

    cursor = dbapi_connection.cursor()
    try:
        # (1) Integridad referencial. Ver el encabezado del archivo.
        cursor.execute("PRAGMA foreign_keys=ON")
        # (2) WAL: los lectores no bloquean al escritor ni al reves. Es una
        #     propiedad persistente del archivo, pero se pide en cada conexion
        #     porque es idempotente y asi una base nueva tambien queda en WAL.
        cursor.execute("PRAGMA journal_mode=WAL")
        # (3) Esperar en vez de fallar cuando otra terminal esta escribiendo.
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        # (4) En WAL, NORMAL es seguro ante caida del proceso (que es el riesgo
        #     real: se cierra la ventana del .bat) y evita un fsync por commit.
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


@event.listens_for(engine, "begin")
def _abrir_transaccion(conexion):
    """Abre la transaccion, en modo IMMEDIATE si la peticion va a escribir.

    Con `isolation_level = None` el driver ya no emite el BEGIN, asi que lo
    emitimos aca y de paso elegimos el modo. Ver el punto 2 del encabezado.
    """
    if transaccion_de_escritura.get():
        conexion.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        conexion.exec_driver_sql("BEGIN")


# SessionFactory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para los modelos
Base = declarative_base()


# Dependencia para obtener la sesión de DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
