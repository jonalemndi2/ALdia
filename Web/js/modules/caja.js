/**
 * caja.js - Módulo de Caja Chica, Bancos y Chequera
 * Equivale a: caja_cc_Click, caja_c_Click, caja_b_Click en menu.frm
 */
const Caja = {
    showCajaChica() {
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#bf360c,#e65100)">
                <h4><i class="bi bi-safe"></i> Caja Chica</h4>
            </div>
            <div class="row mb-3">
                <div class="col-md-4">
                    <div class="form-card">
                        <label class="form-label-sm">Desde</label>
                        <input type="date" class="form-control form-control-sm" id="cajaDesde">
                        <label class="form-label-sm mt-2">Hasta</label>
                        <input type="date" class="form-control form-control-sm" id="cajaHasta" value="${Utils.today()}">
                        <button class="btn btn-sm btn-primary mt-2 w-100" data-action="Caja.filtrarCaja">
                            <i class="bi bi-funnel"></i> Filtrar
                        </button>
                        <hr>
                        <div class="d-grid gap-2">
                            <button class="btn btn-outline-success btn-sm" data-action="Caja.nuevoMovimiento" data-arg="debe">
                                <i class="bi bi-plus-circle"></i> Ingreso
                            </button>
                            <button class="btn btn-outline-danger btn-sm" data-action="Caja.nuevoMovimiento" data-arg="haber">
                                <i class="bi bi-dash-circle"></i> Egreso
                            </button>
                        </div>
                    </div>
                </div>
                <div class="col-md-8">
                    <div class="row mb-2 text-center">
                        <div class="col-4">
                            <div class="card bg-success text-white p-2">
                                <small>Total Debe</small>
                                <h5 id="cajaDebe">$0.00</h5>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="card bg-danger text-white p-2">
                                <small>Total Haber</small>
                                <h5 id="cajaHaber">$0.00</h5>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="card bg-primary text-white p-2">
                                <small>Saldo</small>
                                <h5 id="cajaSaldo">$0.00</h5>
                            </div>
                        </div>
                    </div>
                    <div id="cajaTabla"></div>
                </div>
            </div>
        `;
        Utils.showView(html);
        this.filtrarCaja();
    },

    async filtrarCaja() {
        const desde = document.getElementById('cajaDesde').value;
        const hasta = document.getElementById('cajaHasta').value;

        let rows = [];
        try {
            rows = await API.caja.getAll();
        } catch (err) {
            console.error('Error al cargar caja:', err);
            Utils.toast('Error al cargar movimientos de caja: ' + err.message, 'Error', 'error');
            return;
        }
        // El endpoint sólo filtra por fecha exacta, así que el rango se aplica acá.
        if (desde) rows = rows.filter(r => (r.fecha || '') >= desde);
        if (hasta) rows = rows.filter(r => (r.fecha || '') <= hasta);
        rows.sort((a, b) => (b.fecha || '').localeCompare(a.fecha || '') || (b.id - a.id));

        let totalDebe = 0, totalHaber = 0;
        rows.forEach(r => { totalDebe += (r.debe || 0); totalHaber += (r.haber || 0); });

        document.getElementById('cajaDebe').textContent = Utils.formatCurrency(totalDebe);
        document.getElementById('cajaHaber').textContent = Utils.formatCurrency(totalHaber);
        document.getElementById('cajaSaldo').textContent = Utils.formatCurrency(totalDebe - totalHaber);

        const columns = [
            { field: 'referencia', label: 'Referencia' },
            { field: 'fecha', label: 'Fecha', format: 'date' },
            { field: 'debe', label: 'Debe', format: 'currency' },
            { field: 'haber', label: 'Haber', format: 'currency' },
            { field: 'descripcion', label: 'Descripción' }
        ];
        document.getElementById('cajaTabla').innerHTML = Utils.buildTable(columns, rows);
    },

    async nuevoMovimiento(tipo) {
        const data = await Utils.multiInput(`Nuevo ${tipo === 'debe' ? 'Ingreso' : 'Egreso'}`, [
            { name: 'monto', label: 'Monto', type: 'number' },
            { name: 'desc', label: 'Descripción', type: 'text' },
            { name: 'ref', label: 'Referencia', type: 'text' }
        ]);
        if (!data) return;

        const monto = parseFloat(data.monto) || 0;
        if (monto <= 0) {
            Utils.toast('El monto debe ser mayor a cero', 'Validación', 'error');
            return;
        }

        try {
            await API.caja.create({
                referencia: data.ref || 'Manual',
                fecha: Utils.today(),
                debe: tipo === 'debe' ? monto : 0,
                haber: tipo === 'haber' ? monto : 0,
                descripcion: data.desc || ''
            });
            Utils.toast('Movimiento registrado', 'Caja', 'success');
            await this.filtrarCaja();
        } catch (err) {
            Utils.toast('Error al registrar movimiento: ' + err.message, 'Error', 'error');
        }
    },

    /* ───────── Chequera ───────── */
    showChequera() {
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#1565c0,#0d47a1)">
                <h4><i class="bi bi-credit-card-2-front"></i> Chequera</h4>
            </div>
            <div class="row mb-3">
                <div class="col-md-3">
                    <div class="form-card">
                        <label class="form-label-sm">Filtro</label>
                        <select class="form-select form-select-sm" id="chequeFiltro">
                            <option value="todos">Todos</option>
                            <option value="recibidos">Recibidos (Tercero)</option>
                            <option value="propios">Emitidos (Propios)</option>
                            <option value="pendientes">Pendientes cobro</option>
                            <option value="pagados">Ya pagados</option>
                        </select>
                    </div>
                </div>
                <div class="col-md-9">
                    <div class="row mb-2">
                        <div class="col-6 text-center">
                            <div class="card text-white bg-info p-2">
                                <small>Total Cheques Recibidos</small>
                                <h5 id="chequeRecibido">$0.00</h5>
                            </div>
                        </div>
                        <div class="col-6 text-center">
                            <div class="card text-white bg-warning p-2">
                                <small>Total Cheques Emitidos</small>
                                <h5 id="chequeEmitido">$0.00</h5>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div id="chequeTabla"></div>
        `;
        Utils.showView(html);
        this.filtrarCheques();
        const chequeFiltroEl = document.getElementById('chequeFiltro');
        if (chequeFiltroEl && !chequeFiltroEl.__chequeBound) {
            chequeFiltroEl.addEventListener('change', () => { try { this.filtrarCheques(); } catch (err) { console.error(err); } });
            chequeFiltroEl.__chequeBound = true;
        }
    },

    async filtrarCheques() {
        const filtro = document.getElementById('chequeFiltro').value;

        let rows = [];
        try {
            rows = await API.caja.getChequera();
        } catch (err) {
            console.error('Error al cargar chequera:', err);
            Utils.toast('Error al cargar la chequera: ' + err.message, 'Error', 'error');
            return;
        }
        // Convencion de `chequera.tipo` (ver models.py): 0 = emitido (cheque
        // propio), 1 = recibido (cheque de tercero). Esto estaba al reves y
        // mostraba los cheques en la columna equivocada.
        if (filtro === 'recibidos')  rows = rows.filter(r => r.tipo === 1);
        if (filtro === 'propios')    rows = rows.filter(r => r.tipo === 0);
        if (filtro === 'pendientes') rows = rows.filter(r => !r.pagado);
        if (filtro === 'pagados')    rows = rows.filter(r => !!r.pagado);
        rows.sort((a, b) => (b.vencimiento || '').localeCompare(a.vencimiento || ''));

        let recibido = 0, emitido = 0;
        rows.forEach(r => {
            if (r.tipo === 1) recibido += (r.monto || 0);
            else emitido += (r.monto || 0);
        });

        document.getElementById('chequeRecibido').textContent = Utils.formatCurrency(recibido);
        document.getElementById('chequeEmitido').textContent = Utils.formatCurrency(emitido);

        const columns = [
            { field: 'numcheque', label: 'N° Cheque' },
            { field: 'banco', label: 'Banco' },
            { field: 'monto', label: 'Monto', format: 'currency' },
            { field: 'vencimiento', label: 'Vencimiento', format: 'date' },
            { field: 'nombre', label: 'Nombre' },
            { field: 'pagado', label: 'Pagado', format: 'date' },
            { field: 'descripcion', label: 'Nota' }
        ];
        document.getElementById('chequeTabla').innerHTML = Utils.buildTable(columns, rows);
    },

    /* ───────── Bancos / Cta Cte Banco ───────── */
    showBancos() {
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#37474f,#546e7a)">
                <h4><i class="bi bi-bank"></i> Cuenta Corriente Bancaria</h4>
            </div>
            <div class="row mb-3">
                <div class="col-md-4">
                    <div class="form-card">
                        <label class="form-label-sm">Desde</label>
                        <input type="date" class="form-control form-control-sm" id="bancoDesde">
                        <label class="form-label-sm mt-2">Hasta</label>
                        <input type="date" class="form-control form-control-sm" id="bancoHasta" value="${Utils.today()}">
                        <button class="btn btn-sm btn-primary mt-2 w-100" data-action="Caja.filtrarBancos">
                            <i class="bi bi-funnel"></i> Filtrar
                        </button>
                    </div>
                </div>
                <div class="col-md-8">
                    <div class="row mb-2 text-center">
                        <div class="col-4">
                            <div class="card bg-success text-white p-2">
                                <small>Depósitos</small>
                                <h5 id="bancoDepositos">$0.00</h5>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="card bg-danger text-white p-2">
                                <small>Cheques Emitidos</small>
                                <h5 id="bancoCheques">$0.00</h5>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="card bg-primary text-white p-2">
                                <small>Saldo Banco</small>
                                <h5 id="bancoSaldo">$0.00</h5>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div id="bancoTabla"></div>
        `;
        Utils.showView(html);
        this.filtrarBancos();
    },

    async filtrarBancos() {
        const desde = document.getElementById('bancoDesde').value;
        const hasta = document.getElementById('bancoHasta').value;

        let rows = [], movimientos = [];
        try {
            [rows, movimientos] = await Promise.all([
                API.caja.getChequera(),
                API.caja.getAll()
            ]);
        } catch (err) {
            console.error('Error al cargar bancos:', err);
            Utils.toast('Error al cargar la cuenta bancaria: ' + err.message, 'Error', 'error');
            return;
        }
        // Bancos lista los cheques PROPIOS emitidos (restan del saldo bancario):
        // tipo 0 = emitido. Ver la convencion en models.py / Chequera.
        rows = rows.filter(r => r.tipo === 0);
        if (desde) rows = rows.filter(r => (r.vencimiento || '') >= desde);
        if (hasta) rows = rows.filter(r => (r.vencimiento || '') <= hasta);
        rows.sort((a, b) => (b.vencimiento || '').localeCompare(a.vencimiento || ''));

        let totalEmitido = 0;
        rows.forEach(r => totalEmitido += (r.monto || 0));

        const depositos = movimientos
            .filter(m => /dep[oó]sito/i.test(m.descripcion || ''))
            .reduce((s, m) => s + (m.debe || 0), 0);

        document.getElementById('bancoDepositos').textContent = Utils.formatCurrency(depositos);
        document.getElementById('bancoCheques').textContent = Utils.formatCurrency(totalEmitido);
        document.getElementById('bancoSaldo').textContent = Utils.formatCurrency(depositos - totalEmitido);

        const columns = [
            { field: 'numcheque', label: 'N° Cheque' },
            { field: 'banco', label: 'Banco' },
            { field: 'monto', label: 'Monto', format: 'currency' },
            { field: 'vencimiento', label: 'Vencimiento', format: 'date' },
            { field: 'cuit', label: 'CUIT Proveedor' },
            { field: 'nombre', label: 'Proveedor' },
            { field: 'pagado', label: 'Cobrado' }
        ];
        document.getElementById('bancoTabla').innerHTML = Utils.buildTable(columns, rows);
    }
};
// Exponer Caja
window.Caja = Caja;
