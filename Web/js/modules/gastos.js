/**
 * gastos.js - Módulo de Gastos y Facturas de Proveedores
 * Equivale a: F_g.frm, Fac_nc.frm, Fac_nd.frm
 *
 * MIGRADO A LA API REST: antes escribía con DB.run() contra la base sql.js del
 * navegador, que ya no se inicializa nunca. Cada "gasto guardado" se perdía sin
 * aviso. Ahora todo pasa por API.gastos / API.caja.
 */
const Gastos = {
    _items: [],

    /** Alícuotas de IVA vigentes en Argentina (mismo criterio que el backend). */
    ALICUOTAS_IVA: [0, 2.5, 5, 10.5, 21, 27],

    showFacturaGasto() {
        this._items = [];
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#880e4f,#ad1457)">
                <h4><i class="bi bi-receipt"></i> Factura de Gastos</h4>
            </div>
            <div class="row mb-3">
                <div class="col-md-5">
                    <div class="form-card">
                        <label class="form-label-sm">Proveedor</label>
                        <input type="text" class="form-control" id="gastoProveedor" placeholder="Buscar proveedor...">
                        <div class="row mt-2">
                            <div class="col-6">
                                <label class="form-label-sm">N° Factura</label>
                                <input type="text" class="form-control form-control-sm" id="gastoNumFact">
                            </div>
                            <div class="col-6">
                                <label class="form-label-sm">Fecha</label>
                                <input type="date" class="form-control form-control-sm" id="gastoFecha" value="${Utils.today()}">
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-7">
                    <div class="form-card">
                        <h6>Agregar Concepto</h6>
                        <div class="row">
                            <div class="col-6">
                                <input type="text" class="form-control form-control-sm" id="gastoConcepto" placeholder="Concepto">
                            </div>
                            <div class="col-2">
                                <input type="number" class="form-control form-control-sm" id="gastoMonto" placeholder="Monto" step="0.01" min="0">
                            </div>
                            <div class="col-2">
                                <select class="form-select form-select-sm" id="gastoIVA">
                                    ${this.ALICUOTAS_IVA.map(a => `<option value="${a}" ${a === 21 ? 'selected' : ''}>${a}%</option>`).join('')}
                                </select>
                            </div>
                            <div class="col-2">
                                <button class="btn btn-sm btn-success w-100" data-action="Gastos.agregarItem">
                                    <i class="bi bi-plus"></i> Agregar
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div id="gastoItems"></div>
            <div class="row mt-2">
                <div class="col text-end">
                    <h5>Subtotal: <span id="gastoSubtotal">$0.00</span></h5>
                    <h5>IVA: <span id="gastoTotalIVA">$0.00</span></h5>
                    <h4>Total: <span id="gastoTotal" class="text-primary">$0.00</span></h4>
                    <button class="btn btn-primary mt-2" id="gastoGuardarBtn" data-action="Gastos.guardarFacturaGasto">
                        <i class="bi bi-save"></i> Guardar Factura de Gasto
                    </button>
                </div>
            </div>
            <hr>
            <h6><i class="bi bi-clock-history"></i> Últimos gastos registrados</h6>
            <div id="gastoUltimos"><p class="text-muted small">Cargando...</p></div>
        `;
        Utils.showView(html);
        Utils.searchEntity('proveedores', 'gastoProveedor', () => {});
        this._renderItems();
        this.cargarUltimos();
    },

    /** Lista los gastos ya persistidos en el servidor (evidencia de que se guardaron). */
    async cargarUltimos() {
        const cont = document.getElementById('gastoUltimos');
        if (!cont) return;
        try {
            const gastos = await API.gastos.getAll();
            if (!gastos.length) {
                cont.innerHTML = '<p class="text-muted small">Todavía no hay gastos cargados.</p>';
                return;
            }
            const columns = [
                { field: 'id', label: 'N°' },
                { field: 'proveedor', label: 'Proveedor (CUIT)' },
                { field: 'numfactura', label: 'N° Factura' },
                { field: 'fecha', label: 'Fecha', format: 'date' },
                { field: 'subtotal', label: 'Neto', format: 'currency' },
                { field: 'iva', label: 'IVA', format: 'currency' },
                { field: 'total', label: 'Total', format: 'currency' },
                { field: 'descripcion', label: 'Conceptos' }
            ];
            cont.innerHTML = Utils.buildTable(columns, gastos.slice(0, 20), { id: 'gastosUltimosTable' });
        } catch (err) {
            console.error('Error al cargar los gastos:', err);
            cont.innerHTML = `<div class="alert alert-danger py-2 mb-0">No se pudieron cargar los gastos: ${Utils.escapeHtml(err.message)}</div>`;
        }
    },

    agregarItem() {
        const concepto = document.getElementById('gastoConcepto').value.trim();
        const monto = parseFloat(document.getElementById('gastoMonto').value) || 0;
        const ivaPct = parseFloat(document.getElementById('gastoIVA').value) || 0;

        if (!concepto) { Utils.flagInvalid('gastoConcepto'); Utils.toast('Indique el concepto', 'Validación', 'error'); return; }
        if (monto <= 0) { Utils.flagInvalid('gastoMonto'); Utils.toast('El monto debe ser mayor a cero', 'Validación', 'error'); return; }
        if (!this.ALICUOTAS_IVA.includes(ivaPct)) {
            Utils.flagInvalid('gastoIVA');
            Utils.toast(`Alícuota de IVA inválida. Válidas: ${this.ALICUOTAS_IVA.join('%, ')}%`, 'Validación', 'error');
            return;
        }

        const iva = monto * ivaPct / 100;
        this._items.push({ concepto, monto, ivaPct, iva, total: monto + iva });
        this._renderItems();

        document.getElementById('gastoConcepto').value = '';
        document.getElementById('gastoMonto').value = '';
    },

    _renderItems() {
        let subtotal = 0, totalIva = 0;
        this._items.forEach(it => { subtotal += it.monto; totalIva += it.iva; });

        const columns = [
            { field: 'concepto', label: 'Concepto' },
            { field: 'monto', label: 'Neto', format: 'currency' },
            { field: 'ivaPct', label: 'IVA %' },
            { field: 'iva', label: 'IVA $', format: 'currency' },
            { field: 'total', label: 'Total', format: 'currency' }
        ];
        document.getElementById('gastoItems').innerHTML = Utils.buildTable(columns, this._items);
        document.getElementById('gastoSubtotal').textContent = Utils.formatCurrency(subtotal);
        document.getElementById('gastoTotalIVA').textContent = Utils.formatCurrency(totalIva);
        document.getElementById('gastoTotal').textContent = Utils.formatCurrency(subtotal + totalIva);
    },

    /** Resumen textual de los conceptos: se persiste en gastosfacturas.descripcion. */
    _descripcionConceptos() {
        const texto = this._items
            .map(it => `${it.concepto} $${Utils.formatNumber(it.monto)} (IVA ${it.ivaPct}%)`)
            .join(' | ');
        return texto.slice(0, 500);
    },

    async guardarFacturaGasto() {
        const cuit = document.getElementById('gastoProveedor').dataset.cuit;
        if (!cuit) { Utils.flagInvalid('gastoProveedor'); Utils.toast('Seleccione un proveedor', 'Error', 'error'); return; }
        if (this._items.length === 0) { Utils.toast('Agregue al menos un concepto', 'Error', 'error'); return; }

        const numFact = document.getElementById('gastoNumFact').value.trim();
        const fecha = document.getElementById('gastoFecha').value || Utils.today();

        let subtotal = 0, totalIva = 0;
        this._items.forEach(it => { subtotal += it.monto; totalIva += it.iva; });
        const total = subtotal + totalIva;

        const btn = document.getElementById('gastoGuardarBtn');
        if (btn) btn.disabled = true;

        let creado;
        try {
            // Una sola petición: el servidor persiste la cabecera y los renglones,
            // suma el total al saldo del proveedor y genera el egreso de caja,
            // todo dentro de la misma transacción.
            creado = await API.gastos.create({
                proveedor: cuit,
                numfactura: numFact,
                fecha,
                subtotal,
                iva: totalIva,
                total,
                descripcion: this._descripcionConceptos(),
                cdc: 0,
                items: this._items.map(it => ({
                    descripcion: it.concepto || '',
                    monto: it.monto,
                    iva: it.ivaPct   // alícuota %, la que valida el backend
                }))
            });
        } catch (err) {
            console.error('Error al guardar la factura de gastos:', err);
            Utils.toast('No se pudo guardar la factura de gastos: ' + err.message, 'Error', 'error');
            if (btn) btn.disabled = false;
            return;   // nunca reportar éxito si el servidor no confirmó
        }

        Utils.toast(`Factura de gastos N°${creado.id} guardada por ${Utils.formatCurrency(total)}`, 'Gastos', 'success');
        this.showFacturaGasto();
    },

    /* ───────── NC / ND Proveedor ───────── */
    notaCreditoProveedor() {
        this._emitirNotaProv('NC');
    },

    notaDebitoProveedor() {
        this._emitirNotaProv('ND');
    },

    _emitirNotaProv(tipo) {
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,${tipo === 'NC' ? '#2e7d32,#388e3c' : '#c62828,#d32f2f'})">
                <h4><i class="bi bi-${tipo === 'NC' ? 'file-earmark-minus' : 'file-earmark-plus'}"></i>
                    Nota de ${tipo === 'NC' ? 'Crédito' : 'Débito'} a Proveedor</h4>
            </div>
            <div class="alert alert-warning">
                <i class="bi bi-exclamation-triangle"></i>
                <strong>Módulo no operativo.</strong> El servidor todavía no expone un endpoint REST para
                notas de crédito/débito a proveedor (tablas <code>nfan</code> / <code>ndprov</code>).
                Hasta que exista, esta pantalla <strong>no guarda nada</strong>: se muestra solo para no
                ocultar la funcionalidad pendiente.
            </div>
            <div class="row">
                <div class="col-md-6 mx-auto">
                    <div class="form-card">
                        <label class="form-label-sm">Proveedor</label>
                        <input type="text" class="form-control" id="notaProvProv" placeholder="Buscar proveedor...">
                        <div class="row mt-2">
                            <div class="col-6">
                                <label class="form-label-sm">Monto</label>
                                <input type="number" class="form-control form-control-sm" id="notaProvMonto" step="0.01" min="0">
                            </div>
                            <div class="col-6">
                                <label class="form-label-sm">N° Referencia</label>
                                <input type="text" class="form-control form-control-sm" id="notaProvRef">
                            </div>
                        </div>
                        <label class="form-label-sm mt-2">Motivo</label>
                        <textarea class="form-control form-control-sm" id="notaProvMotivo" rows="2"></textarea>
                        <button class="btn btn-${tipo === 'NC' ? 'success' : 'danger'} mt-3 w-100"
                            data-action="Gastos._guardarNotaProv" data-arg="${tipo}">
                            <i class="bi bi-save"></i> Guardar ${tipo}
                        </button>
                    </div>
                </div>
            </div>
        `;
        Utils.showView(html);
        Utils.searchEntity('proveedores', 'notaProvProv', () => {});
    },

    async _guardarNotaProv(tipo) {
        const cuit = document.getElementById('notaProvProv').dataset.cuit;
        if (!cuit) { Utils.flagInvalid('notaProvProv'); Utils.toast('Seleccione un proveedor', 'Error', 'error'); return; }

        const monto = parseFloat(document.getElementById('notaProvMonto').value) || 0;
        if (monto <= 0) { Utils.flagInvalid('notaProvMonto'); Utils.toast('El monto debe ser mayor a cero', 'Validación', 'error'); return; }

        // No hay endpoint: antes esto escribía en la base sql.js del navegador y el
        // usuario veía un toast de éxito sobre un dato que nunca se guardaba.
        const tabla = tipo === 'NC' ? 'nfan' : 'ndprov';
        console.warn(
            `[gastos] Nota de ${tipo === 'NC' ? 'crédito' : 'débito'} a proveedor NO GUARDADA: ` +
            `la API no expone ningún endpoint para la tabla "${tabla}" ni para ajustar proveedores.saldo. ` +
            `Datos descartados -> proveedor=${cuit}, monto=${monto}. ` +
            'Falta backend: POST /api/notas-proveedor/ (NC/ND) con su ajuste de saldo.'
        );
        Utils.toast(
            `No guardada: el servidor no expone todavía el endpoint de notas de ${tipo === 'NC' ? 'crédito' : 'débito'} a proveedor.`,
            'Funcionalidad pendiente', 'error'
        );
    }
};
// Exponer Gastos
window.Gastos = Gastos;
