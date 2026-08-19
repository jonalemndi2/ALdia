"""
security.py - Nucleo de seguridad de ALdia.

Reune tres cosas que antes faltaban o estaban mal resueltas:

1. SECRET_KEY persistente y unica por instalacion (antes estaba hardcodeada en
   el codigo fuente, con lo cual cualquiera que viera el repo podia fabricarse
   un token de administrador).
2. Autorizacion por modulo y rol del lado del SERVIDOR (antes solo se ocultaban
   items del menu en el navegador, lo cual se saltea llamando a la API directo).
3. Limite de intentos de login, para que exponer el sistema a internet no
   habilite un ataque de fuerza bruta contra las contrasenas.
4. IP real del que llama cuando hay un proxy inverso adelante, porque sin eso
   el limite del punto 3 se vuelve global y cualquiera deja al comercio entero
   afuera con ocho logins fallidos.
"""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from collections import defaultdict
from datetime import datetime, timedelta
import os
import secrets
import stat
import threading

from errores import ErrorDeNegocio
from database import get_db
from tiempo import ahora_utc
from models import Modulo, Usuario


# ─────────────────────────────────────────────────────────────
# 1. Clave secreta persistente
# ─────────────────────────────────────────────────────────────

_SECRET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".aldia_secret")


def _cargar_o_crear_secret() -> str:
    """Devuelve la SECRET_KEY del JWT.

    Prioridad:
      1. Variable de entorno ALDIA_SECRET_KEY (recomendado en produccion).
      2. Archivo .aldia_secret junto a la base de datos.
      3. Se genera una clave aleatoria nueva y se guarda en ese archivo.

    El paso 3 existe para que el sistema se pueda arrancar con doble clic en
    iniciar_web.bat sin configurar nada, pero SIN caer en una clave por defecto
    conocida: cada instalacion termina con una clave distinta e impredecible.
    """
    desde_entorno = os.getenv("ALDIA_SECRET_KEY")
    if desde_entorno and desde_entorno.strip():
        return desde_entorno.strip()

    if os.path.exists(_SECRET_FILE):
        try:
            with open(_SECRET_FILE, "r", encoding="utf-8") as fh:
                guardada = fh.read().strip()
            if guardada:
                return guardada
        except OSError:
            pass

    nueva = secrets.token_urlsafe(64)
    try:
        with open(_SECRET_FILE, "w", encoding="utf-8") as fh:
            fh.write(nueva)
        # Restringir el archivo al usuario actual en la medida en que el SO lo permita.
        try:
            os.chmod(_SECRET_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    except OSError:
        # Si el disco es de solo lectura, seguimos en memoria: la clave dura lo
        # que dure el proceso (obliga a reloguear tras reiniciar, pero es segura).
        pass
    return nueva


SECRET_KEY = _cargar_o_crear_secret()


# ─────────────────────────────────────────────────────────────
# 2. Autorizacion por modulo y rol
# ─────────────────────────────────────────────────────────────

# Rol que puede leer todo pero no debe escribir nada.
ROL_SOLO_LECTURA = "auditor"


def _roles_del_modulo(db: Session, clave: str) -> list[str]:
    modulo = db.query(Modulo).filter(Modulo.clave == clave).first()
    if not modulo:
        # Modulo desconocido: por defecto negamos a todos menos al administrador.
        return []
    if not modulo.habilitado:
        return []
    return [r.strip().lower() for r in (modulo.roles or "").split(",") if r.strip()]


METODOS_DE_ESCRITURA = {"POST", "PUT", "PATCH", "DELETE"}


def require_modulo(clave: str):
    """Dependencia FastAPI: exige acceso al modulo `clave` segun el rol del usuario.

    Se aplica a nivel de router, de modo que TODAS las rutas quedan cubiertas
    aunque despues se agreguen nuevas (antes era facil olvidarse de proteger una).

    La lectura y la escritura se distinguen por el metodo HTTP: el rol auditor
    puede consultar todo pero no puede POST/PUT/PATCH/DELETE.
    El administrador siempre pasa.

    El mapeo rol -> modulo sale de la tabla `modulos`, la misma que edita el
    administrador desde la pantalla "Modulos del Sistema", de modo que la regla
    del servidor y la del menu del navegador nunca se contradicen.
    """
    # Import diferido: auth.py importa este modulo, evitamos el ciclo.
    from routers.auth import current_user_dep

    def _dep(
        request: Request,
        user: Usuario = Depends(current_user_dep),
        db: Session = Depends(get_db),
    ) -> Usuario:
        exigir_modulo(request, db, user, clave)
        return user

    return _dep


def exigir_modulo(request: Request, db: Session, credencial: Usuario, clave: str) -> None:
    """El mismo control que require_modulo, pero invocable desde adentro de una ruta.

    Hace falta cuando el modulo no se sabe al declarar la ruta sino al leer el
    pedido: GET /api/admin/movimientos/{tipo} consulta remitos, facturas,
    compras, cobros o pagos segun el parametro, y cada uno pertenece a un modulo
    distinto. Declarar una sola clave ahi seria mentir en cuatro de los cinco
    casos.
    """
    # Un agente puede declarar por que persona actua. Se verifica que ambos
    # tengan permiso: ver resolver_actor().
    actor = resolver_actor(request, db, credencial)
    for quien in _sujetos_a_verificar(credencial, actor):
        _verificar_acceso(quien, clave, request.method, db)


def _sujetos_a_verificar(credencial: Usuario, actor: Usuario | None) -> list[Usuario]:
    """Los permisos efectivos son la INTERSECCION de la credencial y el actor.

    Si un agente se autentica con su cuenta de servicio y declara actuar por
    Juan, la operacion debe estar permitida para LOS DOS. Nunca alcanza con uno.

    Por que no basta con mirar solo al actor, que es lo que parece mas natural:
    si los permisos salieran unicamente de una cabecera, la credencial del
    agente se convertiria en una llave de suplantacion universal — cualquiera
    que la tuviera declararia ser el administrador y operaria como tal. La
    interseccion da permisos reales por persona SIN abrir esa puerta: el agente
    nunca puede hacer mas de lo que su propia cuenta permite.
    """
    if actor is None or actor.id == credencial.id:
        return [credencial]
    return [credencial, actor]


def _verificar_acceso(user: Usuario, clave: str, metodo: str, db: Session) -> None:
    rol = (user.rol or "").lower()
    if rol == "administrador":
        return

    if metodo in METODOS_DE_ESCRITURA and rol == ROL_SOLO_LECTURA:
        raise ErrorDeNegocio(
            "SOLO_LECTURA",
            f"{user.username} tiene rol auditor, de solo consulta: no puede modificar datos",
        )

    if rol not in _roles_del_modulo(db, clave):
        raise ErrorDeNegocio(
            "SIN_PERMISO",
            f"{user.username} ({rol or 'sin rol'}) no tiene acceso al modulo '{clave}'",
        )


# Cabecera con la que un agente declara por que PERSONA esta actuando.
CABECERA_ACTOR = "x-actor-user-id"


def puede_actuar_por_otro(credencial: Usuario) -> bool:
    """Si esta credencial tiene derecho a hablar por otra persona.

    El administrador siempre puede, y no por comodidad: es el que otorga el
    permiso, asi que exigirle que se lo conceda a si mismo no agrega ninguna
    barrera (le alcanza con una llamada) y en cambio lo dejaria sin la unica
    forma de ejecutar algo con los limites reales de un empleado, que es la
    interseccion de permisos.

    Para el resto es un permiso explicito y apagado por defecto. Se piensa para
    la cuenta de servicio de un agente, no para una cuenta de persona.
    """
    if (credencial.rol or "").lower() == "administrador":
        return True
    return bool(getattr(credencial, "puede_actuar_por", False))


def resolver_actor(request: Request, db: Session, credencial: Usuario) -> Usuario | None:
    """La persona por la que actua un agente, si la declaro.

    Acepta el id numerico o el nombre de usuario. Se valida que exista de
    verdad: si la cabecera nombra a alguien inexistente, se rechaza en vez de
    seguir silenciosamente como la cuenta del agente, porque entonces la
    operacion quedaria atribuida a quien no fue.

    Y se valida que la credencial TENGA DERECHO a declararla. Sin ese control,
    cualquier usuario mandaba la cabecera desde una consola y su operacion
    quedaba asentada a nombre de un companero: el registro de auditoria, que es
    el argumento central del sistema, pasaba a ser dictado por el que opera.
    Que un permiso no se pueda escalar por aca (los permisos son la
    interseccion) no arregla eso: el problema no es lo que se puede hacer, es a
    quien se le atribuye.
    """
    declarado = (request.headers.get(CABECERA_ACTOR) or "").strip()
    if not declarado:
        return None

    if not puede_actuar_por_otro(credencial):
        raise ErrorDeNegocio(
            "NO_PUEDE_ACTUAR_POR",
            (
                f"{credencial.username} no tiene permiso para actuar por otra persona: "
                f"la cabecera {CABECERA_ACTOR} solo la puede usar una cuenta habilitada "
                "para eso. Pidale al administrador que se lo habilite en "
                "POST /api/auth/usuarios/{id}/actuar-por"
            ),
        )

    consulta = db.query(Usuario)
    actor = (
        consulta.filter(Usuario.id == int(declarado)).first()
        if declarado.isdigit()
        else consulta.filter(Usuario.username == declarado).first()
    )
    if actor is None:
        raise ErrorDeNegocio(
            "ACTOR_INEXISTENTE",
            (
                f"El usuario declarado en {CABECERA_ACTOR} no existe ({declarado}). "
                "La operacion no se ejecuta para no quedar atribuida a nadie."
            ),
        )
    return actor


# ─────────────────────────────────────────────────────────────
# 3. IP real del cliente detras de un proxy inverso
# ─────────────────────────────────────────────────────────────

# Proxies en los que se confia para leer X-Forwarded-For, separados por coma.
# VACIO POR DEFECTO a proposito: si se confiara en cualquiera, cualquiera se
# fabricaria la IP que quiera con una cabecera y el limite de intentos dejaria
# de existir. Se completa unicamente si adelante hay un proxy inverso propio
# (el README recomienda Caddy, que corre en la misma maquina: ALDIA_PROXIES=127.0.0.1).
VARIABLE_PROXIES = "ALDIA_PROXIES"

_proxies_cache: tuple[str, frozenset[str]] = ("", frozenset())


def proxies_de_confianza() -> frozenset[str]:
    """Las direcciones de las que SI se acepta un X-Forwarded-For.

    Se relee de la variable de entorno en cada llamada (con memoria del texto
    crudo para no reprocesarlo) en vez de fijarse al importar: asi cambiar la
    configuracion no obliga a razonar sobre en que orden se cargaron los modulos.
    """
    global _proxies_cache
    crudo = os.getenv(VARIABLE_PROXIES, "") or ""
    if crudo != _proxies_cache[0]:
        _proxies_cache = (
            crudo,
            frozenset(p.strip() for p in crudo.split(",") if p.strip()),
        )
    return _proxies_cache[1]


def ip_del_cliente(request: Request) -> str:
    """La IP de quien realmente llama, no la del proxy que reenvia.

    Detras de un proxy inverso `request.client.host` es la del proxy (127.0.0.1
    con Caddy en la misma maquina) para TODO el mundo. Con eso, el limite de
    intentos deja de ser por atacante y pasa a ser uno solo para todos: ocho
    logins fallidos desde cualquier lado y el comercio entero queda quince
    minutos afuera de su propio sistema.

    Se recorre X-Forwarded-For de DERECHA a IZQUIERDA y se devuelve la primera
    direccion que no sea un proxy de confianza. Tomar la de mas a la izquierda,
    que es lo que se ve hecho por todos lados, es justamente lo que no hay que
    hacer: esa parte de la cabecera la escribe el cliente y se la inventa.

    Publica a proposito: backend/auditoria.py resuelve hoy la IP por su cuenta y
    tiene el mismo problema; que las dos respuestas salgan de aca evita que el
    registro diga una IP y el bloqueo cuente otra.
    """
    directa = request.client.host if request and request.client else "desconocida"
    confiables = proxies_de_confianza()
    if not confiables or directa not in confiables:
        return directa

    cadena = [
        parte.strip()
        for parte in (request.headers.get("x-forwarded-for") or "").split(",")
        if parte.strip()
    ]
    for candidato in reversed(cadena):
        if candidato not in confiables:
            return candidato[:60]
    return directa


# ─────────────────────────────────────────────────────────────
# 4. Limite de intentos de login (anti fuerza bruta)
# ─────────────────────────────────────────────────────────────

MAX_INTENTOS = 8
VENTANA = timedelta(minutes=15)
BLOQUEO = timedelta(minutes=15)

# Se cuenta por DOS claves distintas y con contadores independientes:
#
#   ip:<direccion>   frena al que prueba muchas cuentas desde un mismo lugar.
#   usuario:<nombre> frena al que prueba muchas claves contra UNA cuenta.
#
# Faltaba el segundo, que es el que de verdad protege la cuenta: una botnet
# reparte los intentos entre miles de direcciones y contra el contador por IP no
# choca nunca. Que el bloqueo por usuario habilite a molestar a un empleado
# ajeno durante quince minutos es un costo conocido y asumido: es
# preferible a dejar la cuenta abierta a fuerza bruta, y no revela si el nombre
# existe (se aplica igual a un usuario inexistente).
_ALCANCE_IP = "ip"
_ALCANCE_USUARIO = "usuario"

_intentos: dict[str, list[datetime]] = defaultdict(list)
_bloqueos: dict[str, datetime] = {}
_lock = threading.Lock()


def _claves_de(request: Request, username: str | None) -> list[tuple[str, str]]:
    """(alcance, clave) de este intento. El usuario solo si vino declarado."""
    claves = [(_ALCANCE_IP, f"{_ALCANCE_IP}:{ip_del_cliente(request)}")]
    nombre = (username or "").strip().lower()
    if nombre:
        # Normalizado a minusculas para que probar "Admin", "ADMIN" y "admin"
        # no de tres contadores distintos.
        claves.append((_ALCANCE_USUARIO, f"{_ALCANCE_USUARIO}:{nombre[:60]}"))
    return claves


def verificar_bloqueo_login(request: Request, username: str | None = None) -> None:
    """Rechaza el intento si esa IP o esa cuenta superaron el limite.

    Llamar ANTES de validar la clave.
    """
    ahora = ahora_utc()
    with _lock:
        for alcance, clave in _claves_de(request, username):
            hasta = _bloqueos.get(clave)
            if hasta and ahora >= hasta:
                _bloqueos.pop(clave, None)
                _intentos.pop(clave, None)
                continue
            if hasta:
                faltan = int((hasta - ahora).total_seconds() // 60) + 1
                motivo = (
                    "desde esta direccion" if alcance == _ALCANCE_IP
                    else "contra esta cuenta"
                )
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Demasiados intentos fallidos {motivo}. "
                        f"Reintente en {faltan} minuto(s)."
                    ),
                )


def registrar_login_fallido(request: Request, username: str | None = None) -> None:
    ahora = ahora_utc()
    with _lock:
        for _alcance, clave in _claves_de(request, username):
            recientes = [t for t in _intentos[clave] if ahora - t < VENTANA]
            recientes.append(ahora)
            _intentos[clave] = recientes
            if len(recientes) >= MAX_INTENTOS:
                _bloqueos[clave] = ahora + BLOQUEO


def registrar_login_exitoso(request: Request, username: str | None = None) -> None:
    with _lock:
        for _alcance, clave in _claves_de(request, username):
            _intentos.pop(clave, None)
            _bloqueos.pop(clave, None)


def reiniciar_control_de_login() -> None:
    """Borra todos los contadores. Existe para las pruebas.

    Sin esto, una prueba que provoca un bloqueo a proposito se lo deja puesto a
    las que corren despues: los contadores viven en memoria del proceso y el
    conjunto de pruebas comparte proceso.
    """
    with _lock:
        _intentos.clear()
        _bloqueos.clear()
