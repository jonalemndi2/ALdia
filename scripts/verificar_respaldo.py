#!/usr/bin/env python3
"""Ensaya restauración en un directorio temporal; nunca reemplaza la base activa."""
import argparse
import sqlite3
import tempfile
from pathlib import Path


def verificar(origen):
    origen = Path(origen).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='aldia-restauracion-') as carpeta:
        destino = Path(carpeta) / 'restaurada.db'
        with sqlite3.connect(origen.as_uri() + '?mode=ro', uri=True) as fuente:
            with sqlite3.connect(destino) as copia:
                fuente.backup(copia)
                if copia.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise ValueError('La copia tiene errores de integridad')
                if copia.execute('PRAGMA foreign_key_check').fetchall():
                    raise ValueError('La copia tiene referencias huérfanas')
                tablas = [fila[0] for fila in copia.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
                if not {'clientes', 'facturas', 'usuarios'}.issubset(tablas):
                    raise ValueError('No es una base completa de ALdía')
        # Reabrir sin WAL/SHM del origen: comprueba independencia física.
        with sqlite3.connect(destino.as_uri() + '?mode=ro', uri=True) as restaurada:
            restaurada.execute('SELECT COUNT(*) FROM facturas').fetchone()
        return len(tablas)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archivo', help='Ruta a la copia de seguridad')
    args = parser.parse_args()
    print(f'Restauración aislada verificada: {verificar(args.archivo)} tablas. No se modificó la base activa.')
