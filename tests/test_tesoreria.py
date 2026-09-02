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
