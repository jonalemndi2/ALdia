#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ALdia - Servidor de gestión (Linux y macOS)
#
# Equivalente de iniciar_web.bat. Levanta el backend y deja el sistema
# disponible en esta computadora y en la red local.
#
#     ./iniciar_web.sh
#
# Variables que reconoce (todas opcionales):
#     ALDIA_HOST            interfaz donde escuchar     (por defecto 0.0.0.0)
#     ALDIA_PORT            puerto                       (por defecto 8000)
#     ALDIA_PYTHON          intérprete a usar si no hay .venv
#     ALDIA_SIN_NAVEGADOR   =1 para no abrir el navegador (servidor sin pantalla)
#
# Se escribe en bash 3.2 a proposito: es el que trae macOS de fabrica.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")"
RAIZ="$(pwd)"

HOST="${ALDIA_HOST:-0.0.0.0}"
PORT="${ALDIA_PORT:-8000}"

# Validar el puerto ACA y no mas abajo. Si ALDIA_PORT trae cualquier cosa, la
# comprobacion de "puerto ocupado" que sigue le pasa el valor a int() en Python,
# revienta, y el script informaria que el puerto esta en uso -- que es falso y
# manda a buscar el problema al lado equivocado.
case "$PORT" in
    ''|*[!0-9]*)
        echo "  [ERROR] ALDIA_PORT tiene que ser un número: recibí '$PORT'." >&2
        exit 1
        ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "  [ERROR] ALDIA_PORT tiene que estar entre 1 y 65535: recibí '$PORT'." >&2
    exit 1
fi

echo "============================================"
echo "    ALDIA - Servidor de Gestión"
echo "============================================"
echo

# ── Elegir el interprete ─────────────────────────────────────────────────────
#
# Usar el entorno virtual si existe; si no, el Python del sistema. Las rutas van
# entre comillas SIEMPRE: si la carpeta del proyecto tiene espacios (que es lo
# normal, "Proyecto Asistente Personal/ALdia"), sin comillas el shell parte la
# ruta en dos y el error que aparece —"no such file or directory"— apunta a un
# archivo que nadie nombro.
if [ -x ".venv/bin/python" ]; then
    PYTHON="$RAIZ/.venv/bin/python"
    ORIGEN="entorno virtual del proyecto"
else
    PYTHON="${ALDIA_PYTHON:-python3}"
    ORIGEN="Python del sistema"
    if ! command -v "$PYTHON" >/dev/null 2>&1; then
        echo "  [ERROR] No hay entorno virtual y tampoco se encuentra '$PYTHON'." >&2
        echo >&2
        echo "  Ejecute primero:  ./instalar.sh" >&2
        exit 1
    fi
fi

if ! "$PYTHON" --version >/dev/null 2>&1; then
    echo "  [ERROR] No se puede ejecutar Python." >&2
    echo >&2
    echo "  Ruta probada:  $PYTHON" >&2
    echo >&2
    if [ -e ".venv/bin/python" ]; then
        echo "  El entorno virtual existe pero no responde. Puede estar dañado, o" >&2
        echo "  haber quedado apuntando a un Python que ya no está (pasa al" >&2
        echo "  actualizar el sistema operativo o al mover la carpeta del proyecto):" >&2
        echo "  borre la carpeta .venv y vuelva a ejecutar  ./instalar.sh" >&2
    else
        echo "  No hay entorno virtual. Ejecute primero  ./instalar.sh" >&2
    fi
    exit 1
fi

# ── Verificar las dependencias e informar EXACTAMENTE cual falta ─────────────
if ! "$PYTHON" -c 'import fastapi, uvicorn, sqlalchemy, pydantic, bcrypt, jwt, httpx' 2>/dev/null; then
    echo "  [!] Faltan dependencias del sistema. Detalle:" >&2
    echo >&2
    "$PYTHON" -c 'import importlib.util as u; [print("     falta:", m) for m in ["fastapi","uvicorn","sqlalchemy","pydantic","bcrypt","jwt","httpx"] if not u.find_spec(m)]' >&2 || true
    echo >&2
    echo "  Ejecute  ./instalar.sh  para instalarlas." >&2
    exit 1
fi

# ── Que el puerto este libre ─────────────────────────────────────────────────
#
# Si ya hay un ALdia corriendo, uvicorn muere con un traceback de "address
# already in use" que en una PC de comercio no le dice nada a nadie. Se avisa
# antes y con la causa mas probable, que es justamente esa: ya esta abierto.
if ! "$PYTHON" - "$HOST" "$PORT" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
prueba = "127.0.0.1" if host in ("0.0.0.0", "::") else host
s = socket.socket()
s.settimeout(1)
try:
    ocupado = s.connect_ex((prueba, port)) == 0
