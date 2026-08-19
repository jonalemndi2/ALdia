"""
auth.py - Router de autenticación con JWT y bcrypt
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import bcrypt
import jwt

from errores import ErrorDeNegocio
from database import get_db, Base
from tiempo import ahora_utc
from models import Usuario
from schemas import (
    CambioActuarPor, CambioPassword, LoginRequest, MAX_BYTES_PASSWORD,
    TokenResponse, UsuarioCreate, UsuarioResponse,
)
from security import (
    SECRET_KEY,
    verificar_bloqueo_login,
    registrar_login_fallido,
    registrar_login_exitoso,
)

router = APIRouter()

# La SECRET_KEY se genera y persiste por instalacion en security.py.
# Ya NO hay valor por defecto hardcodeado: uno conocido permitia a cualquiera
# que leyera el codigo fabricarse un token de administrador valido.
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 horas

# Esquema de seguridad Bearer para proteger endpoints
security = HTTPBearer(auto_error=False)


# Prefijos que emite bcrypt. NO alcanza con "$2b$": "$2a$" es el de bcrypt<4 y
# el de casi todo lo que viene de PHP, y "$2y$" el de las bibliotecas de PHP
# posteriores. Los tres son hashes bcrypt VALIDOS y esta misma biblioteca los
# verifica sin problema. Mirar solo uno hacia que migrate-passwords tratara a
# los otros dos como texto plano y los volviera a hashear: la contrasena del
# usuario dejaba de servir para siempre, sin aviso y sin vuelta atras.
PREFIJOS_BCRYPT = ("$2a$", "$2b$", "$2y$")


def es_hash_bcrypt(valor: str) -> bool:
    return bool(valor) and str(valor).startswith(PREFIJOS_BCRYPT)


def hash_password(password: str) -> str:
    """Hashear contraseña con bcrypt.

    Lanza ValueError si la contraseña pasa el limite de bcrypt. Los schemas
    Pydantic ya lo validan antes (ver schemas.validar_largo_password), asi que
    esto es la red de contencion de las llamadas internas, no el control que ve
    el usuario.
    """
    bytes_password = password.encode('utf-8')
    if len(bytes_password) > MAX_BYTES_PASSWORD:
        raise ValueError(
            f"La contrasena ocupa {len(bytes_password)} bytes y bcrypt admite "
            f"hasta {MAX_BYTES_PASSWORD}"
        )
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(bytes_password, salt).decode('utf-8')


def verify_password(plain_password: str, hashed: str) -> bool:
    """Verificar contraseña contra hash bcrypt. Nunca revienta: o coincide o no.

    bcrypt lanza ValueError en dos casos que entran solos por la puerta de
    adelante: una contrasena de mas de 72 bytes (una passphrase pegada de un
    gestor de contrasenas) y un hash que no es un hash (el usuario legacy en
    texto plano, que es exactamente el que migrate-passwords existe para
    arreglar). Los dos terminaban en un 500, y un 500 es peor que un 401 por
    algo que no se ve: sale por el manejador de errores y no por el camino del
    login fallido, asi que el intento no se contaba para el limite de fuerza
    bruta.
    """
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed.encode('utf-8'))
    except (ValueError, TypeError):
        return False


# Tolerancia de reloj al validar el token, en segundos. Un unico segundo, que es
# lo minimo que hace falta: el `iat` de un JWT se guarda en segundos enteros y el
# token que reemplaza a la sesion cerrada se fecha en el segundo siguiente al
# cambio de contrasena (ver _proximo_segundo), asi que sin esta tolerancia el
# propio sistema lo rechazaria por "todavia no emitido" durante esa fraccion.
TOLERANCIA_RELOJ = 1


def _proximo_segundo(momento: datetime) -> datetime:
    """El siguiente segundo entero a partir de `momento`.

    El `iat` de un JWT se guarda en segundos enteros, sin fracciones, asi que un
    token emitido a las 10:00:00,7 dice 10:00:00 y queda "antes" de un cambio de
    contrasena hecho a las 10:00:00,3. El token de reemplazo que se entrega en
    ese mismo cambio se fecha en el segundo siguiente para que no lo invalide el
    corte que acaba de crear.
    """
    return (momento + timedelta(seconds=1)).replace(microsecond=0)


def create_access_token(data: dict, expires_delta: timedelta,
                        emitido: datetime | None = None) -> str:
    """Crear token JWT.

    Lleva `iat` (instante de emision) ademas de `exp`. No es decorativo: es lo
    unico que despues permite saber si este token es anterior o posterior al
    ultimo cambio de contrasena de su dueno.
    """
    to_encode = data.copy()
    emitido = emitido or ahora_utc()
    to_encode.update({"exp": emitido + expires_delta, "iat": emitido})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _token_anterior_al_cambio(payload: dict, user: Usuario) -> bool:
    """Si este token se emitio antes del ultimo cambio de contrasena del usuario.

    NULL en `password_cambiada_en` significa que el usuario nunca la cambio
    desde que existe la columna: no hay nada que invalidar y las sesiones
    abiertas de una instalacion ya en marcha siguen valiendo.

    Un token SIN `iat` pero con la columna ya cargada se considera anterior: si
    no trae la marca es porque lo emitio una version del sistema previa a este
    control, o sea que es viejo por definicion.

    El `iat` del JWT va en segundos enteros y el corte tiene fraccion, asi que
    un token emitido en el mismo segundo del cambio tambien se descarta. El
    error se prefiere hacia el lado de cerrar una sesion de mas y no de menos.
    """
    cambiada = getattr(user, "password_cambiada_en", None)
    if cambiada is None:
        return False
    emitido = payload.get("iat")
    if emitido is None:
        return True
    corte = cambiada.replace(tzinfo=timezone.utc).timestamp()
    return int(emitido) < corte


def get_current_user(token: str, db: Session) -> Usuario:
    """Obtener usuario actual desde token JWT"""
    try:
        payload = jwt.decode(
            token, SECRET_KEY, algorithms=[ALGORITHM], leeway=TOLERANCIA_RELOJ
        )
        username: str = payload.get("sub")
        if username is None:
            raise ErrorDeNegocio("SESION_VENCIDA", "Token inválido")
    except jwt.PyJWTError:
        raise ErrorDeNegocio("SESION_VENCIDA", "Token inválido o expirado")

    user = db.query(Usuario).filter(Usuario.username == username).first()
    if user is None:
        raise ErrorDeNegocio("SESION_VENCIDA", "El usuario de esta sesión ya no existe")

    # Cambiar la contrasena PORQUE alguien la vio no servia de nada: el token
    # que esa persona ya tenia seguia abierto hasta ocho horas mas.
    if _token_anterior_al_cambio(payload, user):
        raise HTTPException(
            status_code=401,
            detail=(
                "La contraseña de este usuario cambió después de emitirse esta "
                "sesión. Vuelva a iniciar sesión."
            ),
        )
    return user


def current_user_dep(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Usuario:
    """Dependencia FastAPI: obtiene el usuario autenticado desde el header Bearer.

    Si el usuario todavia tiene la contrasena inicial, aca se corta: puede
    autenticarse, pero no puede usar el sistema hasta cambiarla. Como TODOS los
    routers de datos dependen de esta funcion (ver main.py), el bloqueo cubre la
    API entera sin tener que acordarse ruta por ruta.
    """
    if credentials is None or not credentials.credentials:
        raise ErrorDeNegocio("NO_AUTENTICADO", "No autenticado")
    user = get_current_user(credentials.credentials, db)
    if getattr(user, "debe_cambiar_password", False):
        raise HTTPException(
            status_code=403,
            detail=(
                "Debe cambiar la contraseña inicial antes de usar el sistema. "
                "La contraseña de fábrica figura en la documentación pública del "
                "proyecto: mientras no la cambie, su instalación es de acceso "
                "conocido. Use POST /api/auth/cambiar-password."
            ),
        )
    return user


def usuario_autenticado_sin_exigir_cambio(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Usuario:
    """Como current_user_dep pero SIN el bloqueo por contrasena inicial.

    La usa el propio endpoint de cambio de contrasena: si exigiera la contrasena
    ya cambiada, nadie podria cambiarla nunca.
    """
    if credentials is None or not credentials.credentials:
        raise ErrorDeNegocio("NO_AUTENTICADO", "No autenticado")
    return get_current_user(credentials.credentials, db)


def require_admin(user: Usuario = Depends(current_user_dep)) -> Usuario:
    """Dependencia FastAPI: exige que el usuario sea administrador."""
    if (user.rol or "").lower() != "administrador":
        raise ErrorDeNegocio("SIN_PERMISO", "Requiere permisos de administrador")
    return user


@router.post("/login", response_model=TokenResponse)
def login(login_data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Iniciar sesión"""
    # Anti fuerza bruta: imprescindible si el sistema se publica a internet.
    # Se cuenta por IP y TAMBIEN por nombre de usuario: el contador por IP no
    # frena a una botnet que reparte los intentos, y el que protege a la cuenta
    # es el segundo. Ver security.py.
    verificar_bloqueo_login(request, login_data.username)

    user = db.query(Usuario).filter(Usuario.username == login_data.username).first()

    if not user or not verify_password(login_data.password, user.password_hash):
        registrar_login_fallido(request, login_data.username)
        raise ErrorDeNegocio("CREDENCIALES_INVALIDAS", "Usuario o contraseña incorrectos")

    registrar_login_exitoso(request, login_data.username)
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UsuarioResponse(
            id=user.id, username=user.username, rol=user.rol,
            # El frontend usa esta marca para llevar directo a la pantalla de
            # cambio de contrasena en vez de mostrar un sistema que va a
            # rechazar todo lo que intente hacer.
            debe_cambiar_password=bool(getattr(user, "debe_cambiar_password", False)),
            puede_actuar_por=bool(getattr(user, "puede_actuar_por", False)),
        ),
    )


