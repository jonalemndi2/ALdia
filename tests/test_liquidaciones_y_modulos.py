"""
Pruebas de Fase 1 (Módulos Verticales y Perfiles de Negocio) y Fase 2
(Motor de Liquidaciones de Cereales, Hacienda y Rubros Compuestos — Multipaís AR/US).
"""
from datetime import timedelta
import itertools
from database import SessionLocal
from models import ExistenciaDeposito, Liquidacion, MovimientoStock, Usuario
from paises import fijar_pais
from routers.auth import create_access_token, hash_password

_codigos_agro = itertools.count(985001)


def _crear_usuario_con_rol(rol: str, username: str) -> str:
    with SessionLocal() as db:
        u = db.query(Usuario).filter(Usuario.username == username).first()
        if not u:
            u = Usuario(
                username=username,
                password_hash=hash_password("ClaveSegura123!"),
                rol=rol,
                debe_cambiar_password=False,
            )
            db.add(u)
            db.commit()
            db.refresh(u)
        return create_access_token({"sub": u.username, "rol": u.rol}, timedelta(minutes=60))


class TestPerfilesYModulosVerticales:
    """Fase 1: instalar/activar solo los módulos que cada usuario necesita."""

    def test_catalogo_de_perfiles_y_aplicacion(self, admin, app_cliente):
        try:
            r_perfiles = admin.get("/api/modulos/perfiles")
            assert r_perfiles.status_code == 200
            claves = {p["clave"] for p in r_perfiles.json()}
            assert {"comercio", "agro_granos", "agro_hacienda", "agro_mixto", "servicios"} <= claves

            # 1. Aplicar perfil "comercio" apaga liquidaciones_granos y liquidaciones_hacienda
            r_com = admin.post("/api/modulos/perfiles/comercio")
            assert r_com.status_code == 200, r_com.text
            assert "liquidaciones_granos" in r_com.json()["modulos_deshabilitados"]
            assert "liquidaciones_hacienda" in r_com.json()["modulos_deshabilitados"]

            # Un encargado_ventas no puede usar liquidaciones cuando el perfil es comercio
            tok_ventas = _crear_usuario_con_rol("encargado_ventas", "ventas_perfil_test")
            r_denegado = app_cliente.get(
                "/api/liquidaciones/",
                params={"rubro": "granos"},
                headers={"Authorization": f"Bearer {tok_ventas}"},
            )
            assert r_denegado.status_code == 403
            assert r_denegado.json()["codigo"] == "SIN_PERMISO"

            # 2. Aplicar perfil "agro_granos" habilita granos pero mantiene hacienda apagado
            r_granos = admin.post("/api/modulos/perfiles/agro_granos")
            assert r_granos.status_code == 200
            assert "liquidaciones_granos" in r_granos.json()["modulos_habilitados"]
            assert "liquidaciones_hacienda" in r_granos.json()["modulos_deshabilitados"]

            r_ok_granos = app_cliente.get(
                "/api/liquidaciones/",
                params={"rubro": "granos"},
                headers={"Authorization": f"Bearer {tok_ventas}"},
            )
            assert r_ok_granos.status_code == 200

            r_no_hacienda = app_cliente.get(
                "/api/liquidaciones/",
                params={"rubro": "hacienda"},
                headers={"Authorization": f"Bearer {tok_ventas}"},
            )
            assert r_no_hacienda.status_code == 403
        finally:
            # Dejar todos los módulos activos (agro_mixto) para el resto de la suite
            admin.post("/api/modulos/perfiles/agro_mixto")
            app_cliente.headers.update(admin.headers)


