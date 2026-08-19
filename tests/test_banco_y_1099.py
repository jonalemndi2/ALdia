"""
Libro de banco y planilla 1099.

El libro de banco arregla un número que estaba mal: el saldo de caja incluía
transferencias y tarjetas, o sea plata que no está en el cajón. Cerrar la caja
contando billetes nunca podía dar ese número.

La planilla 1099 es lo contrario de generar un formulario: junta los datos y
dice, en la misma respuesta, todo lo que el sistema NO puede saber.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import medios_de_pago as mp  # noqa: E402


def _cliente_con_deuda(admin, cuit, monto=1000.0):
    c = cuit()
    admin.post("/api/clientes/", json={"cuit": c, "nombre": "Cliente banco"})
    admin.post("/api/facturas/", json={
        "cliente": c, "fecha": "2026-08-19", "tipo": "A",
        "subtotal": monto, "iva": 0.0, "total": monto, "items": []})
    return c


class TestACualCuentaVaCadaMedio:
    def test_el_efectivo_va_al_cajon(self):
        assert mp.cuenta_de("efectivo") == mp.CUENTA_EFECTIVO

    def test_lo_electronico_va_al_banco(self):
        for tipo in ("transferencia", "ach", "tarjeta_credito", "tarjeta_debito"):
            assert mp.cuenta_de(tipo) == mp.CUENTA_BANCO, tipo

    def test_un_tipo_desconocido_se_asume_en_el_cajon(self):
        """Es la suposición conservadora: si alguien contó mal la caja, se nota."""
        assert mp.cuenta_de("cualquier cosa") == mp.CUENTA_EFECTIVO


class TestElSaldoSeSepara:
    def test_una_transferencia_no_infla_el_efectivo(self, admin, cuit):
        """El bug: cerrar la caja contando billetes nunca daba el saldo."""
        c = _cliente_con_deuda(admin, cuit)
        antes = admin.get("/api/caja/saldo").json()

        r = admin.post("/api/cobros/", json={
            "cliente": c, "monto": 1000.0, "fecha": "2026-08-19",
            "tipo": "transferencia", "referencia": "TRF-001"})
        assert r.status_code in (200, 201), r.text

        despues = admin.get("/api/caja/saldo").json()
        # El total sube: la plata entró y tiene que figurar.
        assert despues["saldo"] == antes["saldo"] + 1000.0
        # Pero el efectivo NO: no hay mil pesos más en el cajón.
        assert despues["efectivo"] == antes["efectivo"]
        assert despues["banco"] == antes["banco"] + 1000.0

    def test_el_efectivo_si_sube_con_efectivo(self, admin, cuit):
        c = _cliente_con_deuda(admin, cuit)
        antes = admin.get("/api/caja/saldo").json()
        admin.post("/api/cobros/", json={
            "cliente": c, "monto": 1000.0, "fecha": "2026-08-19", "tipo": "efectivo"})
        despues = admin.get("/api/caja/saldo").json()
        assert despues["efectivo"] == antes["efectivo"] + 1000.0
        assert despues["banco"] == antes["banco"]

    def test_las_dos_cuentas_suman_el_total(self, admin, cuit):
        """Nada se pierde entre medio: es la garantía de que no desaparece plata."""
        c = _cliente_con_deuda(admin, cuit, 500.0)
        admin.post("/api/cobros/", json={
            "cliente": c, "monto": 500.0, "fecha": "2026-08-19",
            "tipo": "tarjeta_credito", "referencia": "T-9"})
        s = admin.get("/api/caja/saldo").json()
        assert round(s["efectivo"] + s["banco"], 2) == round(s["saldo"], 2)

    def test_el_dashboard_muestra_la_apertura(self, admin):
        d = admin.get("/api/admin/dashboard").json()
        # `caja_saldo` conserva el significado de siempre para no cambiarle el
        # número a nadie de golpe; la apertura va al lado.
        assert "caja_saldo" in d and "caja_efectivo" in d and "caja_banco" in d
        assert round(d["caja_efectivo"] + d["caja_banco"], 2) == round(d["caja_saldo"], 2)


class TestPlanilla1099:
    def _proveedor(self, admin, cuit, **extra):
        c = cuit("30")
        datos = {"cuit": c, "nombre": "Acme Supply"}
        datos.update(extra)
        admin.post("/api/proveedores/", json=datos)
        return c

    def test_solo_aparecen_los_marcados_como_elegibles(self, admin, cuit):
        comun = self._proveedor(admin, cuit)
        elegible = self._proveedor(admin, cuit, elegible_1099=True, w9_recibido=True)
        for prov in (comun, elegible):
            admin.post("/api/pagos/", json={
                "proveedor": prov, "monto": 800.0, "fecha": "2026-05-10",
                "tipo": "efectivo"})

        r = admin.get("/api/proveedores/informe-1099", params={"anio": 2026})
        assert r.status_code == 200, r.text
        ids = {f["tax_id"] for f in r.json()["proveedores"]}
        assert elegible in ids
        assert comun not in ids, "Un proveedor no marcado no puede aparecer"

    def test_suma_solo_los_pagos_del_anio(self, admin, cuit):
        p = self._proveedor(admin, cuit, elegible_1099=True, w9_recibido=True)
        admin.post("/api/pagos/", json={"proveedor": p, "monto": 300.0,
                                        "fecha": "2026-03-01", "tipo": "efectivo"})
        admin.post("/api/pagos/", json={"proveedor": p, "monto": 200.0,
                                        "fecha": "2026-11-30", "tipo": "efectivo"})
        admin.post("/api/pagos/", json={"proveedor": p, "monto": 999.0,
                                        "fecha": "2025-12-31", "tipo": "efectivo"})

        fila = next(f for f in admin.get("/api/proveedores/informe-1099",
                                         params={"anio": 2026}).json()["proveedores"]
                    if f["tax_id"] == p)
        assert fila["total_pagado"] == 500.0, "Se coló un pago de otro año"

    def test_avisa_de_quien_falta_el_W9(self, admin, cuit):
        """No se lo esconde: se lista para que se sepa que hay que pedirlo."""
        p = self._proveedor(admin, cuit, elegible_1099=True, w9_recibido=False,
                            nombre="Sin Papeles LLC")
        admin.post("/api/pagos/", json={"proveedor": p, "monto": 700.0,
                                        "fecha": "2026-06-01", "tipo": "efectivo"})
        datos = admin.get("/api/proveedores/informe-1099",
                          params={"anio": 2026}).json()
        fila = next(f for f in datos["proveedores"] if f["tax_id"] == p)
        assert fila["listo_para_declarar"] is False
        assert "Sin Papeles LLC" in datos["sin_w9"]
        assert any("W-9" in a for a in datos["advertencias"])

    def test_dice_que_NO_es_un_formulario(self, admin):
        """Lo más importante del endpoint: que nadie lo confunda con un 1099."""
        datos = admin.get("/api/proveedores/informe-1099",
                          params={"anio": 2026}).json()
        texto = " ".join(datos["advertencias"]).lower()
        assert "no es un formulario 1099" in texto
        # Y que declara lo que el sistema no puede saber.
        assert "servicios" in texto and "mercaderia" in texto

    def test_un_anio_absurdo_se_rechaza(self, admin):
        r = admin.get("/api/proveedores/informe-1099", params={"anio": 99})
        assert r.status_code == 422
        assert r.json()["codigo"] == "DATOS_INVALIDOS"
