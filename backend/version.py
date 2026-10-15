"""
version.py - Que version de ALdia esta instalada, si hay una nueva y como instalarla.

FUENTE DE VERDAD
----------------
El archivo VERSION de la raiz del repositorio. Las novedades salen de
CHANGELOG.md, con titulos `## X.Y.Z — AAAA-MM-DD`. Publicar una version es
subir esos dos archivos actualizados: no hay otro lugar donde anotarla.

BUSQUEDA DE ACTUALIZACIONES
---------------------------
Se leen VERSION y CHANGELOG.md del repositorio publico (raw.githubusercontent,
sin API ni token, sin limite de consultas que importe). Solo se envia un GET
anonimo: ningun dato del comercio sale del equipo. Se cachea unas horas.

  ALDIA_BUSCAR_ACTUALIZACIONES=no     no consultar nunca (equipo sin internet o
                                      por politica del comercio).
  ALDIA_ACTUALIZACIONES_URL=...       otra fuente (un fork, una rama).

INSTALACION
-----------
Solo para instalaciones hechas con `git clone`: copia de seguridad de la base,
`git fetch` + `git merge --ff-only`, dependencias si cambio el lock, y reinicio
si hay un comando configurado:

  ALDIA_COMANDO_REINICIO="systemctl --user restart --no-block aldia-web"

Sin ese comando, ALdia avisa que hay que reiniciarlo a mano. Nunca se pisa un
cambio local: si el arbol tiene modificaciones o la rama se aparto del
repositorio, la actualizacion se niega y explica por que.
"""
from __future__ import annotations

import os
import re
import shlex
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime

import httpx

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVO_VERSION = os.path.join(RAIZ, "VERSION")
ARCHIVO_CHANGELOG = os.path.join(RAIZ, "CHANGELOG.md")

URL_POR_DEFECTO = "https://raw.githubusercontent.com/jonalemndi2/ALdia/master"
CACHE_SEGUNDOS = 6 * 3600
TIMEOUT_SEGUNDOS = 5

_RE_TITULO = re.compile(r"^##\s+(\d+\.\d+\.\d+)\s*(?:[—–-]\s*(\S+))?\s*$")

_cache: dict = {"momento": 0.0, "resultado": None}
_candado = threading.Lock()


class ErrorDeActualizacion(Exception):
    """La actualizacion no se puede hacer; el mensaje dice por que y que hacer."""


# ─────────────────────────────────────────────────────────────
# Version instalada
# ─────────────────────────────────────────────────────────────

