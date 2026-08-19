"""
errores.py - Errores con codigo de maquina, para que un agente pueda decidir.

EL PROBLEMA QUE RESUELVE
========================
Los mensajes de error de ALdia estan escritos para una persona: "Stock
insuficiente de 'Coca 2.25': se intentan facturar 12 y hay 5". Eso esta bien y
no se toca — el duenio del comercio lo lee y entiende.

Pero cuando del otro lado hay un agente, ese texto es todo lo que tiene para
decidir que hacer, y decidir mal cuesta plata:

  * Si REINTENTA un error que no era transitorio, repite el pedido para siempre.
  * Si NO reintenta uno que si lo era, pierde una venta que iba a entrar sola.
  * Si le PREGUNTA al usuario por algo que podia arreglar solo, lo interrumpe al
    pedo. Si NO le pregunta cuando debia, inventa un dato.

Parsear castellano para eso es adivinar. Y el dia que alguien corrija una tilde
del mensaje, el agente cambia de comportamiento sin que nadie lo note.

QUE SE AGREGA
=============
Dos campos al cuerpo del error, sin tocar `detail`:

    {
      "detail": "Stock insuficiente de 'Coca 2.25': ...",   <- la persona
      "codigo": "STOCK_INSUFICIENTE",                        <- la maquina
      "accion": "corregir"                                   <- que hacer
    }

`codigo` es un identificador ESTABLE. Cambiar el texto de `detail` es libre;
cambiar un `codigo` es romper el contrato con los agentes conectados.

`accion` es la parte util: dice que corresponde hacer, y es un conjunto cerrado
de cuatro valores. Existe para que un agente nuevo se comporte bien sin tener
que conocer el catalogo entero.

    reintentar  El pedido estaba bien y puede salir solo. Esperar y repetir.
    corregir    Falta o sobra un dato, y el agente PUEDE arreglarlo con lo que
                ya sabe (el producto no existe, el importe no cierra).
    preguntar   Falta una decision que el agente NO puede tomar por su cuenta:
                una ambiguedad, una confirmacion explicita.
    abortar     No va a funcionar por mas que se insista. No hay permiso, o la
                operacion ya se hizo. Reintentar es siempre un error.

POR QUE NO HUBO QUE TOCAR LAS 86 EXCEPCIONES DEL SISTEMA
========================================================
Migrar sitio por sitio habria dejado la mitad del sistema sin codigo por meses,
que es la peor version de esto: un agente no puede confiar en un campo que a
veces esta. Asi que el codigo se resuelve en DOS pasos:

  1. Si la excepcion es un `ErrorDeNegocio`, usa el codigo preciso que se le
     puso (`STOCK_INSUFICIENTE`, `CAE_YA_EMITIDO`).
  2. Si es una `HTTPException` comun — las 86 de siempre y las que se escriban
     manana — se le deriva un codigo generico del estado HTTP
     (404 -> NO_ENCONTRADO, 403 -> SIN_PERMISO).

Asi TODO error tiene codigo y accion desde el primer dia, y los codigos precisos
se van agregando donde aportan, sin dejar huecos en el medio.
"""
from __future__ import annotations

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as HTTPExceptionStarlette

__all__ = [
    "ErrorDeNegocio", "CATALOGO", "ACCIONES",
    "codigo_y_accion", "cuerpo_de_error", "instalar_errores",
]

# Las cuatro acciones posibles. Conjunto CERRADO a proposito: si manana hace
# falta una quinta, es una decision de diseno, no algo que se agregue al pasar.
REINTENTAR = "reintentar"
CORREGIR = "corregir"
PREGUNTAR = "preguntar"
ABORTAR = "abortar"

ACCIONES = (REINTENTAR, CORREGIR, PREGUNTAR, ABORTAR)


