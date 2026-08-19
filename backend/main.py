"""
ALdia - Backend API
Servidor FastAPI con SQLite real y SQLAlchemy ORM
"""
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError
import mimetypes
import os
import sys
import uvicorn

from database import engine, Base, SessionLocal, transaccion_de_escritura, DB_PATH
from errores import instalar_errores
from respaldo import respaldar_al_arrancar
from migraciones import aplicar_migraciones, aplicar_claves_foraneas
from routers import (
    auth, clientes, proveedores, stock, remitos, facturas,
    cobros, pagos, caja, gastos, iva, admin, modulos, config, compras, afip,
    pendientes,
)
from routers.auth import current_user_dep
from security import require_modulo

# Copia de seguridad del dia, ANTES de tocar nada.
#
# El orden no es casual: va antes de create_all y de las migraciones. Si una
# migracion sale mal, la copia que se necesita es la de ANTES de esa migracion;
# una copia posterior conserva el problema. Nunca aborta el arranque.
respaldar_al_arrancar(DB_PATH)

# Crear todas las tablas en la base de datos
Base.metadata.create_all(bind=engine)

# Agregar a las tablas ya existentes las columnas nuevas (ALTER TABLE ADD COLUMN,
# seguro en SQLite: no reescribe la tabla ni toca los datos del comercio).
aplicar_migraciones(engine)

# Poner las claves foraneas REALES en las tablas que ya existian. SQLite no
# permite agregar una FK con ALTER TABLE, asi que hay que recrear la tabla; el
# procedimiento -- y sobre todo la verificacion previa de huerfanos que decide si
# se aplica o no -- esta explicado en migraciones.py. Nunca aborta el arranque:
# si una tabla tiene datos que violarian las reglas nuevas, la deja como estaba y
# lo informa por consola y en /api/admin/verificar-integridad.
aplicar_claves_foraneas(engine)


def inicializar_datos():
    """Sembrar módulos, configuración y usuario admin por defecto en el primer arranque."""
    from models import Usuario
    from routers.modulos import seed_modulos
    from routers.config import seed_config
    from routers.auth import hash_password

    db = SessionLocal()
    try:
        seed_modulos(db)
        seed_config(db)
        # Crear usuario administrador por defecto si no existe ninguno.
        # Nace con debe_cambiar_password=True: puede iniciar sesion, pero el
        # sistema no lo deja operar hasta definir una contrasena propia. La de
        # fabrica esta publicada en el README, asi que dejarla puesta equivale
        # a no tener contrasena.
        if db.query(Usuario).count() == 0:
            db.add(Usuario(
                username="admin",
                password_hash=hash_password("admin123"),
                rol="administrador",
                debe_cambiar_password=True,
            ))
            db.commit()
    finally:
        db.close()


inicializar_datos()

# La documentacion interactiva describe toda la superficie de la API y facilita
# el trabajo de un atacante. Se publica solo si se pide explicitamente.
DOCS_PUBLICAS = os.getenv("ALDIA_DOCS", "").lower() in ("1", "true", "si")

app = FastAPI(
    title="ALdia API",
    description="Sistema de Gestión Comercial - Backend",
    version="2.0.0",
    docs_url="/docs" if DOCS_PUBLICAS else None,
    redoc_url="/redoc" if DOCS_PUBLICAS else None,
    openapi_url="/openapi.json" if DOCS_PUBLICAS else None,
)

# CORS: el frontend se sirve desde ESTE mismo servidor, asi que por defecto no
# hace falta habilitar ningun origen externo. Antes estaba en "*" junto con
# allow_credentials=True, combinacion invalida y permisiva que dejaba a
# cualquier sitio web hacer llamadas a la API con las credenciales del usuario.
# Si algun dia se sirve el frontend aparte, listar los origenes en
# ALDIA_ORIGINS separados por coma.
_origenes = [o.strip() for o in os.getenv("ALDIA_ORIGINS", "").split(",") if o.strip()]
if _origenes:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origenes,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


