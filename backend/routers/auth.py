"""
auth.py - Router de autenticación con JWT y bcrypt
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import bcrypt
import jwt

from database import get_db, Base
from models import Usuario
from schemas import LoginRequest, TokenResponse, UsuarioResponse, UsuarioCreate, CambioPassword
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


def hash_password(password: str) -> str:
    """Hashear contraseña con bcrypt"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(plain_password: str, hashed: str) -> bool:
    """Verificar contraseña contra hash bcrypt"""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed.encode('utf-8'))


def create_access_token(data: dict, expires_delta: timedelta) -> str:
    """Crear token JWT"""
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str, db: Session) -> Usuario:
    """Obtener usuario actual desde token JWT"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Token inválido")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    
    user = db.query(Usuario).filter(Usuario.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
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
        raise HTTPException(status_code=401, detail="No autenticado")
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
        raise HTTPException(status_code=401, detail="No autenticado")
    return get_current_user(credentials.credentials, db)


def require_admin(user: Usuario = Depends(current_user_dep)) -> Usuario:
    """Dependencia FastAPI: exige que el usuario sea administrador."""
    if (user.rol or "").lower() != "administrador":
        raise HTTPException(status_code=403, detail="Requiere permisos de administrador")
    return user


@router.post("/login", response_model=TokenResponse)
def login(login_data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Iniciar sesión"""
    # Anti fuerza bruta: imprescindible si el sistema se publica a internet.
    verificar_bloqueo_login(request)

    user = db.query(Usuario).filter(Usuario.username == login_data.username).first()

    if not user or not verify_password(login_data.password, user.password_hash):
        registrar_login_fallido(request)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    registrar_login_exitoso(request)
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
    """
    if not verify_password(datos.password_actual, user.password_hash):
        raise HTTPException(status_code=401, detail="La contraseña actual no es correcta")

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

    user.password_hash = hash_password(nueva)
    user.debe_cambiar_password = False
    db.commit()
    return {"message": "Contraseña actualizada. Ya puede usar el sistema."}


@router.post("/register", response_model=UsuarioResponse)
def register(user_data: UsuarioCreate, db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Registrar nuevo usuario (solo administrador)"""
    # Verificar si el usuario ya existe
    existing = db.query(Usuario).filter(Usuario.username == user_data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe")
    
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


# Migrar usuarios existentes de texto plano a bcrypt
@router.post("/migrate-passwords")
def migrate_passwords(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Migrar contraseñas de texto plano a bcrypt (solo administrador).

    Sin la guardia de admin, un anonimo podia re-hashear toda la tabla usuarios.
    """
    users = db.query(Usuario).all()
    migrated = 0
    for user in users:
        # Si el hash no empieza con $2b$, es texto plano
        if not user.password_hash.startswith("$2b$"):
            user.password_hash = hash_password(user.password_hash)
            migrated += 1
    db.commit()
    return {"message": f"{migrated} contraseñas migradas a bcrypt"}