@router.post("/cambiar-password")
def cambiar_password(
    datos: CambioPassword,
    db: Session = Depends(get_db),
    user: Usuario = Depends(usuario_autenticado_sin_exigir_cambio),
):
    """Cambiar la propia contraseña. Es lo unico que se puede hacer con la inicial.

    Exige la contraseña actual: si alguien deja la sesion abierta, que no puedan
    cambiarsela desde ahi.

    CIERRA TODAS LAS SESIONES ABIERTAS, incluida la que hace este pedido, y
    devuelve un token nuevo para reemplazarla. El motivo de cambiar una
    contraseña casi siempre es que alguien la vio; si los tokens ya emitidos
    siguieran valiendo ocho horas mas, el cambio no lograria nada. Quien llame a
    este endpoint tiene que guardar el `access_token` que recibe: el anterior
    deja de servir en el acto.
    """
    if not verify_password(datos.password_actual, user.password_hash):
        raise ErrorDeNegocio("CREDENCIALES_INVALIDAS", "La contraseña actual no es correcta")

    nueva = (datos.password_nueva or "").strip()
    if len(nueva) < 8:
        raise HTTPException(
            status_code=422,
            detail="La contraseña nueva debe tener al menos 8 caracteres",
        )
    if verify_password(nueva, user.password_hash):
        raise HTTPException(
            status_code=422,
            detail="La contraseña nueva debe ser distinta de la actual",
        )

    cambiada_en = ahora_utc()
    user.password_hash = hash_password(nueva)
    user.debe_cambiar_password = False
    user.password_cambiada_en = cambiada_en
    db.commit()

    nuevo_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        emitido=_proximo_segundo(cambiada_en),
    )
    return {
        "message": (
            "Contraseña actualizada. Ya puede usar el sistema. "
            "Las demás sesiones abiertas quedaron cerradas."
        ),
        "access_token": nuevo_token,
        "token_type": "bearer",
        "sesiones_anteriores_cerradas": True,
    }


