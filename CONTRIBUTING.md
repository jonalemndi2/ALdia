# Contribuir a ALdía

Las contribuciones son bienvenidas. Este archivo es corto a propósito: son
pocas reglas, pero las tres primeras no se negocian.

## Las tres reglas

### 1. Nada de datos reales de ningún comercio

Ni en el código, ni en un test, ni en una captura de pantalla, ni en la
descripción de un issue. Sin CUIT reales, sin nombres de clientes, sin importes
facturados, y por supuesto sin el archivo `backend/aldia.db` ni certificados de
AFIP. El `.gitignore` los excluye y hay un job de CI que lo verifica en cada
push, pero eso es la red de contención, no el control principal.

Para los tests hay un generador de CUIT válidos (fixture `cuit` en
`tests/conftest.py`), porque el sistema valida el dígito verificador y un número
inventado a mano se rechaza.

### 2. Si tocás dinero o stock, explicá cómo lo verificaste

Los importes se guardan como **enteros de centavos** (ver `backend/dinero.py`,
que explica por qué) y las operaciones son transaccionales: emitir un remito
descuenta stock, facturar suma la deuda, un cobro baja el saldo y genera el
asiento de caja. Todo eso tiene que poder revertirse al anular.

El patrón de prueba es siempre el mismo: **medir antes, operar, medir después**.
No alcanza con que la respuesta HTTP diga 200.

### 3. La validación va del lado del servidor

El navegador no es una barrera de seguridad. Ocultar un botón o un ítem del menú
no protege nada: quien quiera llamar la API directamente lo va a hacer. Todo
control de permisos vive en el servidor, en `backend/security.py`, y se declara
a nivel de router para que **una ruta nueva nazca protegida** sin que su autor
tenga que acordarse.

Lo mismo vale para la auditoría y la idempotencia: son middleware, no algo que
cada ruta llame a mano. Si tu cambio necesita que alguien "se acuerde" de
llamar a algo, probablemente vaya en el lugar equivocado.

## Levantar el entorno

En Windows, que es donde se instala el sistema:

```
instalar.bat
```

Crea el entorno en `.venv` e instala las dependencias. Para desarrollar hacen
falta además pytest y httpx:

```
.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
```

Para arrancar el servidor: `iniciar_web.bat` (o `.venv\Scripts\python.exe
backend\main.py`). La base se crea sola en el primer arranque, vacía, y el
usuario `admin` te obliga a cambiar la contraseña antes de dejarte operar.

## Correr las pruebas

```
.venv\Scripts\python.exe -m pytest tests/ -q      # todas
.venv\Scripts\python.exe -m pytest tests/ -v      # con el nombre de cada una
.venv\Scripts\python.exe -m pytest tests/test_negocio.py::TestFactura -v
```

**No hace falta levantar el servidor.** Las pruebas montan la aplicación en
memoria y usan una base temporal que se borra al terminar: nunca tocan
`backend/aldia.db`. Ver [tests/README.md](tests/README.md) para qué cubre cada
archivo.

Las mismas pruebas corren en CI (Linux, Python 3.10 y 3.13) en cada push y cada
pull request, y además una vez con las versiones exactas de
`backend/requirements.lock.txt`, que son las que se le recomiendan a un comercio.
Si tu cambio anda en Windows pero rompe en CI, casi siempre es una ruta con
backslash o un permiso de archivo.

## Sobre los comentarios

Este repo tiene una convención marcada y vale la pena respetarla: **los
comentarios explican por qué, no qué**. `backend/dinero.py`,
`backend/database.py` y `backend/secuencias.py` son los mejores ejemplos —
cuentan qué alternativas se descartaron y qué se rompía antes. Un comentario
que parafrasea la línea de abajo no aporta; uno que explica por qué esa línea no
puede ser de otra manera evita que alguien la "simplifique" dentro de dos años.

Los comentarios del backend van sin tildes (compatibilidad con consolas viejas
de Windows); el texto que ve el usuario, con tildes normales.

## Al abrir el pull request

Contá qué problema resuelve y cómo lo verificaste. Si es un arreglo, lo ideal es
un test que **falle sin el cambio y pase con él** — y decir explícitamente que
comprobaste las dos cosas.

## Licencia

Al contribuir aceptás que tu aporte se publique bajo la
**GNU Affero General Public License v3.0**, igual que el resto del proyecto.
