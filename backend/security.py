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
"""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from collections import defaultdict
from datetime import datetime, timedelta
import os
import secrets
import stat
import threading

from database import get_db
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
        # Un agente puede declarar por que persona actua. Se verifica que ambos
        # tengan permiso: ver resolver_actor().
        actor = resolver_actor(request, db, user)
        for quien in _sujetos_a_verificar(user, actor):
            _verificar_acceso(quien, clave, request.method, db)
        return user

    return _dep


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
        raise HTTPException(
            status_code=403,
            detail=f"{user.username} tiene rol auditor, de solo consulta: no puede modificar datos",
        )

    if rol not in _roles_del_modulo(db, clave):
        raise HTTPException(
            status_code=403,
            detail=f"{user.username} ({rol or 'sin rol'}) no tiene acceso al modulo '{clave}'",
        )


# Cabecera con la que un agente declara por que PERSONA esta actuando.
CABECERA_ACTOR = "x-actor-user-id"


def resolver_actor(request: Request, db: Session, credencial: Usuario) -> Usuario | None:
    """La persona por la que actua un agente, si la declaro.

    Acepta el id numerico o el nombre de usuario. Se valida que exista de
    verdad: si la cabecera nombra a alguien inexistente, se rechaza en vez de
    seguir silenciosamente como la cuenta del agente, porque entonces la
    operacion quedaria atribuida a quien no fue.
    """
    declarado = (request.headers.get(CABECERA_ACTOR) or "").strip()
    if not declarado:
        return None

    consulta = db.query(Usuario)
    actor = (
        consulta.filter(Usuario.id == int(declarado)).first()
        if declarado.isdigit()
        else consulta.filter(Usuario.username == declarado).first()
    )
    if actor is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"El usuario declarado en {CABECERA_ACTOR} no existe ({declarado}). "
                "La operacion no se ejecuta para no quedar atribuida a nadie."
            ),
        )
    return actor


# ─────────────────────────────────────────────────────────────
# 3. Limite de intentos de login (anti fuerza bruta)
# ─────────────────────────────────────────────────────────────

MAX_INTENTOS = 8
VENTANA = timedelta(minutes=15)
BLOQUEO = timedelta(minutes=15)

_intentos: dict[str, list[datetime]] = defaultdict(list)
_bloqueos: dict[str, datetime] = {}
_lock = threading.Lock()


def _ip_de(request: Request) -> str:
    return request.client.host if request and request.client else "desconocida"


def verificar_bloqueo_login(request: Request) -> None:
    """Rechaza el intento si esa IP supero el limite. Llamar ANTES de validar la clave."""
    ip = _ip_de(request)
    ahora = datetime.utcnow()
    with _lock:
        hasta = _bloqueos.get(ip)
        if hasta and ahora < hasta:
            faltan = int((hasta - ahora).total_seconds() // 60) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Demasiados intentos fallidos. Reintente en {faltan} minuto(s).",
            )
        if hasta and ahora >= hasta:
            _bloqueos.pop(ip, None)
            _intentos.pop(ip, None)


def registrar_login_fallido(request: Request) -> None:
    ip = _ip_de(request)
    ahora = datetime.utcnow()
    with _lock:
        recientes = [t for t in _intentos[ip] if ahora - t < VENTANA]
        recientes.append(ahora)
        _intentos[ip] = recientes
        if len(recientes) >= MAX_INTENTOS:
            _bloqueos[ip] = ahora + BLOQUEO


def registrar_login_exitoso(request: Request) -> None:
    ip = _ip_de(request)
    with _lock:
        _intentos.pop(ip, None)
        _bloqueos.pop(ip, None)