# ─────────────────────────────────────────────────────────────────────────────
# El catalogo: codigo -> (estado HTTP, accion, para que sirve)
#
# El tercer campo no es decoracion: es lo que se publica en
# GET /api/errores para que un agente pueda leer el catalogo entero en vez de
# que se lo tengan que explicar en el prompt.
# ─────────────────────────────────────────────────────────────────────────────
CATALOGO: dict[str, tuple[int, str, str]] = {
    # ── Identidad y permisos ──────────────────────────────────────────────
    "NO_AUTENTICADO": (401, ABORTAR,
        "No se envio token, o no es valido."),
    "SESION_VENCIDA": (401, ABORTAR,
        "El token vencio o la contrasena cambio despues de emitirlo. "
        "Hay que volver a iniciar sesion; reintentar con el mismo token no sirve."),
    "CREDENCIALES_INVALIDAS": (401, ABORTAR,
        "Usuario o contrasena incorrectos."),
    "DEBE_CAMBIAR_PASSWORD": (403, CORREGIR,
        "La cuenta todavia tiene la contrasena inicial. Lo unico que puede "
        "hacer es POST /api/auth/cambiar-password."),
    "SIN_PERMISO": (403, ABORTAR,
        "El rol no tiene acceso a este modulo. Insistir no cambia nada: hace "
        "falta que un administrador otorgue el permiso."),
    "SOLO_LECTURA": (403, ABORTAR,
        "El rol auditor puede consultar todo pero no modificar nada."),
    "NO_PUEDE_ACTUAR_POR": (403, ABORTAR,
        "La cuenta no tiene permiso para operar a nombre de otra persona. Un "
        "administrador debe otorgarlo con POST /api/auth/usuarios/{id}/actuar-por."),
    "ACTOR_INEXISTENTE": (400, CORREGIR,
        "La persona declarada en X-Actor-User-Id no existe. La operacion no se "
        "ejecuta para no quedar atribuida a nadie."),
    "DEMASIADOS_INTENTOS": (429, REINTENTAR,
        "Se supero el limite de intentos de login. Esperar y reintentar."),

    # ── Cosas que no estan ────────────────────────────────────────────────
    "NO_ENCONTRADO": (404, CORREGIR,
        "El registro pedido no existe. Generico: cuando se sabe QUE falta, se "
        "usa el codigo especifico."),
    "CLIENTE_NO_EXISTE": (404, CORREGIR,
        "El cliente indicado no esta dado de alta. Darlo de alta o elegir otro."),
    "PROVEEDOR_NO_EXISTE": (404, CORREGIR,
        "El proveedor indicado no esta dado de alta."),
    "PRODUCTO_NO_EXISTE": (404, CORREGIR,
        "El articulo indicado no existe en el stock."),
    "COMPROBANTE_NO_ENCONTRADO": (404, CORREGIR,
        "No existe el comprobante con ese numero."),

    # ── Reglas del negocio ────────────────────────────────────────────────
    "STOCK_INSUFICIENTE": (400, CORREGIR,
        "No hay existencia suficiente. El mensaje dice cuanto hay: se puede "
        "reducir la cantidad, o preguntarle al usuario si quiere facturar igual."),
    "YA_EXISTE": (400, CORREGIR,
        "Ya hay un registro con esa clave. No se puede duplicar."),
    "TIENE_MOVIMIENTOS": (409, ABORTAR,
        "No se puede eliminar la ficha porque tiene comprobantes asociados. Los "
        "comprobantes emitidos no pueden quedar sin titular."),
    "IMPORTES_NO_CIERRAN": (400, CORREGIR,
        "La suma de los renglones no coincide con el total declarado."),
    "CONFIRMACION_REQUERIDA": (400, PREGUNTAR,
        "La operacion sobrescribe datos y exige una confirmacion textual "
        "explicita. Es una decision de una persona: el agente no debe inventarla."),
    "DATOS_INVALIDOS": (422, CORREGIR,
        "Un campo no pasa la validacion (CUIT, alicuota de IVA, importe)."),
    "CONFLICTO_DE_INTEGRIDAD": (409, CORREGIR,
        "La operacion dejaria un registro apuntando a algo que no existe, o "
        "borraria una ficha que todavia tiene movimientos."),

    # ── Reglas que dependen del pais ──────────────────────────────────────
    "PAIS_NO_SOPORTADO": (400, CORREGIR,
        "Se pidio configurar un pais para el que no hay paquete de reglas "
        "fiscales. GET /api/config/pais informa cual esta vigente."),
    "OPERACION_NO_APLICA_EN_ESTE_PAIS": (409, ABORTAR,
        "La operacion existe pero no tiene sentido con las reglas fiscales de "
        "esta instalacion: pedir un CAE en un pais sin autorizacion previa de "
        "comprobantes, por ejemplo. No es un error a corregir ni a reintentar."),

    # ── Factura electronica ───────────────────────────────────────────────
    "CAE_YA_EMITIDO": (409, ABORTAR,
        "El comprobante ya tiene CAE. Pedir otro duplicaria la declaracion ante "
        "AFIP: nunca reintentar."),
    "FALTA_CAE": (409, CORREGIR,
        "El comprobante todavia no fue autorizado por AFIP."),
    "TIPO_COMPROBANTE_INVALIDO": (400, CORREGIR,
        "El tipo de comprobante no esta soportado. El mensaje lista los validos."),
    "AFIP_NO_DISPONIBLE": (503, REINTENTAR,
        "No se pudo hablar con AFIP. Es transitorio: reintentar mas tarde CON EL "
        "MISMO X-Operation-Id, porque puede que AFIP si lo haya procesado."),
    "AFIP_RECHAZO": (400, CORREGIR,
        "AFIP rechazo el comprobante. El mensaje trae el motivo que devolvio."),

    # ── Operaciones repetidas (ver idempotencia.py) ───────────────────────
    "OPERACION_EN_CURSO": (409, REINTENTAR,
        "Otra peticion con el mismo X-Operation-Id se esta ejecutando ahora. "
        "Esperar unos segundos y repetir: se va a devolver su resultado."),
    "OPERACION_CONFLICTIVA": (409, CORREGIR,
        "El X-Operation-Id ya se uso para una operacion DISTINTA. Usar uno nuevo."),

    # ── Operaciones que esperan una aclaracion (ver pendientes.py) ────────
    "ACLARACION_REQUERIDA": (409, PREGUNTAR,
        "La operacion quedo guardada porque hay una ambiguedad que solo el "
        "usuario puede resolver. Preguntarle y confirmar la pendiente."),
    "PENDIENTE_VENCIDA": (409, ABORTAR,
        "La operacion pendiente vencio. Hay que volver a armarla."),
}


