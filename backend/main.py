"""
ALdia - Backend API
Servidor FastAPI con SQLite real y SQLAlchemy ORM
"""
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import uvicorn

from database import engine, Base, SessionLocal
from migraciones import aplicar_migraciones
from routers import (
    auth, clientes, proveedores, stock, remitos, facturas,
    cobros, pagos, caja, gastos, iva, admin, modulos, config, compras, afip
)
from routers.auth import current_user_dep
from security import require_modulo

# Crear todas las tablas en la base de datos
Base.metadata.create_all(bind=engine)

# Agregar a las tablas ya existentes las columnas nuevas (ALTER TABLE ADD COLUMN,
# seguro en SQLite: no reescribe la tabla ni toca los datos del comercio).
aplicar_migraciones(engine)


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
        # Crear usuario administrador por defecto si no existe ninguno
        if db.query(Usuario).count() == 0:
            db.add(Usuario(
                username="admin",
                password_hash=hash_password("admin123"),
                rol="administrador",
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


@app.middleware("http")
async def cabeceras_de_seguridad(request, call_next):
    """Cabeceras defensivas para cuando el sistema se publica a internet."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"  # evita clickjacking
    response.headers["Referrer-Policy"] = "same-origin"
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


# Servir archivos estáticos (frontend) usando ruta absoluta al directorio Web.
# IMPORTANTE: el mount en "/" debe declararse al final, después de todas las
# rutas /api/*, porque actúa como catch-all de las rutas no coincidentes.
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Web")
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="static")


if __name__ == "__main__":
    host = os.getenv("ALDIA_HOST", "0.0.0.0")
    port = int(os.getenv("ALDIA_PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=False)