class TransaccionDeEscrituraMiddleware:
    """Marca las peticiones que escriben, para que su transaccion sea IMMEDIATE.

    Es el interruptor que hace que dos cajas facturando en el mismo segundo hagan
    fila en vez de pisarse (ver el encabezado de database.py). Va como middleware
    ASGI puro y no como `@app.middleware("http")` a proposito: BaseHTTPMiddleware
    ejecuta la aplicacion en OTRA tarea, y el ContextVar que se setea aca no
    llegaria al hilo donde corre la ruta. Un middleware ASGI puro comparte el
    contexto, y de ahi lo copia el pool de hilos de FastAPI.

    Se declara aca, envolviendo a toda la aplicacion, para que NINGUNA ruta de
    escritura -- ni las que se agreguen manana -- pueda quedarse afuera.
    """

    METODOS_DE_ESCRITURA = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        testigo = transaccion_de_escritura.set(
            scope.get("method", "GET") in self.METODOS_DE_ESCRITURA
        )
        try:
            await self.app(scope, receive, send)
        finally:
            transaccion_de_escritura.reset(testigo)


app.add_middleware(TransaccionDeEscrituraMiddleware)


# ─────────────────────────────────────────────────────────────
# Content-Security-Policy
#
# Es la unica cabecera que realmente CONTIENE un XSS: aunque un dato del
# comercio con HTML adentro llegue a la pantalla, el navegador se niega a
# ejecutarlo. Antes no se podia poner estricta porque Bootstrap venia de
# cdn.jsdelivr.net; ahora se sirve desde Web/vendor/, asi que todo lo que la
# pagina necesita sale de este mismo origen y la politica sale gratis.
#
# El porque de cada directiva -- sobre todo el de las excepciones, que son las
# que alguien va a querer sacar y no puede:
#
#   default-src 'self'        Piso de todo: nada se carga de un origen ajeno.
#   script-src 'self' 'unsafe-inline'
#                             FALLBACK para navegadores que no entienden
#                             script-src-elem/-attr. Los que si las entienden
#                             ignoran esta linea para scripts y aplican las dos
#                             de abajo; los que no, quedan como estaban antes de
#                             existir la CSP (ninguna proteccion perdida, pero
#                             tampoco los handlers rotos).
#   script-src-elem 'self'    Ningun <script> escrito dentro del HTML corre.
#                             Este es el vector que importa: es lo que un
#                             atacante inyecta en el nombre de un producto o en
#                             una descripcion. Por eso los placeholders
#                             defensivos de index.html se mudaron a
#                             Web/js/placeholders.js.
#   script-src-attr 'unsafe-inline'
#                             Sobreviven dos handlers en atributo:
#                             Web/js/utils.js (onclick del boton "Cancelar" del
#                             inputBox) y Web/js/modules/admin.js (onchange del
#                             selector de tipo de movimiento). Mientras existan,
#                             sacar esto rompe esas dos pantallas. Se aprieta a
#                             'none' el dia que se pasen a addEventListener.
#   style-src 'self' 'unsafe-inline'
#                             Los modulos arman su HTML con style="..." (mas de
#                             70 casos, casi todos en las vistas de impresion de
#                             remitos, facturas, recibos y pagos, que se
#                             escriben con document.write en la ventana nueva).
#                             Un atributo de estilo no ejecuta codigo: el riesgo
#                             real que queda es cosmetico.
#   style-src-elem 'self'     Lo que si se bloquea es un <style> inyectado, que
#                             sirve para tapar la pantalla o disfrazar un boton.
#                             Hoy no hay ninguno en el proyecto.
#   img-src 'self' data:      Una imagen data: es inerte y evita romper el dia
#                             que se embeba un logo o un QR; ningun origen externo.
#   font-src 'self'           Las tipografias de bootstrap-icons son locales.
#   connect-src 'self'        La API es este mismo origen (API_BASE = "/api" en
#                             Web/js/api.js). Si un XSS igual lograra correr, no
#                             tiene a donde mandarse los datos.
#   object-src 'none'         No hay Flash ni applets: no hay nada que permitir.
#   base-uri 'self'           Un <base href="http://malo/"> inyectado redirigiria
#                             TODAS las rutas relativas -- incluidas las de js/ --
#                             a otro servidor.
#   form-action 'self'        Un formulario inyectado no puede postear afuera.
#   frame-ancestors 'none'    Anti-clickjacking. Es la version moderna de
#                             X-Frame-Options, que se sigue mandando abajo para
#                             los navegadores que solo entienden aquella.
# ─────────────────────────────────────────────────────────────
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "script-src-elem 'self'",
    "script-src-attr 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "style-src-elem 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


