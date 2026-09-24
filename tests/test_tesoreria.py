"""Reglas de ubicación real del dinero y separación devengado/pagado."""


def _cuenta(admin, nombre, clase, banco=""):
    r = admin.post("/api/tesoreria/cuentas", json={
        "nombre": nombre, "clase": clase, "banco": banco,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_transferencia_exige_banco_concreto(admin, cuit):
    cliente = cuit()
    assert admin.post("/api/clientes/", json={"cuit": cliente, "nombre": "Cliente banco"}).status_code == 200
    sin_banco = admin.post("/api/cobros/", json={
        "cliente": cliente, "monto": 100, "fecha": "2026-09-01",
        "tipo": "transferencia", "referencia": "TRX-1",
    })
    assert sin_banco.status_code == 422

    banco = _cuenta(admin, f"Banco destino {cliente}", "banco", "Banco Nación")
    ok = admin.post("/api/cobros/", json={
        "cliente": cliente, "monto": 100, "fecha": "2026-09-01",
        "tipo": "transferencia", "referencia": "TRX-1",
        "cuenta_tesoreria_id": banco,
    })
    assert ok.status_code == 200, ok.text
    saldo = next(x for x in admin.get("/api/tesoreria/saldos").json() if x["id"] == banco)
    assert saldo["saldo"] == 100.0


def test_cheque_recibido_entra_a_cartera_y_se_endosa_una_vez(admin, cuit):
    cliente, proveedor = cuit(), cuit("33")
    admin.post("/api/clientes/", json={"cuit": cliente, "nombre": "Cliente cheque"})
    admin.post("/api/proveedores/", json={"cuit": proveedor, "nombre": "Proveedor cheque"})
    cobro = admin.post("/api/cobros/", json={
        "cliente": cliente, "monto": 250, "fecha": "2026-09-01", "tipo": "cheque",
        "referencia": "CH-1", "banco": "Banco Provincia", "vencimiento": "2026-09-30",
    })
    assert cobro.status_code == 200, cobro.text
    cheque = next(c for c in admin.get("/api/tesoreria/cheques", params={"disponibles": True}).json()
                  if c["numcheque"] == "CH-1")
    pago = admin.post("/api/pagos/", json={
        "proveedor": proveedor, "monto": 250, "fecha": "2026-09-02",
        "tipo": "cheque tercero", "referencia": "CH-1", "cheque_id": cheque["id"],
    })
    assert pago.status_code == 200, pago.text
    disponibles = admin.get("/api/tesoreria/cheques", params={"disponibles": True}).json()
    assert cheque["id"] not in {c["id"] for c in disponibles}


def test_gasto_solo_devenga_no_mueve_tesoreria(admin, cuit):
    proveedor = cuit("33")
    admin.post("/api/proveedores/", json={"cuit": proveedor, "nombre": "Proveedor gasto"})
    caja = _cuenta(admin, f"Caja {proveedor}", "caja_chica")
    antes = next(x for x in admin.get("/api/tesoreria/saldos").json() if x["id"] == caja)["saldo"]
    r = admin.post("/api/gastos/", json={
        "proveedor": proveedor, "numfactura": "A-1", "fecha": "2026-09-01",
        "subtotal": 100, "iva": 21, "total": 121, "descripcion": "Servicio", "items": [],
    })
    assert r.status_code == 200, r.text
    despues = next(x for x in admin.get("/api/tesoreria/saldos").json() if x["id"] == caja)["saldo"]
    assert despues == antes
    assert admin.get(f"/api/proveedores/{proveedor}").json()["saldo"] == 121.0
    mayor = admin.get(f"/api/proveedores/{proveedor}/cuenta-corriente").json()
    assert mayor["saldo_actual"] == 121.0
    assert mayor["movimientos"][0]["tipo"] == "Gasto"
    assert mayor["movimientos"][0]["debe"] == 121.0


def test_reversa_no_borra_movimiento_y_fecha_invalida_se_rechaza(admin, cuit, tesoreria_caja):
    cliente = cuit()
    admin.post("/api/clientes/", json={"cuit": cliente, "nombre": "Cliente reversa"})
    invalido = admin.post("/api/cobros/", json={
        "cliente": cliente, "monto": 10, "fecha": "2026-99-01", "tipo": "efectivo",
        "cuenta_tesoreria_id": tesoreria_caja,
    })
    assert invalido.status_code == 422
    cobro = admin.post("/api/cobros/", json={
        "cliente": cliente, "monto": 10, "fecha": "2026-09-01", "tipo": "efectivo",
        "cuenta_tesoreria_id": tesoreria_caja,
    }).json()
    assert admin.delete(f"/api/cobros/{cobro['ordcobro']}").status_code == 200
    movs = admin.get("/api/tesoreria/movimientos", params={"cuenta_id": tesoreria_caja}).json()
    original = next(m for m in movs if m["origen_tipo"] == "cobro" and m["origen_id"] == cobro["ordcobro"])
    reversa = next(m for m in movs if m["origen_tipo"] == "reversa_cobro" and m["origen_id"] == cobro["ordcobro"])
    assert original["estado"] == "reversado" and reversa["reversa_de"] == original["id"]


def test_cuenta_duplicada_y_cheques_conciliados(admin, cuit):
    nombre = f"Banco cheques {cuit()}"
    banco = _cuenta(admin, nombre, "banco", "Banco Nación")
    duplicada = admin.post("/api/tesoreria/cuentas", json={
        "nombre": nombre, "clase": "banco", "banco": "Otro",
    })
    assert duplicada.status_code == 409

    cliente, proveedor = cuit(), cuit("33")
    admin.post("/api/clientes/", json={"cuit": cliente, "nombre": "Cliente depósito"})
    admin.post("/api/proveedores/", json={"cuit": proveedor, "nombre": "Proveedor cheque propio"})
    admin.post("/api/cobros/", json={
        "cliente": cliente, "monto": 80, "fecha": "2026-09-01", "tipo": "cheque",
        "referencia": "REC-DEP", "banco": "Emisor", "vencimiento": "2026-09-20",
    })
    recibido = next(c for c in admin.get("/api/tesoreria/cheques", params={"disponibles": True}).json()
                    if c["numcheque"] == "REC-DEP")
    dep = admin.post(f"/api/tesoreria/cheques/{recibido['id']}/depositar", json={
        "cuenta_tesoreria_id": banco, "fecha": "2026-09-10", "referencia": "DEP-1",
    })
    assert dep.status_code == 200, dep.text
    assert admin.post(f"/api/tesoreria/cheques/{recibido['id']}/depositar", json={
        "cuenta_tesoreria_id": banco, "fecha": "2026-09-10",
    }).status_code == 409

    pago = admin.post("/api/pagos/", json={
        "proveedor": proveedor, "monto": 50, "fecha": "2026-09-01", "tipo": "cheque propio",
        "referencia": "PROP-1", "vencimiento": "2026-09-30", "cuenta_tesoreria_id": banco,
    })
    assert pago.status_code == 200, pago.text
    propio = next(c for c in admin.get("/api/caja/chequera").json() if c["numcheque"] == "PROP-1")
    deb = admin.post(f"/api/tesoreria/cheques/{propio['id']}/marcar-debitado", json={
        "cuenta_tesoreria_id": banco, "fecha": "2026-09-30",
    })
    assert deb.status_code == 200, deb.text


def test_reinicio_no_reimporta_dual_write_como_legacy(admin, cuit, tesoreria_caja):
    """El corte v1 sobre Caja permanece fijo aunque la migración corra de nuevo."""
    from database import engine
    from migraciones import aplicar_migraciones

    aplicar_migraciones(engine)
    cliente = cuit()
    admin.post("/api/clientes/", json={"cuit": cliente, "nombre": "Cliente reinicio"})
    cobro = admin.post("/api/cobros/", json={
        "cliente": cliente, "monto": 33, "fecha": "2026-09-01", "tipo": "efectivo",
        "cuenta_tesoreria_id": tesoreria_caja,
    })
    assert cobro.status_code == 200, cobro.text
    orden = cobro.json()["ordcobro"]
    aplicar_migraciones(engine)  # simula arranque posterior
    movimientos = admin.get("/api/tesoreria/movimientos").json()
    assert len([m for m in movimientos if m["origen_tipo"] == "cobro" and m["origen_id"] == orden]) == 1
    assert not any(m["origen_tipo"] == "caja_legacy" and m["referencia"] == f"COBRO {orden}"
                   for m in movimientos)


def test_anular_cobro_con_cheque_anula_cartera_y_revierte_deposito(admin, cuit, tesoreria_banco):
    cliente = cuit()
    admin.post("/api/clientes/", json={"cuit": cliente, "nombre": "Cliente cheque anulado"})
    cobro = admin.post("/api/cobros/", json={
        "cliente": cliente, "monto": 140, "fecha": "2026-09-01", "tipo": "cheque",
        "referencia": "REC-ANULA", "banco": "Emisor", "vencimiento": "2026-09-20",
    }).json()
    cheque = next(c for c in admin.get("/api/tesoreria/cheques", params={"disponibles": True}).json()
                  if c["numcheque"] == "REC-ANULA")
    saldo_antes = next(s for s in admin.get("/api/tesoreria/saldos").json()
                       if s["id"] == tesoreria_banco)["saldo"]
    assert admin.post(f"/api/tesoreria/cheques/{cheque['id']}/depositar", json={
        "cuenta_tesoreria_id": tesoreria_banco,
        "fecha": "2026-09-05",
        "referencia": "DEP-ANULA",
    }).status_code == 200

    anulacion = admin.delete(f"/api/cobros/{cobro['ordcobro']}")
    assert anulacion.status_code == 200, anulacion.text
    saldo_despues = next(s for s in admin.get("/api/tesoreria/saldos").json()
                         if s["id"] == tesoreria_banco)["saldo"]
    assert saldo_despues == saldo_antes
    cartera = admin.get("/api/caja/chequera").json()
    assert next(c for c in cartera if c["id"] == cheque["id"])["pagado"].startswith("Anulado")
    movimientos = admin.get("/api/tesoreria/movimientos", params={"cuenta_id": tesoreria_banco}).json()
    deposito = next(m for m in movimientos if m["origen_tipo"] == "deposito_cheque"
                    and m["origen_id"] == cheque["id"])
    reversa = next(m for m in movimientos if m["origen_tipo"] == "reversa_deposito_cheque"
                   and m["origen_id"] == cheque["id"])
    assert deposito["estado"] == "reversado"
    assert reversa["reversa_de"] == deposito["id"]


def test_no_se_anula_cobro_si_su_cheque_financia_un_pago_vigente(admin, cuit):
    cliente, proveedor = cuit(), cuit("33")
    admin.post("/api/clientes/", json={"cuit": cliente, "nombre": "Cliente endoso"})
    admin.post("/api/proveedores/", json={"cuit": proveedor, "nombre": "Proveedor endoso"})
    cobro = admin.post("/api/cobros/", json={
        "cliente": cliente, "monto": 75, "fecha": "2026-09-01", "tipo": "cheque",
        "referencia": "REC-ENDOSO", "banco": "Emisor", "vencimiento": "2026-09-20",
    }).json()
    cheque = next(c for c in admin.get("/api/tesoreria/cheques", params={"disponibles": True}).json()
                  if c["numcheque"] == "REC-ENDOSO")
    pago = admin.post("/api/pagos/", json={
        "proveedor": proveedor, "monto": 75, "fecha": "2026-09-02",
        "tipo": "cheque tercero", "cheque_id": cheque["id"],
    })
    assert pago.status_code == 200, pago.text
    saldo_cliente = admin.get(f"/api/clientes/{cliente}").json()["saldo"]
    anulacion = admin.delete(f"/api/cobros/{cobro['ordcobro']}")
    assert anulacion.status_code == 409
    assert admin.get(f"/api/clientes/{cliente}").json()["saldo"] == saldo_cliente


def test_anular_pago_con_cheque_propio_cancela_cheque_y_revierte_debito(admin, cuit, tesoreria_banco):
    proveedor = cuit("33")
    admin.post("/api/proveedores/", json={"cuit": proveedor, "nombre": "Proveedor cheque anulado"})
    saldo_antes = next(s for s in admin.get("/api/tesoreria/saldos").json()
                       if s["id"] == tesoreria_banco)["saldo"]
    pago = admin.post("/api/pagos/", json={
        "proveedor": proveedor, "monto": 90, "fecha": "2026-09-01",
        "tipo": "cheque propio", "referencia": "PROP-ANULA",
        "vencimiento": "2026-09-30", "cuenta_tesoreria_id": tesoreria_banco,
    }).json()
    cheque = next(c for c in admin.get("/api/caja/chequera").json()
                  if c["numcheque"] == "PROP-ANULA")
    assert admin.post(f"/api/tesoreria/cheques/{cheque['id']}/marcar-debitado", json={
        "cuenta_tesoreria_id": tesoreria_banco,
        "fecha": "2026-09-30",
    }).status_code == 200

    anulacion = admin.delete(f"/api/pagos/{pago['ordpago']}")
    assert anulacion.status_code == 200, anulacion.text
    saldo_despues = next(s for s in admin.get("/api/tesoreria/saldos").json()
                         if s["id"] == tesoreria_banco)["saldo"]
    assert saldo_despues == saldo_antes
    cheque_final = next(c for c in admin.get("/api/caja/chequera").json()
                        if c["id"] == cheque["id"])
    assert cheque_final["pagado"].startswith("Anulado")
    movimientos = admin.get("/api/tesoreria/movimientos", params={"cuenta_id": tesoreria_banco}).json()
    debito = next(m for m in movimientos if m["origen_tipo"] == "debito_cheque"
                  and m["origen_id"] == cheque["id"])
    reversa = next(m for m in movimientos if m["origen_tipo"] == "reversa_debito_cheque"
                   and m["origen_id"] == cheque["id"])
    assert debito["estado"] == "reversado"
    assert reversa["reversa_de"] == debito["id"]


def test_movimiento_manual_usa_caja_concreta_y_su_borrado_deja_reversa(admin, tesoreria_caja):
    saldo_antes = next(s for s in admin.get("/api/tesoreria/saldos").json()
                       if s["id"] == tesoreria_caja)["saldo"]
    creado = admin.post("/api/caja/", json={
        "fecha": "2026-09-03", "debe": 125, "haber": 0,
        "referencia": "FONDO-1", "descripcion": "Fondo fijo",
        "cuenta_tesoreria_id": tesoreria_caja,
    })
    assert creado.status_code == 200, creado.text
    movimiento_id = creado.json()["id"]
    saldo_con_fondo = next(s for s in admin.get("/api/tesoreria/saldos").json()
                           if s["id"] == tesoreria_caja)["saldo"]
    assert saldo_con_fondo == saldo_antes + 125

    borrado = admin.delete(f"/api/caja/{movimiento_id}")
    assert borrado.status_code == 200, borrado.text
    saldo_final = next(s for s in admin.get("/api/tesoreria/saldos").json()
                       if s["id"] == tesoreria_caja)["saldo"]
    assert saldo_final == saldo_antes
    movimientos = admin.get("/api/tesoreria/movimientos", params={"cuenta_id": tesoreria_caja}).json()
    original = next(m for m in movimientos if m["origen_tipo"] == "caja_manual"
                    and m["origen_id"] == movimiento_id)
    reversa = next(m for m in movimientos if m["origen_tipo"] == "reversa_caja_manual"
                   and m["origen_id"] == movimiento_id)
    assert original["estado"] == "reversado"
    assert reversa["reversa_de"] == original["id"]


def test_no_se_puede_borrar_solo_el_asiento_de_un_cobro(admin, cuit, tesoreria_caja):
    cliente = cuit()
    admin.post("/api/clientes/", json={"cuit": cliente, "nombre": "Cliente caja protegida"})
    cobro = admin.post("/api/cobros/", json={
        "cliente": cliente, "monto": 30, "fecha": "2026-09-03", "tipo": "efectivo",
        "cuenta_tesoreria_id": tesoreria_caja,
    }).json()
    asiento = next(m for m in admin.get("/api/caja/").json()
                   if m["referencia"] == f"COBRO {cobro['ordcobro']}")
    intento = admin.delete(f"/api/caja/{asiento['id']}")
    assert intento.status_code == 409
    assert admin.delete(f"/api/cobros/{cobro['ordcobro']}").status_code == 200
