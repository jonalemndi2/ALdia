/**
 * clientes.js - Módulo de Clientes
 * Equivale a: c_cli_Click, C_nc_Click, c_deudores_Click, Morosos.frm
 */
const Clientes = {
    _data: [],

    async showClientes() {
        try {
            this._data = await API.clientes.getAll();
            // Mostrar la condición con su nombre legible, no la clave interna.
            const condiciones = await this._condicionesIva();
            const nombres = Object.fromEntries(condiciones.map(c => [c.value, c.label]));
            this._data.forEach(c => {
                c.condicionTexto = nombres[c.condicion_iva] || 'Consumidor Final';
            });
        } catch (err) {
            console.error('Error al cargar clientes:', err);
            Utils.toast('Error al cargar clientes', 'Error', 'error');
            return;
        }
        const columns = [
            { field: 'cuit', label: 'CUIT' },
            { field: 'nombre', label: 'Razón Social' },
            { field: 'condicionTexto', label: 'Cond. IVA' },
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
                <h4><i class="bi bi-people"></i> Clientes Cargados</h4>
                <button class="btn btn-sm btn-success" data-action="Clientes.nuevoCliente">
                    <i class="bi bi-person-plus"></i> Nuevo Cliente
                </button>
            </div>
            <div class="mb-3">
                <input type="text" class="form-control" id="clienteSearch" placeholder="Buscar cliente...">
            </div>
            <div id="clienteTable">
                ${Utils.buildTable(columns, this._data, { id: 'clienteGrid', onDblClick: 'Clientes.editCliente' })}
            </div>
            <div class="mt-2 text-muted"><small>Doble click para editar. Total: ${this._data.length} clientes</small></div>
        `;
        Utils.showView(html);
        // Bind search input programmatically
        const clienteSearchEl = document.getElementById('clienteSearch');
        if (clienteSearchEl && !clienteSearchEl.__clienteBound) {
            clienteSearchEl.addEventListener('input', (e) => {
                try { Clientes.filtrar(e.target.value); } catch (err) { console.error('Clientes.filtrar error', err); }
            });
            clienteSearchEl.__clienteBound = true;
        }
    },

    filtrar(val) {
        const filtered = this._data.filter(r =>
            r.nombre.toLowerCase().includes(val.toLowerCase()) ||
            (r.cuit && String(r.cuit).includes(val))
        );
        const columns = [
            { field: 'cuit', label: 'CUIT' }, { field: 'nombre', label: 'Razón Social' },
            { field: 'domicilio', label: 'Domicilio' }, { field: 'localidad', label: 'Localidad' },
            { field: 'provincia', label: 'Provincia' }, { field: 'cp', label: 'CP' },
            { field: 'telefono', label: 'Teléfono' }, { field: 'mail', label: 'E-Mail' },
            { field: 'saldo', label: 'Saldo', format: 'currency' }
        ];
        document.getElementById('clienteTable').innerHTML = Utils.buildTable(columns, filtered, { id: 'clienteGrid', onDblClick: 'Clientes.editCliente' });
    },

    /** Condiciones frente al IVA, para el desplegable. Se piden una sola vez. */
    async _condicionesIva() {
        if (this._condiciones) return this._condiciones;
        try {
            const lista = await API.afip.condicionesIva();
            this._condiciones = lista.map(c => ({ value: c.clave, label: c.nombre }));
        } catch (err) {
            console.warn('No se pudieron cargar las condiciones de IVA:', err.message);
            this._condiciones = [{ value: 'consumidor_final', label: 'Consumidor Final' }];
        }
        return this._condiciones;
    },

    async nuevoCliente() {
        const condiciones = await this._condicionesIva();
        const result = await Utils.multiInput('Nuevo Cliente', [
            { name: 'cuit', label: 'CUIT', required: true, placeholder: 'XX-XXXXXXXX-X' },
            { name: 'nombre', label: 'Razón Social', required: true },
            {
                name: 'condicion_iva', label: 'Condición frente al IVA',
                options: condiciones, default: 'consumidor_final',
                help: 'Define si le corresponde factura A, B o C. Si es incorrecta, AFIP rechaza el comprobante.'
            },
            { name: 'domicilio', label: 'Domicilio' },
            { name: 'localidad', label: 'Localidad' },
            { name: 'provincia', label: 'Provincia' },
            { name: 'cp', label: 'Código Postal' },
            { name: 'telefono', label: 'Teléfono' },
            { name: 'mail', label: 'E-Mail' }
        ]);

        if (!result || !result.cuit || !result.nombre) return;

        try {
            await API.clientes.create({
                cuit: result.cuit.trim(),
                nombre: result.nombre.trim(),
                condicion_iva: result.condicion_iva || 'consumidor_final',
                domicilio: result.domicilio || '',
                localidad: result.localidad || '',
                provincia: result.provincia || '',
                cp: result.cp || '',
                telefono: result.telefono || '',
                mail: result.mail || ''
            });
            Utils.toast('Nuevo cliente cargado', 'Clientes', 'success');
            this.showClientes();
        } catch (e) {
            Utils.toast('Error al cargar nuevo cliente: ' + e.message, 'Error', 'error');
        }
    },

    async editCliente(idx) {
        const c = this._data[idx];
        if (!c) return;
        const condiciones = await this._condicionesIva();
        const result = await Utils.multiInput('Editar Cliente: ' + c.nombre, [
            { name: 'nombre', label: 'Razón Social', default: c.nombre },
            {
                name: 'condicion_iva', label: 'Condición frente al IVA',
                options: condiciones, default: c.condicion_iva || 'consumidor_final',
                help: 'Define si le corresponde factura A, B o C.'
            },
            { name: 'domicilio', label: 'Domicilio', default: c.domicilio },
            { name: 'localidad', label: 'Localidad', default: c.localidad },
            { name: 'provincia', label: 'Provincia', default: c.provincia },
            { name: 'cp', label: 'CP', default: c.cp },
            { name: 'telefono', label: 'Teléfono', default: c.telefono },
            { name: 'mail', label: 'E-Mail', default: c.mail }
        ]);
        if (!result) return;

        try {
            await API.clientes.update(c.cuit, {
                nombre: result.nombre,
                condicion_iva: result.condicion_iva,
                domicilio: result.domicilio,
                localidad: result.localidad,
                provincia: result.provincia,
                cp: result.cp,
                telefono: result.telefono,
                mail: result.mail
            });
            Utils.toast('Cliente actualizado', 'Clientes', 'success');
            this.showClientes();
        } catch (e) {
            Utils.toast('Error al actualizar cliente: ' + e.message, 'Error', 'error');
        }
    },

    async showDeudores() {
        try {
            const all = await API.clientes.getAll();
            const data = all.filter(c => c.saldo > 0).sort((a, b) => b.saldo - a.saldo);
            const columns = [
                { field: 'cuit', label: 'CUIT' },
                { field: 'nombre', label: 'Razón Social' },
                { field: 'telefono', label: 'Teléfono' },
                { field: 'saldo', label: 'Saldo Adeudado', format: 'currency' }
            ];

            const totalDeuda = data.reduce((sum, r) => sum + (r.saldo || 0), 0);

            const html = `
                <div class="section-header">
                    <h4><i class="bi bi-exclamation-triangle"></i> Deudores</h4>
                </div>
                <div class="alert alert-danger">
                    <strong>Total Deuda:</strong> ${Utils.formatCurrency(totalDeuda)} | <strong>Deudores:</strong> ${data.length}
                </div>
                ${Utils.buildTable(columns, data, { id: 'deudoresGrid' })}
            `;
            Utils.showView(html);
        } catch (err) {
            console.error('Error al cargar deudores:', err);
            Utils.toast('Error al cargar deudores', 'Error', 'error');
        }
    }
};
// Exponer módulo Clientes
window.Clientes = Clientes;
