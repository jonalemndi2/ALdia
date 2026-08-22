#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ALdia - Instalacion del sistema (Linux y macOS)
#
# Equivalente de instalar.bat. Prepara el entorno virtual en .venv/ e instala
# las dependencias. Solo debe ejecutarse una vez, en la PC que hace de servidor.
#
#     ./instalar.sh              instala el rango de versiones (requirements.txt)
#     ./instalar.sh --lock       instala las versiones exactas ya verificadas
#     ./instalar.sh --dev        agrega pytest y httpx (para desarrollar)
#
# Se escribe en bash 3.2 a proposito: es el que trae macOS de fabrica, y una
# sintaxis de bash 4 (arrays asociativos, ${var,,}) fallaria ahi con un error
# que no dice nada.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# Trabajar SIEMPRE desde la carpeta del script y no desde donde se lo invoco.
# Es el equivalente de `cd /d "%~dp0"`: sin esto, ejecutarlo por ruta absoluta
# desde otro directorio crearia el .venv en el lugar equivocado.
cd "$(dirname "$0")"
RAIZ="$(pwd)"

REQUISITOS="backend/requirements.txt"
ETIQUETA="rango de compatibilidad"

for argumento in "$@"; do
    case "$argumento" in
        --lock)
            REQUISITOS="backend/requirements.lock.txt"
            ETIQUETA="versiones exactas verificadas"
            ;;
        --dev)
            REQUISITOS="backend/requirements-dev.txt"
            ETIQUETA="desarrollo (incluye pytest y httpx)"
            ;;
        -h|--help)
            sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "  [ERROR] Opción desconocida: $argumento" >&2
            echo "  Use --lock, --dev o ninguna. Con --help se ve el detalle." >&2
            exit 1
            ;;
    esac
done

echo "============================================"
echo "    ALDIA - Instalación del sistema"
echo "============================================"
echo
echo "  Este proceso prepara el sistema en esta computadora (servidor)."
echo "  Sólo debe ejecutarse una vez."
echo
echo "  Sistema:      $(uname -s) $(uname -m)"
echo "  Carpeta:      $RAIZ"
echo "  Dependencias: $ETIQUETA"
echo

# ── Buscar un Python que sirva ───────────────────────────────────────────────
#
# No alcanza con `command -v python3`: macOS trae 3.9 como `python3` en las
# versiones que todavia se usan, y ALdia necesita 3.10 como minimo. Por eso se
# prueban los nombres versionados primero y se VERIFICA la version de cada
# candidato en vez de confiar en el nombre. ALDIA_PYTHON permite forzar uno
# (por ejemplo el de Homebrew) sin tocar el script.
buscar_python() {
    local candidato
    for candidato in "${ALDIA_PYTHON:-}" python3.13 python3.12 python3.11 python3.10 python3 python; do
        [ -n "$candidato" ] || continue
        command -v "$candidato" >/dev/null 2>&1 || continue
        # En macOS sin las Command Line Tools, `python3` existe pero es un stub
        # que abre un instalador grafico; ejecutarlo de verdad lo descarta.
        if "$candidato" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            command -v "$candidato"
            return 0
        fi
    done
    return 1
}

if ! PYTHON="$(buscar_python)"; then
    echo "  [ERROR] No se encontró Python 3.10 o superior." >&2
    echo >&2
    case "$(uname -s)" in
        Darwin)
            echo "  macOS:  brew install python@3.12" >&2
            echo "          (o descargarlo de https://www.python.org/downloads/)" >&2
            ;;
        *)
            echo "  Debian / Ubuntu:  sudo apt install python3 python3-venv python3-pip" >&2
            echo "  Fedora:           sudo dnf install python3 python3-pip" >&2
            echo "  Arch:             sudo pacman -S python" >&2
            ;;
    esac
    echo >&2
    echo "  Si ya lo tiene instalado en otra ruta:  ALDIA_PYTHON=/ruta/a/python3 ./instalar.sh" >&2
    exit 1
fi

echo "  Python:       $PYTHON ($("$PYTHON" -c 'import platform; print(platform.python_version())'))"
echo

# ── 1/4 Entorno virtual ──────────────────────────────────────────────────────
echo "  [1/4] Creando entorno virtual..."
if [ ! -x ".venv/bin/python" ]; then
    if ! "$PYTHON" -m venv .venv; then
        echo >&2
        echo "  [ERROR] No se pudo crear el entorno virtual en:" >&2
        echo "  $RAIZ/.venv" >&2
        echo >&2
        # En Debian y Ubuntu el modulo venv viene en un paquete aparte, y el
        # error que tira Python no lo dice con esas palabras. Es LA falla que
        # se lleva puesta a quien instala esto por primera vez en Ubuntu.
        if [ "$(uname -s)" != "Darwin" ]; then
            echo "  En Debian / Ubuntu suele faltar el paquete del módulo venv:" >&2
            echo "      sudo apt install python3-venv" >&2
            echo >&2
        fi
        echo "  Verifique también que tiene permisos de escritura en esta carpeta." >&2
        exit 1
    fi
fi

VENV_PY=".venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
    echo "  [ERROR] El entorno virtual se creó pero no tiene intérprete en" >&2
    echo "  $RAIZ/.venv/bin/python — borre la carpeta .venv y reintente." >&2
    exit 1
fi

# ── 2/4 pip ──────────────────────────────────────────────────────────────────
echo "  [2/4] Actualizando pip..."
"$VENV_PY" -m pip install --upgrade pip --quiet

# ── 3/4 Dependencias ─────────────────────────────────────────────────────────
echo "  [3/4] Instalando dependencias ($REQUISITOS)..."
if ! "$VENV_PY" -m pip install -r "$REQUISITOS"; then
    echo >&2
    echo "  [ERROR] Falló la instalación de dependencias." >&2
    echo "  Revise su conexión a internet y vuelva a intentarlo." >&2
    echo >&2
    echo "  Si el error menciona un compilador o 'building wheel', falta el" >&2
    echo "  compilador de C que necesitan cryptography y lxml:" >&2
    case "$(uname -s)" in
        Darwin) echo "      xcode-select --install" >&2 ;;
        *)      echo "      sudo apt install build-essential python3-dev libffi-dev libxml2-dev libxslt1-dev" >&2 ;;
    esac
    exit 1
fi

# ── 4/4 Verificacion ─────────────────────────────────────────────────────────
#
# Comprobar que el sistema realmente arranca, en vez de dar por buena la
# instalacion solo porque pip no devolvio error.
echo "  [4/4] Verificando la instalación..."
if ! "$VENV_PY" -c 'import fastapi, uvicorn, sqlalchemy, pydantic, bcrypt, jwt, httpx' 2>/dev/null; then
    echo >&2
    echo "  [ERROR] Las dependencias se instalaron pero no se pueden importar." >&2
    echo "  Detalle:" >&2
    "$VENV_PY" -c 'import importlib.util as u; [print("     falta:", m) for m in ["fastapi","uvicorn","sqlalchemy","pydantic","bcrypt","jwt","httpx"] if not u.find_spec(m)]' >&2 || true
    exit 1
fi

echo
echo "============================================"
echo "  Instalación completada y verificada."
echo "  Ahora puede iniciar el sistema con:  ./iniciar_web.sh"
echo "============================================"
echo
