"""
Copia de seguridad automatica.

La prueba que importa de verdad es `test_la_copia_en_caliente_no_pierde_nada`:
es la que distingue este respaldo de un `shutil.copy`, que es lo que uno
escribiria sin pensarlo y lo que produce copias incompletas en modo WAL.
"""
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import respaldo  # noqa: E402


def _base_con_datos(ruta: str, filas: int = 50, wal: bool = True) -> None:
    con = sqlite3.connect(ruta)
    if wal:
        con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY, total INTEGER)")
    con.executemany("INSERT INTO facturas (total) VALUES (?)", [(i * 100,) for i in range(filas)])
    con.commit()
    con.close()


def _contar(ruta: str, tabla: str = "facturas") -> int:
    con = sqlite3.connect(ruta)
    try:
        return con.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]
    finally:
        con.close()


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Base y carpeta de copias aisladas: nunca se toca la del comercio."""
    db = tmp_path / "aldia.db"
    copias = tmp_path / "copias"
    monkeypatch.setenv("ALDIA_BACKUP_DIR", str(copias))
    monkeypatch.delenv("ALDIA_SIN_RESPALDO", raising=False)
    return db, copias


class TestLaCopia:
    def test_se_crea_y_es_integra(self, entorno):
        db, copias = entorno
        _base_con_datos(str(db))

        destino = respaldo.copiar(str(db))

        assert destino is not None and os.path.exists(destino)
        assert _contar(destino) == 50
        con = sqlite3.connect(destino)
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        con.close()

    def test_la_copia_en_caliente_no_pierde_nada(self, entorno):
        """El motivo por el que no se usa shutil.copy.

        En modo WAL las operaciones recientes viven en el archivo -wal, no en el
        .db. Se deja una conexion ABIERTA con transacciones ya confirmadas pero
        sin checkpoint --exactamente el estado del servidor a media manana-- y
        se comprueba que la copia las tenga.
        """
        db, _ = entorno
        _base_con_datos(str(db), filas=10)

        viva = sqlite3.connect(str(db))
        viva.execute("PRAGMA journal_mode=WAL")
        viva.executemany("INSERT INTO facturas (total) VALUES (?)",
                         [(999,) for _ in range(40)])
        viva.commit()
        try:
            # Sin checkpoint: las 40 nuevas estan en el -wal.
            assert os.path.exists(str(db) + "-wal")

            destino = respaldo.copiar(str(db))

            assert _contar(destino) == 50, (
                "La copia perdio las operaciones que estaban en el WAL. "
                "Es exactamente lo que pasa con shutil.copy."
            )
            # Y se restaura sola, sin necesitar los -wal/-shm al lado.
            assert not os.path.exists(destino + "-wal")
        finally:
            viva.close()

    def test_no_repite_la_copia_del_dia(self, entorno):
        db, copias = entorno
        _base_con_datos(str(db))

        assert respaldo.copiar(str(db)) is not None
        # Reiniciar el servidor cinco veces no debe generar cinco copias ni
        # demorar el arranque.
        assert respaldo.copiar(str(db)) is None
        assert respaldo.copiar(str(db)) is None
        assert len(list(copias.iterdir())) == 1

    def test_forzar_la_rehace(self, entorno):
        db, _ = entorno
        _base_con_datos(str(db))
        respaldo.copiar(str(db))
        assert respaldo.copiar(str(db), forzar=True) is not None

    def test_una_base_que_todavia_no_existe_no_es_un_error(self, entorno):
        db, _ = entorno
        # Primer arranque: no hay nada que respaldar y no debe romper.
        assert respaldo.copiar(str(db)) is None

    def test_no_deja_copias_a_medias(self, entorno, monkeypatch):
        """Si el proceso muere copiando, no puede quedar un archivo truncado
        ocupando el nombre del dia y haciendo creer que la copia existe."""
        db, copias = entorno
        _base_con_datos(str(db))

        # sqlite3.Connection es inmutable, asi que no se le puede pisar el
        # metodo: se envuelve la conexion que devuelve connect().
        real_connect = sqlite3.connect

        class ConexionQueFallaAlCopiar:
            def __init__(self, real):
                self._real = real

            def backup(self, *a, **k):
                raise sqlite3.OperationalError("disco lleno")

            def __getattr__(self, nombre):
                return getattr(self._real, nombre)

        monkeypatch.setattr(
            respaldo.sqlite3, "connect",
            lambda *a, **k: ConexionQueFallaAlCopiar(real_connect(*a, **k)),
        )
        with pytest.raises(sqlite3.OperationalError):
            respaldo.copiar(str(db))

        nombre_del_dia = f"aldia-{datetime.now().strftime('%Y-%m-%d')}.db"
        assert not (copias / nombre_del_dia).exists(), (
            "Quedo una copia con el nombre del dia que en realidad esta incompleta"
        )
        # Y tampoco el temporal: si falla en cada arranque, se acumularian.
        assert list(copias.iterdir()) == [], (
            f"Quedaron restos: {[p.name for p in copias.iterdir()]}"
        )


class TestRotacion:
    def test_conserva_las_ultimas_y_borra_las_viejas(self, entorno):
        _db, copias = entorno
        copias.mkdir()
        for dia in range(1, 13):
            (copias / f"aldia-2026-03-{dia:02d}.db").write_bytes(b"x")

        borradas = respaldo._rotar(str(copias), conservar=7)

        quedan = sorted(p.name for p in copias.iterdir())
        assert len(quedan) == 7
        assert len(borradas) == 5
        # Se van las mas VIEJAS, no cualesquiera.
        assert quedan[0] == "aldia-2026-03-06.db"
        assert quedan[-1] == "aldia-2026-03-12.db"

    def test_no_toca_archivos_ajenos(self, entorno):
        _db, copias = entorno
        copias.mkdir()
        for dia in range(1, 11):
            (copias / f"aldia-2026-03-{dia:02d}.db").write_bytes(b"x")
        (copias / "LEEME.txt").write_text("no me borres")
        (copias / "aldia.db").write_bytes(b"x")  # sin fecha: no es una copia rotativa

        respaldo._rotar(str(copias), conservar=7)

        assert (copias / "LEEME.txt").exists()
        assert (copias / "aldia.db").exists()


class TestArranque:
    def test_nunca_impide_arrancar(self, entorno, monkeypatch, capsys):
        """Un problema con la copia no puede dejar al comercio sin facturar."""
        db, _ = entorno
        _base_con_datos(str(db))
        monkeypatch.setattr(respaldo, "copiar",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("disco lleno")))

        respaldo.respaldar_al_arrancar(str(db))  # no debe propagar

        assert "NO HAY COPIA" in capsys.readouterr().err

    def test_se_puede_apagar(self, entorno, monkeypatch):
        db, copias = entorno
        _base_con_datos(str(db))
        monkeypatch.setenv("ALDIA_SIN_RESPALDO", "1")

        respaldo.respaldar_al_arrancar(str(db))

        assert not copias.exists()

    def test_el_circuito_completo_avisa_donde_quedo(self, entorno, capsys):
        db, _ = entorno
        _base_con_datos(str(db))

        respaldo.respaldar_al_arrancar(str(db))

        salida = capsys.readouterr().out
        assert "Copia del dia" in salida
        # Que la copia esta en el mismo disco es un limite real y hay que decirlo.
        assert "MISMO disco" in salida
