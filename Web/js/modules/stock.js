/**
 * stock.js - Módulo de Stock de Mercadería
 * Equivale a: Stock_existencia, stock_newpro, stock_price en menu.frm + Modificar_mercaderia
 */
const Stock = {
    _data: [],

    async showExistencia() {
        try {
            this._data = await API.stock.getAll();
        } catch (err) {
            console.error('Error al cargar stock:', err);
            Utils.toast('Error al cargar stock', 'Error', 'error');
            return;
        }
        const columns = [
            { field: 'codigo', label: 'Código', width: '80px' },
            { field: 'producto', label: 'Producto' },
            { field: 'cantidad', label: 'Cantidad', format: 'number', decimals: 0 },
            { field: 'unidad', label: 'Unidad' },
            { field: 'preven', label: 'Precio Venta', format: 'currency' },
            { field: 'iva', label: 'IVA %', format: 'number', decimals: 1 },
            { field: 'precom', label: 'Precio Compra', format: 'currency' }
        ];

        const html = `
            <div class="section-header d-flex justify-content-between align-items-center">
                <h4><i class="bi bi-box-seam"></i> Stock de Mercadería Existente</h4>
                <div>
                    <button class="btn btn-sm btn-success" data-action="Stock.nuevoProducto">
                        <i class="bi bi-plus-circle"></i> Nuevo Producto
                    </button>
                    <button class="btn btn-sm btn-warning" data-action="Stock.cambiarPrecio">
                        <i class="bi bi-pencil"></i> Cambiar Precio
                    </button>
                </div>
            </div>
            <div class="mb-3">
                <input type="text" class="form-control" id="stockSearch" placeholder="Buscar producto...">
            </div>
            <div id="stockTable">
                ${Utils.buildTable(columns, this._data, { id: 'stockGrid', onRowClick: 'Stock.selectRow', onDblClick: 'Stock.modificar' })}
            </div>
            <div class="mt-2 text-muted"><small>Doble click en una fila para modificar</small></div>
        `;
        Utils.showView(html);
        // Bind search input programmatically (avoids inline handlers and ReferenceError)
        const stockSearchEl = document.getElementById('stockSearch');
        if (stockSearchEl && !stockSearchEl.__stockBound) {
            stockSearchEl.addEventListener('input', (e) => {
                try { Stock.filtrar(e.target.value); } catch (err) { console.error('Stock.filtrar error', err); }
            });
            stockSearchEl.__stockBound = true;
        }
    },

    filtrar(val) {
        const filtered = this._data.filter(r =>
            r.producto.toLowerCase().includes(val.toLowerCase()) ||
            String(r.codigo).includes(val)
        );
        const columns = [
            { field: 'codigo', label: 'Código' },
            { field: 'producto', label: 'Producto' },
            { field: 'cantidad', label: 'Cantidad', format: 'number', decimals: 0 },
            { field: 'unidad', label: 'Unidad' },
            { field: 'preven', label: 'Precio Venta', format: 'currency' },
            { field: 'iva', label: 'IVA %', format: 'number', decimals: 1 },
            { field: 'precom', label: 'Precio Compra', format: 'currency' }
        ];
        document.getElementById('stockTable').innerHTML = Utils.buildTable(columns, filtered, { id: 'stockGrid', onRowClick: 'Stock.selectRow', onDblClick: 'Stock.modificar' });
    },

    selectRow(idx, el) {
        Utils.selectRow(idx, el);
        this._selectedIdx = idx;
    },

    async nuevoProducto() {
        // El backend exige `codigo` (clave primaria, no autoincremental):
        // proponemos el siguiente libre para que el alta no falle con 422.
        let sugerido = 1;
        try {
            const actuales = await API.stock.getAll();
            this._data = actuales;
            sugerido = actuales.reduce((max, p) => Math.max(max, parseInt(p.codigo) || 0), 0) + 1;
        } catch (err) {
            console.error('No se pudo calcular el próximo código de producto:', err);
            Utils.toast('No se pudo leer el stock actual: ' + err.message, 'Error', 'error');
            return;
        }

        const result = await Utils.multiInput('Nuevo Producto', [
            { name: 'codigo', label: 'Código', type: 'number', default: String(sugerido), required: true },
            { name: 'producto', label: 'Nombre del Producto', required: true },
            { name: 'cantidad', label: 'Cantidad Inicial', type: 'number', default: '0' },
            { name: 'unidad', label: 'Unidad (Kg, Lt, UN)', default: 'Kg' },
            { name: 'preven', label: 'Precio de Venta', type: 'number', default: '0' },
            { name: 'precom', label: 'Precio de Compra', type: 'number', default: '0' },
            { name: 'iva', label: 'IVA %', type: 'number', default: '21' }
        ]);

        if (!result || !result.producto) return;

        const codigo = parseInt(result.codigo);
        if (!codigo || codigo <= 0) {
            Utils.toast('El código del producto es obligatorio y debe ser numérico', 'Validación', 'error');
            return;
        }

        try {
            await API.stock.create({
                codigo: codigo,
                producto: result.producto,
                cantidad: parseFloat(result.cantidad) || 0,
                unidad: result.unidad || 'UN',
                preven: parseFloat(result.preven) || 0,
                precom: parseFloat(result.precom) || 0,
                iva: parseFloat(result.iva) || 21
            });

            Utils.toast('Nuevo producto cargado correctamente', 'Stock', 'success');
            this.showExistencia();
        } catch (err) {
            Utils.toast('Error al crear producto: ' + err.message, 'Error', 'error');
        }
    },

    async modificar(idx) {
        const prod = this._data[idx];
        if (!prod) return;

        const result = await Utils.multiInput('Modificar Producto: ' + prod.producto, [
            { name: 'producto', label: 'Nombre', default: prod.producto },
            { name: 'cantidad', label: 'Cantidad', type: 'number', default: String(prod.cantidad) },
            { name: 'unidad', label: 'Unidad', default: prod.unidad },
            { name: 'preven', label: 'Precio Venta', type: 'number', default: String(prod.preven) },
            { name: 'iva', label: 'IVA %', type: 'number', default: String(prod.iva) }
        ]);

        if (!result) return;

        try {
            await API.stock.update(prod.codigo, {
                producto: result.producto,
                cantidad: parseFloat(result.cantidad),
                unidad: result.unidad,
                preven: parseFloat(result.preven),
                iva: parseFloat(result.iva)
            });

            Utils.toast('Producto modificado', 'Stock', 'success');
            this.showExistencia();
        } catch (err) {
            Utils.toast('Error al modificar producto: ' + err.message, 'Error', 'error');
        }
    },

    async cambiarPrecio() {
        this.showExistencia();
        Utils.toast('Haga doble click en el producto para cambiar su precio', 'Stock', 'info');
    }
};
// Exponer módulo Stock al scope global
window.Stock = Stock;
