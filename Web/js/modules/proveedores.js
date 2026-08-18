/**
 * proveedores.js - Módulo de Proveedores y Compras
 * Equivale a: pro_pro_Click, pro_np_Click, pro_com_Click (F_c.frm), Devolucion.frm
 */
const Proveedores = {
    _data: [],
    _compraItems: [],

    async showProveedores() {
        try {
            this._data = await API.proveedores.getAll();
        } catch (err) {
            console.error('Error al cargar proveedores:', err);
            Utils.toast('Error al cargar proveedores', 'Error', 'error');
            return;
        }
        const columns = [
            { field: 'cuit', label: 'CUIT' },
            { field: 'nombre', label: 'Razón Social' },
            { field: 'domicilio', label: 'Domicilio' },
            { field: 'localidad', label: 'Localidad' },
            { field: 'provincia', label: 'Provincia' },
            { field: 'cp', label: 'CP' },
            { field: 'telefono', label: 'Teléfono' },
            { field: 'mail', label: 'E-Mail' },
            { field: 'saldo', label: 'Saldo', format: 'currency' }
        ];

        const html = `
            <div class="section-header d-flex justify-content-between align-items-center">
                <h4><i class="bi bi-truck"></i> Proveedores Cargados</h4>
                <button class="btn btn-sm btn-success" data-action="Proveedores.nuevoProveedor">
                    <i class="bi bi-plus-circle"></i> Nuevo Proveedor
                </button>
            </div>
            <div class="mb-3">
                  <input type="text" class="form-control" id="provSearch" placeholder="Buscar proveedor...">
            </div>
            <div id="provTable">
                ${Utils.buildTable(columns, this._data, { id: 'provGrid', onDblClick: 'Proveedores.editProv' })}
            </div>
        `;
        Utils.showView(html);
        // Bind search input programmatically
        const provSearchEl = document.getElementById('provSearch');
        if (provSearchEl && !provSearchEl.__provBound) {
            provSearchEl.addEventListener('input', (e) => {
                try { Proveedores.filtrar(e.target.value); } catch (err) { console.error('Proveedores.filtrar error', err); }
            });
            provSearchEl.__provBound = true;
        }
    },

    filtrar(val) {
        const filtered = this._data.filter(r =>
            r.nombre.toLowerCase().includes(val.toLowerCase()) || (r.cuit && String(r.cuit).includes(val))
        );
        const columns = [
            { field: 'cuit', label: 'CUIT' }, { field: 'nombre', label: 'Razón Social' },
            { field: 'domicilio', label: 'Domicilio' }, { field: 'localidad', label: 'Localidad' },
            { field: 'provincia', label: 'Provincia' }, { field: 'cp', label: 'CP' },
            { field: 'telefono', label: 'Teléfono' }, { field: 'mail', label: 'E-Mail' },
            { field: 'saldo', label: 'Saldo', format: 'currency' }
        ];
        document.getElementById('provTable').innerHTML = Utils.buildTable(columns, filtered, { id: 'provGrid', onDblClick: 'Proveedores.editProv' });
    },

    async nuevoProveedor() {
        const result = await Utils.multiInput('Nuevo Proveedor', [
            { name: 'cuit', label: 'CUIT', required: true, placeholder: 'XX-XXXXXXXX-X' },
            { name: 'nombre', label: 'Razón Social', required: true },
            { name: 'domicilio', label: 'Domicilio' },
            { name: 'localidad', label: 'Localidad' },
            { name: 'provincia', label: 'Provincia' },
            { name: 'cp', label: 'Código Postal' },
            { name: 'telefono', label: 'Teléfono' },
            { name: 'mail', label: 'E-Mail' }
        ]);

        if (!result || !result.cuit || !result.nombre) return;

        try {
            await API.proveedores.create({
                cuit: result.cuit.trim(),
                nombre: result.nombre.trim(),
                domicilio: result.domicilio || '',
                localidad: result.localidad || '',
                provincia: result.provincia || '',
                cp: result.cp || '',
                telefono: result.telefono || '',
                mail: result.mail || ''
            });
            Utils.toast('Nuevo proveedor cargado', 'Proveedores', 'success');
            this.showProveedores();
        } catch (e) {
            Utils.toast('Error al cargar proveedor: ' + e.message, 'Error', 'error');
        }
    },

    async editProv(idx) {
        const p = this._data[idx];
        if (!p) return;
        const result = await Utils.multiInput('Editar Proveedor: ' + p.nombre, [
            { name: 'nombre', label: 'Razón Social', default: p.nombre },
            { name: 'domicilio', label: 'Domicilio', default: p.domicilio },
            { name: 'localidad', label: 'Localidad', default: p.localidad },
            { name: 'provincia', label: 'Provincia', default: p.provincia },
            { name: 'cp', label: 'CP', default: p.cp },
            { name: 'telefono', label: 'Teléfono', default: p.telefono },
            { name: 'mail', label: 'E-Mail', default: p.mail }
        ]);
        if (!result) return;

        try {
            await API.proveedores.update(p.cuit, {
                nombre: result.nombre,
                domicilio: result.domicilio,
                localidad: result.localidad,
                provincia: result.provincia,
                cp: result.cp,
                telefono: result.telefono,
                mail: result.mail
            });
            Utils.toast('Proveedor actualizado', 'Proveedores', 'success');
            this.showProveedores();
        } catch (e) {
            Utils.toast('Error al actualizar proveedor: ' + e.message, 'Error', 'error');
        }
    },

    /** Cargar Compra (equivale a F_c.frm) */
    cargarCompra() {
        this._compraItems = [];
        const html = `
            <div class="section-header">
                <h4><i class="bi bi-cart-plus"></i> Factura de Compra</h4>
            </div>
            <div class="row mb-3">
                <div class="col-md-6">
                    <div class="form-card">
                        <label class="form-label-sm">Proveedor</label>
                        <div class="position-relative">
                            <input type="text" class="form-control" id="compraProveedor" placeholder="Buscar proveedor...">
                        </div>
                        <div class="row mt-2">
                            <div class="col-6">
                                <label class="form-label-sm">Nro. Factura</label>
                                <input type="text" class="form-control form-control-sm" id="compraNumFact">
                            </div>
                            <div class="col-6">
                                <label class="form-label-sm">Fecha</label>
                                <input type="date" class="form-control form-control-sm" id="compraFecha" value="${Utils.today()}">
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="form-card">
                        <label class="form-label-sm">Agregar Producto</label>
                        <div class="position-relative">
                            <input type="text" class="form-control form-control-sm" id="compraProd" placeholder="Buscar producto...">
                        </div>
                        <div class="row mt-2">
                            <div class="col-4">
                                <label class="form-label-sm">Cantidad</label>
                                <input type="number" class="form-control form-control-sm" id="compraCant" value="1">
                            </div>
                            <div class="col-4">
                                <label class="form-label-sm">Precio Compra</label>
                                <input type="number" class="form-control form-control-sm" id="compraPrecio" step="0.01">
                            </div>
                                <div class="col-4 d-flex align-items-end">
                                <button class="btn btn-sm btn-primary w-100" data-action="Proveedores.addCompraItem">
                                    <i class="bi bi-plus"></i> Agregar
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div id="compraGrid"></div>
            <div class="row mt-3">
                <div class="col-md-4 offset-md-8">
                    <table class="table table-sm">
                        <tr><td>Subtotal:</td><td class="text-end" id="compraSubtotal">$0.00</td></tr>
                        <tr><td>IVA:</td><td class="text-end" id="compraIVA">$0.00</td></tr>
                        <tr class="fw-bold"><td>TOTAL:</td><td class="text-end" id="compraTotal">$0.00</td></tr>
                    </table>
                    <button class="btn btn-success w-100" data-action="Proveedores.guardarCompra">
                        <i class="bi bi-check-circle"></i> Registrar Compra
                    </button>
                </div>
            </div>
        `;
        Utils.showView(html);
        Utils.searchEntity('proveedores', 'compraProveedor');
        Utils.searchProduct('compraProd', (p) => {
            document.getElementById('compraPrecio').value = p.precom || p.preven;
        });
    },

    async addCompraItem() {
        const prodInput = document.getElementById('compraProd');
        const codigo = prodInput.dataset.codigo;
        if (!codigo) { Utils.toast('Seleccione un producto', 'Error', 'error'); return; }

        const cant = parseFloat(document.getElementById('compraCant').value) || 0;
        const precio = parseFloat(document.getElementById('compraPrecio').value) || 0;

        try {
            const prod = await API.stock.getById(codigo);

            this._compraItems.push({
                codigo: prod.codigo, producto: prod.producto, cantidad: cant,
                precio: precio, iva: prod.iva, unidad: prod.unidad,
                subtotal: cant * precio, ivaTotal: cant * precio * (prod.iva / 100)
            });

            prodInput.value = '';
            prodInput.dataset.codigo = '';
            document.getElementById('compraCant').value = '1';
            document.getElementById('compraPrecio').value = '';
            this._renderCompraGrid();
        } catch (err) {
            Utils.toast('Error al obtener producto: ' + err.message, 'Error', 'error');
        }
    },

    _renderCompraGrid() {
        let subtotal = 0, ivaTotal = 0;
        let html = '<table class="table table-sm flex-grid"><thead><tr>' +
            '<th>Código</th><th>Producto</th><th>Cant.</th><th>Precio</th><th>IVA%</th><th>Subtotal</th><th></th>' +
            '</tr></thead><tbody>';

        this._compraItems.forEach((item, i) => {
            subtotal += item.subtotal;
            ivaTotal += item.ivaTotal;
            html += `<tr>
                <td>${Utils.escapeHtml(String(item.codigo))}</td><td>${Utils.escapeHtml(String(item.producto))}</td><td>${Utils.escapeHtml(String(item.cantidad))}</td>
                <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(item.precio))}</td>
                <td>${Utils.escapeHtml(String(item.iva))}%</td><td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(item.subtotal))}</td>
                <td><button class="btn btn-sm btn-outline-danger" data-action="Proveedores.removeCompraItem" data-idx="${i}"><i class="bi bi-trash"></i></button></td>
            </tr>`;
        });
        html += '</tbody></table>';

        document.getElementById('compraGrid').innerHTML = html;
        if (window.App && typeof App.bindDataActions === 'function') App.bindDataActions();
        document.getElementById('compraSubtotal').textContent = Utils.formatCurrency(subtotal);
        document.getElementById('compraIVA').textContent = Utils.formatCurrency(ivaTotal);
        document.getElementById('compraTotal').textContent = Utils.formatCurrency(subtotal + ivaTotal);
    },

    removeCompraItem(idx, el) {
        this._compraItems.splice(idx, 1);
        // if called from dev grid, re-render dev grid, else compra grid
        try {
            if (el && el.dataset && el.dataset.render === 'dev') this._renderDevGrid();
            else this._renderCompraGrid();
        } catch (err) {
            this._renderCompraGrid();
        }
    },

    async guardarCompra() {
        const provInput = document.getElementById('compraProveedor');
        const provCuit = provInput.dataset.cuit;
        if (!provCuit) { Utils.toast('Seleccione un proveedor', 'Error', 'error'); return; }
        if (this._compraItems.length === 0) { Utils.toast('Agregue al menos un producto', 'Error', 'error'); return; }

        const fecha = document.getElementById('compraFecha').value;
        const numFact = document.getElementById('compraNumFact').value || '0';
        let subtotal = 0, ivaTotal = 0;
        this._compraItems.forEach(i => { subtotal += i.subtotal; ivaTotal += i.ivaTotal; });
        const total = subtotal + ivaTotal;

        try {
            // Enviar la compra completa al backend
            await API.post('/compras/', {
                proveedor_cuit: provCuit,
                fecha: fecha,
                num_factura: numFact,
                items: this._compraItems.map(item => ({
                    codigo: item.codigo,
                    producto: item.producto,
                    cantidad: item.cantidad,
                    precio: item.precio
                }))
            });

            Utils.toast('Compra registrada correctamente', 'Compras', 'success');
            this.showProveedores();
        } catch (err) {
            Utils.toast('Error al registrar compra: ' + err.message, 'Error', 'error');
        }
    },

    /** Devolución a Proveedores (equivale a Devolucion.frm) */
    devolucion() {
        this._compraItems = [];
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#b71c1c,#d32f2f)">
                <h4><i class="bi bi-arrow-return-left"></i> Devolución a Proveedores</h4>
            </div>
            <div class="row mb-3">
                <div class="col-md-6">
                    <div class="form-card">
                        <label class="form-label-sm">Proveedor</label>
                        <div class="position-relative">
                            <input type="text" class="form-control" id="devProveedor" placeholder="Buscar proveedor...">
                        </div>
                        <div class="row mt-2">
                            <div class="col-6">
                                <label class="form-label-sm">Fecha</label>
                                <input type="date" class="form-control form-control-sm" id="devFecha" value="${Utils.today()}">
                            </div>
                            <div class="col-6">
                                <label class="form-check-label mt-4">
                                    <input type="checkbox" class="form-check-input" id="devSinIVA"> Sin IVA
                                </label>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="form-card">
                        <label class="form-label-sm">Producto a Devolver</label>
                        <div class="position-relative">
                            <input type="text" class="form-control form-control-sm" id="devProd" placeholder="Buscar producto...">
                        </div>
                        <div class="row mt-2">
                            <div class="col-4">
                                <label class="form-label-sm">Cantidad</label>
                                <input type="number" class="form-control form-control-sm" id="devCant" value="1">
                            </div>
                            <div class="col-4">
                                <label class="form-label-sm">Precio</label>
                                <input type="number" class="form-control form-control-sm" id="devPrecio" step="0.01">
                            </div>
                            <div class="col-4 d-flex align-items-end">
                                                <button class="btn btn-sm btn-danger w-100" data-action="Proveedores.addDevItem">
                                                    <i class="bi bi-plus"></i> Agregar
                                                </button>
                                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div id="devGrid"></div>
            <div class="row mt-3">
                <div class="col-md-4 offset-md-8">
                    <table class="table table-sm">
                        <tr><td>Subtotal:</td><td class="text-end" id="devSubtotal">$0.00</td></tr>
                        <tr><td>IVA:</td><td class="text-end" id="devIVA">$0.00</td></tr>
                        <tr class="fw-bold"><td>TOTAL:</td><td class="text-end" id="devTotal">$0.00</td></tr>
                    </table>
                    <button class="btn btn-danger w-100" data-action="Proveedores.guardarDevolucion">
                        <i class="bi bi-arrow-return-left"></i> Registrar Devolución
                    </button>
                </div>
            </div>
        `;
        Utils.showView(html);
        Utils.searchEntity('proveedores', 'devProveedor');
        Utils.searchProduct('devProd', (p) => {
            document.getElementById('devPrecio').value = p.precom || p.preven;
        });
    },

    async addDevItem() {
        const prodInput = document.getElementById('devProd');
        const codigo = prodInput.dataset.codigo;
        if (!codigo) { Utils.toast('Seleccione un producto', 'Error', 'error'); return; }

        const cant = parseFloat(document.getElementById('devCant').value) || 0;
        const precio = parseFloat(document.getElementById('devPrecio').value) || 0;
        const sinIVA = document.getElementById('devSinIVA').checked;

        try {
            const prod = await API.stock.getById(codigo);

            this._compraItems.push({
                codigo: prod.codigo, producto: prod.producto, cantidad: cant,
                precio: precio, iva: sinIVA ? 0 : prod.iva, unidad: prod.unidad,
                subtotal: cant * precio, ivaTotal: sinIVA ? 0 : cant * precio * (prod.iva / 100)
            });

            prodInput.value = '';
            prodInput.dataset.codigo = '';
            this._renderDevGrid();
        } catch (err) {
            Utils.toast('Error al obtener producto: ' + err.message, 'Error', 'error');
        }
    },

    _renderDevGrid() {
        let subtotal = 0, ivaTotal = 0;
        let html = '<table class="table table-sm flex-grid"><thead><tr>' +
            '<th>Código</th><th>Producto</th><th>Cant.</th><th>Precio</th><th>IVA%</th><th>Subtotal</th><th></th>' +
            '</tr></thead><tbody>';

        this._compraItems.forEach((item, i) => {
            subtotal += item.subtotal;
            ivaTotal += item.ivaTotal;
            html += `<tr>
                <td>${Utils.escapeHtml(String(item.codigo))}</td><td>${Utils.escapeHtml(String(item.producto))}</td><td>${Utils.escapeHtml(String(item.cantidad))}</td>
                <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(item.precio))}</td>
                <td>${Utils.escapeHtml(String(item.iva))}%</td><td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(item.subtotal))}</td>
                <td><button class="btn btn-sm btn-outline-danger" data-action="Proveedores.removeCompraItem" data-idx="${i}" data-render="dev"><i class="bi bi-trash"></i></button></td>
            </tr>`;
        });
        html += '</tbody></table>';

        document.getElementById('devGrid').innerHTML = html;
        if (window.App && typeof App.bindDataActions === 'function') App.bindDataActions();
        document.getElementById('devSubtotal').textContent = Utils.formatCurrency(subtotal);
        document.getElementById('devIVA').textContent = Utils.formatCurrency(ivaTotal);
        document.getElementById('devTotal').textContent = Utils.formatCurrency(subtotal + ivaTotal);
    },

    async guardarDevolucion() {
        const provInput = document.getElementById('devProveedor');
        const provCuit = provInput.dataset.cuit;
        if (!provCuit) { Utils.toast('Seleccione un proveedor', 'Error', 'error'); return; }
        if (this._compraItems.length === 0) { Utils.toast('Agregue al menos un producto', 'Error', 'error'); return; }

        const fecha = document.getElementById('devFecha').value;
        let subtotal = 0, ivaTotal = 0;
        this._compraItems.forEach(i => { subtotal += i.subtotal; ivaTotal += i.ivaTotal; });
        const total = subtotal + ivaTotal;

        try {
            // Enviar la devolución completa al backend
            await API.post('/devoluciones/', {
                proveedor_cuit: provCuit,
                fecha: fecha,
                items: this._compraItems.map(item => ({
                    codigo: item.codigo,
                    producto: item.producto,
                    cantidad: item.cantidad,
                    precio: item.precio
                }))
            });

            Utils.toast('Devolución registrada', 'Devoluciones', 'success');
            this.showProveedores();
        } catch (err) {
            Utils.toast('Error al registrar devolución: ' + err.message, 'Error', 'error');
        }
    }
};
// Exponer Proveedores globalmente
window.Proveedores = Proveedores;
