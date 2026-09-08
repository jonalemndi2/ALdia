#!/usr/bin/env bash
# Única puerta permitida para publicar ALdía.
# Verifica el árbol público, corre las pruebas privadas locales y recién después
# permite enviar master a GitHub.
set -euo pipefail

cd "$(dirname "$0")"

fallar() {
    echo "[PUBLICACIÓN BLOQUEADA] $*" >&2
    exit 1
}

MODO="${1:---verificar}"
case "$MODO" in
    --verificar|--publicar|--instalar-hook) ;;
    *) fallar "Uso: ./publicar.sh [--verificar|--publicar|--instalar-hook]" ;;
esac

if [ "$MODO" = "--instalar-hook" ]; then
    git config core.hooksPath .githooks
    echo "Hook instalado: los push directos quedan bloqueados."
    exit 0
fi

[ "$(git branch --show-current)" = "master" ] || fallar "Sólo se publica desde master."
git diff --quiet || fallar "Hay cambios sin commit."
git diff --cached --quiet || fallar "Hay cambios preparados sin commit."
[ -z "$(git ls-files --others --exclude-standard)" ] || fallar "Hay archivos nuevos sin clasificar."

# No alcanza con .gitignore: este control mira lo que Git publicaría realmente.
PROHIBIDOS="$(git ls-files | grep -E '(^|/)(tests?|fixtures?|private|privado)(/|$)|(^|/)requirements-dev\.txt$|(^|/)\.env($|\.)|\.(db|sqlite|sqlite3|pem|key|p12|pfx|crt|csr)$' | grep -vE '\.env\.example$' || true)"
[ -z "$PROHIBIDOS" ] || {
    echo "$PROHIBIDOS" | sed 's/^/  /' >&2
    fallar "Hay pruebas o archivos privados rastreados por Git."
}

# Patrones de credenciales de alta confianza. Sólo se muestran nombres de
# archivo, nunca el contenido que produjo la coincidencia.
SENSIBLES="$(git grep -IlE --cached '(-----BEGIN ([A-Z0-9 ]+ )?PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16})' -- . || true)"
[ -z "$SENSIBLES" ] || {
    echo "$SENSIBLES" | sed 's/^/  /' >&2
    fallar "Se detectó contenido con apariencia de credencial."
}

# Lista privada opcional: una cadena por línea (clientes, proveedores, dominios
# internos, etc.). Está ignorada por Git y nunca se imprime en pantalla.
if [ -s .publicar-privado ]; then
    TEMP_PATRONES="$(mktemp)"
    trap 'rm -f "$TEMP_PATRONES"' EXIT
    grep -vE '^[[:space:]]*(#|$)' .publicar-privado > "$TEMP_PATRONES" || true
    if [ -s "$TEMP_PATRONES" ]; then
        COINCIDENCIAS="$(git grep -IlF --cached -f "$TEMP_PATRONES" -- . || true)"
        [ -z "$COINCIDENCIAS" ] || {
            echo "$COINCIDENCIAS" | sed 's/^/  /' >&2
            fallar "Un archivo público contiene información marcada como privada."
        }
    fi
fi

# Las pruebas viven en el equipo de desarrollo, pero no forman parte del árbol
# público. Publicar sin tenerlas o sin ejecutarlas queda prohibido.
[ -d tests ] || fallar "No está disponible la suite privada local."
if [ -x .venv/bin/python ]; then
    PYTHON=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then
    PYTHON=.venv/Scripts/python.exe
else
    fallar "No existe el entorno virtual local."
fi

"$PYTHON" -m pytest tests/ -q
"$PYTHON" -m compileall -q backend mcp
git diff --check

if command -v node >/dev/null 2>&1; then
    find Web/js -type f -name '*.js' -print | while IFS= read -r archivo; do
        node --check "$archivo"
    done
fi

echo "Publicación verificada: pruebas privadas y controles de privacidad aprobados."

if [ "$MODO" = "--publicar" ]; then
    git fetch origin master
    set -- $(git rev-list --left-right --count origin/master...master)
    [ "$1" = "0" ] || fallar "origin/master tiene cambios que faltan localmente."
    ALDIA_PUBLICACION_VALIDADA=1 git push origin master
fi
