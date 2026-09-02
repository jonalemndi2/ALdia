"""Contrato mínimo del payload UI; evita perder la cuenta elegida en refactors."""
from pathlib import Path


def test_cheque_propio_envia_cuenta_tesoreria_seleccionada():
    fuente = (Path(__file__).parents[1] / "Web/js/modules/pagos.js").read_text(encoding="utf-8")
    bloque = fuente[fuente.index("if (tipoSel === 'cheque_propio')"):
                    fuente.index("} else if (tipoSel === 'cheque_tercero')")]
    assert "document.getElementById('pagoCuenta').value" in bloque
    assert "cuenta_tesoreria_id =" in bloque
    assert "proveedor: cuit, monto, fecha, tipo, referencia, banco, vencimiento, cheque_id, cuenta_tesoreria_id" in fuente