@app.middleware("http")
async def cabeceras_de_seguridad(request, call_next):
    """Cabeceras defensivas para cuando el sistema se publica a internet."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"  # evita clickjacking
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    return response

# ─────────────────────────────────────────────────────────────
# Rutas de la API
#
# SEGURIDAD: cada router de datos lleva su control de acceso declarado ACA, a
# nivel de router, y no ruta por ruta. Antes ninguno lo tenia: se podia leer,
# escribir y borrar sin enviar ningun token. Al ponerlo en el include_router,
# toda ruta nueva que se agregue a esos modulos nace protegida.
#
# require_modulo(clave) valida contra la tabla `modulos` que el rol del usuario
# tenga acceso, y distingue lectura de escritura por el metodo HTTP (el rol
# auditor consulta todo pero no modifica nada).
# ─────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api/auth", tags=["Autenticación"])

app.include_router(
    clientes.router, prefix="/api/clientes", tags=["Clientes"],
    dependencies=[Depends(require_modulo("clientes"))],
)
app.include_router(
    proveedores.router, prefix="/api/proveedores", tags=["Proveedores"],
    dependencies=[Depends(require_modulo("proveedores"))],
)
app.include_router(
    stock.router, prefix="/api/stock", tags=["Stock"],
    dependencies=[Depends(require_modulo("stock"))],
)
app.include_router(
    remitos.router, prefix="/api/remitos", tags=["Remitos"],
    dependencies=[Depends(require_modulo("ventas"))],
)
app.include_router(
    facturas.router, prefix="/api/facturas", tags=["Facturas"],
    dependencies=[Depends(require_modulo("ventas"))],
)
# Factura electronica AFIP: solicitar un CAE es emitir un comprobante fiscal, o
# sea una operacion de VENTAS y de escritura. require_modulo("ventas") deja las
# consultas (GET /estado, /tipos-comprobante) al rol auditor y bloquea el POST.
app.include_router(
    afip.router, prefix="/api/afip", tags=["AFIP"],
    dependencies=[Depends(require_modulo("ventas"))],
)
app.include_router(
    cobros.router, prefix="/api/cobros", tags=["Cobros"],
    dependencies=[Depends(require_modulo("cuentas_corrientes"))],
)
app.include_router(
    pagos.router, prefix="/api/pagos", tags=["Pagos"],
    dependencies=[Depends(require_modulo("proveedores"))],
)
app.include_router(
    caja.router, prefix="/api/caja", tags=["Caja"],
    dependencies=[Depends(require_modulo("caja"))],
)
app.include_router(
    gastos.router, prefix="/api/gastos", tags=["Gastos"],
    dependencies=[Depends(require_modulo("gastos"))],
)
app.include_router(
    iva.router, prefix="/api/iva", tags=["IVA"],
    dependencies=[Depends(require_modulo("iva"))],
)
# admin: el dashboard lo consulta CUALQUIER usuario logueado al entrar, asi que
# aca solo se exige estar autenticado. Las rutas peligrosas de este router
# (reset-db, seed-data, db-info, eliminar movimientos) llevan require_admin
# declarado individualmente en routers/admin.py.
app.include_router(
    admin.router, prefix="/api/admin", tags=["Administración"],
    dependencies=[Depends(current_user_dep)],
)
# Operaciones que esperan una aclaracion. Solo exige estar autenticado: lo que
# se puede o no ejecutar lo decide la ruta original al reejecutarse.
app.include_router(
    pendientes.router, prefix="/api/pendientes", tags=["Pendientes"],
    dependencies=[Depends(current_user_dep)],
)
app.include_router(modulos.router, prefix="/api/modulos", tags=["Módulos"])
app.include_router(config.router, prefix="/api/config", tags=["Configuración"])
app.include_router(
    compras.router, prefix="/api/compras", tags=["Compras"],
    dependencies=[Depends(require_modulo("proveedores"))],
)
app.include_router(
    compras.router_devoluciones, prefix="/api/devoluciones", tags=["Devoluciones"],
    dependencies=[Depends(require_modulo("proveedores"))],
)


@app.exception_handler(IntegrityError)
async def error_de_integridad(request, exc):  # noqa: ARG001
    """Traduce una violacion de integridad de la base a un error entendible.

    Ahora que las claves foraneas se verifican de verdad (ver database.py), la
    base puede rechazar una operacion que antes pasaba. Sin esto, el usuario
    veria un 500 "Internal Server Error" y el mensaje real quedaria solo en la
    consola del servidor, que en una instalacion de comercio nadie mira.

    Es una RED DE SEGURIDAD, no el control principal: cada ruta valida antes lo
    que le corresponde y devuelve un 404/409 con el detalle concreto. Esto cubre
    los casos que se escapen y, sobre todo, las rutas que se agreguen manana.
    409 (conflicto) y no 400: el pedido esta bien formado, lo que no se puede es
    aplicarlo contra el estado actual de la base.
    """
    detalle = str(getattr(exc, "orig", exc))
    if "FOREIGN KEY" in detalle.upper():
        mensaje = (
            "La operacion dejaria un registro apuntando a un cliente, proveedor o "
            "producto que no existe, o intenta borrar una ficha que todavia tiene "
            "movimientos. Verifique los datos antes de reintentar."
        )
    elif "UNIQUE" in detalle.upper():
        mensaje = "Ya existe un registro con esa clave: no se puede duplicar."
    else:
        mensaje = "La operacion viola una regla de integridad de la base de datos."
    print(f"[integridad] {request.method} {request.url.path}: {detalle}", file=sys.stderr)
    return JSONResponse(status_code=409, content={"detail": mensaje})


@app.get("/api/health")
def health_check():
    return {"status": "ok", "message": "ALdia API running"}


# ─────────────────────────────────────────────────────────────
# Registro de auditoria (quien hizo que y cuando)
#
# Una sola llamada instala todo: la tabla `auditoria` (en su propio MetaData,
# fuera del alcance de reset-db), el middleware que registra AUTOMATICAMENTE
# toda escritura POST/PUT/PATCH/DELETE a /api/* -- exitosa o rechazada -- y el
# router de consulta, que es de solo lectura a proposito.
#
# Va DESPUES de todos los include_router para que el middleware envuelva a la
# aplicacion entera, y ANTES del mount de archivos estaticos.
#
# Toda la logica vive en backend/auditoria.py y backend/routers/auditoria.py:
# ninguna ruta necesita acordarse de auditar, y por eso ninguna ruta nueva puede
# quedar sin auditar por olvido.
# ─────────────────────────────────────────────────────────────
from auditoria import instalar_auditoria  # noqa: E402

instalar_auditoria(app)

# Codigos de error de maquina. Va DESPUES de todos los include_router para que
# el manejador cubra a la aplicacion entera, incluidas las rutas de auditoria.
# Sin esto, un agente tiene que adivinar leyendo castellano si un error se
# reintenta, se corrige o se abandona (ver backend/errores.py).
instalar_errores(app)


# Los tipos MIME de las tipografias no vienen en la tabla de Python (y en
# Windows, ademas, la tabla se completa con lo que diga el registro, que varia de
# PC en PC). Sin esto, StaticFiles sirve los .woff/.woff2 de Web/vendor/ como
# "text/plain" y los iconos quedan a merced de que el navegador de turno sea
# tolerante. Se declaran a mano para que la instalacion se comporte igual en
# cualquier maquina del comercio.
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/woff2", ".woff2")

# Servir archivos estáticos (frontend) usando ruta absoluta al directorio Web.
# IMPORTANTE: el mount en "/" debe declararse al final, después de todas las
# rutas /api/*, porque actúa como catch-all de las rutas no coincidentes.
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Web")
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="static")


if __name__ == "__main__":
    host = os.getenv("ALDIA_HOST", "0.0.0.0")
    port = int(os.getenv("ALDIA_PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=False)
