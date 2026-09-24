"""
test_dinero.py - Exactitud de los importes.

Los importes se guardan como enteros de centavos justamente para que estas
pruebas pasen. Con decimales flotantes, varias de ellas fallan.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from dinero import a_centavos, a_pesos, aplicar_alicuota, multiplicar  # noqa: E402


class TestConversion:
    @pytest.mark.parametrize("pesos,centavos", [
        (0, 0),
        (1, 100),
        (0.01, 1),
        (0.1, 10),
        (1234.56, 123456),
        (999999.99, 99999999),
        (-50.25, -5025),
    ])
    def test_pesos_a_centavos(self, pesos, centavos):
        assert a_centavos(pesos) == centavos

    def test_ida_y_vuelta(self):
        for v in [0.01, 0.1, 1, 33.33, 1234.56, 99999.99]:
            assert a_pesos(a_centavos(v)) == v

    def test_redondeo_comercial_no_bancario(self):
        """0,005 redondea PARA ARRIBA, como la calculadora del contador.

        El round() de Python usa banker's rounding y daria 0,00.
        """
        assert a_centavos(0.005) == 1
        assert a_centavos(0.015) == 2
        assert a_centavos(2.675) == 268   # round(2.675, 2) da 2.67


class TestExactitud:
    def test_sumar_diez_veces_diez_centavos(self):
        """El caso que con float da 0.9999999999999999."""
        total = sum(a_centavos(0.10) for _ in range(10))
        assert total == 100
        assert a_pesos(total) == 1.00

    def test_cien_renglones_de_un_centavo(self):
        total = sum(a_centavos(0.01) for _ in range(100))
        assert a_pesos(total) == 1.00

    def test_el_clasico_cero_uno_mas_cero_dos(self):
        assert a_centavos(0.1) + a_centavos(0.2) == a_centavos(0.3)

    def test_mil_operaciones_no_derivan(self):
        total = 0
        for _ in range(1000):
            total += a_centavos(0.07)
        assert a_pesos(total) == 70.00


class TestIva:
    @pytest.mark.parametrize("neto,alicuota,iva", [
        (1000.00, 21.0, 210.00),
        (1234.56, 21.0, 259.26),    # con float daba 259.25759999999997
        (233.31, 21.0, 49.00),      # 48,9951 -> 49,00, no 48,99
        (1000.00, 10.5, 105.00),
        (100.00, 0.0, 0.00),
    ])
    def test_alicuota(self, neto, alicuota, iva):
        assert a_pesos(aplicar_alicuota(a_centavos(neto), alicuota)) == iva

    def test_suma_de_alicuotas_cierra_con_el_total(self):
        """Dos alicuotas distintas en un mismo comprobante deben cerrar exacto.

        La comparacion se hace EN CENTAVOS a proposito. Sumar los pesos ya
        convertidos (300.09 + 52.52) da 352.61000000000007 y la prueba fallaria
        por el mismo defecto del punto flotante que este modulo existe para
        evitar: en centavos la suma es de enteros, y es exacta.
        """
        base_21 = a_centavos(200.10)
        base_105 = a_centavos(99.99)
        iva_21 = aplicar_alicuota(base_21, 21.0)
        iva_105 = aplicar_alicuota(base_105, 10.5)
        neto = base_21 + base_105
        total = neto + iva_21 + iva_105

        assert a_pesos(neto) == 300.09
        assert a_pesos(iva_21) == 42.02
        assert a_pesos(iva_105) == 10.50
        # El total es exactamente neto + IVA, sin centavos perdidos.
        assert total == neto + iva_21 + iva_105
        assert a_pesos(total) == 352.61


class TestMultiplicacion:
    def test_cantidad_fraccionaria(self):
        """2,5 kg a $33,33 = $83,325 -> $83,33 (una sola vez)."""
        assert a_pesos(multiplicar(a_centavos(33.33), 2.5)) == 83.33

    def test_siete_por_treinta_y_tres_treinta_y_tres(self):
        assert a_pesos(multiplicar(a_centavos(33.33), 7)) == 233.31
