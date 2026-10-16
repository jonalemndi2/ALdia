#!/usr/bin/env python3
"""
crear_demo.py - Genera una base SQLite de demostracion (`aldia_demo.db`) con datos
ficticios de comercio y agro (soja, maiz, novillos, productores, acopio y una
liquidacion en borrador lista para confirmar desde un agente personal).

SEGURIDAD:
  - NUNCA escribe sobre `aldia.db` (la base real de produccion).
  - Todos los CUIT, razones sociales e importes son 100% ficticios.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _cuit_ficticio_valido(prefijo: str, numero_8_digitos: str) -> str:
    """Calcula el digito verificador modulo 11 para un CUIT ficticio."""
    base = (str(prefijo) + str(numero_8_digitos).zfill(8))[:10]
    pesos = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    suma = sum(int(d) * p for d, p in zip(base, pesos))
    resto = 11 - (suma % 11)
    if resto == 11:
        verif = 0
    elif resto == 10:
        verif = 9
    else:
        verif = resto
    return f"{base}{verif}"


def crear_base_demo(
    ruta_destino: str | Path | None = None,
    password_admin: str = "demo-aldia-2026",
) -> dict[str, Any]:
    """Crea y puebla `aldia_demo.db` con datos ficticios de comercio y agro."""
    destino = Path(ruta_destino) if ruta_destino else (BACKEND / "aldia_demo.db")
    destino = destino.resolve()

    if destino.name.lower() == "aldia.db":
        raise ValueError(
            "Seguridad: crear_demo.py nunca puede escribir sobre 'aldia.db' "
            "(reservado para la base real del comercio). Use 'aldia_demo.db'."
        )

    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    import models
    from routers.auth import hash_password
    from routers.modulos import MODULOS_DEFAULT

    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        destino.unlink()

    motor = create_engine(
        f"sqlite:///{destino}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(motor, "connect")
    def _fk_on(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    models.Base.metadata.create_all(bind=motor)
    Sesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)
    hoy = date.today().isoformat()

    cuit_empresa = _cuit_ficticio_valido("30", "65432100")
    cuit_acopio = _cuit_ficticio_valido("30", "71001122")
    cuit_frigorifico = _cuit_ficticio_valido("30", "72003344")
    cuit_productor = _cuit_ficticio_valido("20", "28111222")

    with Sesion() as db:
        # 1. Usuarios (admin y agente personal)
        db.add(
            models.Usuario(
                username="admin",
                password_hash=hash_password(password_admin),
                rol="administrador",
                debe_cambiar_password=False,
                puede_actuar_por=True,
            )
        )
        db.add(
            models.Usuario(
                username="agente",
                password_hash=hash_password(password_admin),
                rol="administrador",
                debe_cambiar_password=False,
                puede_actuar_por=False,
            )
        )

        # 2. Modulos (perfil agro_mixto activo)
        for m in MODULOS_DEFAULT:
            db.add(models.Modulo(**{**m, "habilitado": True}))

        # 3. Configuracion del negocio ficticio
        configs = {
            "negocio_nombre": "Establecimiento y Acopio El Ceibo S.A. (DEMO)",
            "negocio_cuit": cuit_empresa,
            "negocio_direccion": "Ruta Provincial 6 Km 42",
            "negocio_localidad": "Marcos Juarez",
            "negocio_telefono": "03472-420000",
            "negocio_punto_venta": "0001",
            "negocio_moneda": "ARS",
            "negocio_iva": "responsable_inscripto",
            "pais": "AR",
        }
        for clave, valor in configs.items():
            db.add(models.Configuracion(clave=clave, valor=valor))

        # 4. Deposito y articulos (granos, hacienda e insumos comerciales)
        deposito = models.Deposito(nombre="Principal", activo=True)
        db.add(deposito)
        db.flush()

        articulos = [
            # codigo, descripcion, cantidad, unidad, preven (centavos), precom (centavos), iva %
            (101, "Soja Grano Campana 25/26", 45000.0, "KG", 28500, 26000, 10.5),
            (102, "Maiz Grano Seco", 60000.0, "KG", 19500, 17500, 10.5),
            (201, "Novillo Mestizo en Pie", 12500.0, "KG", 240000, 220000, 10.5),
            (301, "Alambre Alta Resistencia 17/15", 40.0, "UN", 9500000, 7800000, 21.0),
        ]
        for cod, desc, cant, uni, preven, precom, iva in articulos:
            db.add(
                models.StockMercaderia(
                    codigo=cod,
                    producto=desc,
                    cantidad=cant,
                    unidad=uni,
                    preven=preven,
                    precom=precom,
                    iva=iva,
                )
            )
        db.flush()

        for cod, _desc, cant, _uni, _preven, precom, _iva in articulos:
            db.add(
                models.ExistenciaDeposito(
                    deposito_id=deposito.id,
                    codigo=cod,
                    cantidad=cant,
                    costo_promedio=precom,
                )
            )

        # 5. Clientes y Productor/Proveedor ficticios
        db.add(
            models.Cliente(
                cuit=cuit_acopio,
                tax_id_type="CUIT",
                nombre="Acopio del Litoral S.A. (Ficticio)",
                domicilio="Av. Puerto 1200",
                localidad="Rosario",
                provincia="Santa Fe",
                condicion_iva="responsable_inscripto",
                saldo=145000000,  # $ 1.450.000,00 a cobrar
            )
        )
        db.add(
            models.Cliente(
                cuit=cuit_frigorifico,
                tax_id_type="CUIT",
                nombre="Frigorifico Pampa Sur S.R.L. (Ficticio)",
                domicilio="Camino Rural s/n",
                localidad="Rio Cuarto",
                provincia="Cordoba",
                condicion_iva="responsable_inscripto",
                saldo=0,
            )
        )
        db.add(
            models.Proveedor(
                cuit=cuit_productor,
                tax_id_type="CUIT",
                nombre="Estancia Don Segundo S.R.L. (Productor Ficticio)",
                domicilio="Zona Rural Lote 14",
                localidad="Inriville",
                provincia="Cordoba",
                saldo=82000000,  # $ 820.000,00 a pagar
            )
        )
        db.flush()

        # 6. Caja inicial para que el briefing matutino muestre liquidez
        db.add(
            models.Caja(
                referencia="APERTURA-DEMO",
                fecha=hoy,
                debe=325000000,  # $ 3.250.000,00
                haber=0,
                descripcion="Saldo inicial de demostracion en caja",
            )
        )

        # 7. Liquidacion #1 en BORRADOR (Granos - Soja con merma, flete, secado y SISA)
        # 30.000 kg brutos, 2% merma (600 kg) -> 29.400 kg netos a $280/kg (28000 centavos)
        # Bruto = 29400 * 28000 = 823.200.000 centavos ($8.232.000,00)
        # IVA 10,5% = 86.436.000 centavos ($864.360,00)
        # Deducciones: Flete $350.000 + Secado $90.000 = $440.000 (44.000.000 centavos) + IVA 21% ($92.400 = 9.240.000 centavos)
        # Retenciones: SISA $164.640 (16.464.000 centavos)
        # Neto = (823.200.000 + 86.436.000) - (44.000.000 + 9.240.000) - 16.464.000 = 839.932.000 centavos ($8.399.320,00)
        liq_soja = models.Liquidacion(
            id=1,
            rubro="granos",
            operacion="compra",
            proveedor=cuit_productor,
            fecha=hoy,
            num_comprobante="LPG-0001-00000101",
            subtotal_bruto=823200000,
            iva_operacion=86436000,
            subtotal_deducciones=44000000,
            iva_deducciones=9240000,
            total_retenciones=16464000,
            neto_liquidado=839932000,
            datos_dominio=json.dumps(
                {
                    "campana": "25/26",
                    "especie": "Soja",
                    "grado": "G2",
                    "factor": 98.5,
                    "humedad_pct": 14.8,
                    "carta_porte": "0001-99887766",
                    "procedencia": "Inriville",
                    "puerto": "Rosario",
                },
                ensure_ascii=False,
            ),
            observaciones="Liquidacion primaria de soja en borrador lista para confirmar",
            estado="borrador",
        )
        db.add(liq_soja)
        db.flush()

        db.add(
            models.LiquidacionItem(
                liquidacion_id=1,
                codigo=101,
                descripcion="Soja Grano Campana 25/26",
                cabezas=0,
                cantidad_bruta=30000.0,
                merma_pct=2.0,
                merma_cantidad=600.0,
                cantidad_neta=29400.0,
                unidad="KG",
                precio_unitario=28000,
                iva_alicuota=10.5,
                subtotal=823200000,
                iva_importe=86436000,
            )
        )
        db.add(
            models.LiquidacionDeduccion(
                liquidacion_id=1,
                concepto="flete",
                descripcion="Flete corto y largo a puerto",
                base_imponible=35000000,
                iva_alicuota=21.0,
                iva_importe=7350000,
                total=42350000,
            )
        )
        db.add(
            models.LiquidacionDeduccion(
                liquidacion_id=1,
                concepto="secado",
                descripcion="Secado y zarandeo",
                base_imponible=9000000,
                iva_alicuota=21.0,
                iva_importe=1890000,
                total=10890000,
            )
        )
        db.add(
            models.LiquidacionRetencion(
                liquidacion_id=1,
                tipo="sisa",
                descripcion="Retencion IVA RG 4310 (SISA Calificacion 2)",
                base_calculo=823200000,
                alicuota=2.0,
                importe=16464000,
                certificado="CERT-SISA-0001",
            )
        )

        db.add(models.Secuencia(tipo="liquidacion", ultimo=1))
        db.commit()

    motor.dispose()
    return {
        "ruta_db": str(destino),
        "usuario": "admin",
        "password": password_admin,
        "cuit_productor": cuit_productor,
        "cuit_acopio": cuit_acopio,
        "cuit_frigorifico": cuit_frigorifico,
        "liquidacion_borrador_id": 1,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera aldia_demo.db con datos ficticios de comercio y agro."
    )
    parser.add_argument(
        "--ruta",
        default=str(BACKEND / "aldia_demo.db"),
        help="Ruta donde crear la base SQLite de demostracion (por defecto: backend/aldia_demo.db).",
    )
    parser.add_argument(
        "--password",
        default="demo-aldia-2026",
        help="Contrasena del usuario admin en la base demo.",
    )
    args = parser.parse_args()

    info = crear_base_demo(args.ruta, password_admin=args.password)
    print("============================================================")
    print("  Base de demostracion de ALdia creada con exito")
    print("============================================================")
    print(f"  Archivo SQLite : {info['ruta_db']}")
    print(f"  Usuario        : {info['usuario']}")
    print(f"  Contrasena     : {info['password']}")
    print(f"  Productor demo : {info['cuit_productor']} (Estancia Don Segundo S.R.L.)")
    print(f"  Cliente demo   : {info['cuit_acopio']} (Acopio del Litoral S.A.)")
    print(f"  Borrador LPG   : Liquidacion #{info['liquidacion_borrador_id']} (Soja 30.000 kg brutos)")
    print()
    print("1) Para levantar el servidor de ALdia con esta base demo:")
    print(f'   ALDIA_DB="{info["ruta_db"]}" python backend/main.py')
    print()
    print("2) Para conectar su agente personal por MCP (pipx / uvx):")
    print("   ALDIA_URL=http://127.0.0.1:8000 \\")
    print(f"   ALDIA_USER={info['usuario']} \\")
    print(f"   ALDIA_PASSWORD={info['password']} \\")
    print("   uvx --from ./mcp aldia-mcp")
    print("============================================================")


if __name__ == "__main__":
    main()
