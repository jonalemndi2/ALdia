/**
 * utils.js - Funciones utilitarias compartidas
 * Equivalente a funciones comunes del VB6
 */
const Utils = {
        /** Escape HTML to prevent injection when inserting into innerHTML */
        escapeHtml(str) {
            if (str === null || str === undefined) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        },
    /**
     * Normalizar un importe a 2 decimales antes de mandarlo al servidor.
     *
     * El navegador tambien hace cuentas con floats binarios: 1234.56 * 0.21 da
     * 259.25759999999997 y sumar 0.10 diez veces da 0.9999999999999999. El
     * backend guarda el dinero en CENTAVOS ENTEROS (ver backend/dinero.py) y
     * redondea al recibir, pero conviene redondear tambien aca para que lo que
     * se envia sea EXACTAMENTE lo que el usuario vio en pantalla.
     *
     * toFixed(2) redondea el medio centavo para arriba: el mismo criterio
     * comercial (HALF_UP) que usa el backend.
     */
    money(n) {
        const num = parseFloat(n) || 0;
        return Number(num.toFixed(2));
    },

    /** Formatear número como moneda argentina ($1.234,56) */
    formatCurrency(n) {
        const num = Utils.money(n);
        return '$' + num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },

    /** Formatear número simple */
    formatNumber(n, decimals = 2) {
        const num = parseFloat(n) || 0;
        return num.toLocaleString('es-AR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    },

    /** Fecha actual en formato YYYY-MM-DD */
    today() {
        return new Date().toISOString().split('T')[0];
    },

    /** Formatear fecha para display */
    formatDate(d) {
        if (!d) return '';
        const parts = d.split('-');
        if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
        return d;
    },

    /** Mostrar una vista y ocultar las demás */
    showView(html) {
        document.getElementById('homeView').classList.add('d-none');
        const dyn = document.getElementById('dynamicView');
        dyn.innerHTML = html;
        dyn.classList.remove('d-none');
        // Enlazar actions programáticos si App lo provee
        if (window.App && typeof App.bindDataActions === 'function') App.bindDataActions();
    },

    /** Mostrar la vista Home */
    showHome() {
        document.getElementById('dynamicView').classList.add('d-none');
        document.getElementById('homeView').classList.remove('d-none');
    },

    /** Generar tabla HTML a partir de datos */
    buildTable(columns, rows, options = {}) {
        const tableId = options.id || 'dataTable';
        const tableClass = options.class || 'table-aldia';
        const onRowClick = options.onRowClick || '';
        const onDblClick = options.onDblClick || '';

        let html = `<div class="grid-container"><table class="table table-sm table-bordered ${tableClass}" id="${tableId}"><thead><tr>`;
        columns.forEach(col => {
            html += `<th>${col.label}</th>`;
        });
        html += '</tr></thead><tbody>';

        rows.forEach((row, idx) => {
            const clickAttr = onRowClick ? `data-action="${onRowClick}" data-idx="${idx}"` : '';
            const dblAttr = onDblClick ? `data-action-dbl="${onDblClick}" data-idx="${idx}"` : '';
            html += `<tr ${clickAttr} ${dblAttr} data-idx="${idx}">`;
            columns.forEach(col => {
                let val = row[col.field];
                if (col.render) val = col.render(row);
                else if (col.format === 'currency') val = Utils.formatCurrency(val);
                else if (col.format === 'number') val = Utils.formatNumber(val, col.decimals || 2);
                else if (col.format === 'date') val = Utils.formatDate(val);
                else val = val !== null && val !== undefined ? val : ''; 
                // Escape raw string values to avoid injecting HTML from DB or user input
                if (typeof val === 'string') val = Utils.escapeHtml(val);
                const align = col.align || (col.format === 'currency' || col.format === 'number' ? 'text-end' : '');
                html += `<td class="${align}">${val}</td>`;
            });
            html += '</tr>';
        });

        html += '</tbody></table></div>';
        return html;
    },

    /** Generar tabla editable tipo FlexGrid (para remitos/facturas) */
    buildFlexGrid(columns, id = 'flexGrid') {
        let html = `<div class="grid-container"><table class="table table-sm flex-grid" id="${id}"><thead><tr>`;
        columns.forEach(col => {
            html += `<th style="width:${col.width || 'auto'}">${col.label}</th>`;
        });
        html += '</tr></thead><tbody id="' + id + '_body"></tbody>';
        html += '<tfoot><tr class="totals-row" id="' + id + '_totals"></tr></tfoot>';
        html += '</table></div>';
        return html;
    },

    /** Mostrar toast */
    toast(msg, title = 'ALdia', type = 'info') {
        document.getElementById('toastTitle').textContent = title;
        document.getElementById('toastBody').textContent = msg;
        const t = document.getElementById('appToast');
        t.className = `toast bg-${type === 'error' ? 'danger' : type === 'success' ? 'success' : 'primary'} text-white`;
        const toast = new bootstrap.Toast(t);
        toast.show();
    },

    /** Marcar un campo con error (flag) */
    flagInvalid(inputId) {
        const el = document.getElementById(inputId);
        if (el) {
            el.classList.add('is-invalid');
            setTimeout(() => {
                el.classList.remove('is-invalid');
            }, 3000);
        }
    },

    /** Mostrar modal genérico */
    showModal(title, bodyHtml, footerHtml = '') {
        document.getElementById('genericModalTitle').textContent = title;
        document.getElementById('genericModalBody').innerHTML = bodyHtml;
        const footer = document.getElementById('genericModalFooter');
        footer.innerHTML = footerHtml || '<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cerrar</button>';
        const modal = new bootstrap.Modal(document.getElementById('genericModal'));
        modal.show();
        return modal;
    },

    /** Diálogo de confirmación */
    confirm(title, message) {
        if (message === undefined) { message = title; title = 'Confirmar'; }
        return new Promise(resolve => {
            document.getElementById('confirmTitle').textContent = title;
            document.getElementById('confirmBody').innerHTML = message;
            const modal = new bootstrap.Modal(document.getElementById('confirmModal'));
            const btn = document.getElementById('confirmBtn');
            const handler = () => {
                resolve(true);
                modal.hide();
                btn.removeEventListener('click', handler);
            };
            btn.addEventListener('click', handler);
            document.getElementById('confirmModal').addEventListener('hidden.bs.modal', () => {
                btn.removeEventListener('click', handler);
                resolve(false);
            }, { once: true });
            modal.show();
        });
    },

    /** InputBox equivalente a VB6 (prompt modal) */
    inputBox(title, label, defaultVal = '') {
        return new Promise(resolve => {
            const bodyHtml = `
                <div class="mb-3">
                    <label class="form-label">${label}</label>
                    <input type="text" class="form-control" id="inputBoxVal" value="${Utils.escapeHtml(defaultVal)}">
                </div>
            `;
            const footerHtml = `
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal" onclick="document.getElementById('inputBoxVal')._resolve(null)">Cancelar</button>
                <button type="button" class="btn btn-primary" id="inputBoxOk">Aceptar</button>
            `;
            const modal = Utils.showModal(title, bodyHtml, footerHtml);
            const input = document.getElementById('inputBoxVal');
            input._resolve = resolve;
            input.focus();
            input.select();

            document.getElementById('inputBoxOk').addEventListener('click', () => {
                resolve(input.value);
                modal.hide();
            }, { once: true });

            document.getElementById('genericModal').addEventListener('hidden.bs.modal', () => {
                resolve(null);
            }, { once: true });
        });
    },

    /** Multi-input box para formularios */
    multiInput(title, fields) {
        return new Promise(resolve => {
            let bodyHtml = '<form id="multiInputForm">';
            fields.forEach(f => {
                // Un campo con `options` se muestra como desplegable: sirve para
                // valores de lista cerrada (ej. condicion frente al IVA), donde
                // escribir libre haria que el backend rechace el alta.
                if (Array.isArray(f.options)) {
                    const opciones = f.options.map(o => {
                        const valor = (o && o.value !== undefined) ? o.value : o;
                        const texto = (o && o.label !== undefined) ? o.label : o;
                        const sel = String(valor) === String(f.default || '') ? ' selected' : '';
                        return `<option value="${Utils.escapeHtml(String(valor))}"${sel}>${Utils.escapeHtml(String(texto))}</option>`;
                    }).join('');
                    bodyHtml += `
                        <div class="mb-2">
                            <label class="form-label form-label-sm">${Utils.escapeHtml(f.label)}</label>
                            <select class="form-select form-select-sm" id="mi_${f.name}">${opciones}</select>
                            ${f.help ? `<div class="form-text">${Utils.escapeHtml(f.help)}</div>` : ''}
                        </div>`;
                    return;
                }
                bodyHtml += `
                    <div class="mb-2">
                        <label class="form-label form-label-sm">${Utils.escapeHtml(f.label)}</label>
                        <input type="${f.type || 'text'}" class="form-control form-control-sm"
                               id="mi_${f.name}" value="${Utils.escapeHtml(f.default || '')}"
                               ${f.required ? 'required' : ''} placeholder="${Utils.escapeHtml(f.placeholder || '')}">
                        ${f.help ? `<div class="form-text">${Utils.escapeHtml(f.help)}</div>` : ''}
                    </div>
                `;
            });
            bodyHtml += '</form>';

            const footerHtml = `
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
                <button type="button" class="btn btn-primary" id="multiInputOk">Guardar</button>
            `;
            const modal = Utils.showModal(title, bodyHtml, footerHtml);

            document.getElementById('multiInputOk').addEventListener('click', () => {
                const result = {};
                fields.forEach(f => {
                    result[f.name] = document.getElementById('mi_' + f.name).value;
                });
                resolve(result);
                modal.hide();
            }, { once: true });

            document.getElementById('genericModal').addEventListener('hidden.bs.modal', () => {
                resolve(null);
            }, { once: true });
        });
    },

    /** Buscar cliente/proveedor con autocompletado (contra la API REST) */
    searchEntity(table, inputId, callback) {
        // Sólo entidades con endpoint REST de listado por CUIT/nombre.
        const fuentes = {
            clientes: () => API.clientes.getAll(),
            proveedores: () => API.proveedores.getAll()
        };
        if (!fuentes[table]) throw new Error('Invalid table for searchEntity: ' + table);
        const input = document.getElementById(inputId);
        if (!input) return;

        input.addEventListener('input', async function () {
            const val = this.value.trim();
            let existing = document.getElementById(inputId + '_results');
            if (existing) existing.remove();

            if (val.length < 2) return;

            let rows = [];
            try {
                const todos = await fuentes[table]();
                const needle = val.toLowerCase();
                rows = todos.filter(r =>
                    String(r.nombre || '').toLowerCase().includes(needle) ||
                    String(r.cuit || '').toLowerCase().includes(needle)
                ).slice(0, 10);
            } catch (err) {
                console.error(`Error al buscar en ${table}:`, err);
                Utils.toast(`Error al buscar ${table}: ${err.message}`, 'Error', 'error');
                return;
            }

            // El usuario pudo seguir tecleando mientras esperábamos la respuesta.
            if (input.value.trim() !== val) return;
            const previo = document.getElementById(inputId + '_results');
            if (previo) previo.remove();
            if (rows.length === 0) return;

            const div = document.createElement('div');
            div.className = 'search-results';
            div.id = inputId + '_results';

            rows.forEach(r => {
                const item = document.createElement('div');
                item.className = 'search-item';
                item.textContent = `${r.cuit} - ${r.nombre}`;
                item.addEventListener('click', () => {
                    input.value = r.nombre;
                    input.dataset.cuit = r.cuit;
                    div.remove();
                    if (callback) callback(r);
                });
                div.appendChild(item);
            });

            input.parentElement.style.position = 'relative';
            input.parentElement.appendChild(div);
        });

        // Cerrar al hacer click fuera -> usar listener global único que cierre todos los resultados
        if (!Utils._searchEntityClickAdded) {
            document.addEventListener('click', (e) => {
                document.querySelectorAll('.search-results').forEach(el => {
                    if (!el.contains(e.target)) el.remove();
                });
            });
            Utils._searchEntityClickAdded = true;
        }
    },

    /** Buscar producto con autocompletado (contra la API REST) */
    searchProduct(inputId, callback) {
        const input = document.getElementById(inputId);
        if (!input) return;

        input.addEventListener('input', async function () {
            const val = this.value.trim();
            let existing = document.getElementById(inputId + '_results');
            if (existing) existing.remove();

            if (val.length < 1) return;

            let rows = [];
            try {
                const todos = await API.stock.getAll();
                const needle = val.toLowerCase();
                const cod = parseInt(val);
                rows = todos.filter(r =>
                    String(r.producto || '').toLowerCase().includes(needle) ||
                    (!isNaN(cod) && Number(r.codigo) === cod)
                ).slice(0, 15);
            } catch (err) {
                console.error('Error al buscar productos:', err);
                Utils.toast('Error al buscar productos: ' + err.message, 'Error', 'error');
                return;
            }

            if (input.value.trim() !== val) return;
            const previo = document.getElementById(inputId + '_results');
            if (previo) previo.remove();
            if (rows.length === 0) return;

            const div = document.createElement('div');
            div.className = 'search-results';
            div.id = inputId + '_results';

            rows.forEach(r => {
                const item = document.createElement('div');
                item.className = 'search-item';
                item.textContent = `[${r.codigo}] ${r.producto} - Stock: ${r.cantidad} ${r.unidad} - $${Utils.formatNumber(r.preven)}`;
                item.addEventListener('click', () => {
                    input.value = r.producto;
                    input.dataset.codigo = r.codigo;
                    div.remove();
                    if (callback) callback(r);
                });
                div.appendChild(item);
            });

            input.parentElement.style.position = 'relative';
            input.parentElement.appendChild(div);
        });
    },

    /** Seleccionar fila de tabla */
    selectRow(idx, rowEl) {
        const table = rowEl.closest('table');
        table.querySelectorAll('tr.selected-row').forEach(r => r.classList.remove('selected-row'));
        rowEl.classList.add('selected-row');
    }
};

// Exponer Utils al scope global
window.Utils = Utils;
