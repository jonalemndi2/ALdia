# Contribuir a ALdía

Las contribuciones son bienvenidas. Este archivo es corto a propósito: son
pocas reglas, pero las tres primeras no se negocian.

## Las tres reglas

### 1. Nada de datos reales de ningún comercio

Ni en el código, ni en material de validación, ni en una captura de pantalla, ni en la
descripción de un issue. Sin CUIT reales, sin nombres de clientes, sin importes
facturados, y por supuesto sin el archivo `backend/aldia.db` ni certificados de
AFIP. El `.gitignore` los excluye y hay un job de CI que lo verifica en cada
push, pero eso es la red de contención, no el control principal.

### 2. Si tocás dinero o stock, explicá cómo lo verificaste

Los importes se guardan como **enteros de centavos** (ver `backend/dinero.py`,
que explica por qué) y las operaciones son transaccionales: emitir un remito
descuenta stock, facturar suma la deuda, un cobro baja el saldo y genera el
asiento de caja. Todo eso tiene que poder revertirse al anular.

El patrón de validación es siempre el mismo: **medir antes, operar, medir después**.
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

El sistema se instala en Windows, Linux y macOS:

**Linux y macOS**

```bash
./instalar.sh
```

**Windows**

```
instalar.bat
```

Crea el entorno en `.venv` e instala las dependencias. Para arrancar el
servidor: `./iniciar_web.sh` (o `iniciar_web.bat`). La base se crea sola en el
primer arranque, vacía, y el usuario `admin` te obliga a cambiar la contraseña
antes de dejarte operar.

La validación funcional completa se ejecuta en el entorno privado del proyecto
antes de publicar. GitHub verifica además que el paquete público instale en los
tres sistemas y que no contenga material de prueba ni información sensible.

## Sobre los comentarios

Este repo tiene una convención marcada y vale la pena respetarla: **los
comentarios explican por qué, no qué**. `backend/dinero.py`,
`backend/database.py` y `backend/secuencias.py` son los mejores ejemplos —
cuentan qué alternativas se descartaron y qué se rompía antes. Un comentario
que parafrasea la línea de abajo no aporta; uno que explica por qué esa línea no
puede ser de otra manera evita que alguien la "simplifique" dentro de dos años.

Los comentarios del backend van sin tildes (compatibilidad con consolas viejas
de Windows); el texto que ve el usuario, con tildes normales. Lo mismo vale para
los scripts: los comentarios de `instalar.sh` e `iniciar_web.sh` van sin tildes,
y los mensajes que se imprimen en pantalla con tildes.

## Al abrir el pull request

Contá qué problema resuelve y cómo lo verificaste, sin adjuntar datos reales ni
material privado de validación.

## Licencia

Al contribuir aceptás que tu aporte se publique bajo la **Apache License 2.0**,
igual que el resto del proyecto. No hace falta firmar nada: enviar un pull
request ya lo implica (Apache 2.0 §5).
