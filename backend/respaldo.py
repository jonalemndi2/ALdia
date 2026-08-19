"""
respaldo.py - Copia de seguridad automatica de la base.

POR QUE ESTO NO PUEDE QUEDAR "A CARGO DE QUIEN INSTALA"
======================================================
El README decia que automatizar la copia es responsabilidad de quien instala el
sistema. Es cierto en teoria y falso en la practica: el destinatario de ALdia es
un kiosco o un supermercado chico, donde nadie va a configurar una tarea
programada. En los hechos eso significaba que la copia no se hacia NUNCA.

Y es el unico desastre del que no se vuelve. Un error de facturacion se corrige;
un disco que muere sin respaldo se lleva la cuenta corriente de todos los
clientes, el libro de IVA y los comprobantes emitidos. La auditoria tampoco
ayuda ahi: vive en el mismo archivo.

Asi que la copia se hace sola, al arrancar, sin preguntar nada.

POR QUE NO ALCANZA CON COPIAR EL ARCHIVO
========================================
La base corre en modo WAL (ver database.py). En WAL las operaciones mas
recientes viven en `aldia.db-wal`, NO dentro de `aldia.db`, y se pasan al
archivo principal recien en el checkpoint. Copiar `aldia.db` con `shutil.copy`
mientras el servidor esta andando produce un archivo que:

  * puede estar internamente inconsistente (se copio a la mitad de una escritura), y
  * casi seguro NO tiene las ultimas operaciones del dia.

Es la peor clase de respaldo: el que parece que existe. Por eso se usa la API de
respaldo propia de SQLite (`Connection.backup()`, en la biblioteca estandar
desde Python 3.7), que toma una foto coherente aunque haya escrituras en curso y
resuelve el WAL sola. El resultado es un unico archivo `.db` que se restaura
copiandolo encima del original, sin necesidad de los `-wal` y `-shm`.

De paso corre `PRAGMA integrity_check` sobre la copia recien hecha: un respaldo
que nadie verifico es una suposicion, y el momento de descubrir que esta
corrupto no puede ser el dia que hace falta.

CUANDO CORRE
============
Al arrancar el servidor, UNA VEZ POR DIA. En un comercio el servidor se prende a
la manana y se apaga a la noche, asi que "al arrancar" es "una vez por dia" sin
necesidad de dejar nada corriendo en segundo plano. Si ya existe la copia de hoy
no hace nada, de modo que reiniciar el sistema cinco veces no genera cinco
copias ni demora el arranque.

QUE NO HACE
===========
No saca la copia de la maquina. Un respaldo en el mismo disco protege contra un
borrado accidental o una base corrupta, NO contra el disco que se rompe ni
contra el ransomware. Esa parte sigue siendo responsabilidad de quien instala, y
ahora es mucho mas facil: alcanza con sincronizar la carpeta de copias a un
pendrive o a la nube. El arranque lo dice por consola para que no se olvide.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime

# Cuantas copias diarias se conservan. Una semana es el punto donde deja de
# crecer el disco y todavia alcanza para notar un problema del lunes el viernes.
COPIAS_A_CONSERVAR = int(os.getenv("ALDIA_COPIAS", "7"))

# Donde se guardan. Por defecto al lado de la base; se puede apuntar a otro
# disco o a una carpeta sincronizada, que es lo recomendable.
CARPETA_POR_DEFECTO = "copias"

PREFIJO = "aldia-"
EXTENSION = ".db"


def carpeta_de_copias(db_path: str) -> str:
    destino = os.getenv("ALDIA_BACKUP_DIR")
    if destino and destino.strip():
        return os.path.abspath(destino.strip())
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), CARPETA_POR_DEFECTO)


def _nombre_de_hoy() -> str:
    return f"{PREFIJO}{datetime.now().strftime('%Y-%m-%d')}{EXTENSION}"


def _copias_existentes(carpeta: str) -> list[str]:
    """Las copias que hay, de la mas vieja a la mas nueva.

    Se ordenan por NOMBRE y no por fecha de modificacion: el nombre lleva la
    fecha en formato ISO, que ordena bien como texto, y no se rompe si alguien
    copia los archivos a otro lado (lo cual cambia la fecha del sistema).
    """
    if not os.path.isdir(carpeta):
        return []
    return sorted(
        n for n in os.listdir(carpeta)
        if n.startswith(PREFIJO) and n.endswith(EXTENSION)
    )


def _verificar(ruta: str) -> None:
    """Que la copia recien hecha se pueda abrir y no este corrupta."""
    con = sqlite3.connect(ruta)
    try:
        resultado = con.execute("PRAGMA integrity_check").fetchone()
        if not resultado or resultado[0] != "ok":
            raise sqlite3.DatabaseError(f"integrity_check devolvio {resultado!r}")
    finally:
        con.close()


def _rotar(carpeta: str, conservar: int) -> list[str]:
    """Borra las copias mas viejas, dejando `conservar`. Devuelve las borradas."""
    copias = _copias_existentes(carpeta)
    sobrantes = copias[:-conservar] if conservar > 0 else []
    borradas = []
    for nombre in sobrantes:
        try:
            os.remove(os.path.join(carpeta, nombre))
            borradas.append(nombre)
        except OSError:
            # Que no se pueda borrar una copia vieja no es motivo para nada:
            # el respaldo de hoy ya esta hecho, que es lo que importa.
            pass
    return borradas


def copiar(db_path: str, forzar: bool = False) -> str | None:
    """Hace la copia del dia y rota las viejas. Devuelve la ruta, o None si no hizo falta.

    `forzar` saltea el "ya existe la de hoy" y sirve para pedir una copia a mano
    antes de una operacion riesgosa.
    """
    if not os.path.exists(db_path):
        return None  # base nueva: todavia no hay nada que respaldar

    carpeta = carpeta_de_copias(db_path)
    os.makedirs(carpeta, exist_ok=True)
    destino = os.path.join(carpeta, _nombre_de_hoy())

    if os.path.exists(destino) and not forzar:
        return None

    # A un archivo temporal primero: si el proceso muere a la mitad, no queda
    # una copia truncada ocupando el nombre del dia y haciendo creer que existe.
    parcial = destino + ".parcial"
    try:
        origen = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            copia = sqlite3.connect(parcial)
            try:
                # La API de respaldo de SQLite: coherente aunque haya escrituras
                # en curso, y resuelve el WAL. Ver el encabezado del archivo.
                origen.backup(copia)
            finally:
                copia.close()
        finally:
            origen.close()
        _verificar(parcial)
    except BaseException:
        # Que no quede el .parcial tirado. Si falla siempre --disco lleno-- sin
        # esto se acumula una copia rota por arranque, que es la unica forma de
        # que el respaldo termine ocupando MAS lugar justo cuando no hay lugar.
        for resto in (parcial, parcial + "-wal", parcial + "-shm"):
            try:
                os.remove(resto)
            except OSError:
                pass
        raise

    os.replace(parcial, destino)  # atomico: o esta la copia entera, o no esta
    return destino


def respaldar_al_arrancar(db_path: str) -> None:
    """Punto de entrada desde main.py. NUNCA impide que el sistema arranque.

    Un problema con la copia no puede dejar al comercio sin poder facturar: se
    avisa por consola, fuerte, y el sistema sigue. El caso tipico es un disco
    lleno o una carpeta de red que no responde.
    """
    if os.getenv("ALDIA_SIN_RESPALDO", "").lower() in ("1", "true", "si"):
        return

    try:
        destino = copiar(db_path)
    except Exception as exc:  # pragma: no cover - defensivo
        print(f"[respaldo] NO se pudo copiar la base: {exc}", file=sys.stderr)
        print("[respaldo] El sistema arranca igual, pero HOY NO HAY COPIA.",
              file=sys.stderr)
        return

    carpeta = carpeta_de_copias(db_path)
    if destino is None:
        return  # ya estaba la de hoy, o la base todavia no existe

    borradas = _rotar(carpeta, COPIAS_A_CONSERVAR)
    print(f"[respaldo] Copia del dia: {destino}")
    if borradas:
        print(f"[respaldo] Se borraron {len(borradas)} copias con mas de "
              f"{COPIAS_A_CONSERVAR} dias.")
    print("[respaldo] Recorde que esta copia esta en el MISMO disco: sincroniza "
          "esta carpeta a un pendrive o a la nube.")
