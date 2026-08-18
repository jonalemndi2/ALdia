/**
 * cobros.js - Módulo de Cobros a Clientes
 * Equivale a: Cobro_cli.frm
 *
 * Migrado de la base SQLite del navegador (db.js / sql.js, ya muerta) a la API REST.
 * IMPORTANTE: el backend (POST /api/cobros/) aplica TODOS los efectos contables en
 * una sola transacción: crea el cobro, descuenta el saldo del cliente y genera el
 * ingreso a caja (o la entrada en la chequera si es cheque). Acá NO se tocan saldos,
 * ni caja, ni chequera: sólo se llama al endpoint y se refresca la vista.
 */
const Cobros = {
    showCuentas() {
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#00695c,#00897b)">
                <h4><i class="bi bi-journal-text"></i> Cuentas Corrientes - Cobros a Clientes</h4>
            </div>
            <div class="row mb-3">
                <div class="col-md-6">
                    <div class="form-card">
                        <label class="form-label-sm">Buscar Cliente</label>
                        <div class="position-relative">
                            <input type="text" class="form-control" id="cobroCliente" placeholder="Buscar cliente...">
                        </div>
                        <div class="row mt-2">
                            <div class="col-6">
                                <label class="form-label-sm">Desde</label>
                                <input type="date" class="form-control form-control-sm" id="cobroDesde">
                            </div>
                            <div class="col-6">
                                <label class="form-label-sm">Hasta</label>
                                <input type="date" class="form-control form-control-sm" id="cobroHasta" value="${Utils.today()}">
                            </div>
                        </div>
                        <button class="btn btn-sm btn-primary mt-2" data-action="Cobros.buscarMovimientos">
                            <i class="bi bi-search"></i> Buscar
                        </button>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="form-card">
                        <h6>Saldo del Cliente</h6>
                        <h3 id="cobroSaldo" class="text-danger">$0.00</h3>
                        <hr>
                        <h6>Registrar Cobro</h6>
                        <div class="row">
                            <div class="col-6">
                                <label class="form-label-sm">Monto</label>
                                <input type="number" class="form-control form-control-sm" id="cobroMonto" step="0.01">
                            </div>
                            <div class="col-6">
                                <label class="form-label-sm">Forma de Pago</label>
                                <select class="form-select form-select-sm" id="cobroTipo">
                                    <option value="efectivo">Efectivo</option>
                                    <option value="cheque">Cheque</option>
                                </select>
                            </div>
                        </div>
                        <div id="cobroChequeDiv" class="mt-2 d-none">
                            <div class="row">
                                <div class="col-4">
                                    <label class="form-label-sm">N° Cheque</label>
                                    <input type="text" class="form-control form-control-sm" id="cobroNumCheque">
                                </div>
                                <div class="col-4">
                                    <label class="form-label-sm">Banco</label>
                                    <input type="text" class="form-control form-control-sm" id="cobroBanco">
                                </div>
                                <div class="col-4">
                                    <label class="form-label-sm">Vencimiento</label>
                                    <input type="date" class="form-control form-control-sm" id="cobroVenc">
                                </div>
                            </div>
                            <small class="text-muted d-block mt-1">
                                El cheque se registra en la chequera. Banco y vencimiento todavía no se
                                guardan (falta soporte en el endpoint de cobros).
                            </small>
                        </div>
                        <button class="btn btn-success mt-2 w-100" data-action="Cobros.registrarCobro">
                            <i class="bi bi-cash-coin"></i> Registrar Cobro
                        </button>
                    </div>
                </div>
            </div>
            <div id="cobroMovimientos"></div>
        `;
        Utils.showView(html);
        Utils.searchEntity('clientes', 'cobroCliente', (cli) => {
            document.getElementById('cobroSaldo').textContent = Utils.formatCurrency(cli.saldo);
            // Guardar el nombre para el recibo sin tener que volver a pedirlo.
            document.getElementById('cobroCliente').dataset.nombre = cli.nombre || '';
            this.buscarMovimientos();
        });

        // Enlazar listener directamente al select para evitar listeners globales acumulativos
        const tipoEl = document.getElementById('cobroTipo');
        if (tipoEl) {
            tipoEl.addEventListener('change', (e) => {
                const div = document.getElementById('cobroChequeDiv');
                if (div) div.classList.toggle('d-none', e.target.value !== 'cheque');
            });
        }
    },

    /** Refrescar el saldo mostrado leyéndolo de la API (fuente de verdad). */
    async _refrescarSaldo(cuit) {
        try {
            const cli = await API.clientes.getById(cuit);
            const el = document.getElementById('cobroSaldo');
            if (el) el.textContent = Utils.formatCurrency(cli ? cli.saldo : 0);
            return cli;
        } catch (err) {
            console.error('Error al leer el saldo del cliente:', err);
            return null;
        }
    },

    async buscarMovimientos() {
        const input = document.getElementById('cobroCliente');
        const cuit = input && input.dataset.cuit;
        if (!cuit) return;

        const desde = document.getElementById('cobroDesde').value;
        const hasta = document.getElementById('cobroHasta').value;

        let facturas = [], cobros = [];
        try {
            // Los endpoints sólo filtran por fecha exacta, así que el rango se aplica acá.
            [facturas, cobros] = await Promise.all([
                API.facturas.getAll(null, cuit),
                API.cobros.getAll(null, cuit)
            ]);
        } catch (err) {
            console.error('Error al cargar movimientos del cliente:', err);
            Utils.toast('Error al cargar los movimientos: ' + err.message, 'Error', 'error');
            return;
        }

        const enRango = (f) => (!desde || (f || '') >= desde) && (!hasta || (f || '') <= hasta);

        const all = [
            ...facturas.filter(f => enRango(f.fecha)).map(f => ({
                numero: f.facturanumero, tipo: 'Factura', fecha: f.fecha, monto: f.total
            })),
            ...cobros.filter(c => enRango(c.fecha)).map(c => ({
                numero: c.ordcobro, tipo: 'Cobro', fecha: c.fecha, monto: c.monto
            }))
        ].sort((a, b) => (b.fecha || '').localeCompare(a.fecha || '') || (b.numero - a.numero));

        const columns = [
            { field: 'numero', label: 'N° Documento' },
            { field: 'tipo', label: 'Tipo' },
            { field: 'fecha', label: 'Fecha', format: 'date' },
            { field: 'monto', label: 'Monto', format: 'currency' }
        ];

        // Utils.buildTable ya escapa los valores string que vienen de la BD.
        document.getElementById('cobroMovimientos').innerHTML = Utils.buildTable(columns, all);
    },

    async registrarCobro() {
        const input = document.getElementById('cobroCliente');
        const cuit = input && input.dataset.cuit;
        if (!cuit) { Utils.toast('Seleccione un cliente', 'Error', 'error'); return; }

        const monto = parseFloat(document.getElementById('cobroMonto').value) || 0;
        if (monto <= 0) { Utils.toast('Ingrese un monto válido', 'Error', 'error'); return; }

        const tipo = document.getElementById('cobroTipo').value;
        const fecha = Utils.today();
        let referencia = '';

        if (tipo === 'cheque') {
            referencia = (document.getElementById('cobroNumCheque').value || '').trim();
            if (!referencia) {
                Utils.toast('Ingrese el N° de cheque', 'Error', 'error');
                Utils.flagInvalid('cobroNumCheque');
                return;
            }
            const banco = (document.getElementById('cobroBanco').value || '').trim();
            const venc = document.getElementById('cobroVenc').value;
            if (banco || venc) {
                // No inventamos un endpoint: avisamos en vez de simular que se guardó.
                console.warn(
                    'Cobros: el endpoint POST /api/cobros/ no acepta banco ni vencimiento del cheque. ' +
                    `Se registrará el cheque N° ${referencia} en la chequera sin banco ("${banco}") ` +
                    `y con el vencimiento igual a la fecha del cobro (se ignora "${venc}").`
                );
            }
        }

        const btn = document.querySelector('[data-action="Cobros.registrarCobro"]');
        if (btn) btn.disabled = true;

        let cobro;
        try {
            cobro = await API.cobros.create({ cliente: cuit, monto, fecha, tipo, referencia });
        } catch (err) {
            console.error('Error al registrar el cobro:', err);
            Utils.toast('No se pudo registrar el cobro: ' + err.message, 'Error', 'error');
            return;
        } finally {
            if (btn) btn.disabled = false;
        }

        Utils.toast(
            `Cobro N° ${cobro.ordcobro} registrado por ${Utils.formatCurrency(cobro.monto)}`,
            'Cobros', 'success'
        );

        // El backend ya descontó el saldo y generó el asiento: sólo releemos.
        await this._refrescarSaldo(cuit);
        document.getElementById('cobroMonto').value = '';
        const numChequeEl = document.getElementById('cobroNumCheque');
        if (numChequeEl) numChequeEl.value = '';
        await this.buscarMovimientos();

        const ok = await Utils.confirm('Imprimir Recibo', `¿Desea imprimir el recibo del cobro N° ${cobro.ordcobro}?`);
        if (ok) await this.imprimirCobro(cobro);
    },

    /** Acepta el objeto cobro devuelto por la API o un número de cobro. */
    async imprimirCobro(cobro) {
        try {
            if (cobro === null || cobro === undefined) return;
            if (typeof cobro !== 'object') {
                const ord = parseInt(cobro);
                const todos = await API.cobros.getAll();
                cobro = todos.find(c => c.ordcobro === ord);
            }
            if (!cobro) { Utils.toast('Cobro no encontrado', 'Error', 'error'); return; }

            let cli = null;
            try {
                cli = await API.clientes.getById(cobro.cliente);
            } catch (err) {
                console.warn('No se pudo obtener el cliente del cobro:', err.message);
            }

            const printHtml = `
                <div style="font-family:Arial; padding:20px; max-width:800px; margin:auto; border: 1px solid #ccc;">
                    <h2 style="text-align:center;">RECIBO DE COBRO N° ${Utils.escapeHtml(String(cobro.ordcobro))}</h2>
                    <hr>
                    <p><strong>Fecha:</strong> ${Utils.escapeHtml(Utils.formatDate(cobro.fecha))}</p>
                    <p><strong>Recibimos de:</strong> ${Utils.escapeHtml(cli ? cli.nombre : cobro.cliente)}</p>
                    <p><strong>CUIT:</strong> ${Utils.escapeHtml(cobro.cliente)}</p>
                    <br>
                    <p><strong>La cantidad de:</strong> ${Utils.escapeHtml(Utils.formatCurrency(cobro.monto))}</p>
                    <p><strong>Forma de pago:</strong> ${Utils.escapeHtml(String(cobro.tipo || '').toUpperCase())} ${cobro.referencia ? '(' + Utils.escapeHtml(cobro.referencia) + ')' : ''}</p>
                    <br><br><br>
                    <div style="text-align:right;">
                        <p>___________________________________</p>
                        <p>Firma y Aclaración</p>
                    </div>
                </div>
            `;

            const win = window.open('', '_blank', 'width=850,height=600');
            if (!win) { Utils.toast('El navegador bloqueó la ventana de impresión', 'Aviso', 'error'); return; }
            win.document.write(printHtml);
            win.document.close();
            win.print();
        } catch (err) {
            console.error('Error al imprimir el recibo:', err);
            Utils.toast('Error al imprimir el recibo: ' + err.message, 'Error', 'error');
        }
    }
};
// Exponer Cobros
window.Cobros = Cobros;
