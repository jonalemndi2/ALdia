/**
 * remitos.js - Módulo de Remitos
 * Equivale a: remito.frm, reimpr.frm, remnofac.frm
 */
const Remitos = {
    _items: [],

    emitirRemito() {
        this._items = [];
        const html = `
            <div class="section-header" style="background:linear-gradient(135deg,#1b5e20,#388e3c)">
                <h4><i class="bi bi-file-earmark-text"></i> Emitir Remito</h4>
            </div>
            <div class="row mb-3">
                <div class="col-md-5">
                    <div class="form-card">
                        <label class="form-label-sm">Cliente</label>
                        <div class="position-relative">
                            <input type="text" class="form-control" id="remCliente" placeholder="Buscar cliente...">
                        </div>
                        <div class="row mt-2">
                            <div class="col-6">
                                <label class="form-label-sm">Fecha</label>
                                <input type="date" class="form-control form-control-sm" id="remFecha" value="${Utils.today()}">
                            </div>
                            <div class="col-6">
                                <label class="form-check-label mt-4">
                                    <input type="checkbox" class="form-check-input" id="remIntermediario">
                                    Entrega a Intermediario
                                </label>
                            </div>
                        </div>
                        <div id="remIntermediarioDiv" class="mt-2 d-none">
                            <label class="form-label-sm">Intermediario</label>
                            <input type="text" class="form-control form-control-sm" id="remIntermediarioNombre">
                        </div>
                    </div>
                </div>
                <div class="col-md-7">
                    <div class="form-card">
                        <label class="form-label-sm">Agregar Producto</label>
                        <div class="position-relative">
                            <input type="text" class="form-control form-control-sm" id="remProd" placeholder="Buscar producto...">
                        </div>
                        <div class="row mt-2">
                            <div class="col-3">
                                <label class="form-label-sm">Cantidad</label>
                                <input type="number" class="form-control form-control-sm" id="remCant" value="1">
                            </div>
                            <div class="col-3">
                                <label class="form-label-sm">Precio</label>
                                <input type="number" class="form-control form-control-sm" id="remPrecio" step="0.01">
                            </div>
                                <div class="col-3 d-flex align-items-end">
                                <button class="btn btn-sm btn-success w-100" data-action="Remitos.addItem">
                                    <i class="bi bi-plus"></i> Agregar
                                </button>
                            </div>
                        </div>
                        <div class="mt-2">
                            <label class="form-label-sm">Observaciones</label>
                            <input type="text" class="form-control form-control-sm" id="remObs" placeholder="Observaciones...">
                        </div>
                    </div>
                </div>
            </div>
            <div id="remGrid"></div>
            <div class="row mt-3">
                <div class="col-md-4">
                    <h5>Total: <span id="remTotal" class="badge bg-success badge-total">$0.00</span></h5>
                </div>
                <div class="col-md-4 offset-md-4 text-end">
                    <button class="btn btn-success btn-lg" data-action="Remitos.guardarRemito">
                        <i class="bi bi-check-circle"></i> Realizar Remito
                    </button>
                </div>
            </div>
        `;
        Utils.showView(html);
        Utils.searchEntity('clientes', 'remCliente');
        Utils.searchProduct('remProd', (p) => {
            document.getElementById('remPrecio').value = p.preven;
        });

        document.getElementById('remIntermediario').addEventListener('change', function() {
            document.getElementById('remIntermediarioDiv').classList.toggle('d-none', !this.checked);
        });
    },

    async addItem() {
        const prodInput = document.getElementById('remProd');
        const codigo = prodInput.dataset.codigo;
        if (!codigo) { Utils.toast('Seleccione un producto', 'Error', 'error'); return; }

        const cant = parseFloat(document.getElementById('remCant').value) || 0;
        const precio = parseFloat(document.getElementById('remPrecio').value) || 0;

        try {
            const prod = await API.stock.getById(codigo);

            if (cant > prod.cantidad) {
                Utils.toast(`Stock insuficiente. Disponible: ${prod.cantidad} ${prod.unidad}`, 'Stock', 'error');
                return;
            }

            this._items.push({
                codigo: prod.codigo, producto: prod.producto, cantidad: cant,
                precio: precio, unidad: prod.unidad, iva: prod.iva,
                subtotal: cant * precio
            });

            prodInput.value = '';
            prodInput.dataset.codigo = '';
            document.getElementById('remCant').value = '1';
            document.getElementById('remPrecio').value = '';
            this._renderGrid();
        } catch (err) {
            Utils.toast('Error al obtener producto: ' + err.message, 'Error', 'error');
        }
    },

    _renderGrid() {
        let total = 0;
        let html = '<table class="table table-sm flex-grid"><thead><tr>' +
            '<th>Cód.</th><th>Producto</th><th>Cant.</th><th>Unidad</th><th>Precio</th><th>Subtotal</th><th></th>' +
            '</tr></thead><tbody>';

        this._items.forEach((item, i) => {
            total += item.subtotal;
            html += `<tr class="item-row">
                <td>${Utils.escapeHtml(String(item.codigo))}</td><td>${Utils.escapeHtml(String(item.producto))}</td><td>${Utils.escapeHtml(String(item.cantidad))}</td>
                <td>${Utils.escapeHtml(String(item.unidad))}</td><td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(item.precio))}</td>
                <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(item.subtotal))}</td>
                <td><button class="btn btn-sm btn-outline-danger" data-action="Remitos.removeItem" data-idx="${i}"><i class="bi bi-trash"></i></button></td>
            </tr>`;
        });
        html += '</tbody></table>';

        document.getElementById('remGrid').innerHTML = html;
        document.getElementById('remTotal').textContent = Utils.formatCurrency(total);
        if (window.App && typeof App.bindDataActions === 'function') App.bindDataActions();
    },

    removeItem(idx) {
        this._items.splice(idx, 1);
        this._renderGrid();
    },

    async guardarRemito() {
        const cliInput = document.getElementById('remCliente');
        const clienteCuit = cliInput.dataset.cuit;
        if (!clienteCuit) { Utils.toast('Seleccione un cliente', 'Error', 'error'); return; }
        if (this._items.length === 0) { Utils.toast('Agregue al menos un producto', 'Error', 'error'); return; }

        const fecha = document.getElementById('remFecha').value;
        let total = 0, ivaTotal = 0;
        this._items.forEach(i => {
            total += i.subtotal;
            ivaTotal += i.subtotal * (i.iva / 100);
        });
        // Redondeo unico a 2 decimales antes de enviar (ver Utils.money).
        total = Utils.money(total);
        ivaTotal = Utils.money(ivaTotal);

        const intermediario = document.getElementById('remIntermediario').checked ? 
            document.getElementById('remIntermediarioNombre').value : null;
        const obs = document.getElementById('remObs').value;

        try {
            // La API expone la cabecera y los renglones por separado:
            //   POST /remitos/         -> { cliente, fecha, total, iva }
            //   POST /remitos/ventas   -> un renglón por ítem, ligado por `nmov`
            // Se envía TODO en una sola petición (cabecera + renglones). El
            // servidor los persiste y descuenta el stock dentro de una misma
            // transacción. Enviarlos por separado dejaba un remito huérfano sin
            // renglones si fallaba a mitad de camino, y el stock no se descontaba.
            const result = await API.remitos.create({
                cliente: clienteCuit,
                fecha: fecha,
                total: total,
                iva: ivaTotal,
                items: this._items.map(item => ({
                    codigo: item.codigo,
                    producto: item.producto,
                    cantidad: item.cantidad,
                    precio: item.precio,
                    unidad: item.unidad
                }))
            });

            const remitoId = result.id;

            if (intermediario || obs) {
                console.warn('Intermediario/observaciones no se persisten: la API de remitos aún no expone esos campos.',
                    { intermediario, obs });
            }

            const ok = await Utils.confirm('Remito Generado',
                `Remito N° <strong>${remitoId}</strong> creado exitosamente.<br>
                 Total: <strong>${Utils.formatCurrency(total)}</strong><br>
                 ¿Desea imprimir?`);

            if (ok) this.imprimirRemito(remitoId);

            Utils.toast(`Remito N° ${remitoId} generado`, 'Remitos', 'success');
            this.emitirRemito();
        } catch (err) {
            Utils.toast('Error al guardar remito: ' + err.message, 'Error', 'error');
        }
    },

    async imprimirRemito(id) {
        try {
            const rem = await API.remitos.getById(id);
            const items = await API.remitos.getVentas(id);
            const cliente = await API.clientes.getById(rem.cliente);

            let itemsHtml = '';
            items.forEach(i => {
                itemsHtml += `<tr><td>${Utils.escapeHtml(String(i.codigo))}</td><td>${Utils.escapeHtml(String(i.producto))}</td><td>${Utils.escapeHtml(String(i.cantidad))}</td>
                    <td>${Utils.escapeHtml(String(i.unidad || ''))}</td><td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(i.precio))}</td>
                    <td class="text-end">${Utils.escapeHtml(Utils.formatCurrency(i.cantidad * i.precio))}</td></tr>`;
            });

            const printHtml = `
                <div style="font-family:Arial; padding:20px; max-width:800px; margin:auto;">
                    <h2 style="text-align:center;">REMITO N° ${id}</h2>
                    <hr>
                    <p><strong>Cliente:</strong> ${Utils.escapeHtml(String(cliente ? cliente.nombre : rem.cliente))}</p>
                    <p><strong>CUIT:</strong> ${Utils.escapeHtml(String(rem.cliente || ''))}</p>
                    <p><strong>Fecha:</strong> ${Utils.formatDate(rem.fecha)}</p>
                    <table style="width:100%; border-collapse:collapse; margin-top:10px;">
                        <thead><tr style="background:#333;color:white;">
                            <th style="padding:6px;border:1px solid #333;">Cód.</th>
                            <th style="padding:6px;border:1px solid #333;">Producto</th>
                            <th style="padding:6px;border:1px solid #333;">Cant.</th>
                            <th style="padding:6px;border:1px solid #333;">Unidad</th>
                            <th style="padding:6px;border:1px solid #333;">Precio</th>
                            <th style="padding:6px;border:1px solid #333;">Subtotal</th>
                        </tr></thead>
                        <tbody>${itemsHtml}</tbody>
                    </table>
                    <h3 style="text-align:right; margin-top:20px;">TOTAL: ${Utils.formatCurrency(rem.total)}</h3>
                </div>
            `;

            const win = window.open('', '_blank', 'width=850,height=600');
            if (!win) {
                Utils.toast('El navegador bloqueó la ventana de impresión. Habilite los pop-ups para imprimir.', 'Remitos', 'error');
                return;
            }
            win.document.write(printHtml);
            win.document.close();
            win.print();
        } catch (err) {
            Utils.toast('Error al imprimir remito: ' + err.message, 'Error', 'error');
        }
    },

    /** Reimprimir remitos (reimpr.frm) */
    async reimprimir() {
        try {
            const remitos = await API.remitos.getAll();
            const columns = [
                { field: 'id', label: 'N° Remito' },
                { field: 'cliente', label: 'Cliente (CUIT)' },
                { field: 'fecha', label: 'Fecha', format: 'date' },
                { field: 'total', label: 'Total', format: 'currency' }
            ];

            const html = `
                <div class="section-header">
                    <h4><i class="bi bi-printer"></i> Reimprimir Remitos</h4>
                </div>
                ${Utils.buildTable(columns, remitos, { id: 'remitosList', onDblClick: 'Remitos.reimprimirItem' })}
                <div class="mt-2 text-muted"><small>Doble click en un remito para reimprimir</small></div>
            `;
            Utils.showView(html);
            this._remitosList = remitos;
        } catch (err) {
            Utils.toast('Error al cargar remitos: ' + err.message, 'Error', 'error');
        }
    },

    reimprimirItem(idx) {
        const rem = this._remitosList[idx];
        if (rem) this.imprimirRemito(rem.id);
    },

    /** Remitos no facturados (remnofac.frm) */
    async remitosNoFacturados() {
        try {
            const data = await API.remitos.getNoFacturados();
            // GET /remitos/nofacturados devuelve cabeceras de remito, no renglones.
            const columns = [
                { field: 'id', label: 'N° Remito' },
                { field: 'cliente', label: 'Cliente (CUIT)' },
                { field: 'fecha', label: 'Fecha', format: 'date' },
                { field: 'total', label: 'Total', format: 'currency' },
                { field: 'iva', label: 'IVA', format: 'currency' }
            ];

            const html = `
                <div class="section-header">
                    <h4><i class="bi bi-file-earmark-x"></i> Remitos No Facturados</h4>
                </div>
                ${Utils.buildTable(columns, data)}
            `;
            Utils.showView(html);
        } catch (err) {
            Utils.toast('Error al cargar remitos no facturados: ' + err.message, 'Error', 'error');
        }
    }
};
// Exponer Remitos
window.Remitos = Remitos;
