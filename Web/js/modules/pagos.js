/**
 * pagos.js - Módulo de Pagos a Proveedores
 * Equivale a: pago_prov.frm
 *
 * Migrado de la base SQLite del navegador (db.js / sql.js, ya muerta) a la API REST.
 * IMPORTANTE: el backend (POST /api/pagos/) aplica TODOS los efectos contables en una
 * sola transacción: crea el pago, descuenta el saldo del proveedor y genera el egreso
 * de caja (o la entrada en la chequera si es cheque). Acá NO se tocan saldos, ni caja,
 * ni chequera: sólo se llama al endpoint y se refresca la vista.
 */
const Pagos = {
    /** Cheques de tercero disponibles, cacheados para resolver el select por id. */
    _chequesTercero: [],

    showPagos() {
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#4527a0,#7b1fa2)">
                <h4><i class="bi bi-cash-stack"></i> Pagos a Proveedores</h4>
            </div>
            <div class="row mb-3">
                <div class="col-md-5">
                    <div class="form-card">
                        <label class="form-label-sm">Buscar Proveedor</label>
                        <input type="text" class="form-control" id="pagoProveedor" placeholder="Buscar proveedor...">
                        <h6 class="mt-2">Saldo Proveedor</h6>
                        <h3 id="pagoSaldo" class="text-danger">$0.00</h3>
                    </div>
                </div>
                <div class="col-md-7">
                    <div class="form-card">
                        <h6>Registrar Pago</h6>
                        <div class="row">
                            <div class="col-4">
                                <label class="form-label-sm">Monto</label>
                                <input type="number" class="form-control form-control-sm" id="pagoMonto" step="0.01">
                            </div>
                            <div class="col-4">
                                <label class="form-label-sm">Forma de Pago</label>
                                <select class="form-select form-select-sm" id="pagoTipo">
                                    <option value="efectivo">Efectivo</option>
                                    <option value="cheque_propio">Cheque Propio</option>
                                    <option value="cheque_tercero">Cheque Tercero</option>
                                </select>
                            </div>
                            <div class="col-4">
                                <label class="form-label-sm">Fecha</label>
                                <input type="date" class="form-control form-control-sm" id="pagoFecha" value="${Utils.today()}">
                            </div>
                        </div>
                        <div id="pagoChequeDiv" class="mt-2 d-none">
                            <div class="row">
                                <div class="col-4">
                                    <label class="form-label-sm">N° Cheque</label>
                                    <input type="text" class="form-control form-control-sm" id="pagoNumCheque">
                                </div>
                                <div class="col-4">
                                    <label class="form-label-sm">Banco</label>
                                    <input type="text" class="form-control form-control-sm" id="pagoBanco">
                                </div>
                                <div class="col-4">
                                    <label class="form-label-sm">Vencimiento</label>
                                    <input type="date" class="form-control form-control-sm" id="pagoVenc">
                                </div>
                            </div>
                            <small class="text-muted d-block mt-1">
                                El cheque se registra en la chequera. Banco y vencimiento todavía no se
                                guardan (falta soporte en el endpoint de pagos).
                            </small>
                        </div>
                        <div id="pagoChequeTerceroDiv" class="mt-2 d-none">
                            <label class="form-label-sm">Seleccionar cheque de tercero disponible</label>
                            <select class="form-select form-select-sm" id="pagoChequeTercero">
                                <option value="">-- Seleccione --</option>
                            </select>
                            <small class="text-muted d-block mt-1">
                                El cheque endosado no queda marcado como usado en la chequera
                                (falta endpoint para actualizarla): verificar antes de reutilizarlo.
                            </small>
                        </div>
                        <button class="btn btn-primary mt-3 w-100" data-action="Pagos.registrarPago">
                            <i class="bi bi-wallet2"></i> Registrar Pago
                        </button>
                    </div>
                </div>
            </div>
            <h5>Historial de Pagos</h5>
            <div id="pagoHistorial"></div>
        `;
        Utils.showView(html);
        Utils.searchEntity('proveedores', 'pagoProveedor', (prov) => {
            document.getElementById('pagoSaldo').textContent = Utils.formatCurrency(prov.saldo);
            document.getElementById('pagoProveedor').dataset.nombre = prov.nombre || '';
            this.cargarHistorial(prov.cuit);
        });

        const pagoTipoEl = document.getElementById('pagoTipo');
        if (pagoTipoEl && !pagoTipoEl.__changeBound) {
            pagoTipoEl.addEventListener('change', (e) => {
                const val = e.target.value;
                document.getElementById('pagoChequeDiv').classList.toggle('d-none', val !== 'cheque_propio');
                document.getElementById('pagoChequeTerceroDiv').classList.toggle('d-none', val !== 'cheque_tercero');
                if (val === 'cheque_tercero') this.cargarChequesTercero();
            });
            pagoTipoEl.__changeBound = true;
        }
        if (App && typeof App.bindDataActions === 'function') App.bindDataActions();
    },

    /** Refrescar el saldo mostrado leyéndolo de la API (fuente de verdad). */
    async _refrescarSaldo(cuit) {
        try {
            const prov = await API.proveedores.getById(cuit);
            const el = document.getElementById('pagoSaldo');
            if (el) el.textContent = Utils.formatCurrency(prov ? prov.saldo : 0);
            return prov;
        } catch (err) {
            console.error('Error al leer el saldo del proveedor:', err);
            return null;
        }
    },

    async cargarChequesTercero() {
        const sel = document.getElementById('pagoChequeTercero');
        if (!sel) return;

        let cheques = [];
        try {
            // tipo === 1 => cheque recibido/a cobrar (así los graba POST /api/cobros/).
            const todos = await API.caja.getChequera();
            cheques = todos.filter(ch => ch.tipo === 1 && !ch.pagado);
        } catch (err) {
            console.error('Error al cargar la chequera:', err);
            Utils.toast('Error al cargar los cheques de tercero: ' + err.message, 'Error', 'error');
            return;
        }

        this._chequesTercero = cheques;
        sel.innerHTML = '';
        const def = document.createElement('option');
        def.value = '';
        def.textContent = cheques.length ? '-- Seleccione --' : '-- Sin cheques disponibles --';
        sel.appendChild(def);
        cheques.forEach(ch => {
            const opt = document.createElement('option');
            opt.value = ch.id;
            // textContent: no hay interpolación en HTML, no hace falta escapar.
            opt.textContent = `${ch.numcheque} - ${ch.banco} - ${Utils.formatCurrency(ch.monto)} - Venc: ${Utils.formatDate(ch.vencimiento)}`;
            sel.appendChild(opt);
        });
    },

    async cargarHistorial(cuit) {
        let pagos = [];
        try {
            pagos = await API.pagos.getAll(null, cuit);
        } catch (err) {
            console.error('Error al cargar el historial de pagos:', err);
            Utils.toast('Error al cargar el historial de pagos: ' + err.message, 'Error', 'error');
            return;
        }
        pagos = pagos
            .sort((a, b) => (b.fecha || '').localeCompare(a.fecha || '') || (b.ordpago - a.ordpago))
            .slice(0, 50);

        const columns = [
            { field: 'ordpago', label: 'N° Pago' },
            { field: 'fecha', label: 'Fecha', format: 'date' },
            { field: 'monto', label: 'Monto', format: 'currency' },
            { field: 'tipo', label: 'Forma' }
        ];
        const cont = document.getElementById('pagoHistorial');
        // Utils.buildTable ya escapa los valores string que vienen de la BD.
        if (cont) cont.innerHTML = Utils.buildTable(columns, pagos);
    },

    async registrarPago() {
        const input = document.getElementById('pagoProveedor');
        const cuit = input && input.dataset.cuit;
        if (!cuit) { Utils.toast('Seleccione un proveedor', 'Error', 'error'); return; }

        const tipoSel = document.getElementById('pagoTipo').value;
        const fecha = document.getElementById('pagoFecha').value || Utils.today();
        let monto = parseFloat(document.getElementById('pagoMonto').value) || 0;
        let tipo = 'efectivo';
        let referencia = '';

        if (tipoSel === 'cheque_propio') {
            tipo = 'cheque propio';
            referencia = (document.getElementById('pagoNumCheque').value || '').trim();
            if (!referencia) {
                Utils.toast('Ingrese el N° de cheque', 'Error', 'error');
                Utils.flagInvalid('pagoNumCheque');
                return;
            }
            const banco = (document.getElementById('pagoBanco').value || '').trim();
            const venc = document.getElementById('pagoVenc').value;
            if (banco || venc) {
                // No inventamos un endpoint: avisamos en vez de simular que se guardó.
                console.warn(
                    'Pagos: el endpoint POST /api/pagos/ no acepta banco ni vencimiento del cheque. ' +
                    `Se registrará el cheque N° ${referencia} en la chequera sin banco ("${banco}") ` +
                    `y con el vencimiento igual a la fecha del pago (se ignora "${venc}").`
                );
            }
        } else if (tipoSel === 'cheque_tercero') {
            tipo = 'cheque tercero';
            const chequeId = document.getElementById('pagoChequeTercero').value;
            if (!chequeId) { Utils.toast('Seleccione un cheque', 'Error', 'error'); return; }
            const cheque = this._chequesTercero.find(ch => String(ch.id) === String(chequeId));
            if (!cheque) { Utils.toast('El cheque seleccionado ya no está disponible', 'Error', 'error'); return; }
            monto = cheque.monto;
            referencia = cheque.numcheque || '';
            console.warn(
                'Pagos: no existe un endpoint para actualizar la chequera (PUT/PATCH /api/caja/chequera/{id}). ' +
                `El cheque de tercero N° ${referencia} (id=${cheque.id}) NO queda marcado como usado ` +
                'y va a seguir apareciendo como disponible.'
            );
        }

        if (monto <= 0) { Utils.toast('Ingrese un monto válido', 'Error', 'error'); return; }

        const btn = document.querySelector('[data-action="Pagos.registrarPago"]');
        if (btn) btn.disabled = true;

        let pago;
        try {
            pago = await API.pagos.create({ proveedor: cuit, monto, fecha, tipo, referencia });
        } catch (err) {
            console.error('Error al registrar el pago:', err);
            Utils.toast('No se pudo registrar el pago: ' + err.message, 'Error', 'error');
            return;
        } finally {
            if (btn) btn.disabled = false;
        }

        Utils.toast(
            `Pago N° ${pago.ordpago} registrado por ${Utils.formatCurrency(pago.monto)}`,
            'Pagos', 'success'
        );

        if (tipoSel === 'cheque_tercero') {
            Utils.toast(
                'El cheque de tercero no quedó marcado como usado en la chequera (falta endpoint).',
                'Chequera', 'warning'
            );
        }

        // El backend ya descontó el saldo y generó el asiento: sólo releemos.
        await this._refrescarSaldo(cuit);
        document.getElementById('pagoMonto').value = '';
        const numChequeEl = document.getElementById('pagoNumCheque');
        if (numChequeEl) numChequeEl.value = '';
        await this.cargarHistorial(cuit);
        if (tipoSel === 'cheque_tercero') await this.cargarChequesTercero();

        const ok = await Utils.confirm('Imprimir Orden de Pago', `¿Desea imprimir la orden de pago N° ${pago.ordpago}?`);
        if (ok) await this.imprimirPago(pago);
    },

    /** Acepta el objeto pago devuelto por la API o un número de pago. */
    async imprimirPago(pago) {
        try {
            if (pago === null || pago === undefined) return;
            if (typeof pago !== 'object') {
                const ord = parseInt(pago);
                const todos = await API.pagos.getAll();
                pago = todos.find(p => p.ordpago === ord);
            }
            if (!pago) { Utils.toast('Pago no encontrado', 'Error', 'error'); return; }

            let prov = null;
            try {
                prov = await API.proveedores.getById(pago.proveedor);
            } catch (err) {
                console.warn('No se pudo obtener el proveedor del pago:', err.message);
            }

            const printHtml = `
                <div style="font-family:Arial; padding:20px; max-width:800px; margin:auto; border: 1px solid #ccc;">
                    <h2 style="text-align:center;">ORDEN DE PAGO N° ${Utils.escapeHtml(String(pago.ordpago))}</h2>
                    <hr>
                    <p><strong>Fecha:</strong> ${Utils.escapeHtml(Utils.formatDate(pago.fecha))}</p>
                    <p><strong>Pagamos a:</strong> ${Utils.escapeHtml(prov ? prov.nombre : pago.proveedor)}</p>
                    <p><strong>CUIT:</strong> ${Utils.escapeHtml(pago.proveedor)}</p>
                    <br>
                    <p><strong>La cantidad de:</strong> ${Utils.escapeHtml(Utils.formatCurrency(pago.monto))}</p>
                    <p><strong>Forma de pago:</strong> ${Utils.escapeHtml(String(pago.tipo || '').toUpperCase())} ${pago.referencia ? '(' + Utils.escapeHtml(pago.referencia) + ')' : ''}</p>
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
            console.error('Error al imprimir la orden de pago:', err);
            Utils.toast('Error al imprimir la orden de pago: ' + err.message, 'Error', 'error');
        }
    }
};
// Exponer Pagos
window.Pagos = Pagos;