@router.post("/register", response_model=UsuarioResponse)
def register(user_data: UsuarioCreate, db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Registrar nuevo usuario (solo administrador)"""
    # Verificar si el usuario ya existe
    existing = db.query(Usuario).filter(Usuario.username == user_data.username).first()
    if existing:
        raise ErrorDeNegocio("YA_EXISTE", "El nombre de usuario ya existe")
    
    hashed_pw = hash_password(user_data.password)
    new_user = Usuario(
        username=user_data.username,
        password_hash=hashed_pw,
        rol=user_data.rol,
        # La contrasena la eligio el administrador, no el dueno de la cuenta:
        # el empleado la reemplaza al entrar por una que solo el conozca. Sin
        # esto, el administrador conoce la clave de todos sus empleados y la
        # auditoria por usuario deja de significar algo.
        debe_cambiar_password=True,
        # Impersonacion apagada salvo pedido explicito. Ver security.resolver_actor().
        puede_actuar_por=bool(user_data.puede_actuar_por),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.get("/me", response_model=UsuarioResponse)
def get_me(user: Usuario = Depends(usuario_autenticado_sin_exigir_cambio)):
    """Información del usuario actual.

    NO exige la contraseña ya cambiada: es la consulta con la que el frontend
    decide qué pantalla mostrar al recargar. Si bloqueara, el usuario que aún
    tiene la contraseña inicial quedaría fuera del sistema sin poder cambiarla.
    Solo devuelve datos propios, incluida la marca `debe_cambiar_password`.
    """
    return user


@router.get("/usuarios", response_model=list[UsuarioResponse])
def listar_usuarios(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Listar todos los usuarios (solo administrador)."""
    return db.query(Usuario).all()


@router.delete("/usuarios/{user_id}")
def eliminar_usuario(user_id: int, db: Session = Depends(get_db), admin: Usuario = Depends(require_admin)):
    """Eliminar un usuario (solo administrador, no puede eliminarse a sí mismo)."""
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="No puede eliminar su propio usuario")
    user = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    db.delete(user)
    db.commit()
    return {"message": "Usuario eliminado"}