def version_instalada() -> str:
    try:
        with open(ARCHIVO_VERSION, encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _git(*args: str, timeout: int = 60) -> str:
    r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise ErrorDeActualizacion((r.stderr or r.stdout).strip() or f"git {' '.join(args)} fallo")
    return r.stdout.strip()


def commit_instalado() -> str | None:
    try:
        return _git("rev-parse", "--short", "HEAD", timeout=5)
    except Exception:  # noqa: BLE001 - sin git o sin repo: no es un error
        return None


def comparar(a: str, b: str) -> int:
    """-1, 0 o 1 segun a < b, a == b o a > b. Lo que no es numero cuenta como 0."""
    def partes(v: str) -> tuple[int, ...]:
        return tuple(int(x) if x.isdigit() else 0 for x in (v or "0").split(".")[:3])
    pa, pb = partes(a), partes(b)
    return (pa > pb) - (pa < pb)


# ─────────────────────────────────────────────────────────────
# Novedades
# ─────────────────────────────────────────────────────────────

def secciones_changelog(texto: str) -> list[dict]:
    """Las secciones `## X.Y.Z — fecha` del changelog, en el orden del archivo."""
    secciones: list[dict] = []
    actual = None
    for linea in texto.splitlines():
        m = _RE_TITULO.match(linea.strip())
        if m:
            actual = {"version": m.group(1), "fecha": m.group(2) or "", "lineas": []}
            secciones.append(actual)
        elif actual is not None:
            actual["lineas"].append(linea)
    return [
        {"version": s["version"], "fecha": s["fecha"], "texto": "\n".join(s["lineas"]).strip()}
        for s in secciones
    ]


def novedades_entre(texto_changelog: str, desde: str, hasta: str) -> list[dict]:
    """Secciones con version > desde y <= hasta, de la mas nueva a la mas vieja."""
    return [
        s for s in secciones_changelog(texto_changelog)
        if comparar(s["version"], desde) > 0 and comparar(s["version"], hasta) <= 0
    ]


def changelog_local() -> str:
    try:
        with open(ARCHIVO_CHANGELOG, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# ─────────────────────────────────────────────────────────────
# Version disponible
# ─────────────────────────────────────────────────────────────

def busqueda_habilitada() -> bool:
    return os.getenv("ALDIA_BUSCAR_ACTUALIZACIONES", "si").strip().lower() not in ("no", "0", "false")


def _url_base() -> str:
    return os.getenv("ALDIA_ACTUALIZACIONES_URL", URL_POR_DEFECTO).rstrip("/")


def buscar_actualizacion(refrescar: bool = False) -> dict:
    """Compara la version instalada con la publicada. Nunca lanza: informa el error."""
    instalada = version_instalada()
    if not busqueda_habilitada():
        return {"consultada": False, "disponible": False, "ultima": None, "novedades": [],
                "motivo": "Busqueda de actualizaciones desactivada (ALDIA_BUSCAR_ACTUALIZACIONES=no)."}

    with _candado:
        vigente = _cache["resultado"] is not None and time.time() - _cache["momento"] < CACHE_SEGUNDOS
        if vigente and not refrescar and _cache["resultado"].get("_instalada") == instalada:
            return {k: v for k, v in _cache["resultado"].items() if not k.startswith("_")}

        base = _url_base()
        try:
            r = httpx.get(f"{base}/VERSION", timeout=TIMEOUT_SEGUNDOS, follow_redirects=True)
            r.raise_for_status()
            ultima = r.text.strip()
            if not re.fullmatch(r"\d+\.\d+\.\d+", ultima):
                raise ValueError(f"VERSION publicada con formato inesperado: {ultima[:20]!r}")
            novedades: list[dict] = []
            if comparar(ultima, instalada) > 0:
                c = httpx.get(f"{base}/CHANGELOG.md", timeout=TIMEOUT_SEGUNDOS, follow_redirects=True)
                if c.status_code == 200:
                    novedades = novedades_entre(c.text, instalada, ultima)
            resultado = {"consultada": True, "disponible": comparar(ultima, instalada) > 0,
                         "ultima": ultima, "novedades": novedades,
                         "consultada_en": datetime.now().isoformat(timespec="seconds")}
        except Exception as exc:  # noqa: BLE001 - sin internet no es un error del sistema
            resultado = {"consultada": False, "disponible": False, "ultima": None, "novedades": [],
                         "motivo": f"No se pudo consultar la version publicada ({type(exc).__name__})."}

        _cache.update(momento=time.time(), resultado={**resultado, "_instalada": instalada})
        return resultado


def estado() -> dict:
    return {
        "version": version_instalada(),
        "commit": commit_instalado(),
        "actualizacion": buscar_actualizacion(),
        "puede_autoactualizarse": _es_repositorio_git(),
        "reinicio_automatico": bool(os.getenv("ALDIA_COMANDO_REINICIO", "").strip()),
    }


# ─────────────────────────────────────────────────────────────
# Instalacion
# ─────────────────────────────────────────────────────────────

def _es_repositorio_git() -> bool:
    try:
        return _git("rev-parse", "--is-inside-work-tree", timeout=5) == "true"
    except Exception:  # noqa: BLE001
        return False


def _respaldar_base(db_path: str) -> str | None:
    """Copia coherente de la base, FUERA de la rotacion diaria de respaldo.py."""
    if not os.path.exists(db_path):
        return None
    from respaldo import carpeta_de_copias
    carpeta = carpeta_de_copias(db_path)
    os.makedirs(carpeta, exist_ok=True)
    destino = os.path.join(carpeta, f"pre-actualizacion-{datetime.now():%Y%m%d-%H%M%S}.db")
    origen = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        copia = sqlite3.connect(destino)
        try:
            origen.backup(copia)
        finally:
            copia.close()
    finally:
        origen.close()
    return destino


def _programar_reinicio() -> bool:
    comando = os.getenv("ALDIA_COMANDO_REINICIO", "").strip()
    if not comando:
        return False

    def reiniciar():
        time.sleep(2)  # que la respuesta llegue al navegador antes de caerse
        subprocess.Popen(shlex.split(comando), cwd=RAIZ, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    threading.Thread(target=reiniciar, daemon=True).start()
    return True


def actualizar(db_path: str) -> dict:
    """Instala la ultima version publicada. Lanza ErrorDeActualizacion si no corresponde."""
    if not _es_repositorio_git():
        raise ErrorDeActualizacion(
            "Esta instalacion no se hizo con git clone, asi que no se puede actualizar sola. "
            "Descargue la version nueva del repositorio y reemplace los archivos del programa "
            "(nunca la carpeta backend/copias ni la base aldia.db)."
        )

    cambios = _git("status", "--porcelain", "--untracked-files=no")
    if cambios:
        raise ErrorDeActualizacion(
            "Hay archivos del programa modificados en este equipo. Para no pisarlos, la "
            "actualizacion se cancela. Archivos: " + ", ".join(l[3:] for l in cambios.splitlines()[:10])
        )

    try:
        _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", timeout=5)
    except ErrorDeActualizacion:
        raise ErrorDeActualizacion(
            "La rama actual no sigue a ninguna rama del repositorio publico (git branch -u origin/master)."
        ) from None

    anterior = version_instalada()
    commit_anterior = _git("rev-parse", "HEAD", timeout=5)
    _git("fetch", "--quiet", timeout=120)
    pendientes = int(_git("rev-list", "--count", "HEAD..@{u}", timeout=10) or 0)
    if pendientes == 0:
        return {"actualizado": False, "version": anterior,
                "mensaje": f"ALdia ya esta en la ultima version ({anterior})."}

    respaldo = _respaldar_base(db_path)
    try:
        _git("merge", "--ff-only", "@{u}", timeout=60)
    except ErrorDeActualizacion as exc:
        raise ErrorDeActualizacion(
            "Este equipo tiene cambios propios que no estan en el repositorio publico; no se puede "
            f"actualizar sin mezclar a mano. Detalle de git: {exc}"
        ) from None

    nueva = version_instalada()
    cambiados = set(_git("diff", "--name-only", commit_anterior, "HEAD", timeout=10).splitlines())
    dependencias = None
    if "backend/requirements.lock.txt" in cambiados:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r",
             os.path.join(RAIZ, "backend", "requirements.lock.txt")],
            cwd=RAIZ, capture_output=True, text=True, timeout=900,
        )
        dependencias = "instaladas" if r.returncode == 0 else f"ERROR: {(r.stderr or r.stdout)[-400:]}"

    avisos = []
    if "mcp/requirements.lock.txt" in cambiados:
        avisos.append("Cambiaron las dependencias del servidor MCP: reinstalarlas en mcp/.venv.")
    if any(p.startswith("skills/") for p in cambiados):
        avisos.append("Cambiaron las skills del asistente: si el asistente usa una copia, actualizarla desde skills/.")

    reinicio = _programar_reinicio()
    return {
        "actualizado": True,
        "version_anterior": anterior,
        "version": nueva,
        "respaldo": os.path.basename(respaldo) if respaldo else None,
        "dependencias": dependencias,
        "novedades": novedades_entre(changelog_local(), anterior, nueva),
        "avisos": avisos,
        "reinicio": "automatico" if reinicio else "manual",
        "mensaje": (
            f"ALdia se actualizo de {anterior} a {nueva}. "
            + ("Se reinicia solo en unos segundos." if reinicio
               else "Reinicie ALdia para que tome la version nueva.")
        ),
    }
