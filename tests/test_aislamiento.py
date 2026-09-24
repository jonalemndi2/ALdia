"""
Que la suite NUNCA toque la base real del comercio.

Esto existe por un incidente concreto: un cambio hizo que construir un objeto de
error disparara el primer `import database` del proceso, antes de que la fixture
definiera ALDIA_DB. El motor quedó apuntando a `backend/aldia.db` --la base real,
con clientes, facturación y auditoría-- y la suite entera escribió sobre ella.

Se detectó de casualidad, porque el login de las pruebas empezó a fallar con la
contraseña verdadera del administrador. Podría no haberse notado.

Estas pruebas son baratas y convierten ese modo de falla en algo imposible de
pasar por alto.
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
BASE_REAL = BACKEND / "aldia.db"


class TestAislamiento:
    def test_la_variable_apunta_a_una_base_temporal(self):
        ruta = os.environ.get("ALDIA_DB", "")
        assert ruta, "ALDIA_DB no está definida: la suite correría contra la base real"
        assert "aldia_test_" in ruta, f"ALDIA_DB no parece temporal: {ruta}"

    def test_el_motor_no_apunta_a_la_base_del_comercio(self):
        """La comprobación que de verdad importa: dónde quedó el engine.

        Se mira el motor YA construido, no la variable de entorno: entre las dos
        cosas está justamente el bug que esto previene.
        """
        sys.path.insert(0, str(BACKEND))
        import database

        real = str(BASE_REAL.resolve()).lower()
        usada = str(Path(database.DB_PATH).resolve()).lower()
        assert usada != real, (
            f"El motor está apuntando a la base REAL del comercio ({usada}). "
            "Alguien importó `database` antes de que conftest fijara ALDIA_DB."
        )
        assert str(database.engine.url).lower().find("aldia_test_") != -1, (
            f"El engine no está sobre una base de pruebas: {database.engine.url}"
        )

    def test_la_base_real_no_se_modifica(self, admin, cuit):
        """Operar de verdad no puede dejar rastro en el archivo del comercio."""
        if not BASE_REAL.exists():
            import pytest
            pytest.skip("No hay base real en esta máquina")

        antes = BASE_REAL.stat().st_mtime_ns
        c = cuit()
        admin.post("/api/clientes/", json={"cuit": c, "nombre": "No debe existir"})
        assert BASE_REAL.stat().st_mtime_ns == antes, (
            "La base real del comercio se modificó durante las pruebas"
        )