# Codigo generico segun el estado HTTP, para toda HTTPException que no declare
# el suyo. Ver "POR QUE NO HUBO QUE TOCAR LAS 86 EXCEPCIONES" en el encabezado.
_POR_ESTADO: dict[int, str] = {
    400: "DATOS_INVALIDOS",
    401: "NO_AUTENTICADO",
    403: "SIN_PERMISO",
    404: "NO_ENCONTRADO",
    409: "CONFLICTO_DE_INTEGRIDAD",
    422: "DATOS_INVALIDOS",
    429: "DEMASIADOS_INTENTOS",
    503: "AFIP_NO_DISPONIBLE",
}

# Que hacer cuando ni siquiera el estado esta en la tabla. 5xx es del servidor y
# suele ser transitorio; 4xx es de quien llama y repetir igual no lo arregla.
_ACCION_POR_DEFECTO_5XX = REINTENTAR
_ACCION_POR_DEFECTO_4XX = CORREGIR


class ErrorDeNegocio(HTTPException):
    """Una HTTPException que ademas dice QUE paso y QUE conviene hacer.

    Se usa igual que HTTPException, pero con el codigo del catalogo adelante:

        raise ErrorDeNegocio(
            "STOCK_INSUFICIENTE",
            f"Stock insuficiente de '{p.producto}': se piden {n} y hay {hay}",
        )

    El estado HTTP sale del catalogo, asi que un mismo codigo no puede contestar
    404 en un router y 400 en otro — que es exactamente la clase de
    inconsistencia que vuelve inservible un codigo de maquina. Se puede forzar
    con `estado=` para no cambiar el comportamiento de una ruta ya existente,
    pero si hace falta seguido, lo que esta mal es el catalogo.
    """

    def __init__(self, codigo: str, detail: str, estado: int | None = None):
        if codigo not in CATALOGO:
            # Un codigo fuera del catalogo es un error de programacion, no algo
            # que deba llegarle al agente: se avisa fuerte y en el acto.
            raise ValueError(
                f"Codigo de error desconocido: {codigo!r}. "
                f"Agregalo a CATALOGO en backend/errores.py."
            )
        estado_catalogo, accion, _ = CATALOGO[codigo]
        super().__init__(status_code=estado or estado_catalogo, detail=detail)
        self.codigo = codigo
        self.accion = accion


