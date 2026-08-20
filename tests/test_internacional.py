"""
Los pasos 3 a 7 del plan de internacionalización, contra la aplicación real.

Dirección internacional, moneda explícita, medios de pago generalizados,
impuesto enchufable y datos de proveedor estadounidense.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import direcciones  # noqa: E402
import impuestos  # noqa: E402
import medios_de_pago as mp  # noqa: E402


class TestDireccionInternacional:
    def test_lo_viejo_completa_lo_nuevo(self, admin, cuit):
        """Una ficha cargada con los campos de siempre queda bien en los dos."""
        c = cuit()
        r = admin.post("/api/clientes/", json={
            "cuit": c, "nombre": "De Siempre",
            "domicilio": "San Martín 123", "localidad": "Del Campillo",
            "provincia": "Córdoba", "cp": "6270"})
        d = r.json()
        assert d["address_line_1"] == "San Martín 123"
        assert d["city"] == "Del Campillo"
        assert d["region"] == "Córdoba"
        assert d["postal_code"] == "6270"
        # El país se toma de la instalación: no existía en el modelo viejo.
        assert d["country_code"] == "AR"

    def test_lo_nuevo_completa_lo_viejo(self, admin, cuit):
        """Para que el frontend y el MCP, que leen los campos viejos, sigan andando."""
        c = cuit()
        r = admin.post("/api/clientes/", json={
            "cuit": c, "nombre": "Acme Plumbing",
            "address_line_1": "742 Evergreen Ter", "city": "Miami",
            "region": "FL", "postal_code": "33101", "country_code": "US"})
        d = r.json()
        assert d["domicilio"] == "742 Evergreen Ter"
        assert d["localidad"] == "Miami"
        # La columna se sigue llamando `provincia`; el dato es el estado.
        assert d["provincia"] == "FL"
        assert d["cp"] == "33101"

    def test_el_mismo_modelo_arma_las_dos_direcciones(self):
        class Ficha:
            address_line_1 = "742 Evergreen Ter"
            address_line_2 = ""
            city = "Miami"
            region = "FL"
            postal_code = "33101"
            country_code = "US"

        class Otra:
            address_line_1 = "San Martín 123"
            address_line_2 = ""
            city = "Del Campillo"
            region = "Córdoba"
            postal_code = "6270"
            country_code = "AR"

        assert direcciones.una_linea(Ficha()) == "742 Evergreen Ter, Miami, FL 33101"
        assert direcciones.una_linea(Otra()) == "San Martín 123, Del Campillo, Córdoba 6270"

    def test_la_actualizacion_no_deja_las_dos_mitades_en_desacuerdo(self, admin, cuit):
        c = cuit()
        admin.post("/api/clientes/", json={
            "cuit": c, "nombre": "Se muda", "localidad": "Del Campillo"})
        admin.put(f"/api/clientes/{c}", json={"city": "Río Cuarto"})
        d = admin.get(f"/api/clientes/{c}").json()
        assert d["city"] == "Río Cuarto"
        assert d["localidad"] == "Río Cuarto", (
            "Las dos columnas quedaron diciendo cosas distintas"
        )


class TestMoneda:
    def test_la_api_dice_en_que_moneda_habla(self, admin):
        """Un importe 1250.00 no dice por sí solo si son pesos o dólares."""
        assert admin.get("/api/config/pais").json()["moneda"] == "ARS"

    def test_cambia_con_el_pais(self, admin):
        admin.put("/api/config/", json={"negocio_pais": "US"})
        try:
            assert admin.get("/api/config/pais").json()["moneda"] == "USD"
        finally:
            admin.put("/api/config/", json={"negocio_pais": "AR"})


class TestMediosDePago:
    def test_reconoce_lo_que_ya_esta_guardado_como_texto_libre(self):
        """Hay instalaciones con Cheque 3ros y EFECTIVO desde el sistema viejo."""
        assert mp.es_cheque("Cheque 3ros")
        assert mp.es_cheque("cheque de tercero")
        assert not mp.es_cheque("EFECTIVO")
        assert mp.resolver("EFECTIVO").clave == "efectivo"
        assert mp.resolver("wire transfer").clave == "transferencia"

    def test_un_tipo_vacio_no_se_toma_por_efectivo(self):
        """Antes todo lo que no dijera cheque caía en la rama del efectivo."""
        assert mp.resolver("").clave == "otro"
        assert mp.resolver("cualquier cosa").clave == "otro"

    def test_el_cheque_sigue_sin_entrar_a_caja(self):
        """Es un valor a depositar: va a la chequera. No se rompió al generalizar."""
        assert mp.entra_a_caja("efectivo") is True
        assert mp.entra_a_caja("cheque") is False

    def test_ach_solo_donde_tiene_sentido(self):
        claves_us = {m.clave for m in mp.medios_de("US")}
        claves_ar = {m.clave for m in mp.medios_de("AR")}
        assert "ach" in claves_us
        assert "ach" not in claves_ar
        # Los cheques existen en los dos: no se tiran al internacionalizar.
        assert "cheque" in claves_us and "cheque" in claves_ar

    def test_se_publican_los_del_pais(self, admin):
        medios = admin.get("/api/config/pais").json()["medios_de_pago"]
        assert any(m["clave"] == "cheque" and m["es_valor"] for m in medios)
        assert not any(m["clave"] == "ach" for m in medios)   # instalación AR

    def test_cobrar_con_cheque_sigue_yendo_a_la_chequera(self, admin, cuit):
        """La prueba de que generalizar no cambió el comportamiento del dinero."""
        c = cuit()
        admin.post("/api/clientes/", json={"cuit": c, "nombre": "Paga con cheque"})
        admin.post("/api/facturas/", json={
            "cliente": c, "fecha": "2026-08-19", "tipo": "A",
            "subtotal": 100.0, "iva": 21.0, "total": 121.0, "items": []})
        caja_antes = admin.get("/api/admin/dashboard").json()["caja_saldo"]

        r = admin.post("/api/cobros/", json={
            "cliente": c, "monto": 121.0, "fecha": "2026-08-19",
            "tipo": "cheque", "referencia": "0001234", "banco": "Nación"})
        assert r.status_code in (200, 201), r.text
        # El cheque NO entra a caja: sigue siendo un valor a depositar.
        assert admin.get("/api/admin/dashboard").json()["caja_saldo"] == caja_antes


class TestImpuestoEnchufable:
    def test_sin_proveedor_usa_la_tasa_que_se_le_pasa(self):
        r = impuestos.calcular(123456, tasa=21.0)
        assert r.importe_centavos == 25926      # IVA de $1.234,56
        assert r.fuente == impuestos.FUENTE_LOCAL

    def test_un_proveedor_externo_se_enchufa_sin_tocar_el_nucleo(self):
        class Falso(impuestos.CalculadorExterno):
            nombre = "falso"

            def disponible(self):
                return True

            def calcular(self, base, destino):
                return impuestos.Impuesto(base, base * 7 // 100, 7.0,
                                          impuestos.FUENTE_EXTERNA, "FL-DADE")

        impuestos.registrar_calculador(Falso())
        try:
            r = impuestos.calcular(100000)
            assert r.fuente == impuestos.FUENTE_EXTERNA
            assert r.jurisdiccion == "FL-DADE"
        finally:
            impuestos.registrar_calculador(None)

    def test_si_el_proveedor_falla_el_comercio_igual_factura(self):
        """Lo más importante: nunca bloqueante. Hay un cliente esperando."""
        class SeCae(impuestos.CalculadorExterno):
            def disponible(self):
                return True

            def calcular(self, base, destino):
                raise TimeoutError("el servicio no responde")

        impuestos.registrar_calculador(SeCae())
        try:
            r = impuestos.calcular(100000)
            assert r.fuente == impuestos.FUENTE_LOCAL
            assert r.importe_centavos >= 0
        finally:
            impuestos.registrar_calculador(None)

    def test_cada_calculo_dice_de_donde_salio(self):
        """Un importe de impuesto sin saber quién lo calculó no se puede auditar."""
        assert impuestos.calcular(1000, tasa=5.0).fuente == impuestos.FUENTE_LOCAL


class TestProveedorEstadounidense:
    def test_se_guardan_los_datos_del_W9(self, admin, cuit):
        c = cuit("30")
        r = admin.post("/api/proveedores/", json={
            "cuit": c, "nombre": "Acme Supply",
            "legal_name": "Acme Supply Company LLC", "dba": "Acme Supply",
            "w9_recibido": True, "w9_fecha": "2026-03-15", "elegible_1099": True})
        assert r.status_code in (200, 201), r.text
        d = r.json()
        assert d["legal_name"] == "Acme Supply Company LLC"
        assert d["dba"] == "Acme Supply"
        assert d["w9_recibido"] is True
        assert d["elegible_1099"] is True

    def test_por_defecto_no_hay_W9_ni_elegibilidad(self, admin, cuit):
        """No se asume nada: marcar 1099 sin el W-9 sería inventar una declaración."""
        c = cuit("30")
        d = admin.post("/api/proveedores/", json={"cuit": c, "nombre": "Común"}).json()
        assert d["w9_recibido"] is False
        assert d["elegible_1099"] is False