class TestLiquidacionesCerealesYHacienda:
    """Fase 2: Liquidación Primaria de Granos (LPG) y Hacienda (LSP) con mermas, deducciones y retenciones."""

    def test_liquidacion_granos_compra_con_merma_deducciones_retenciones_y_saldos(self, admin, cuit):
        productor = cuit("20")
        assert admin.post("/api/proveedores/", json={
            "cuit": productor,
            "nombre": "Estancia La Esperanza S.A.",
        }).status_code == 200

        cod_soja = next(_codigos_agro)
        assert admin.post("/api/stock/", json={
            "codigo": cod_soja,
            "producto": "Soja Grado 2 (TN)",
            "cantidad": 100.0,
            "unidad": "TN",
            "preven": 300000.0,
            "iva": 10.5,
            "precom": 250000.0,
        }).status_code == 200

        # 30 TN brutas con 2% de merma de acondicionamiento/humedad = 29.4 TN netas a $280.000/TN
        # Subtotal bruto: 29.4 * 280.000 = $8.232.000,00
        # IVA operación (10.5%): $864.360,00 -> Total bruto c/IVA = $9.096.360,00
        # Deducciones:
        #   - Flete: $300.000 + IVA 21% ($63.000) = $363.000
        #   - Secado y zarandeo: $100.000 + IVA 10.5% ($10.500) = $110.500
        #   -> Subtotal deducciones: $400.000 | IVA deducciones: $73.500 | Total deducciones: $473.500
        # Retenciones:
        #   - SISA Retención IVA (5% sobre $8.232.000): $411.600
        #   - Retención Ganancias RG 4310 (2% sobre $8.232.000): $164.640
        #   -> Total retenciones: $576.240
        # Neto a pagar al productor:
        #   $9.096.360 - $473.500 - $576.240 = $8.046.620,00
        payload = {
            "rubro": "granos",
            "operacion": "compra",
            "proveedor": productor,
            "fecha": "2026-09-10",
            "num_comprobante": "LPG-0001-00004512",
            "estado": "borrador",
            "datos_dominio": {
                "campana": "25/26",
                "especie": "Soja",
                "grado": "G2",
                "factor": 98.5,
                "humedad_pct": 14.8,
                "carta_porte": "0001-99887766",
                "procedencia": "Río Cuarto, Córdoba",
            },
            "items": [
                {
                    "codigo": cod_soja,
                    "descripcion": "Soja Grado 2 Campaña 25/26",
                    "cantidad_bruta": 30.0,
                    "merma_pct": 2.0,
                    "unidad": "TN",
                    "precio_unitario": 280000.0,
                    "iva_alicuota": 10.5,
                }
            ],
            "deducciones": [
                {
                    "concepto": "flete",
                    "descripcion": "Flete corto y largo 180 km",
                    "base_imponible": 300000.0,
                    "iva_alicuota": 21.0,
                },
                {
                    "concepto": "secado",
                    "descripcion": "Secado y zarandeo en planta",
                    "base_imponible": 100000.0,
                    "iva_alicuota": 10.5,
                },
            ],
            "retenciones": [
                {
                    "tipo": "sisa",
                    "descripcion": "Retención IVA SISA Estado 2",
                    "alicuota": 5.0,
                },
                {
                    "tipo": "ganancias",
                    "descripcion": "Retención Ganancias Granos",
                    "alicuota": 2.0,
                },
            ],
        }

        r_borrador = admin.post("/api/liquidaciones/", json=payload)
        assert r_borrador.status_code == 200, r_borrador.text
        liq = r_borrador.json()
        assert liq["estado"] == "borrador"
        assert liq["items"][0]["cantidad_neta"] == 29.4
        assert liq["subtotal_bruto"] == 8232000.0
        assert liq["iva_operacion"] == 864360.0
        assert liq["subtotal_deducciones"] == 400000.0
        assert liq["iva_deducciones"] == 73500.0
        assert liq["total_retenciones"] == 576240.0
        assert liq["neto_liquidado"] == 8046620.0

        # En borrador no mueve stock ni saldo del productor
        assert admin.get(f"/api/stock/{cod_soja}").json()["cantidad"] == 100.0
        assert admin.get(f"/api/proveedores/{productor}").json()["saldo"] == 0.0

        # Confirmar borrador
        r_conf = admin.post(f"/api/liquidaciones/{liq['id']}/confirmar")
        assert r_conf.status_code == 200, r_conf.text
        assert r_conf.json()["estado"] == "confirmada"

        # Stock sube por la cantidad NETA (100 + 29.4 = 129.4 TN)
        assert admin.get(f"/api/stock/{cod_soja}").json()["cantidad"] == 129.4
        # Saldo del proveedor sube por el NETO LIQUIDADO ($8.046.620,00)
        assert admin.get(f"/api/proveedores/{productor}").json()["saldo"] == 8046620.0

        # La verificación global de saldos (saldos.verificar) debe dar 100% consistente
        r_verif = admin.get("/api/admin/verificar-saldos")
        assert r_verif.status_code == 200
        assert r_verif.json()["consistente"] is True, r_verif.json()

        # Registrar COE (Argentina)
        r_coe = admin.post(f"/api/liquidaciones/{liq['id']}/coe", json={
            "coe": "330123456789",
            "observaciones": "Autorizado WSLPG ARCA",
        })
        assert r_coe.status_code == 200, r_coe.text
        assert r_coe.json()["codigo_autorizacion"] == "330123456789"

        # Anular la liquidación revierte stock y saldo y deja reversa append-only
        r_anul = admin.delete(f"/api/liquidaciones/{liq['id']}")
        assert r_anul.status_code == 200
        assert admin.get(f"/api/stock/{cod_soja}").json()["cantidad"] == 100.0
        assert admin.get(f"/api/proveedores/{productor}").json()["saldo"] == 0.0
        assert admin.get("/api/admin/verificar-saldos").json()["consistente"] is True

        with SessionLocal() as db:
            movs = (
                db.query(MovimientoStock)
                .filter(
                    MovimientoStock.origen_id == liq["id"],
                    MovimientoStock.origen_tipo.like("%liquidacion%"),
                )
                .all()
            )
            assert len(movs) == 2
            assert {m.sentido for m in movs} == {"entrada", "salida"}

    def test_liquidacion_hacienda_venta_con_cabezas_desbaste_e_iva(self, admin, cuit):
        frigorifico = cuit("30")
        assert admin.post("/api/clientes/", json={
            "cuit": frigorifico,
            "nombre": "Frigorífico Río Segundo S.A.",
            "condicion_iva": "responsable_inscripto",
        }).status_code == 200

        cod_novillo = next(_codigos_agro)
        assert admin.post("/api/stock/", json={
            "codigo": cod_novillo,
            "producto": "Novillo Mestizo (KG Vivo)",
            "cantidad": 30000.0,
            "unidad": "KG",
            "preven": 2200.0,
            "iva": 10.5,
            "precom": 1800.0,
        }).status_code == 200

        # Venta de 50 cabezas: 22.000 kg brutos en balanza con 4% de desbaste = 21.120 kg netos a $2.200/kg
        # Bruto sin IVA: 21.120 * 2.200 = $46.464.000,00
        # IVA 10.5%: $4.878.720,00
        # Deducción guía y SENASA + comisión consignatario: $1.000.000 + IVA 10.5% ($105.000) = $1.105.000
        # Retención sufrida: $464.640 (1%)
        # Neto a cobrar del frigorífico/consignatario:
        #   (46.464.000 + 4.878.720) - 1.105.000 - 464.640 = $49.773.080,00
        r_hacienda = admin.post("/api/liquidaciones/", json={
            "rubro": "hacienda",
            "operacion": "venta",
            "cliente": frigorifico,
            "fecha": "2026-09-15",
            "num_comprobante": "LSP-0002-00001099",
            "estado": "confirmada",
            "datos_dominio": {
                "dte": "DTE-99112233-4",
                "renspa": "04.012.0.00123/01",
                "tropa": "T-2026-88",
                "categoria": "Novillo",
            },
            "items": [
                {
                    "codigo": cod_novillo,
                    "descripcion": "Novillos Mestizos Gordos",
                    "cabezas": 50,
                    "cantidad_bruta": 22000.0,
                    "merma_pct": 4.0,
                    "unidad": "KG",
                    "precio_unitario": 2200.0,
                    "iva_alicuota": 10.5,
                }
            ],
            "deducciones": [
                {
                    "concepto": "comision",
                    "descripcion": "Comisión feria y arancel SENASA",
                    "base_imponible": 1000000.0,
                    "iva_alicuota": 10.5,
                }
            ],
            "retenciones": [
                {
                    "tipo": "iva",
                    "descripcion": "Retención RG 3964 Sector Pecuario",
                    "alicuota": 1.0,
                }
            ],
        })
        assert r_hacienda.status_code == 200, r_hacienda.text
        datos = r_hacienda.json()
        assert datos["items"][0]["cabezas"] == 50
        assert datos["items"][0]["cantidad_neta"] == 21120.0
        assert datos["neto_liquidado"] == 49773080.0

        # Stock de kg vivos bajó en 21.120 kg netos (30.000 - 21.120 = 8.880 kg)
        assert admin.get(f"/api/stock/{cod_novillo}").json()["cantidad"] == 8880.0
        # Saldo del cliente (frigorífico) subió en $49.773.080,00
        assert admin.get(f"/api/clientes/{frigorifico}").json()["saldo"] == 49773080.0
        assert admin.get("/api/admin/verificar-saldos").json()["consistente"] is True

        # Verificar impacto en consulta de IVA del período
        r_iva = admin.get("/api/iva/consulta", params={"fecha_desde": "2026-09-15", "fecha_hasta": "2026-09-15"})
        assert r_iva.status_code == 200
        iva_json = r_iva.json()
        assert iva_json["iva_liquidaciones_debito"] >= 4878720.0
        assert iva_json["iva_liquidaciones_credito"] >= 105000.0
        assert iva_json["retenciones_sufridas"] >= 464640.0

    def test_liquidacion_multipais_estados_unidos_settlement_sheet(self, admin):
        """En EE.UU. (US) funciona como Grain Settlement Sheet con EIN y tasas abiertas, y rechaza COE."""
        try:
            fijar_pais("US")
            ein_farmer = "12-3456789"
            r_prov = admin.post("/api/proveedores/", json={
                "cuit": ein_farmer,
                "nombre": "Midwest Grain Farms LLC",
                "elegible_1099": True,
                "w9_recibido": True,
            })
            assert r_prov.status_code in (200, 400)

            # Tasa 0% (común en comodities agrícolas mayoristas en EE.UU.) o tasa abierta 6.25%
            r_us = admin.post("/api/liquidaciones/", json={
                "rubro": "granos",
                "operacion": "compra",
                "proveedor": ein_farmer,
                "fecha": "2026-09-20",
                "num_comprobante": "SETTLE-2026-901",
                "estado": "confirmada",
                "datos_dominio": {"crop_year": "2026", "commodity": "Yellow Corn #2", "moisture": 15.5},
                "items": [
                    {
                        "descripcion": "Yellow Corn #2 (Bushels)",
                        "cantidad_bruta": 5000.0,
                        "merma_pct": 1.5,
                        "unidad": "BU",
                        "precio_unitario": 4.50,
                        "iva_alicuota": 0.0,
                    }
                ],
                "deducciones": [
                    {
                        "concepto": "drying",
                        "descripcion": "Elevator drying & storage fee",
                        "base_imponible": 350.0,
                        "iva_alicuota": 6.25,
                    }
                ],
                "retenciones": [
                    {
                        "tipo": "checkoff",
                        "descripcion": "State Corn Checkoff Board",
                        "importe": 49.25,
                    }
                ],
            })
            assert r_us.status_code == 200, r_us.text
            liq_us = r_us.json()
            assert liq_us["moneda"] == "USD"
            assert liq_us["items"][0]["cantidad_neta"] == 4925.0

            # En EE.UU., pedir COE debe rechazarse con OPERACION_NO_APLICA_EN_ESTE_PAIS y acción abortar
            r_coe_us = admin.post(f"/api/liquidaciones/{liq_us['id']}/coe", json={"coe": "123456789012"})
            assert r_coe_us.status_code == 409
            assert r_coe_us.json()["codigo"] == "OPERACION_NO_APLICA_EN_ESTE_PAIS"
            assert r_coe_us.json()["accion"] == "abortar"
        finally:
            fijar_pais("AR")