def codigo_y_accion(exc: HTTPException) -> tuple[str, str]:
    """El (codigo, accion) de cualquier excepcion HTTP, la declare o no."""
    codigo = getattr(exc, "codigo", None)
    if codigo and codigo in CATALOGO:
        return codigo, CATALOGO[codigo][1]

    estado = getattr(exc, "status_code", 500)
    generico = _POR_ESTADO.get(estado)
    if generico:
        return generico, CATALOGO[generico][1]

    accion = _ACCION_POR_DEFECTO_5XX if estado >= 500 else _ACCION_POR_DEFECTO_4XX
    return "ERROR_INTERNO" if estado >= 500 else "ERROR", accion


def cuerpo_de_error(exc: HTTPException) -> dict:
    """El JSON que se le devuelve a quien llama.

    `detail` va primero y sin cambios: es lo que ya leen el frontend y las
    personas, y romperlo no aporta nada.
    """
    codigo, accion = codigo_y_accion(exc)
    return {"detail": exc.detail, "codigo": codigo, "accion": accion}


def instalar_errores(app) -> None:
    """Engancha los manejadores y publica el catalogo. Unico punto a tocar en main.py."""

    # Se engancha a la HTTPException de STARLETTE y no a la de FastAPI porque la
    # de FastAPI hereda de esa: enganchando la base quedan cubiertas las dos, mas
    # ErrorDeNegocio, mas las que levanta el propio framework.
    @app.exception_handler(HTTPExceptionStarlette)
    async def _manejar(request, exc: HTTPExceptionStarlette):  # noqa: ARG001
        # `headers` importa: el 401 lleva WWW-Authenticate y sin esto se perderia.
        return JSONResponse(
            status_code=exc.status_code,
            content=cuerpo_de_error(exc),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _manejar_validacion(request, exc: RequestValidationError):  # noqa: ARG001
        """Los 422 de Pydantic, que son los que mas pega un agente.

        Es el error de "mandaste un campo mal" y hasta ahora salia sin codigo,
        porque lo genera el framework antes de entrar a la ruta. Se conserva el
        `detail` estructurado tal cual --el agente lo necesita para saber QUE
        campo esta mal-- y se le agregan los dos campos de siempre.
        """
        return JSONResponse(
            status_code=422,
            content={
                "detail": jsonable_encoder(exc.errors()),
                "codigo": "DATOS_INVALIDOS",
                "accion": CORREGIR,
            },
        )

    @app.get("/api/errores", tags=["Errores"])
    def listar_errores():
        """El catalogo completo, para que un agente lo lea en vez de adivinar.

        Es publico y de solo lectura a proposito: no revela nada del comercio
        --son las mismas reglas que ya estan en el codigo fuente-- y un agente
        tiene que poder consultarlo antes de autenticarse, cuando justamente
        puede estar recibiendo un 401 que no sabe interpretar.
        """
        return {
            "acciones": {
                REINTENTAR: "El pedido estaba bien y puede salir solo. Esperar y repetir.",
                CORREGIR: "Falta o sobra un dato que el agente puede arreglar.",
                PREGUNTAR: "Hace falta una decision que el agente no puede tomar.",
                ABORTAR: "No va a funcionar por mas que se insista.",
            },
            "errores": [
                {"codigo": c, "http": e, "accion": a, "significado": d}
                for c, (e, a, d) in sorted(CATALOGO.items())
            ],
        }
