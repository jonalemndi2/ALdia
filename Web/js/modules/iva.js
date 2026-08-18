/**
 * iva.js - Módulo de Consulta y Reporte de IVA
 * Equivale a: iva.frm
 *
 * MIGRADO A LA API REST: antes leía con DB.query() contra la base sql.js del
 * navegador, que ya no se inicializa: el libro IVA daba SIEMPRE $0 y tablas
 * vacías aunque hubiera comprobantes cargados.
 *
 * Los totales de las tarjetas vienen de GET /api/iva/consulta (los calcula el
 * servidor sobre la base real). El detalle por comprobante se arma con los
 * listados existentes, filtrando el rango de fechas en el cliente porque esos
 * endpoints sólo aceptan fecha exacta.
 */
const IVA = {
    showConsulta() {
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#004d40,#00695c)">
                <h4><i class="bi bi-percent"></i> Consulta de IVA</h4>
            </div>
            <div class="row mb-3">
                <div class="col-md-4">
                    <div class="form-card">
                        <label class="form-label-sm">Desde</label>
                        <input type="date" class="form-control form-control-sm" id="ivaDesde">
                        <label class="form-label-sm mt-2">Hasta</label>
                        <input type="date" class="form-control form-control-sm" id="ivaHasta" value="${Utils.today()}">
                        <button class="btn btn-primary mt-3 w-100" id="ivaCalcularBtn" data-action="IVA.calcular">
                            <i class="bi bi-calculator"></i> Calcular IVA
                        </button>
                        <button class="btn btn-outline-secondary mt-2 w-100" data-action="IVA.exportarCSV">
                            <i class="bi bi-file-earmark-spreadsheet"></i> Exportar CSV
                        </button>
                    </div>
                </div>
                <div class="col-md-8">
                    <div class="row mb-3 text-center">
                        <div class="col-4">
                            <div class="card bg-success text-white p-2">
                                <small>IVA Débito Fiscal (Ventas)</small>
                                <h5 id="ivaDebito">$0.00</h5>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="card bg-danger text-white p-2">
                                <small>IVA Crédito Fiscal (Compras)</small>
                                <h5 id="ivaCredito">$0.00</h5>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="card bg-primary text-white p-2">
                                <small>Posición IVA</small>
                                <h5 id="ivaPosicion">$0.00</h5>
                            </div>
                        </div>
                    </div>
                    <div id="ivaAvisos"></div>
                    <ul class="nav nav-tabs" id="ivaTabs">
                        <li class="nav-item">
                            <a class="nav-link active" href="#" data-action="IVA._tab" data-arg="ventas">Ventas</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#" data-action="IVA._tab" data-arg="compras">Compras</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#" data-action="IVA._tab" data-arg="gastos">Gastos</a>
                        </li>
                    </ul>
                    <div id="ivaTabla" class="mt-2"></div>
                </div>
            </div>
        `;
        Utils.showView(html);
        if (App && typeof App.bindDataActions === 'function') App.bindDataActions();
    },

    _datosVentas: [],
    _datosCompras: [],
    _datosGastos: [],
    _tabActiva: 'ventas',

    /** ¿La fecha (YYYY-MM-DD) entra en el rango pedido? */
    _enRango(fecha, desde, hasta) {
        const f = String(fecha || '');
        if (!f) return false;
        if (desde && f < desde) return false;
        if (hasta && f > hasta) return false;
        return true;
    },

    async calcular() {
        const desde = document.getElementById('ivaDesde').value;
        const hasta = document.getElementById('ivaHasta').value;
        const btn = document.getElementById('ivaCalcularBtn');
        const avisos = [];
        if (btn) btn.disabled = true;

        try {
            // ── Totales oficiales: los calcula el servidor sobre la base real ──
            let totales;
            try {
                totales = await API.iva.consultar(desde, hasta);
            } catch (err) {
                console.error('Error al consultar el IVA:', err);
                Utils.toast('No se pudo consultar el IVA: ' + err.message, 'IVA', 'error');
                return;
            }

            // ── Detalle por comprobante (best effort, cada fuente por separado) ──
            const [ventas, compras, gastos] = await Promise.all([
                API.facturas.getAll().catch(err => {
                    console.warn('[iva] No se pudo listar el detalle de ventas:', err.message);
                    avisos.push('detalle de <strong>ventas</strong> no disponible (' + Utils.escapeHtml(err.message) + ')');
                    return [];
                }),
                // No hay endpoint de listado de facturas de proveedor; el de
                // administración expone las mismas filas (máx. 200).
                API.admin.buscarMov('compra').catch(err => {
                    console.warn('[iva] No se pudo listar el detalle de compras:', err.message);
                    avisos.push('detalle de <strong>compras</strong> no disponible (' + Utils.escapeHtml(err.message) + ')');
                    return [];
                }),
                API.gastos.getAll().catch(err => {
                    console.warn('[iva] No se pudo listar el detalle de gastos:', err.message);
                    avisos.push('detalle de <strong>gastos</strong> no disponible (' + Utils.escapeHtml(err.message) + ')');
                    return [];
                })
            ]);

            const ordenar = (a, b) => String(a.fecha).localeCompare(String(b.fecha));

            this._datosVentas = ventas
                .filter(f => this._enRango(f.fecha, desde, hasta))
                .map(f => ({
                    numero: f.facturanumero, cliente: f.cliente, fecha: f.fecha,
                    neto: f.subtotal, iva: f.iva, total: f.total
                })).sort(ordenar);

            this._datosCompras = compras
                .filter(c => this._enRango(c.fecha, desde, hasta))
                .map(c => ({
                    numero: c.id, proveedor: c.proveedor, fecha: c.fecha,
                    neto: c.subtotal, iva: c.iva, total: c.total
                })).sort(ordenar);

            this._datosGastos = gastos
                .filter(g => this._enRango(g.fecha, desde, hasta))
                .map(g => ({
                    numero: g.id, proveedor: g.proveedor, fecha: g.fecha,
                    neto: g.subtotal, iva: g.iva, total: g.total
                })).sort(ordenar);

            if (compras.length >= 200) {
                avisos.push('el listado de compras está limitado a los 200 comprobantes más recientes');
            }

            // ── Tarjetas: siempre con los totales del servidor ──
            const ivaDebito = totales.iva_percibido || 0;
            const ivaCredito = totales.iva_total_pagado || 0;
            const posicion = (totales.iva_a_pagar !== undefined && totales.iva_a_pagar !== null)
                ? totales.iva_a_pagar : (ivaDebito - ivaCredito);

            document.getElementById('ivaDebito').textContent = Utils.formatCurrency(ivaDebito);
            document.getElementById('ivaCredito').textContent = Utils.formatCurrency(ivaCredito);
            const elPos = document.getElementById('ivaPosicion');
            elPos.textContent = Utils.formatCurrency(posicion);
            elPos.closest('.card').className = `card text-white p-2 ${posicion >= 0 ? 'bg-danger' : 'bg-success'}`;

            const avisoEl = document.getElementById('ivaAvisos');
            if (avisoEl) {
                avisoEl.innerHTML = avisos.length
                    ? `<div class="alert alert-warning py-2 small mb-2"><i class="bi bi-exclamation-triangle"></i>
                       Los totales son correctos, pero ${avisos.join('; ')}.</div>`
                    : '';
            }

            this._renderTab();
        } finally {
            if (btn) btn.disabled = false;
        }
    },

    _tab(tab) {
        this._tabActiva = tab;
        document.querySelectorAll('#ivaTabs .nav-link').forEach(a => a.classList.remove('active'));
        try {
            const link = document.querySelector(`#ivaTabs .nav-link[data-action="IVA._tab"][data-arg="${tab}"]`);
            if (link) link.classList.add('active');
        } catch (e) {
            console.warn('No se pudo marcar pestaña activa:', e);
        }
        this._renderTab();
    },

    _renderTab() {
        let data;
        const labelEnt = this._tabActiva === 'ventas' ? 'Cliente' : 'Proveedor';
        if (this._tabActiva === 'ventas')  data = this._datosVentas;
        else if (this._tabActiva === 'compras') data = this._datosCompras;
        else data = this._datosGastos;

        const entField = this._tabActiva === 'ventas' ? 'cliente' : 'proveedor';
        const columns = [
            { field: 'numero', label: 'N° Doc' },
            { field: entField, label: labelEnt },
            { field: 'fecha', label: 'Fecha', format: 'date' },
            { field: 'neto', label: 'Neto', format: 'currency' },
            { field: 'iva', label: 'IVA', format: 'currency' },
            { field: 'total', label: 'Total', format: 'currency' }
        ];
        document.getElementById('ivaTabla').innerHTML = Utils.buildTable(columns, data, { id: 'ivaDetalleTable' });
    },

    exportarCSV() {
        const allData = [
            ...this._datosVentas.map(r => ({ ...r, origen: 'Venta' })),
            ...this._datosCompras.map(r => ({ ...r, origen: 'Compra' })),
            ...this._datosGastos.map(r => ({ ...r, origen: 'Gasto' }))
        ];

        if (allData.length === 0) { Utils.toast('No hay datos para exportar', 'IVA', 'error'); return; }

        const csvCampo = (v) => `"${String(v === null || v === undefined ? '' : v).replace(/"/g, '""')}"`;
        let csv = 'Origen,Numero,Entidad,Fecha,Neto,IVA,Total\n';
        allData.forEach(r => {
            const ent = r.cliente || r.proveedor || '';
            csv += [r.origen, r.numero, ent, r.fecha, r.neto, r.iva, r.total].map(csvCampo).join(',') + '\n';
        });

        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `IVA_${Utils.today()}.csv`;
        link.click();
        URL.revokeObjectURL(link.href);
        Utils.toast('CSV exportado correctamente', 'IVA', 'success');
    }
};
// Exponer IVA
window.IVA = IVA;
