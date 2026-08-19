"""
conftest.py - Infraestructura comun de las pruebas.

Cada corrida usa una base de datos NUEVA y descartable: las pruebas no tocan
`backend/aldia.db` ni ningun dato real del comercio. La base se crea en un
directorio temporal y se borra al terminar.
"""
import os
import sys
import tempfile
import uuid

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(RAIZ, "backend")


# ─────────────────────────────────────────────────────────────────────────────
# La base temporal se define ACA, al importar conftest, y NO adentro de la
# fixture.
#
# POR QUE, que costo caro descubrirlo: `database.py` lee ALDIA_DB UNA sola vez,
# cuando se importa, y ahi se queda con esa ruta para todo el proceso. Si
# cualquier cosa importa `database` antes de que la fixture corra --y alcanza
# con que un archivo de pruebas importe un modulo del backend que a su vez lo
# importe-- el motor queda apuntando a backend/aldia.db, o sea LA BASE REAL DEL
# COMERCIO, y la suite entera corre contra ella sin avisar.
#
# Paso de verdad: un test construia un objeto de error suelto, eso disparaba el
# primer `import database` del proceso, y las pruebas empezaron a escribir en la
# base real. Se noto solo porque el login fallaba con la contrasena verdadera
# del administrador.
#
# pytest importa conftest.py ANTES que cualquier archivo de pruebas, asi que
# poniendolo aca no hay ventana posible.
# ─────────────────────────────────────────────────────────────────────────────
_TMP = tempfile.mkdtemp(prefix="aldia_test_")
RUTA_DB = os.path.join(_TMP, f"prueba_{uuid.uuid4().hex[:8]}.db")

os.environ["ALDIA_DB"] = RUTA_DB
os.environ["ALDIA_SECRET_KEY"] = "clave-solo-para-pruebas"
os.environ["AFIP_HABILITADO"] = "no"
# Que ninguna prueba dispare la copia de seguridad del arranque.
os.environ["ALDIA_SIN_RESPALDO"] = "1"

if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


@pytest.fixture(scope="session")
def app_cliente():
    """Cliente HTTP contra la aplicacion, con base temporal propia."""
    ruta_db = RUTA_DB   # ya fijada al importar conftest (ver la nota de arriba)

    from fastapi.testclient import TestClient
    import main

    with TestClient(main.app) as cliente:
        yield cliente

    for sufijo in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(ruta_db + sufijo)
        except OSError:
            pass


PASSWORD_ADMIN = "clave-de-pruebas-del-admin"


@pytest.fixture(scope="session")
def token_admin(app_cliente):
    """Token de administrador ya operativo.

    El sistema obliga a cambiar la contrasena de fabrica antes de dejar operar
    (ver test_password_inicial.py), asi que las pruebas hacen lo mismo que hara
    cualquier instalacion real: entrar, cambiarla, y recien despues trabajar.
    """
    r = app_cliente.post("/api/auth/login",
                         json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, f"El login de admin falló: {r.text}"
    token = r.json()["access_token"]

    if r.json()["user"].get("debe_cambiar_password"):
        cambio = app_cliente.post(
            "/api/auth/cambiar-password",
            json={"password_actual": "admin123", "password_nueva": PASSWORD_ADMIN},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert cambio.status_code == 200, cambio.text
        # Cambiar la contrasena cierra TODAS las sesiones abiertas, incluida
        # esta: el token de arriba se emitio antes del cambio y ya no vale. El
        # endpoint devuelve el reemplazo, que es lo mismo que tiene que hacer
        # cualquier cliente real.
        token = cambio.json()["access_token"]

    return token


@pytest.fixture(scope="session")
def admin(app_cliente, token_admin):
    """Cliente con la cabecera de autorizacion de administrador ya puesta."""
    app_cliente.headers.update({"Authorization": f"Bearer {token_admin}"})
    return app_cliente


def cuit_valido(prefijo: str, semilla) -> str:
    """Genera un CUIT con digito verificador correcto (modulo 11).

    El sistema valida el digito verificador de verdad, asi que los datos de
    prueba tienen que ser fiscalmente correctos igual que los reales.
    """
    cuerpo = (str(prefijo) + str(semilla).zfill(8))[:10]
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    suma = sum(int(d) * p for d, p in zip(cuerpo, pesos))
    verificador = 11 - (suma % 11)
    if verificador == 11:
        verificador = 0
    elif verificador == 10:
        verificador = 9
    return cuerpo + str(verificador)


@pytest.fixture
def cuit():
    """Un CUIT valido y distinto en cada prueba."""
    contador = {"n": 0}

    def _siguiente(prefijo="30"):
        contador["n"] += 1
        return cuit_valido(prefijo, f"{uuid.uuid4().int % 10**6:06d}{contador['n']:02d}")

    return _siguiente