@router.post("/usuarios/{user_id}/actuar-por")
def habilitar_actuar_por(
    user_id: int,
    datos: CambioActuarPor,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Dar o quitar el permiso de operar a nombre de otra persona (solo administrador).

    Es la llave con la que una cuenta de servicio puede declarar
    `X-Actor-User-ID` y que la operacion quede atribuida al empleado por el que
    trabaja. Se otorga cuenta por cuenta y a mano: la impersonacion tiene que
    ser una decision de alguien, no el estado de fabrica.
    """
    user = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user.puede_actuar_por = bool(datos.habilitado)
    db.commit()
    return {
        "message": (
            f"{user.username} {'ya puede' if datos.habilitado else 'ya no puede'} "
            "operar a nombre de otra persona"
        ),
        "username": user.username,
        "puede_actuar_por": bool(user.puede_actuar_por),
    }


# Migrar usuarios existentes de texto plano a bcrypt
@router.post("/migrate-passwords")
def migrate_passwords(
    simular: bool = False,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Migrar contraseñas de texto plano a bcrypt (solo administrador).

    Sin la guardia de admin, un anonimo podia re-hashear toda la tabla usuarios.

    ES IRREVERSIBLE: re-hashear un hash lo destruye, porque el hash original ya
    no se puede recuperar y el usuario queda sin forma de entrar nunca mas. Por
    eso hay dos defensas.

    La primera es reconocer TODOS los prefijos de bcrypt y no solo `$2b$` (ver
    PREFIJOS_BCRYPT): un hash `$2a$` o `$2y$`, que es lo que trae cualquier base
    venida de PHP o de bcrypt<4, ya es bcrypt, y volverlo a hashear dejaba a esa
    persona afuera del sistema para siempre.

    La segunda es `?simular=true`: informa a quien migraria y NO toca nada. Antes
    de una operacion sin vuelta atras corresponde poder mirar primero.
    """
    a_migrar, ya_estaban, no_se_pueden = [], [], []
    for user in db.query(Usuario).order_by(Usuario.username).all():
        if es_hash_bcrypt(user.password_hash):
            ya_estaban.append(user.username)
            continue
        largo = len((user.password_hash or "").encode("utf-8"))
        if largo > MAX_BYTES_PASSWORD:
            # Un texto plano mas largo que el limite de bcrypt no se puede
            # hashear sin recortarlo, y recortarlo en silencio cambia la
            # contrasena del usuario sin avisarle. Se informa y se deja como
            # esta: que el administrador se la resetee.
            no_se_pueden.append({
                "username": user.username,
                "motivo": (
                    f"la contrasena en texto plano ocupa {largo} bytes y bcrypt "
                    f"admite {MAX_BYTES_PASSWORD}: asignele una nueva"
                ),
            })
            continue
        a_migrar.append(user.username)

    if simular:
        return {
            "simulacion": True,
            "message": (
                f"{len(a_migrar)} contraseña(s) se migrarían a bcrypt. "
                "No se modificó nada."
            ),
            "se_migrarian": a_migrar,
            "ya_estaban_en_bcrypt": ya_estaban,
            "no_se_pueden_migrar": no_se_pueden,
        }

    for username in a_migrar:
        user = db.query(Usuario).filter(Usuario.username == username).first()
        user.password_hash = hash_password(user.password_hash)
    db.commit()

    return {
        "simulacion": False,
        "message": f"{len(a_migrar)} contraseña(s) migradas a bcrypt",
        "migrados": a_migrar,
        "ya_estaban_en_bcrypt": ya_estaban,
        "no_se_pueden_migrar": no_se_pueden,
    }