finally:
    s.close()
sys.exit(1 if ocupado else 0)
PY
then
    echo "  [ERROR] El puerto $PORT ya está en uso." >&2
    echo >&2
    echo "  Lo más probable es que ALdia ya esté corriendo: probá abrir" >&2
    echo "  http://localhost:$PORT antes de levantar otro servidor." >&2
    echo >&2
    echo "  Si es otro programa, podés usar otro puerto:" >&2
    echo "      ALDIA_PORT=8080 ./iniciar_web.sh" >&2
    exit 1
fi

# ── Direcciones de la red local ──────────────────────────────────────────────
#
# El equivalente de `ipconfig | findstr IPv4`, pero los dos sistemas lo dicen
# distinto: Linux trae `ip` (iproute2) y macOS trae `ifconfig` con otro formato.
# Se descartan loopback (127.x) y link-local (169.254.x, la que se autoasigna
# una placa SIN red: publicarla manda a las otras terminales a la nada).
direcciones_locales() {
    if command -v ip >/dev/null 2>&1; then
        ip -4 -o addr show scope global 2>/dev/null | awk '{split($4, a, "/"); print a[1]}'
    elif command -v ifconfig >/dev/null 2>&1; then
        ifconfig 2>/dev/null | awk '/[[:space:]]inet /{print $2}'
    fi | grep -Ev '^(127\.|169\.254\.)' || true
}

echo "  Intérprete:  $PYTHON"
echo "               ($ORIGEN)"
echo
echo "  El sistema estará disponible en esta computadora y en la red local."
echo
echo "  En esta computadora:     http://localhost:$PORT"
if [ "$HOST" = "0.0.0.0" ] || [ "$HOST" = "::" ]; then
    direcciones_locales | while IFS= read -r ip; do
        [ -n "$ip" ] && echo "  Desde otras terminales:  http://$ip:$PORT"
    done
else
    echo "  (escuchando sólo en $HOST)"
fi
echo
echo "  Usuario inicial:  admin    Contraseña:  admin123"
echo "  (El sistema le exige cambiarla antes de dejarlo operar)"
echo

# ── Abrir el navegador ───────────────────────────────────────────────────────
#
# En segundo plano y ESPERANDO a que el servidor conteste, no de una: el .bat
# abria la ventana antes de que uvicorn levantara y la primera pantalla que veia
# el usuario era un "no se puede acceder a este sitio".
#
# No se usa `open` en Linux: ahi `open` es un alias de openvt (cambiar de
# terminal virtual), no "abrir el archivo con su programa". Por eso se decide
# por el sistema operativo y no por que comando exista.
abrir_navegador() {
    local url="http://localhost:$PORT"
    local intento=0
    while [ "$intento" -lt 60 ]; do
        if "$PYTHON" -c "
import socket, sys
s = socket.socket(); s.settimeout(1)
sys.exit(0 if s.connect_ex(('127.0.0.1', $PORT)) == 0 else 1)
" 2>/dev/null; then
            case "$(uname -s)" in
                Darwin) open "$url" >/dev/null 2>&1 || true ;;
                *)      xdg-open "$url" >/dev/null 2>&1 || true ;;
            esac
            return
        fi
        intento=$((intento + 1))
        sleep 0.5
    done
}

if [ "${ALDIA_SIN_NAVEGADOR:-}" = "1" ]; then
    : # pedido explicito de no abrirlo (servidor sin pantalla, systemd, docker)
elif [ "$(uname -s)" = "Darwin" ]; then
    echo "  Abriendo navegador..."
    abrir_navegador &
elif command -v xdg-open >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    # Sin DISPLAY ni WAYLAND_DISPLAY no hay escritorio: es un servidor por SSH y
    # xdg-open solo escupiria un error.
    echo "  Abriendo navegador..."
    abrir_navegador &
fi

echo "  Servidor activo. Presione Ctrl+C para detener el sistema."
echo "============================================"

cd backend
export ALDIA_HOST="$HOST"
export ALDIA_PORT="$PORT"

# exec y no una llamada comun: asi uvicorn REEMPLAZA a este script en lugar de
# colgar debajo. Sin eso, Ctrl+C y el `systemctl stop` de un servicio le llegan
# al shell y no al servidor, que queda vivo con la base abierta.
exec "$PYTHON" main.py
